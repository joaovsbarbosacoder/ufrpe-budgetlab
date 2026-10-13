"""Testes da página "Reajuste estimado" (11/10/2026; página própria e repaginada em 12/10/2026).

Mesmo ambiente de `tests/test_contratos_continuos_gov_page.py`: cadastro e fotografia do Contratos.gov em `tmp_path`,
data de referência fixa; nada é gravado em `data/` e nenhuma chamada de rede é feita (nenhum contrato usa índice oficial).
Os cálculos têm teste próprio em `tests/test_estimativa_reajuste.py` e o HTML em `tests/test_ui_reajuste_visual.py`; aqui só
a integração da tela. Limitação do AppTest: só a primeira execução de um `@st.dialog` é alcançável.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import src.contratos_continuos_cadastro as cadastro
from src.contratos_aditivos import Aditivo, aditivo_para_registro
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


def test_linha_do_tempo_do_contrato_mostra_o_reajuste_ja_registrado(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)
    registro = next(r for r in cadastro.carregar_contratos(2026) if r["contrato_numero"] == "13/2026")
    registrado = Aditivo(
        numero="1", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2026, 9, 10), valor_mensal=1100.0,
    )
    cadastro.atualizar_contrato(2026, {**registro, "aditivos": [aditivo_para_registro(registrado)]})

    app = _abrir()
    seletor = next(s for s in app.selectbox if s.label == "Detalhar contrato")
    seletor.select("13/2026").run()

    assert not app.exception, [e.value for e in app.exception]
    html = _html(app)
    assert "R$ 1.100,00/mês · registrado" in html
    assert "10/09/2026" in html


def _com_reajuste_assinado_sem_valor(tmp_path, monkeypatch):
    """13/2026 (início 10/09/2026) com um aditivo de Reajuste ASSINADO sem valor mensal um ano depois (10/09/2027): ciclo
    formalizado "a confirmar" (a regra de anualidade ignora reajuste a menos de um ano do início do contrato)."""
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)
    registro = next(r for r in cadastro.carregar_contratos(2026) if r["contrato_numero"] == "13/2026")
    sem_valor = Aditivo(numero="TA 5", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2027, 9, 10), valor_mensal=None)
    cadastro.atualizar_contrato(2026, {**registro, "reajuste_percentual_manual": 5.0, "aditivos": [aditivo_para_registro(sem_valor)]})
    return registro["id"]


def _abrir_detalhe_13_2026() -> AppTest:
    app = _abrir()
    next(s for s in app.selectbox if s.label == "Detalhar contrato").select("13/2026").run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def test_registrar_reajuste_formalizado_completa_o_aditivo_sem_duplicar(tmp_path, monkeypatch) -> None:
    id_registro = _com_reajuste_assinado_sem_valor(tmp_path, monkeypatch)
    app = _abrir_detalhe_13_2026()

    assert "Registrar reajuste formalizado" in _html(app)
    campo = next(n for n in app.number_input if n.label == "Novo valor mensal (R$)")
    assert campo.value == pytest.approx(1050.0)  # sugestão: R$ 1.000 em vigor × (1 + 5%)
    assert next(t for t in app.text_input if t.label == "Nº do termo").value == "TA 5"  # mantém o termo já cadastrado

    campo.set_value(1100.0).run()
    next(b for b in app.button if b.label == "Registrar reajuste").click().run()
    assert not app.exception, [e.value for e in app.exception]

    gravado = next(r for r in cadastro.carregar_contratos(2026) if r["id"] == id_registro)
    assert len(gravado["aditivos"]) == 1  # completou o existente: nada de duplicata
    assert gravado["aditivos"][0]["numero"] == "TA 5" and gravado["aditivos"][0]["valor_mensal"] == 1100.0
    app = _abrir_detalhe_13_2026()
    assert "R$ 1.100,00/mês · registrado" in _html(app)
    assert "Registrar reajuste formalizado" not in _html(app)  # o ciclo saiu do "a confirmar"


def test_sem_percentual_nao_ha_valor_sugerido_e_registrar_sem_valor_nao_grava_nada(tmp_path, monkeypatch) -> None:
    id_registro = _com_reajuste_assinado_sem_valor(tmp_path, monkeypatch)
    registro = next(r for r in cadastro.carregar_contratos(2026) if r["id"] == id_registro)
    # sem percentual manual e com índice desconhecido: o ciclo continua formalizado, mas sem percentual → sem valor sugerido
    cadastro.atualizar_contrato(2026, {**registro, "reajuste_percentual_manual": None, "reajuste_indice": "SEM_INDICE"})
    app = _abrir_detalhe_13_2026()

    campo = next(n for n in app.number_input if n.label == "Novo valor mensal (R$)")
    assert campo.value is None  # nada inventado: sem percentual, o campo começa vazio (nunca 0)
    next(b for b in app.button if b.label == "Registrar reajuste").click().run()

    assert any("Informe o novo valor mensal" in e.value for e in app.error)
    gravado = next(r for r in cadastro.carregar_contratos(2026) if r["id"] == id_registro)
    assert gravado["aditivos"][0]["valor_mensal"] is None  # nada foi gravado


def test_nada_e_gravado_ao_abrir_a_pagina_nem_ao_ver_o_formulario(tmp_path, monkeypatch) -> None:
    id_registro = _com_reajuste_assinado_sem_valor(tmp_path, monkeypatch)
    antes = next(r for r in cadastro.carregar_contratos(2026) if r["id"] == id_registro)

    _abrir_detalhe_13_2026()

    assert next(r for r in cadastro.carregar_contratos(2026) if r["id"] == id_registro) == antes


def test_quadro_a_registrar_lista_o_ciclo_formalizado_e_fica_vazio_sem_ele(tmp_path, monkeypatch) -> None:
    _ambiente(tmp_path, monkeypatch, com_fotografia=True)
    assert "Nenhum reajuste formalizado a registrar" in _html(_abrir())  # sem ciclo formalizado: nada a registrar

    _com_reajuste_assinado_sem_valor(tmp_path, monkeypatch)
    html = _html(_abrir())

    assert "1 reajuste formalizado a registrar" in html
    assert "<b>13/2026</b>" in html and "ciclo de <b>10/09/2027</b>" in html
    assert "R$ 1.050,00" in html  # novo valor mensal sugerido: R$ 1.000 × (1 + 5%)


def test_registrar_pelo_quadro_completa_o_aditivo_sem_duplicar_e_o_item_sai_da_lista(tmp_path, monkeypatch) -> None:
    id_registro = _com_reajuste_assinado_sem_valor(tmp_path, monkeypatch)
    app = _abrir()

    campo = next(n for n in app.number_input if n.label == "Novo valor mensal do termo (R$)")
    assert campo.value == pytest.approx(1050.0)
    assert next(t for t in app.text_input if t.label == "Nº do termo do reajuste").value == "TA 5"
    campo.set_value(1100.0).run()
    next(b for b in app.button if b.label == "Registrar reajuste selecionado").click().run()
    assert not app.exception, [e.value for e in app.exception]

    gravado = next(r for r in cadastro.carregar_contratos(2026) if r["id"] == id_registro)
    assert len(gravado["aditivos"]) == 1 and gravado["aditivos"][0]["valor_mensal"] == 1100.0
    assert "Nenhum reajuste formalizado a registrar" in _html(_abrir())


def test_quadro_sem_percentual_nao_sugere_valor_e_vazio_nao_grava(tmp_path, monkeypatch) -> None:
    id_registro = _com_reajuste_assinado_sem_valor(tmp_path, monkeypatch)
    registro = next(r for r in cadastro.carregar_contratos(2026) if r["id"] == id_registro)
    cadastro.atualizar_contrato(2026, {**registro, "reajuste_percentual_manual": None, "reajuste_indice": "SEM_INDICE"})
    app = _abrir()

    assert "informe o valor do termo" in _html(app)
    campo = next(n for n in app.number_input if n.label == "Novo valor mensal do termo (R$)")
    assert campo.value is None  # nunca 0
    next(b for b in app.button if b.label == "Registrar reajuste selecionado").click().run()

    assert any("Informe o novo valor mensal" in e.value for e in app.error)
    assert next(r for r in cadastro.carregar_contratos(2026) if r["id"] == id_registro)["aditivos"][0]["valor_mensal"] is None
