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
        "codex_model": "",
        "codex_effort": "",
        "codex_translate_model": "",
        "codex_translate_effort": "low",
        "city": "Argenteuil",
        "season_mode": "auto",
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


def test_la_api_key_de_claude_se_guarda_pero_nunca_se_devuelve(client):
    assert client.get("/api/ai/status").json()["claude_configured"] is False

    saved = client.patch("/api/settings", json={"anthropic_api_key": "clave-de-prueba"})
    assert saved.status_code == 200
    assert "clave-de-prueba" not in saved.text and "anthropic_api_key" not in saved.json()
    assert "clave-de-prueba" not in client.get("/api/settings").text
    assert client.get("/api/ai/status").json()["claude_configured"] is True

    client.patch("/api/settings", json={"anthropic_api_key": ""})  # vacía = borrar
    assert client.get("/api/ai/status").json()["claude_configured"] is False


def test_girar_una_foto(client, photo_bytes):
    from PIL import Image

    from app.services import storage

    garment = _create(client, photo_bytes).json()
    old = garment["photo_front"]["id"]
    assert Image.open(storage.photo_path(old)).size == (1600, 1200)  # apaisada

    new = client.post(f"/api/photos/{old}/rotate").json()
    assert new["id"] != old  # id nuevo: el navegador no reutiliza la imagen en caché
    assert Image.open(storage.photo_path(new["id"])).size == (1200, 1600)  # ahora vertical
    assert client.get(new["thumb_url"]).status_code == 200
    assert not storage.exists(old)

    # La prenda pasa a apuntar a la foto girada.
    assert client.get(f"/api/garments/{garment['id']}").json()["photo_front"]["id"] == new["id"]
    assert client.post(f"/api/photos/{old}/rotate").status_code == 404


def test_informe_de_correcciones_a_la_ia(client, photo_bytes):
    # Una prenda guardada tal cual la propuso la IA y otra con la temporada y el color corregidos.
    _create(client, photo_bytes, ai_provider="codex", ai_draft=VALID_DRAFT)
    _create(client, photo_bytes, ai_provider="codex", ai_draft=VALID_DRAFT, season="verano",
            color_primary={"name": "azul marino", "hex": "#1f2a44"})
    _create(client, photo_bytes)  # rellenada a mano: no cuenta

    report = client.get("/api/ai/corrections").json()
    assert report["analyzed"] == 2 and report["untouched"] == 1
    assert report["by_field"] == {"color_primary": 1, "season": 1}
    season = next(c for c in report["corrections"] if c["field"] == "season")
    assert (season["ai"], season["saved"]) == ("invierno", "verano")


