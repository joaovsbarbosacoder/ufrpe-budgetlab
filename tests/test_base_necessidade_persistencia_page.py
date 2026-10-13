"""A "Base da necessidade de empenho" (Contratos Contínuos) é lembrada entre sessões (12/10/2026).

Preferências em `tmp_path` (nada é gravado em `data/`). Mesmo ambiente de `tests/test_contratos_continuos_gov_page.py`.
"""

from __future__ import annotations

import json

import pytest

from src import preferencias_ui
from tests._apptest import aquecer_pagina
from tests.test_contratos_continuos_gov_page import FIXTURE, MANIFESTO_EXECUCAO, PAGINA, _abrir, _ambiente

pytestmark = pytest.mark.skipif(
    not (FIXTURE.exists() and MANIFESTO_EXECUCAO.exists()),
    reason="Fixture do Contratos.gov ou manifesto atual da Execução Mensal ausente",
)

ROTULO = "Base da necessidade de empenho"


@pytest.fixture(scope="module", autouse=True)
def _aquecer():
    aquecer_pagina(PAGINA)


def _radio(app):
    return next((r for r in app.radio if r.label == ROTULO), None)


def test_escolha_e_lembrada_numa_nova_sessao_e_o_padrao_e_o_valor_contratual(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=False)
    monkeypatch.setattr(preferencias_ui, "DIRETORIO_PADRAO", tmp_path / "preferencias")

    app = _abrir()
    radio = _radio(app)
    if radio is None:
        pytest.skip("Liquidação por Competência indisponível neste ambiente: o seletor não aparece")
    assert radio.value == "Valor contratual"  # sem preferência salva
    assert not (tmp_path / "preferencias").exists()  # abrir a página não grava nada

    radio.set_value("Projeção pela execução").run()
    assert not app.exception, [e.value for e in app.exception]
    salvo = json.loads((tmp_path / "preferencias" / "ui.json").read_text(encoding="utf-8"))
    assert salvo["preferencias"]["contratos_continuos.base_necessidade"] == "Projeção pela execução"

    nova_sessao = _abrir()  # sessão nova: session_state vazio, lê do arquivo
    assert _radio(nova_sessao).value == "Projeção pela execução"

    _radio(nova_sessao).set_value("Valor contratual").run()
    assert _radio(_abrir()).value == "Valor contratual"


def test_arquivo_de_preferencias_ilegivel_avisa_e_usa_o_valor_contratual(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=False)
    monkeypatch.setattr(preferencias_ui, "DIRETORIO_PADRAO", tmp_path / "preferencias")
    (tmp_path / "preferencias").mkdir()
    (tmp_path / "preferencias" / "ui.json").write_text("{ quebrado", encoding="utf-8")

    app = _abrir()

    if _radio(app) is None:
        pytest.skip("Liquidação por Competência indisponível neste ambiente: o seletor não aparece")
    assert _radio(app).value == "Valor contratual"
    assert any("Preferências de tela ilegíveis" in w.value for w in app.warning)
    assert (tmp_path / "preferencias" / "ui.json").read_text(encoding="utf-8") == "{ quebrado"  # intacto
