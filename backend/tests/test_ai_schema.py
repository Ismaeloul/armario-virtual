import json

import pytest
from conftest import VALID_DRAFT, FakeAnalyzer

from app import catalog
from app.services.ai import selector
from app.services.ai.base import OUTPUT_SCHEMA, AnalysisError, parse_draft


def test_respuesta_valida():
    draft = parse_draft(json.dumps(VALID_DRAFT))
    assert draft.type == "chaqueta"
    assert draft.color_primary.name == "negro"


def test_acepta_json_envuelto_en_bloque_de_codigo():
    assert parse_draft("```json\n" + json.dumps(VALID_DRAFT) + "\n```").name == "Bomber negra"


@pytest.mark.parametrize(
    "campo, valor",
    [
        ("season", "primavera"),  # solo verano / invierno / todo_el_ano
        ("type", "bufanda"),
        ("pattern", "lunares"),
        ("style", "gótico"),
        ("color_primary", {"name": "turquesa", "hex": "#00ffff"}),
        ("color_primary", {"name": "negro", "hex": "negro"}),
        ("confidence", 1.5),
    ],
)
def test_valores_fuera_de_las_listas_cuentan_como_fallo(campo, valor):
    with pytest.raises(AnalysisError):
        parse_draft(json.dumps({**VALID_DRAFT, campo: valor}))


def test_json_roto_cuenta_como_fallo():
    with pytest.raises(AnalysisError):
        parse_draft("no puedo ver la imagen")


def test_el_esquema_de_salida_usa_las_listas_cerradas():
    props = OUTPUT_SCHEMA["properties"]
    assert props["type"]["enum"] == list(catalog.TYPES)
    assert props["season"]["enum"] == ["verano", "invierno", "todo_el_ano"]
    assert set(OUTPUT_SCHEMA["required"]) == set(props)


def test_usa_el_proveedor_preferido(analyzers):
    codex, claude = analyzers(
        FakeAnalyzer("codex", json.dumps(VALID_DRAFT)), FakeAnalyzer("claude", json.dumps(VALID_DRAFT))
    )
    result = selector.analyze([], preferred="codex", prompt="x")
    assert (result.provider, result.fallback_used) == ("codex", False)
    assert claude.calls == 0


def test_pasa_al_plan_b_y_lo_dice(analyzers):
    analyzers(
        FakeAnalyzer("codex", error=AnalysisError("sin sesión")), FakeAnalyzer("claude", json.dumps(VALID_DRAFT))
    )
    result = selector.analyze([], preferred="codex", prompt="x")
    assert (result.provider, result.fallback_used) == ("claude", True)
    assert result.draft is not None


def test_respuesta_invalida_tambien_activa_el_plan_b(analyzers):
    analyzers(
        FakeAnalyzer("codex", json.dumps({**VALID_DRAFT, "season": "otoño"})),
        FakeAnalyzer("claude", json.dumps(VALID_DRAFT)),
    )
    assert selector.analyze([], preferred="codex", prompt="x").provider == "claude"


def test_si_fallan_los_dos_hay_error_claro(analyzers):
    analyzers(FakeAnalyzer("codex", is_available=False), FakeAnalyzer("claude", error=AnalysisError("sin saldo")))
    result = selector.analyze([], preferred="codex", prompt="x")
    assert result.draft is None and result.provider is None
    assert "codex" in result.error and "claude" in result.error


def test_lee_el_enlace_y_el_codigo_del_login_de_codex():
    from app.services.ai.codex_login import parse_device_prompt

    salida = (
        "Welcome to Codex [v\x1b[90m0.169.0\x1b[0m]\n\n"
        "1. Open this link in your browser and sign in to your account\n"
        "   \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n\n"
        "2. Enter this one-time code \x1b[90m(expires in 15 minutes)\x1b[0m\n"
        "   \x1b[94mABCD-12345\x1b[0m\n"
    )
    assert parse_device_prompt(salida) == ("https://auth.openai.com/codex/device", "ABCD-12345")
    assert parse_device_prompt("Welcome to Codex") == (None, None)


