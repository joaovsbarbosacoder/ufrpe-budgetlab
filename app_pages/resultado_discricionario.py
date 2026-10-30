"""Página "Discricionário por Plano" (pedido do usuário, 29/10/2026): os quadros do discricionário (Resultado Primário 2) por Plano
Orçamentário, em página própria no menu.

Antes eram uma seção do Resultado Orçamentário; o usuário preferiu uma página à parte. A conta é a mesma do resultado, só que sobre
TODAS as células do RP2, marcadas ou não (a seleção de células do Resultado Orçamentário não interfere aqui):
`src/resultado_orcamentario_planos.py` reparte dotação, executado e projetado por Ação e Plano (e por fonte), e
`src/ui_resultado_planos.py` desenha os quadros. As leituras com cache e a montagem da necessidade de Contratos e Bolsas são as da
página do Resultado, em `src/ui_resultado_dados.py`. Só lê: nada é gravado aqui (despesas previstas e receitas próprias são cadastradas
no Resultado Orçamentário).

Filtros (pedido do usuário, 30/10/2026): Ação, Plano Orçamentário (só os das Ações escolhidas), Fonte (o quadro passa a somar só as
fontes escolhidas) e Situação do saldo — `filtrar_planos`, só exibição. Com filtro, os totais somam o que está visível e saem as
linhas avulsas e a conferência com o resultado, que só valem para o total.
"""

from __future__ import annotations

import gc
from datetime import datetime

import pandas as pd
import streamlit as st

from src import resultado_orcamentario_cadastro as cadastro
from src.importacao_dotacao import DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_DOTACAO
from src.importacao_dotacao import Manifesto as ManifestoDotacao
from src.importacao_dotacao import NOME_PONTEIRO as PONTEIRO_DOTACAO
from src.importacao_execucao_mensal import DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_EXECUCAO_MENSAL
from src.importacao_execucao_mensal import Manifesto as ManifestoExecucaoMensal
from src.importacao_execucao_mensal import NOME_PONTEIRO as PONTEIRO_EXECUCAO_MENSAL
from src.relatorio_necessidade_empenho import mes_referencia_do_exercicio
from src.resultado_orcamentario import ORIGEM_BOLSAS, ORIGEM_CONTRATOS, calcular_resultado, separar_ativos_sem_ne
from src.resultado_orcamentario_cadastro import ArquivoCorrompido
from src.resultado_orcamentario_planos import (
    SITUACOES,
    filtrar_planos,
    opcoes_filtros,
    planos_discricionarios,
    selecao_discricionaria,
)
from src.ui_resultado_dados import (
    CAMINHO_LIQUIDACAO_COMPETENCIA,
    cached_celulas_por_exercicio,
    cached_execucao,
    cached_lancamento,
    cached_liquidacao_competencia,
    necessidade_origem,
)
from src.ui_resultado_planos import html_planos_discricionarios
from src.ui_theme import render_page_header

# Memória (mesma correção do Resultado Orçamentário): coleta no início e no fim. Nenhum dado é alterado.
gc.collect()

render_page_header(
    "Discricionário por Plano Orçamentário",
    "Quanto da dotação de cada Plano do discricionário já foi consumido, e o que falta até dezembro?",
    "Planejamento",
)

manifesto_dotacao = ManifestoDotacao.atual()
manifesto_execucao = ManifestoExecucaoMensal.atual()
if manifesto_dotacao is None or manifesto_execucao is None:
    st.info(
        "Esta página precisa da Dotação Anual e da Execução Mensal já importadas (menu "
        '"Atualizar Planilhas"). Falta: '
        + ", ".join(
            nome for nome, ok in (
                ("Dotação Anual", manifesto_dotacao is not None),
                ("Execução Mensal", manifesto_execucao is not None),
            )
            if not ok
        )
        + "."
    )
    st.stop()

ponteiro_dotacao = DIR_MANIFESTOS_DOTACAO / PONTEIRO_DOTACAO
ponteiro_execucao = DIR_MANIFESTOS_EXECUCAO_MENSAL / PONTEIRO_EXECUCAO_MENSAL
try:
    celulas_por_exercicio = cached_celulas_por_exercicio(str(ponteiro_dotacao), ponteiro_dotacao.stat().st_mtime)
except Exception as erro:
    st.error(f"Não foi possível ler a Dotação Anual: {erro}")
    st.stop()
anos = sorted(celulas_por_exercicio)
if not anos:
    st.info("A Dotação Anual importada não tem nenhum exercício.")
    st.stop()

data_dotacao = datetime.fromisoformat(manifesto_dotacao.data_extracao)
data_execucao = datetime.fromisoformat(manifesto_execucao.data_extracao)
ano_padrao = data_dotacao.year if data_dotacao.year in anos else max(anos)

col_exercicio, col_datas = st.columns([1, 5], vertical_alignment="bottom")
with col_exercicio:
    exercicio = int(
        st.selectbox(
            "Exercício", anos, index=anos.index(ano_padrao), key="rd_exercicio",
            format_func=lambda ano: f"{ano} (em andamento)" if ano == ano_padrao else str(ano),
        )
    )
with col_datas:
    st.caption(
        f"Dotação Anual · extração de {data_dotacao:%d/%m/%Y}  |  "
        f"Execução Mensal · extração de {data_execucao:%d/%m/%Y}  |  "
        "Executado e projetado: projeção pela execução  |  Resultado Primário 2 (discricionário)"
    )

try:
    empenhado, por_ne_execucao, sugestao_inicio = cached_execucao(
        str(ponteiro_execucao), ponteiro_execucao.stat().st_mtime, exercicio
    )
except Exception as erro:
    st.error(f"Não foi possível ler a Execução Mensal: {erro}")
    st.stop()

