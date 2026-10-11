"""Testes da seção "Linha do tempo das vigências" em Contratos Contínuos (11/10/2026).

Mesmo ambiente de `tests/test_contratos_continuos_gov_page.py` (cadastro e fotografia do gov em `tmp_path`, data de
referência 08/10/2026). Somente leitura: a seção não grava nada.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.linha_tempo_vigencias import LinhaDoTempo, Segmento
from src.ui_linha_tempo_vigencias import html_linha
from tests.test_contratos_continuos_gov_page import (
    FIXTURE,
    MANIFESTO_EXECUCAO,
    PAGINA,
    _abrir,
    _ambiente,
    aquecer_pagina,
)

pytestmark = pytest.mark.skipif(
    not (FIXTURE.exists() and MANIFESTO_EXECUCAO.exists()),
    reason="Fixture do Contratos.gov ou manifesto atual da Execução Mensal ausente",
)


@pytest.fixture(scope="module", autouse=True)
def _aquecer():
    aquecer_pagina(PAGINA)


def _secao(app) -> str:
    return " ".join(m.value for m in app.markdown if 'class="ltv-linha"' in m.value)


def test_secao_mostra_uma_linha_por_contrato_com_situacao(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)

    app = _abrir()

    assert any(e.label.startswith("Linha do tempo das vigências") for e in app.expander)
    html = _secao(app)
    assert html.count('class="ltv-linha"') == 4
    for numero in ("13/2026", "29/2021", "99/2026", "18/2014"):
        assert f"<b>{numero}</b>" in html, numero
    assert "Sem ligação ao gov" in html  # 99/2026 não tem par no gov
    assert 'class="ltv-hoje"' in html


def test_busca_e_filtro_de_situacao(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)
    app = _abrir()

    next(t for t in app.text_input if t.key.startswith("ltv_")).input("prime").run()
    assert _secao(app).count('class="ltv-linha"') == 1

    next(t for t in app.text_input if t.key.startswith("ltv_")).input("").run()
    next(s for s in app.selectbox if s.key.startswith("ltv_")).select("Sem ligação ao gov ou sem data").run()
    html = _secao(app)
    assert html.count('class="ltv-linha"') == 1
    assert "<b>99/2026</b>" in html


def test_sem_fotografia_do_gov_mostra_so_o_cadastro(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=False)

    app = _abrir()

    html = _secao(app)
    assert html.count('class="ltv-linha"') == 4
    assert html.count("Sem ligação ao gov") == 4
    assert not app.exception


def test_textos_do_gov_sao_escapados() -> None:
    linha = LinhaDoTempo(
        contrato="01/2026", fornecedor="C&C <LTDA>", ligado=True, fim_gov=date(2027, 1, 1), fim_cadastro=date(2027, 1, 1),
        situacao="Vigente", tom="ok", segmentos=[Segmento(date(2026, 1, 1), date(2027, 1, 1), "TA <1>", "ta")],
    )
    html = html_linha(linha, (date(2024, 1, 1), date(2028, 12, 31)), date(2026, 10, 11))
    assert "C&amp;C &lt;LTDA&gt;" in html
    assert "TA &lt;1&gt;" in html
