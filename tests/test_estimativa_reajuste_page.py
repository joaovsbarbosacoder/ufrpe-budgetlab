"""Testes da seção "Estimativa de reajuste" em Contratos Contínuos (11/10/2026).

Mesmo ambiente de `tests/test_contratos_continuos_gov_page.py`: cadastro e fotografia do Contratos.gov em
`tmp_path`, data de referência fixa; nada é gravado em `data/` e nenhuma chamada de rede é feita (nenhum
contrato usa índice oficial). Os cálculos têm teste próprio em `tests/test_estimativa_reajuste.py`; aqui só a
integração da tela. Limitação do AppTest: só a primeira execução de um `@st.dialog` é alcançável.
"""

from __future__ import annotations

import pandas as pd
import pytest

import src.contratos_continuos_cadastro as cadastro
from tests.test_contratos_continuos_gov_page import (
    FIXTURE,
    MANIFESTO_EXECUCAO,
    _abrir,
    _ambiente,
    aquecer_pagina,
    PAGINA,
)

pytestmark = pytest.mark.skipif(
    not (FIXTURE.exists() and MANIFESTO_EXECUCAO.exists()),
    reason="Fixture do Contratos.gov ou manifesto atual da Execução Mensal ausente",
)


@pytest.fixture(scope="module", autouse=True)
def _aquecer():
    aquecer_pagina(PAGINA)


def _tabela_resumo(app):
    return next(d.value for d in app.dataframe if "Competências sem estimativa" in d.value.columns)


def test_secao_lista_cada_contrato_e_usa_o_percentual_manual(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)
    registro = next(r for r in cadastro.carregar_contratos(2026) if r["contrato_numero"] == "13/2026")
    cadastro.atualizar_contrato(2026, {**registro, "reajuste_percentual_manual": 5.0})

    app = _abrir()

    assert any(e.label.startswith("Estimativa de reajuste") for e in app.expander)
    resumo = _tabela_resumo(app).set_index("Contrato")
    assert {"13/2026", "29/2021", "99/2026", "18/2014"} <= set(resumo.index)
    # 13/2026: ligado ao gov (início 10/09/2026, fim 10/09/2027) → data-base 10/09/2027, 5% manual. O único
    # acréscimo é o de 09/2027: 10 de 30 dias em vigor (R$ 1.000 × 10/30) × 5% × 21/30 do mês após a data-base
    assert resumo.loc["13/2026", "Situação"] == "Estimado"
    assert resumo.loc["13/2026", "Percentual (%)"] == 5.0
    assert resumo.loc["13/2026", "Origem do %"] == "Manual"
    assert resumo.loc["13/2026", "Acréscimo 2026"] == 0.0  # antes da data-base nada incide: zero conhecido
    assert resumo.loc["13/2026", "Acréscimo na vigência"] == pytest.approx(1000 * 10 / 30 * 0.05 * 21 / 30)
    # sem início de vigência (não ligado ao gov) e sem data manual: acréscimo desconhecido (nulo), nunca zero
    assert resumo.loc["99/2026", "Situação"].startswith("Sem data-base")
    assert pd.isna(resumo.loc["99/2026", "Acréscimo na vigência"])
    assert resumo.loc["99/2026", "Competências sem estimativa"] == 13
    # contratos encerrados no cadastro: sem ciclo na vigência, e sem valor (não R$ 0,00)
    assert resumo.loc["29/2021", "Situação"].startswith("Sem reajuste previsto")
    assert pd.isna(resumo.loc["29/2021", "Acréscimo na vigência"])


def test_configuracao_vazia_nao_inventa_percentual(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=False)

    app = _abrir()

    resumo = _tabela_resumo(app)
    assert resumo["Percentual (%)"].isna().all()  # sem índice nem manual: nulo, nunca 0%
    metricas = {m.label: m.value for m in app.metric}
    assert metricas["Acréscimo na vigência"] == "—"  # nenhum contrato tem valor: traço, nunca "R$ 0,00"
    assert metricas["Contratos sem estimativa"] == str(len(resumo))  # todos sem data-base
    assert not app.exception


def test_botao_configurar_abre_a_janela_com_os_campos(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)
    app = _abrir()

    botao = next(b for b in app.button if b.label == "Configurar reajuste")
    botao.click().run()

    assert not app.exception, [e.value for e in app.exception]
    assert "Índice" in [s.label for s in app.selectbox]
    assert "Percentual manual (%)" in [n.label for n in app.number_input]
