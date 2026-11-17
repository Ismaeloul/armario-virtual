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
    result = selector.analyze([], preferred="codex")
    assert (result.provider, result.fallback_used) == ("codex", False)
    assert claude.calls == 0


def test_pasa_al_plan_b_y_lo_dice(analyzers):
    analyzers(
        FakeAnalyzer("codex", error=AnalysisError("sin sesión")), FakeAnalyzer("claude", json.dumps(VALID_DRAFT))
    )
    result = selector.analyze([], preferred="codex")
    assert (result.provider, result.fallback_used) == ("claude", True)
    assert result.draft is not None


def test_respuesta_invalida_tambien_activa_el_plan_b(analyzers):
    analyzers(
        FakeAnalyzer("codex", json.dumps({**VALID_DRAFT, "season": "otoño"})),
        FakeAnalyzer("claude", json.dumps(VALID_DRAFT)),
    )
    assert selector.analyze([], preferred="codex").provider == "claude"


def test_si_fallan_los_dos_hay_error_claro(analyzers):
    analyzers(FakeAnalyzer("codex", is_available=False), FakeAnalyzer("claude", error=AnalysisError("sin saldo")))
    result = selector.analyze([], preferred="codex")
    assert result.draft is None and result.provider is None
    assert "codex" in result.error and "claude" in result.error
