import json

from conftest import VALID_DRAFT, FakeAnalyzer

from app.services.ai.base import AnalysisError


def _analyze(client, photo_bytes, **data):
    return client.post(
        "/api/garments/analyze",
        files={"front": ("delante.jpg", photo_bytes, "image/jpeg")},
        data=data,
    )


def _create(client, photo_bytes, **overrides):
    photo = _analyze(client, photo_bytes, skip_ai="true").json()["photo_front"]["id"]
    body = {k: v for k, v in VALID_DRAFT.items() if k != "confidence"}
    body.update({"photo_front": photo, **overrides})
    return client.post("/api/garments", json=body)


def test_rebanada_completa_foto_analisis_guardar_y_verla(client, analyzers, photo_bytes):
    analyzers(FakeAnalyzer("codex", json.dumps(VALID_DRAFT)), FakeAnalyzer("claude"))

    analysis = _analyze(client, photo_bytes).json()
    assert analysis["provider"] == "codex" and analysis["fallback_used"] is False
    assert analysis["draft"]["name"] == "Bomber negra"
    assert client.get(analysis["photo_front"]["url"]).status_code == 200
    assert client.get(analysis["photo_front"]["thumb_url"]).status_code == 200

    draft = analysis["draft"]
    created = client.post(
        "/api/garments",
        json={
            **{k: v for k, v in draft.items() if k != "confidence"},
            "photo_front": analysis["photo_front"]["id"],
            "ai_provider": analysis["provider"],
            "ai_confidence": draft["confidence"],
        },
    )
    assert created.status_code == 201
    assert created.json()["category"] == "capa_exterior"  # deducida del tipo

    listed = client.get("/api/garments").json()
    assert [g["name"] for g in listed] == ["Bomber negra"]
    assert listed[0]["wear_count"] == 0


def test_si_la_ia_falla_se_conservan_las_fotos_para_reintentar(client, analyzers, photo_bytes):
    analyzers(FakeAnalyzer("codex", error=AnalysisError("caído")), FakeAnalyzer("claude", is_available=False))
    first = _analyze(client, photo_bytes).json()
    assert first["draft"] is None and first["error"]

    analyzers(FakeAnalyzer("codex", error=AnalysisError("caído")), FakeAnalyzer("claude", json.dumps(VALID_DRAFT)))
    retry = client.post("/api/garments/analyze", data={"front_id": first["photo_front"]["id"]}).json()
    assert retry["photo_front"]["id"] == first["photo_front"]["id"]
    assert retry["provider"] == "claude" and retry["fallback_used"] is True


def test_se_puede_guardar_rellenando_a_mano(client, photo_bytes):
    created = _create(client, photo_bytes)
    assert created.status_code == 201
    assert created.json()["ai_provider"] is None


def test_analizar_sin_foto_o_con_archivo_que_no_es_imagen(client):
    assert client.post("/api/garments/analyze").status_code == 422
    bad = client.post("/api/garments/analyze", files={"front": ("nota.txt", b"hola", "text/plain")})
    assert bad.status_code == 422


def test_crear_rechaza_valores_fuera_de_las_listas(client, photo_bytes):
    assert _create(client, photo_bytes, season="primavera").status_code == 422
    assert _create(client, photo_bytes, photo_front="0" * 32).status_code == 422  # foto inexistente


def test_filtros_y_resumen(client, photo_bytes):
    _create(client, photo_bytes)
    _create(client, photo_bytes, name="Camiseta boxy", type="camiseta", season="verano")

    assert [g["name"] for g in client.get("/api/garments", params={"season": "verano"}).json()] == ["Camiseta boxy"]
    assert len(client.get("/api/garments", params={"category": "capa_exterior"}).json()) == 1
    assert len(client.get("/api/garments", params={"q": "bomb"}).json()) == 1

    summary = client.get("/api/garments/summary").json()
    assert summary["total"] == 2
    assert summary["by_category"] == {"capa_exterior": 1, "parte_superior": 1}


def test_lavadora_uso_y_borrado(client, photo_bytes):
    garment = _create(client, photo_bytes).json()
    gid = garment["id"]

    patched = client.patch(f"/api/garments/{gid}", json={"in_laundry": True, "type": "abrigo"}).json()
    assert patched["in_laundry"] is True and patched["laundry_since"]
    assert patched["category"] == "capa_exterior"
    assert client.get("/api/garments/summary").json()["in_laundry"] == 1

    assert client.post("/api/laundry/clear").json() == {"cleared": 1}
    assert client.get(f"/api/garments/{gid}").json()["in_laundry"] is False

    worn = client.post(f"/api/garments/{gid}/wear", json={"worn_on": "2026-11-17"}).json()
    assert worn["wear_count"] == 1 and worn["last_worn_on"] == "2026-11-17"

    assert client.delete(f"/api/garments/{gid}").status_code == 204
    assert client.get(f"/api/garments/{gid}").status_code == 404
    assert client.get(garment["photo_front"]["url"]).status_code == 404  # las fotos se borran con la prenda


def test_ajustes_por_defecto_y_cambio(client):
    assert client.get("/api/settings").json() == {
        "theme": "sistema",
        "ai_provider": "codex",
        "city": "Argenteuil",
        "notify_enabled": True,
        "notify_time": "07:30",
    }
    updated = client.patch("/api/settings", json={"theme": "oscuro", "ai_provider": "claude"}).json()
    assert updated["theme"] == "oscuro" and updated["ai_provider"] == "claude"
    assert client.patch("/api/settings", json={"theme": "rosa"}).status_code == 422


def test_limpieza_de_fotos_huerfanas(client, photo_bytes):
    from app.services import storage

    kept = _create(client, photo_bytes).json()["photo_front"]["id"]
    orphan = _analyze(client, photo_bytes, skip_ai="true").json()["photo_front"]["id"]

    assert storage.cleanup_orphans({kept}) == 0  # reciente: puede ser un borrador en curso
    assert storage.cleanup_orphans({kept}, max_age_hours=0) >= 1  # también las que dejaron otros tests
    assert storage.exists(kept) and not storage.exists(orphan)
    assert not storage.thumb_path(orphan).exists()
