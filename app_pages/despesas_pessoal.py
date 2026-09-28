"""Acompanhamento de Pessoal — apresentação fiel ao HTML de referência.

Componente HTML único com tabelas semânticas, expansão inline e edição de meses
futuros. Processamento financeiro permanece em src.despesas_pessoal.

Abas (27/09/2026): "Acompanhamento" (o componente), "Fórmulas de projeção" (campos
editáveis dos parâmetros, só na sessão) e "Exercícios anteriores" (execução realizada).
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from src.despesas_pessoal import (
    aplicar_overrides, diferencas_do_padrao, consolidar_por_elemento, consolidar_relatorio_ativo,
    dotacao_atualizada_por_acao_beneficios, dotacao_atualizada_por_grupo,
    dotacao_atualizada_por_plano_orcamentario,
    grade_mensal, substituir_beneficios_por_plano_orcamentario, ultimo_mes_fechado,
)
from src.importacao_dotacao import (
    DIRETORIO_MANIFESTOS_PADRAO as DIRETORIO_MANIFESTOS_DOTACAO,
    Manifesto as ManifestoDotacao, NOME_PONTEIRO as NOME_PONTEIRO_DOTACAO,
    carregar_atual as carregar_dotacao_atual,
)
from src.importacao_execucao import (
    DIRETORIO_MANIFESTOS_PADRAO as DIRETORIO_MANIFESTOS_EXECUCAO,
    Manifesto as ManifestoExecucao, NOME_PONTEIRO as NOME_PONTEIRO_EXECUCAO,
    carregar_atual as carregar_execucao_atual,
)
from src.importacao_execucao_mensal import (
    DIRETORIO_MANIFESTOS_PADRAO as DIRETORIO_MANIFESTOS_EXECUCAO_MENSAL,
    Manifesto as ManifestoExecucaoMensal, NOME_PONTEIRO as NOME_PONTEIRO_EXECUCAO_MENSAL,
    carregar_atual as carregar_execucao_mensal_atual,
)
from src.ui_despesas_pessoal import montar_painel, render_painel, validar_edicao
from src.ui_despesas_pessoal_abas import render_exercicios_anteriores, render_formulas


@st.cache_data(show_spinner="Lendo a base de Execução Anual...")
def _cached_execucao_anual(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_execucao_atual()


@st.cache_data(show_spinner="Lendo a base de Execução Mensal...")
def _cached_execucao_mensal(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_execucao_mensal_atual()


@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_dotacao_anual(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_dotacao_atual()


# Escopo desta página: o componente tem o espaçamento de 32px do HTML original.
st.html("""<style>
.stMainBlockContainer:has(.st-key-dp_painel) {max-width:none; padding:0 0 3rem;}
.stMainBlockContainer:has(.st-key-dp_painel) [data-testid="stTabs"] [role="tablist"] {padding:0 32px;}
.st-key-dp_aba_formulas, .st-key-dp_aba_historico, .st-key-dp_aba_aviso {padding:8px 32px 0;}
</style>""")

manifesto_execucao = ManifestoExecucao.atual()
manifesto_dotacao = ManifestoDotacao.atual()
manifesto_execucao_mensal = ManifestoExecucaoMensal.atual()
if manifesto_execucao is None or manifesto_dotacao is None or manifesto_execucao_mensal is None:
    st.info(
        "Este painel precisa da Execução Anual, da Dotação Anual e da Execução Mensal já "
        'importadas (menu "Atualizar Planilhas"). Falta: '
        + ", ".join(
            nome for nome, ok in (
                ("Execução Anual", manifesto_execucao is not None),
                ("Dotação Anual", manifesto_dotacao is not None),
                ("Execução Mensal", manifesto_execucao_mensal is not None),
            )
            if not ok
        )
        + "."
    )
    st.stop()

caminho_ponteiro_execucao = DIRETORIO_MANIFESTOS_EXECUCAO / NOME_PONTEIRO_EXECUCAO
caminho_ponteiro_dotacao = DIRETORIO_MANIFESTOS_DOTACAO / NOME_PONTEIRO_DOTACAO
caminho_ponteiro_execucao_mensal = DIRETORIO_MANIFESTOS_EXECUCAO_MENSAL / NOME_PONTEIRO_EXECUCAO_MENSAL
try:
    anual = _cached_execucao_anual(str(caminho_ponteiro_execucao), caminho_ponteiro_execucao.stat().st_mtime)
    mensal = _cached_execucao_mensal(
        str(caminho_ponteiro_execucao_mensal), caminho_ponteiro_execucao_mensal.stat().st_mtime
    )
    dotacao = _cached_dotacao_anual(str(caminho_ponteiro_dotacao), caminho_ponteiro_dotacao.stat().st_mtime)
except Exception as error:
    st.error(f"Não foi possível ler as bases necessárias: {error}")
    st.stop()

meses_disponiveis = sorted(mensal["ano_mes"].dropna().unique().tolist())
if not meses_disponiveis:
    st.warning("A base mensal não tem nenhum mês com dado.")
    st.stop()

aba_painel, aba_formulas, aba_historico = st.tabs(["Acompanhamento", "Fórmulas de projeção", "Exercícios anteriores"])
# A aba de fórmulas é montada antes do painel: os parâmetros dela alimentam o cálculo.
with aba_formulas, st.container(key="dp_aba_formulas"):
    parametros, erro_parametros = render_formulas()
ajustes_formulas = diferencas_do_padrao(parametros)

mes_padrao = ultimo_mes_fechado(mensal, parametros) or meses_disponiveis[-1]
anos_dotacao = sorted(int(v) for v in dotacao["ano_lancamento"].dropna().unique())
if not anos_dotacao:
    st.warning("A base de Dotação não contém exercícios disponíveis.")
    st.stop()
ano_mes_referencia = st.session_state.get("dp_referencia", int(mes_padrao))
if ano_mes_referencia not in meses_disponiveis:
    ano_mes_referencia = int(mes_padrao)
ano = ano_mes_referencia // 100
ano_dotacao = st.session_state.get("dp_ano_dotacao", ano if ano in anos_dotacao else anos_dotacao[-1])
if ano_dotacao not in anos_dotacao:
    ano_dotacao = anos_dotacao[-1]

def data_extracao(manifesto):
    return datetime.fromisoformat(manifesto.data_extracao).strftime("%d/%m/%Y")

procedencia_bases = (
    f"Procedência: Execução Anual, extração de {data_extracao(manifesto_execucao)}, "
    f"hash {manifesto_execucao.sha256[:8]}; Dotação Anual, extração de "
    f"{data_extracao(manifesto_dotacao)}, hash {manifesto_dotacao.sha256[:8]}; "
    f"Execução Mensal, extração de {data_extracao(manifesto_execucao_mensal)}, "
    f"hash {manifesto_execucao_mensal.sha256[:8]}. "
    "As bases possuem datas de extração independentes."
)

with aba_historico, st.container(key="dp_aba_historico"):
    ano_corrente = max([int(v) for v in anual["ano"].dropna().unique()] + [int(meses_disponiveis[-1]) // 100])
    render_exercicios_anteriores(anual, mensal, dotacao, ano_corrente, procedencia_bases,
                                 parametros=parametros, mes_referencia_padrao=ano_mes_referencia % 100,
                                 formulas_ajustadas=bool(ajustes_formulas))

with aba_painel:
    if erro_parametros or ajustes_formulas:
        with st.container(key="dp_aba_aviso"):
            if erro_parametros:
                st.error("Parâmetro inválido na aba Fórmulas de projeção — painel calculado com as fórmulas padrão.")
            else:
                st.warning("Projeção com fórmulas ajustadas nesta sessão: " + "; ".join(ajustes_formulas) + ".")

    bruta = grade_mensal(mensal, anual, ano, ano_mes_referencia, parametros)
    if bruta.linhas.empty:
        st.info("Não há despesas de pessoal nas ações acompanhadas para esta referência.")
        st.stop()
    grade_base = substituir_beneficios_por_plano_orcamentario(
        consolidar_relatorio_ativo(consolidar_por_elemento(bruta)), mensal, anual, parametros,
    )
    chave_edicoes = f"dp_edicoes_{ano_mes_referencia}"
    # Conserva ajustes da interface anterior, se a sessão ainda os possuir.
    if chave_edicoes not in st.session_state:
        legados = {}
        if not st.session_state.get("dp_legados_migrados", False):
            for grupo in ("ativo", "inativo", "rpps", "outros_beneficios"):
                legados.update(st.session_state.get(f"dp_overrides_{grupo}", {}))
            st.session_state["dp_legados_migrados"] = True
        st.session_state[chave_edicoes] = legados
    edicoes = st.session_state[chave_edicoes]
    grade = aplicar_overrides(grade_base, edicoes) if edicoes else grade_base
    dotacao_grupo = dotacao_atualizada_por_grupo(dotacao, ano_dotacao)
    dotacao_por_po = dotacao_atualizada_por_plano_orcamentario(dotacao, ano_dotacao)
    dotacao_por_acao_beneficios = dotacao_atualizada_por_acao_beneficios(dotacao, ano_dotacao)

    procedencia = procedencia_bases + (
        " Fórmulas ajustadas nesta sessão: " + "; ".join(ajustes_formulas) + "."
        if ajustes_formulas else " Fórmulas de projeção: padrão da metodologia."
    )
    dados = montar_painel(grade, mensal, anual, dotacao_grupo, ano_dotacao,
                          meses_disponiveis=meses_disponiveis, anos_dotacao=anos_dotacao,
                          procedencia=procedencia, editados=edicoes,
                          dotacao_por_plano_orcamentario=dotacao_por_po,
                          dotacao_por_acao_beneficios=dotacao_por_acao_beneficios)
    resultado = render_painel(dados)
    if resultado.edicao:
        try:
            chave, mes, valor = validar_edicao(resultado.edicao, grade_base)
        except ValueError as erro:
            st.error(str(erro))
        else:
            novo = {k: dict(v) for k, v in edicoes.items()}
            novo.setdefault(chave, {})[mes] = valor
            st.session_state[chave_edicoes] = novo
            st.rerun()
    if resultado.filtros:
        filtros = resultado.filtros
        if filtros.get("referencia") in meses_disponiveis and filtros.get("anoDotacao") in anos_dotacao:
            st.session_state["dp_referencia"] = int(filtros["referencia"])
            st.session_state["dp_ano_dotacao"] = int(filtros["anoDotacao"])
            st.rerun()
    if resultado.restaurar and resultado.restaurar.get("referencia") == ano_mes_referencia:
        st.session_state[chave_edicoes] = {}
        st.rerun()
