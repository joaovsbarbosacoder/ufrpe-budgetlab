"""HTML dos cartões e da Composição do Resultado Orçamentário (`src/ui_resultado_orcamentario.py`)."""

from __future__ import annotations

import pandas as pd

from src.ui_resultado_orcamentario import (
    LinhaComposicao,
    html_bloco,
    html_cabecalho_acao,
    html_cartoes,
    html_celula,
    html_dotacao_acao,
    html_rodape_totais,
    percentual,
    situacao_resultado,
)


def test_situacao_resultado():
    assert situacao_resultado(10.0) == ("pos", "Superávit")
    assert situacao_resultado(-1.0) == ("neg", "Déficit")
    assert situacao_resultado(0.0) == ("neu", "Equilíbrio")
    assert situacao_resultado(None) == ("neu", "Incompleto")


def test_cartoes_superavit_e_nulo_vira_traco():
    html = html_cartoes(1000.0, "1 de 5 células", 400.0, None, 600.0, "60% da dotação")
    assert 'class="ro-card res pos"' in html
    assert "Superávit" in html
    assert "R&#36; 1.000,00" in html  # cifrão protegido, nunca "$" cru
    assert "R$" not in html.split("</style>")[1]
    assert "—" in html  # necessidade nula


def test_cartao_deficit():
    assert 'class="ro-card res neg"' in html_cartoes(1.0, "", 2.0, 3.0, -4.0, "")


def test_percentual_com_total_nulo_ou_zero():
    assert percentual(25.0, 100.0) == "25%"
    assert percentual(25.0, None) == "—"
    assert percentual(None, 100.0) == "—"
    assert percentual(1.0, 0.0) == "—"


def test_bloco_linhas_detalhe_e_total():
    detalhe = pd.DataFrame({"NE": ["2026NE000001"], "Empenhado": [400.0]})
    html = html_bloco(
        "Empenhado",
        [
            LinhaComposicao("Contratos Contínuos", 400.0, detalhe, ("Empenhado",)),
            LinhaComposicao("Outros empenhos", 100.0, None, vazio="Nenhuma NE."),
        ],
        500.0, "Total empenhado", "✓ fecha", "ok",
    )
    assert html.count("<details>") == 2
    assert "80%" in html and "20%" in html
    assert "2026NE000001" in html and "R&#36; 400,00" in html
    assert "Nenhuma NE." in html
    assert "R&#36; 500,00" in html and 'class="ro-check ok"' in html
    assert 'style="width:80.0%"' in html


def test_bloco_total_nulo_sem_percentual_nem_barra():
    html = html_bloco("Necessidade", [LinhaComposicao("Contratos", 300.0)], None, "Total da necessidade")
    assert "%</span>" not in html
    assert 'style="width:0.0%"' in html
    assert ">—</span>" in html


def test_cabecalho_acao():
    html = html_cabecalho_acao("4002", "ASSISTENCIA AO ESTUDANTE", 4, 1)
    assert "4002" in html and "ASSISTENCIA AO ESTUDANTE" in html
    assert "4 células" in html and "1 selecionada" in html
    assert "R&#36; 15.674.953,00" in html_dotacao_acao(15674953.0)
    assert "selecionada" not in html_cabecalho_acao("8282", "X", 1, 0)
    assert "1 célula<" in html_cabecalho_acao("8282", "X", 1, 0)


def test_celula_valores_pt_br_e_barra():
    html = html_celula(("0", "2", "4002", "230400", "0002", "3", "1000000000"), 8943623.0, 6707523.21, 2236099.79)
    for trecho in ("PTRES <b>230400</b>", "PO <b>0002</b>", "Fonte <b>1000000000</b>", "IDUSO <b>0</b>", "RP <b>2</b>"):
        assert trecho in html
    assert "R&#36; 8.943.623,00" in html and "R&#36; 6.707.523,21" in html
    assert "75% empenhado" in html and 'style="width:75.0%"' in html


def test_celula_dotacao_nula_sem_barra():
    html = html_celula(("0",) * 7, None, 10.0, None)
    assert html.count(">—<") == 2
    assert "— empenhado" in html and 'style="width:0.0%"' in html


def test_celula_barra_alta_a_partir_de_90():
    assert "ro-barra alto" in html_celula(("0",) * 7, 100.0, 95.0, 5.0)
    assert "ro-barra alto" not in html_celula(("0",) * 7, 100.0, 50.0, 50.0)


def test_rodape_totais():
    html = html_rodape_totais(100.0, None, 40.0)
    assert "R&#36; 100,00" in html and "—" in html and "R&#36; 40,00" in html


def test_bloco_escapa_html():
    html = html_bloco("T", [LinhaComposicao("<b>x</b>", 1.0)], 1.0, "Total")
    assert "<b>x</b>" not in html and "&lt;b&gt;" in html
