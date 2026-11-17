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