celulas = celulas_por_exercicio[exercicio]

avisos_extras: list[str] = []
indice_competencia: pd.Series | None = None
competencia: pd.DataFrame | None = None
lancamento: pd.DataFrame | None = None
if CAMINHO_LIQUIDACAO_COMPETENCIA.exists():
    try:
        indice_competencia, competencia = cached_liquidacao_competencia(
            str(CAMINHO_LIQUIDACAO_COMPETENCIA), CAMINHO_LIQUIDACAO_COMPETENCIA.stat().st_mtime
        )
        lancamento = cached_lancamento(str(ponteiro_execucao), ponteiro_execucao.stat().st_mtime)
    except Exception as erro:
        avisos_extras.append(f"Não foi possível ler a Liquidação por Competência ({erro}).")
else:
    avisos_extras.append(f"Liquidação por Competência não encontrada ('{CAMINHO_LIQUIDACAO_COMPETENCIA}').")

mes_referencia = mes_referencia_do_exercicio(data_execucao.date(), exercicio)
fontes: dict[str, tuple] = {}
for origem in (ORIGEM_CONTRATOS, ORIGEM_BOLSAS):
    try:
        tabela, linhas, sem_ne, motivo, avisos_projecao, _relatorio = necessidade_origem(
            origem, exercicio, por_ne_execucao, sugestao_inicio, indice_competencia, competencia, mes_referencia, lancamento,
        )
    except Exception as erro:
        tabela, linhas, sem_ne, motivo, avisos_projecao = (
            pd.DataFrame(columns=["ne_curta"]), None, pd.DataFrame(), f"erro de leitura ({erro})", [],
        )
    if motivo:
        avisos_extras.append(f"Necessidade de {origem} indisponível: {motivo}.")
    avisos_extras.extend(f"Projeção de {origem}: {aviso}" for aviso in avisos_projecao)
    fontes[origem] = (tabela, linhas, sem_ne)

try:
    despesas = cadastro.carregar_despesas(exercicio, diretorio=cadastro.DIRETORIO_PADRAO)
    receitas = cadastro.carregar_receitas(exercicio, diretorio=cadastro.DIRETORIO_PADRAO)
except ArquivoCorrompido as erro:
    st.error(
        f"{erro}. O cadastro de despesas previstas ou de receitas próprias não pôde ser lido; corrija ou restaure o arquivo "
        "(no Resultado Orçamentário) — os quadros não são calculados com cadastro ilegível."
    )
    st.stop()

tabela_contratos_df, linhas_contratos, sem_ne_contratos = fontes[ORIGEM_CONTRATOS]
tabela_bolsas_df, linhas_bolsas, sem_ne_bolsas = fontes[ORIGEM_BOLSAS]
ativos_sem_ne, _ = separar_ativos_sem_ne(sem_ne_contratos)

resultado_rp2 = calcular_resultado(
    celulas, empenhado, selecao_discricionaria(celulas), tabela_contratos_df, tabela_bolsas_df,
    linhas_contratos, linhas_bolsas, sem_ne_contratos, sem_ne_bolsas, despesas, receitas,
)
planos = planos_discricionarios(resultado_rp2, celulas, empenhado, despesas, ativos_sem_ne)


def _multiselect(coluna, rotulo: str, chave: str, opcoes: dict[str, str]) -> list[str]:
    # seleção que deixou de existir (outro exercício, Ação desmarcada) sai antes do widget, que recusaria valor fora das opções
    if chave in st.session_state:
        st.session_state[chave] = [v for v in st.session_state[chave] if v in opcoes]
    with coluna:
        return st.multiselect(rotulo, list(opcoes), format_func=opcoes.get, key=chave, placeholder="Todos")


# Filtros (30/10/2026): só escolhem o que aparece; a conta acima é sempre sobre todo o discricionário.
col_acao, col_plano, col_fonte, col_situacao = st.columns([3, 3, 2, 2])
opcoes_acao, _, _ = opcoes_filtros(planos)
acoes_escolhidas = _multiselect(col_acao, "Ação", "rd_f_acao", opcoes_acao)
_, opcoes_plano, _ = opcoes_filtros(planos, acoes_escolhidas)
planos_escolhidos = _multiselect(col_plano, "Plano Orçamentário", "rd_f_plano", opcoes_plano)
_, _, opcoes_fonte = opcoes_filtros(planos, acoes_escolhidas, planos_escolhidos)
fontes_escolhidas = _multiselect(col_fonte, "Fonte", "rd_f_fonte", opcoes_fonte)
situacoes_escolhidas = _multiselect(col_situacao, "Situação", "rd_f_situacao", {s: s for s in SITUACOES})

st.html(html_planos_discricionarios(filtrar_planos(
    planos, acoes=acoes_escolhidas, planos=planos_escolhidos, fontes=fontes_escolhidas, situacoes=situacoes_escolhidas,
)))
if fontes_escolhidas:
    st.caption("Com o filtro de Fonte, cada quadro mostra só as fontes escolhidas: dotação, executado, projetado e saldo delas.")

avisos = [*avisos_extras, *resultado_rp2.avisos, *planos.avisos]
if avisos:
    with st.expander(f"Avisos ({len(avisos)})"):
        for aviso in dict.fromkeys(avisos):
            st.caption(aviso.replace("$", "&#36;"))

st.caption(
    "A seleção de células do Resultado Orçamentário não interfere aqui: todas as células do discricionário entram. As despesas "
    "previstas e as receitas próprias são cadastradas no Resultado Orçamentário; a fonte 1050 da 20RK já vem limitada pela "
    "arrecadação própria informada."
)

gc.collect()  # ver o comentário no início da página