def test_el_prompt_explica_que_foto_es_cada_una():
    from app.services.ai.base import build_prompt

    solo = build_prompt(has_back=False, has_label=False)
    assert "una foto" in solo and "trasera" not in solo and "No adivines" in solo

    completo = build_prompt(has_back=True, has_label=True)
    assert "3 fotos" in completo
    assert "Foto 2: la parte trasera" in completo and "Foto 3: la etiqueta" in completo
    assert "léelos de la foto de la etiqueta" in completo

    # Sin trasera, la etiqueta pasa a ser la foto 2.
    assert "Foto 2: la etiqueta" in build_prompt(has_back=False, has_label=True)


def test_resumen_de_los_limites_de_codex():
    from app.services.ai.codex_usage import parse_rate_limits

    usage = parse_rate_limits({
        "ordinaryUsageAllowed": True,
        "rateLimits": {
            "planType": "plus",
            "primary": {"usedPercent": 2, "windowDurationMins": 300, "resetsAt": 1794956350},
            "secondary": {"usedPercent": 0, "windowDurationMins": 10080, "resetsAt": 1795543150},
        },
    })
    assert usage["plan"] == "plus" and usage["allowed"] is True
    assert usage["primary"] == {"used_percent": 2, "window_minutes": 300, "resets_at": 1794956350}
    assert parse_rate_limits({})["primary"] is None


def test_la_ia_puede_decir_entre_que_colores_dudaba():
    assert parse_draft(json.dumps(VALID_DRAFT)).color_primary_alt is None
    assert parse_draft(json.dumps({**VALID_DRAFT, "color_primary_alt": "gris"})).color_primary_alt == "gris"
    with pytest.raises(AnalysisError):
        parse_draft(json.dumps({**VALID_DRAFT, "color_primary_alt": "antracita"}))
    assert None in OUTPUT_SCHEMA["properties"]["color_primary_alt"]["enum"]


def test_lo_que_se_pasa_de_largo_se_recorta_en_vez_de_fallar():
    raw = {
        **VALID_DRAFT,
        "notes": "x" * 700,
        "name": "n" * 200,
        "color_primary": {"name": "negro", "hex": "#000"},
        "colors_secondary": [{"name": c, "hex": "#fff"} for c in ["blanco", "gris", "rojo", "azul", "verde"]],
    }
    draft = parse_draft(json.dumps(raw))
    assert len(draft.notes) == 500 and len(draft.name) == 120
    assert draft.color_primary.hex == "#000000"
    assert [c.name for c in draft.colors_secondary] == ["blanco", "gris", "rojo", "azul"]
    assert draft.colors_secondary[0].hex == "#ffffff"


def test_un_error_inesperado_de_un_proveedor_pasa_al_otro(analyzers):
    analyzers(FakeAnalyzer("codex", error=TypeError("SDK raro")), FakeAnalyzer("claude", json.dumps(VALID_DRAFT)))
    result = selector.analyze([], preferred="codex", prompt="x")
    assert (result.provider, result.fallback_used) == ("claude", True)


def test_el_tiempo_con_nulos_se_queda_sin_tiempo(monkeypatch):
    from app.services import weather

    monkeypatch.setattr(weather, "_locate", lambda city, client: (49.0, 2.2, "Argenteuil"))

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "current": {"temperature_2m": None, "weather_code": 0},
                "daily": {"temperature_2m_max": [None], "temperature_2m_min": [None],
                          "precipitation_probability_max": [None], "weather_code": [0]},
            }

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(weather.httpx, "Client", _Client)
    weather._forecasts.clear()
    assert weather.today("Ciudad con nulos") is None


def test_el_lector_de_limites_no_espera_si_codex_se_cierra_sin_responder(monkeypatch):
    import subprocess
    import sys
    import time

    from app.services.ai import codex_usage

    codex_usage.forget()
    monkeypatch.setattr(codex_usage.shutil, "which", lambda _: sys.executable)
    real_popen = subprocess.Popen

    def fake_popen(cmd, **kwargs):  # un "codex" que termina enseguida sin decir nada
        return real_popen([sys.executable, "-c", "pass"], **kwargs)

    monkeypatch.setattr(codex_usage.subprocess, "Popen", fake_popen)
    start = time.time()
    with pytest.raises(RuntimeError):
        codex_usage.read(timeout=10)
    assert time.time() - start < 5
    with pytest.raises(RuntimeError):  # el fallo se recuerda un rato
        codex_usage.read(timeout=10)
    codex_usage.forget()
