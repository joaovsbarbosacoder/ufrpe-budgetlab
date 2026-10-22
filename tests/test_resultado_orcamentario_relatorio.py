"""Testes de `src/resultado_orcamentario_relatorio.py` — relatório HTML do Resultado Orçamentário (22/10/2026).

Reaproveita os builders sintéticos de `tests/test_resultado_orcamentario.py`. O relatório só repete os números da tela: em todo
cenário o total do detalhamento precisa fechar com os cartões.
"""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

from src.resultado_orcamentario import OUTRAS_DESPESAS
from src.resultado_orcamentario_cadastro import DespesaManual, ReceitaPropria
from src.resultado_orcamentario_detalhe import detalhar_por_gnd_acao
from src.resultado_orcamentario_relatorio import html_relatorio
from tests.test_resultado_orcamentario import (
    A,
    B,
    R1050,
    _calc,
    _celulas,
    _empenhos_padrao,
    _manual,
)

EMITIDO = datetime(2026, 10, 22, 14, 40)


def _receita(valor, considerada=True, descricao="Arrecadação fonte 1050", id_="r1"):
    return ReceitaPropria(id_, descricao, valor, "Balanço", "2026-10-22", "2026-10-22", considerada)


def _celulas_1050(dot=1000.0) -> pd.DataFrame:
    extra = pd.DataFrame({
        "chave": [R1050], "dotacao_atualizada": pd.array([dot], dtype="Float64"),
        "fonte_recursos_detalhada_codigo": ["1050000000"], "fonte_recursos_detalhada_descricao": ["RECURSOS PROPRIOS LIVRES DA UO"],
    })
    return pd.concat([_celulas(), extra], ignore_index=True)


def _gerar(receitas=None, despesas=None, selecao=None, dot_1050=1000.0, **kw):
    despesas = [_manual()] if despesas is None else despesas
    selecao = selecao or [A, B, R1050]
    celulas = _celulas_1050(dot_1050)
    res = _calc(celulas=celulas, selecao=selecao, receitas_proprias=receitas, despesas_manuais=despesas, **kw)
    det = detalhar_por_gnd_acao(res, celulas, _empenhos_padrao(), selecao, despesas)
    return res, det, html_relatorio(res, det, despesas, receitas or [], 2026, len(selecao), 57, EMITIDO)


def test_relatorio_traz_as_cinco_secoes_e_nao_traz_avisos_nem_celulas_nem_rastreabilidade():
    _, _, html = _gerar(receitas=[_receita(300.0)])
    titulos = re.findall(r'<h2[^>]*><span class="n">(\d)</span>([^<]+)', html)
    assert [n for n, _ in titulos] == ["1", "2", "3", "4", "5"]
    assert [t for _, t in titulos] == [
        "Resumo", "Composição", "Detalhamento por GND, Ação e Fonte", "Receitas próprias arrecadadas", OUTRAS_DESPESAS,
    ]
    for ausente in ("Avisos", "Células selecionadas", "Fontes de dados e rastreabilidade"):
        assert ausente not in html


def test_cartoes_repetem_os_numeros_da_regra():
    res, _, html = _gerar(receitas=[_receita(300.0)])
    assert res.resultado is not None
    esperado = f"R&#36; {res.resultado:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    assert esperado in html and "Superávit" in html
    assert "3 de 57 células" in html and "22/10/2026 14:40" in html


def test_detalhamento_mostra_a_fonte_em_cada_linha_e_a_1050_em_linha_propria():
    _, _, html = _gerar(receitas=[_receita(300.0)])
    assert "Fonte 1000000000" in html
    assert "Fonte 1050000000 · RECURSOS PROPRIOS LIVRES DA UO" in html and html.count('class="fonte f1050"') == 1
    assert "✓ A soma das linhas confere com os cartões" in html


def test_nota_da_arrecadacao_so_quando_ultrapassa_a_dotacao():
    _, _, passa = _gerar(receitas=[_receita(1500.0)], dot_1050=1000.0)
    assert passa.count("acima da dotação ficam fora") == 1 and "R&#36; 500,00 acima" in passa
    _, _, nao_passa = _gerar(receitas=[_receita(300.0)], dot_1050=1000.0)
    assert "acima da dotação ficam fora" not in nao_passa


def test_receitas_sem_lancamento_sem_efeito_e_desconsiderada():
    _, _, vazio = _gerar(receitas=[])
    assert "Nenhuma receita própria cadastrada" in vazio
    _, _, fora = _gerar(receitas=[_receita(10.0, considerada=False)])
    assert "Nenhum lançamento considerado" in fora and "Desconsiderada" in fora
    _, _, sem_efeito = _gerar(receitas=[_receita(300.0)], selecao=[A, B])
    assert "não está marcada: a arrecadação não tem efeito" in sem_efeito


def test_outras_despesas_listam_consideradas_e_desconsideradas_com_os_totais():
    despesas = [_manual(40.0, id_="1"), _manual(25.0, considerada=False, id_="2")]
    res, _, html = _gerar(despesas=despesas)
    assert res.projetado[OUTRAS_DESPESAS] == 40.0
    assert "Considerada" in html and "Desconsiderada" in html
    assert "Total cadastrado</td><td class=\"n\">R&#36; 65,00" in html
    assert "Desconsiderado (fora da conta do resultado)</td><td class=\"n\">R&#36; 25,00" in html


def test_sem_despesas_cadastradas_avisa():
    _, _, html = _gerar(despesas=[])
    assert "Nenhuma despesa prevista cadastrada" in html


def test_texto_de_cadastro_e_escapado():
    despesa = DespesaManual("1", "<script>alert(1)</script>", 10.0, "a & b", None, "2026-01-01", "2026-01-01", True)
    _, _, html = _gerar(despesas=[despesa], receitas=[_receita(5.0, descricao="<b>x</b>")])
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html and "a &amp; b" in html


def test_resultado_incompleto_mostra_traco_e_nao_zero():
    celulas = _celulas_1050()
    celulas.loc[celulas["chave"] == A, "dotacao_atualizada"] = pd.NA
    res = _calc(celulas=celulas, selecao=[A, B])
    det = detalhar_por_gnd_acao(res, celulas, _empenhos_padrao(), [A, B], [_manual()])
    html = html_relatorio(res, det, [_manual()], [], 2026, 2, 57, EMITIDO)
    assert res.resultado is None and "Incompleto" in html and "—" in html
