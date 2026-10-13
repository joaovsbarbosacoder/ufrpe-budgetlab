"""Testes da página "Reajuste estimado" (11/10/2026; página própria e repaginada em 12/10/2026).

Mesmo ambiente de `tests/test_contratos_continuos_gov_page.py`: cadastro e fotografia do Contratos.gov em `tmp_path`,
data de referência fixa; nada é gravado em `data/` e nenhuma chamada de rede é feita (nenhum contrato usa índice oficial).
Os cálculos têm teste próprio em `tests/test_estimativa_reajuste.py` e o HTML em `tests/test_ui_reajuste_visual.py`; aqui só
a integração da tela. Limitação do AppTest: só a primeira execução de um `@st.dialog` é alcançável.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import src.contratos_continuos_cadastro as cadastro
from tests._apptest import TEMPO_LIMITE_APPTEST, aquecer_pagina
from tests.test_contratos_continuos_gov_page import FIXTURE, MANIFESTO_EXECUCAO, REF, _ambiente

PAGINA_REAJUSTE = str(Path(__file__).resolve().parents[1] / "app_pages" / "reajuste_estimado.py")

pytestmark = pytest.mark.skipif(
    not (FIXTURE.exists() and MANIFESTO_EXECUCAO.exists()),
    reason="Fixture do Contratos.gov ou manifesto atual da Execução Mensal ausente",
)


@pytest.fixture(scope="module", autouse=True)
def _aquecer():
    aquecer_pagina(PAGINA_REAJUSTE)


def _abrir() -> AppTest:
    app = AppTest.from_file(PAGINA_REAJUSTE, default_timeout=TEMPO_LIMITE_APPTEST)
    app.session_state["contratos_referencia"] = REF
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def _html(app: AppTest) -> str:
    return " ".join(m.value for m in app.markdown)


def _tabela_resumo(app) -> str:
    """HTML da "Tabela completa por contrato" (todas as linhas, com os totais)."""
    return next(m.value for m in app.markdown if "rj-resumo" in m.value)


def _linha(app, contrato: str) -> str:
    """A linha (<tr>) de um contrato na tabela completa."""
    return _tabela_resumo(app).split(f"<b>{contrato}</b>")[1].split("</tr>")[0]


def test_pagina_lista_cada_contrato_e_usa_o_percentual_manual(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)
    registro = next(r for r in cadastro.carregar_contratos(2026) if r["contrato_numero"] == "13/2026")
    cadastro.atualizar_contrato(2026, {**registro, "reajuste_percentual_manual": 5.0})

    app = _abrir()

    assert "Reajuste estimado em 2026" in _html(app)
    for contrato in ("13/2026", "29/2021", "99/2026", "18/2014"):
        assert f"<b>{contrato}</b>" in _tabela_resumo(app)
    # 13/2026: ligado ao gov (início 10/09/2026, fim 10/09/2027) → data-base 10/09/2027, 5% manual. O único
    # acréscimo é o de 09/2027: 10 de 30 dias em vigor (R$ 1.000 × 10/30) × 5% × 21/30 do mês após a data-base
    linha = _linha(app, "13/2026")
    assert "Estimado" in linha and "5,00 %" in linha and "Manual" in linha
    assert "R$ 0,00" in linha  # acréscimo de 2026: antes da data-base nada incide — zero conhecido
    assert "R$ 11,67" in linha  # acréscimo na vigência: 1000 × 10/30 × 5% × 21/30
    # sem início de vigência (não ligado ao gov) e sem data manual: acréscimo desconhecido (nulo), nunca zero
    linha = _linha(app, "99/2026")
    assert "Sem estimativa" in linha and "falta a data-base" in linha
    assert "13 competência(s) sem estimativa" in linha
    assert "R$" not in linha  # nenhum valor (nem R$ 0,00): tudo nulo
    # contratos encerrados no cadastro: sem ciclo na vigência, e sem valor (não R$ 0,00)
    linha = _linha(app, "29/2021")
    assert "Sem reajuste previsto" in linha and "R$" not in linha


def test_lista_mostra_numero_com_o_nome_do_credor_e_contrato_sem_estimativa_visivel(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)

    html = _html(_abrir())

    assert "<b>13/2026</b>" in html and "PRIME CONSULTORIA" in html  # só o número, acompanhado do nome do credor
    assert "<b>99/2026</b>" in html and "SEM PAR LTDA" in html
    assert "Sem estimativa" in html and "falta a data-base" in html  # 99/2026 não some: aparece com o motivo
    assert "Quem mais pesa em 2026" in html and "Mapa de 2026" in html


def test_sem_configuracao_o_indice_padrao_e_o_ipca_oficial(tmp_path, monkeypatch) -> None:
    # a série fixa de tests/conftest.py tem 0,40% ao mês: acumulado de 12 meses = 1,004^12 − 1 = 4,9102...%
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)

    app = _abrir()

    linha = _linha(app, "13/2026")
    assert "Oficial (12 meses)" in linha
    assert f"{(1.004**12 - 1) * 100:.2f} %".replace(".", ",") in linha  # 4,91 %


def test_resumo_separa_formalizado_projetado_e_exercicios_anteriores(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)

    app = _abrir()

    tabela = _tabela_resumo(app)
    for cabecalho in ("Formalizado a confirmar 2026", "Projetado 2026", "Exercícios anteriores", "Observações", "Próximo ciclo"):
        assert cabecalho in tabela, cabecalho
    assert "Projetado" in _linha(app, "13/2026")  # sem reajuste no gov: o próximo ciclo é projetado
    html = _html(app)
    for rotulo in ("Formalizado a confirmar", "Projetado", "Exercícios anteriores", "Sem estimativa"):
        assert rotulo in html, rotulo


def test_configuracao_vazia_nao_inventa_percentual(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=False)

    app = _abrir()

    tabela = _tabela_resumo(app)
    assert " %" not in tabela.replace("Percentual", "")  # sem índice nem manual: nenhum percentual (nulo, nunca 0%)
    html = _html(app)
    # nenhum contrato tem valor: o destaque mostra traço, nunca "R$ 0"
    destaque = html[html.index("Reajuste estimado em 2026"):][:1500]
    assert "R$ 0" not in destaque
    contratos = tabela.count("<tr><td><b>")
    assert f"{contratos} contratos" in destaque  # todos sem data-base
    assert not app.exception


def test_botao_configurar_abre_a_janela_com_os_campos(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)
    app = _abrir()

    botao = next(b for b in app.button if b.label == "Configurar reajuste")
    botao.click().run()

    assert not app.exception, [e.value for e in app.exception]
    assert "Índice" in [s.label for s in app.selectbox]
    assert "Percentual manual (%)" in [n.label for n in app.number_input]