def test_la_base_de_datos_antigua_recibe_las_columnas_nuevas():
    from sqlalchemy import create_engine

    from app import db

    old = create_engine("sqlite://")
    with old.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE garments (id INTEGER PRIMARY KEY, name TEXT)")
        conn.exec_driver_sql("INSERT INTO garments (name) VALUES ('de antes')")
    real, db.engine = db.engine, old
    try:
        db._add_missing_columns()
        db._add_missing_columns()  # repetirlo no falla
    finally:
        db.engine = real
    with old.begin() as conn:
        assert "ai_draft" in {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(garments)")}
        assert conn.exec_driver_sql("SELECT name FROM garments").scalar() == "de antes"


def test_foto_de_etiqueta_para_marca_y_talla(client, analyzers, photo_bytes):
    draft = {**VALID_DRAFT, "brand": "Primark", "size": "XL"}
    codex, _ = analyzers(FakeAnalyzer("codex", json.dumps(draft)), FakeAnalyzer("claude"))

    analysis = client.post(
        "/api/garments/analyze",
        files={
            "front": ("delante.jpg", photo_bytes, "image/jpeg"),
            "label": ("etiqueta.jpg", photo_bytes, "image/jpeg"),
        },
    ).json()
    assert analysis["photo_label"] and analysis["photo_back"] is None
    assert len(codex.images) == 2  # delantera + etiqueta
    assert "Foto 2: la etiqueta" in codex.prompt
    assert (analysis["draft"]["brand"], analysis["draft"]["size"]) == ("Primark", "XL")

    body = {k: v for k, v in analysis["draft"].items() if k != "confidence"}
    body.update(photo_front=analysis["photo_front"]["id"], photo_label=analysis["photo_label"]["id"])
    garment = client.post("/api/garments", json=body).json()
    assert garment["photo_label"]["id"] == analysis["photo_label"]["id"]

    # Al borrar la prenda se borra también la foto de la etiqueta.
    client.delete(f"/api/garments/{garment['id']}")
    assert client.get(garment["photo_label"]["url"]).status_code == 404


def test_no_se_guardan_dos_prendas_con_las_mismas_fotos(client, photo_bytes):
    first = _create(client, photo_bytes).json()
    body = {k: v for k, v in VALID_DRAFT.items() if k != "confidence"}
    again = client.post("/api/garments", json={**body, "photo_front": first["photo_front"]["id"]})
    assert again.status_code == 409
    assert len(client.get("/api/garments").json()) == 1


def test_borrar_no_toca_las_fotos_que_usa_otra_prenda(client, photo_bytes):
    from app.db import SessionLocal
    from app.models import Garment
    from app.services import storage

    a = _create(client, photo_bytes).json()
    b = _create(client, photo_bytes).json()
    with SessionLocal() as db:  # datos antiguos: dos prendas que ya comparten foto
        db.get(Garment, b["id"]).photo_back = a["photo_front"]["id"]
        db.commit()
    assert client.delete(f"/api/garments/{a['id']}").status_code == 204
    assert storage.exists(a["photo_front"]["id"])


def test_quitar_el_color_principal_no_rompe(client, photo_bytes):
    gid = _create(client, photo_bytes).json()["id"]
    patched = client.patch(f"/api/garments/{gid}", json={"color_primary": None})
    assert patched.status_code == 200
    assert patched.json()["color_primary"]["name"] == "negro"


def test_la_ciudad_se_recorta_y_no_puede_quedar_vacia(client):
    assert client.patch("/api/settings", json={"city": "   "}).status_code == 422
    assert client.patch("/api/settings", json={"city": "  Paris "}).json()["city"] == "Paris"


def test_imagen_con_demasiados_pixeles_da_422(client, monkeypatch, photo_bytes):
    from PIL import Image

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # la foto de prueba pasa a ser "enorme"
    response = client.post("/api/garments/analyze", files={"front": ("f.jpg", photo_bytes, "image/jpeg")},
                           data={"skip_ai": "true"})
    assert response.status_code == 422


def test_fotos_de_tienda_con_codex_se_aplican_y_se_puede_volver(client, photo_bytes, monkeypatch):
    from app.services import storage
    from app.services.ai import studio

    seen = []

    def fake(target, view, kind, others, feedback=None, previous=None, texture=None):
        seen.append((view, kind, [name for name, _ in others], feedback, previous is not None))
        return photo_bytes

    monkeypatch.setattr(studio, "product_photo", fake)
    front = client.post("/api/garments/analyze", files={"front": ("a.jpg", photo_bytes, "image/jpeg"),
                                                         "back": ("b.jpg", photo_bytes, "image/jpeg")}).json()
    garment = client.post("/api/garments", json={
        "name": "Sudadera", "type": "sudadera", "color_primary": {"name": "verde", "hex": "#0a5a3c"},
        "colors_secondary": [], "pattern": "liso", "style": "casual", "season": "invierno", "details": "",
        "notes": "", "photo_front": front["photo_front"]["id"], "photo_back": front["photo_back"]["id"],
    }).json()
    assert garment["photos_edited"] is False

    otras = [{"view": "back", "photo": garment["photo_back"]["id"]}]
    nueva = client.post("/api/photos/studio", json={"photo": garment["photo_front"]["id"], "view": "front", "others": otras})
    # La trasera va de referencia.
    assert nueva.status_code == 200 and seen == [("front", "ropa", ["back"], None, False)]
    assert client.post("/api/photos/studio", json={"photo": "0" * 32, "view": "front"}).status_code == 404
    # Rehacerla: lo que dijo el usuario y el intento anterior llegan a Codex.
    rehecha = client.post("/api/photos/studio", json={
        "photo": garment["photo_front"]["id"], "view": "front", "others": otras,
        "feedback": "El logo sale torcido", "previous": nueva.json()["id"]})
    assert rehecha.status_code == 200 and seen[-1] == ("front", "ropa", ["back"], "El logo sale torcido", True)
    client.post("/api/photos/discard", json={"ids": [rehecha.json()["id"]]})
    # Generar no cambia la prenda.
    assert client.get(f"/api/garments/{garment['id']}").json()["photo_front"]["id"] == garment["photo_front"]["id"]

    # Una que se descarta se borra; una con dueño, no.
    otra = client.post("/api/photos/studio", json={"photo": garment["photo_back"]["id"], "view": "back"}).json()
    client.post("/api/photos/discard", json={"ids": [otra["id"], garment["photo_front"]["id"]]})
    assert not storage.exists(otra["id"]) and storage.exists(garment["photo_front"]["id"])

    editada = client.post(f"/api/garments/{garment['id']}/studio/apply", json={"front": nueva.json()["id"]}).json()
    assert editada["photos_edited"] is True and editada["photo_front"]["id"] == nueva.json()["id"]
    assert editada["photo_back"]["id"] == garment["photo_back"]["id"]
    assert storage.exists(garment["photo_front"]["id"])  # la de la cámara se guarda

    vuelta = client.post(f"/api/garments/{garment['id']}/studio/revert").json()
    assert vuelta["photos_edited"] is False and vuelta["photo_front"]["id"] == garment["photo_front"]["id"]
    assert not storage.exists(nueva.json()["id"])
