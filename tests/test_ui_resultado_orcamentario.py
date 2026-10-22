"""HTML dos cartões e da Composição do Resultado Orçamentário (`src/ui_resultado_orcamentario.py`)."""

from __future__ import annotations

import re

import pandas as pd

from src.ui_resultado_orcamentario import (
    LinhaComposicao,
    html_bloco,
    html_cabecalho_acao,
    html_cartoes,
    html_celula,
    html_detalhe_gnd_acao,
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


def test_cartoes_no_criterio_executado_projetado_sem_cartao_de_anulacao():
    html = html_cartoes(1000.0, "", 400.0, 100.0, 500.0, "")
    assert "(−) Executado nas células" in html and "(−) Projetado a realizar" in html
    assert "Anulação" not in html and "Empenhado nas células" not in html
    assert len(re.findall(r'<div class="ro-card[ "]', html)) == 4  # dotação, executado, projetado e resultado


def test_detalhe_gnd_acao_agrupa_nos_dois_sentidos_e_nulo_vira_traco():
    linhas = pd.DataFrame([
        {"tipo": "celula", "gnd": "3", "gnd_descricao": "OUTRAS CORRENTES", "acao": "20RK", "acao_descricao": "FUNCIONAMENTO",
         "dotacao": 100.0, "executado": 40.0, "projetado": 30.0, "resultado": 30.0},
        {"tipo": "celula", "gnd": "4", "gnd_descricao": "INVESTIMENTOS", "acao": "20RK", "acao_descricao": "FUNCIONAMENTO",
         "dotacao": 50.0, "executado": None, "projetado": None, "resultado": None},
        {"tipo": "sem_celula", "gnd": None, "gnd_descricao": None, "acao": None, "acao_descricao": None,
         "dotacao": 0.0, "executado": 0.0, "projetado": 20.0, "resultado": -20.0},
    ])
    total = (150.0, None, None, None)
    por_gnd = html_detalhe_gnd_acao(linhas, total, "gnd")
    por_acao = html_detalhe_gnd_acao(linhas, total, "acao")

    assert por_gnd.count("<details") == 2 and por_acao.count("<details") == 1  # 2 GNDs; 1 só ação
    assert "GND 3" in por_gnd and "20RK" in por_acao
    assert "Sem célula" in por_gnd and "Total do bolsão" in por_gnd
    assert "Déficit" in por_gnd and "Superávit" in por_gnd
    assert "R&#36; 0,00" in por_gnd  # a linha sem célula tem dotação zero, não nula
    # nulo é "—", nunca R$ 0,00: o GND 4 só tem dotação
    gnd4 = por_gnd[por_gnd.index("GND 4"):]
    assert "—" in gnd4[:gnd4.index("</summary>")]


def test_detalhe_gnd_acao_sem_linhas_pede_selecao():
    vazio = pd.DataFrame(columns=["tipo", "gnd", "gnd_descricao", "acao", "acao_descricao", "dotacao", "executado", "projetado", "resultado"])
    assert "Marque ao menos uma célula" in html_detalhe_gnd_acao(vazio, (0.0, 0.0, 0.0, 0.0))


def test_detalhe_gnd_acao_abrir_controla_os_grupos():
    linhas = pd.DataFrame([
        {"tipo": "celula", "gnd": g, "gnd_descricao": None, "acao": "20RK", "acao_descricao": None,
         "dotacao": 100.0, "executado": 40.0, "projetado": 30.0, "resultado": 30.0}
        for g in ("3", "4")
    ])
    total = (200.0, 80.0, 60.0, 60.0)

    assert html_detalhe_gnd_acao(linhas, total, "gnd").count("<details open>") == 1  # padrão: só o primeiro
    assert html_detalhe_gnd_acao(linhas, total, "gnd", abrir=True).count("<details open>") == 2
    assert html_detalhe_gnd_acao(linhas, total, "gnd", abrir=False).count("<details open>") == 0
    assert 'class="mini"' in html_detalhe_gnd_acao(linhas, total, "gnd")  # barra de consumo da dotação


def _linha_ui(fonte, dotacao, **extra):
    return {"tipo": "celula", "gnd": "3", "gnd_descricao": None, "acao": "20RK", "acao_descricao": None, "dotacao": dotacao,
            "executado": 0.0, "projetado": 0.0, "resultado": dotacao, "fonte": fonte, "fonte_descricao": "RECURSOS PROPRIOS LIVRES DA UO",
            **extra}


def test_detalhe_gnd_acao_mostra_a_fonte_em_cada_linha_e_destaca_a_1050():
    linhas = pd.DataFrame([_linha_ui("1000000000", 100.0), _linha_ui("1050000000", 50.0)])
    html = html_detalhe_gnd_acao(linhas, (150.0, 0.0, 0.0, 150.0), "gnd")
    assert "Fonte 1000000000" in html and "Fonte 1050000000 · RECURSOS PROPRIOS LIVRES DA UO" in html
    assert html.count("fonte f1050") == 1 and "destaque" in html
    sem_coluna = linhas.drop(columns=["fonte", "fonte_descricao"])
    assert "Fonte 1050" not in html_detalhe_gnd_acao(sem_coluna, (150.0, 0.0, 0.0, 150.0), "gnd")


def test_nota_da_arrecadacao_so_aparece_quando_ultrapassa_a_dotacao():
    passa = pd.DataFrame([_linha_ui("1050000000", 415401.8, receita_limite=447514.78, receita_excedente=32112.98)])
    html = html_detalhe_gnd_acao(passa, (415401.8, 0.0, 0.0, 415401.8), "gnd")
    assert html.count("acima da dotação ficam fora") == 1  # só na linha da 1050, nunca no grupo nem no total
    assert "informado R&#36; 447.514,78" in html and "R&#36; 32.112,98 acima" in html

    nao_passa = pd.DataFrame([_linha_ui("1050000000", 415401.8, receita_limite=300000.0, receita_excedente=0.0)])
    assert "acima da dotação" not in html_detalhe_gnd_acao(nao_passa, (415401.8, 0.0, 0.0, 415401.8), "gnd")
