"""Acompanhamento de Pessoal — apresentação fiel ao HTML de referência.

Componente HTML único com tabelas semânticas, expansão inline e edição de meses
futuros. Processamento financeiro permanece em src.despesas_pessoal.

Abas (27/09/2026): "Acompanhamento" (o componente), "Fórmulas de projeção" (campos
editáveis dos parâmetros, só na sessão) e "Exercícios anteriores" (execução realizada).
Aba "Folha (DDP)" (27/10/2026): PDFs do SIAPE × saldo dos empenhos da folha (src.ddp_siape).
"""
from datetime import datetime
import gc

import pandas as pd
import streamlit as st

from src.despesas_pessoal import (
    MESES_NOMES, aplicar_overrides, diferencas_do_padrao, consolidar_por_elemento, consolidar_relatorio_ativo,
    dotacao_atualizada_por_acao_beneficios, dotacao_atualizada_por_grupo,
    dotacao_atualizada_por_plano_orcamentario,
    grade_mensal, projetado_beneficios_por_po, quadro_beneficios_por_po_iduso,
    substituir_beneficios_por_plano_orcamentario, ultimo_mes_fechado,
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
from src.ddp_realizado import aplicar_ddp
from src.ddp_siape_arquivos import ArquivoGuardadoInvalido, chave_cache as chave_ddp_guardada, ultima_ddp_completa
from src.ui_ddp_siape import aviso_ddp_aplicada, mes_ano as _mes_ano, render_ddp
from src.ui_despesas_pessoal import montar_painel, render_painel, validar_edicao
from src.ui_despesas_pessoal_abas import (
    calcular_faixa_historica, render_exercicios_anteriores, render_faixa_historica, render_formulas,
)


@st.cache_data(show_spinner="Lendo a base de Execução Anual...")
def _cached_execucao_anual(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_execucao_atual()


@st.cache_data(show_spinner="Lendo a base de Execução Mensal...")
def _cached_execucao_mensal(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_execucao_mensal_atual()


@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_dotacao_anual(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_dotacao_atual()


@st.cache_data(show_spinner="Lendo a DDP guardada...")
def _cached_ddp_guardada(chave: tuple) -> list | None:
    """DDP/Crédito Bancário da competência mais recente com servidor e pensionista (PDFs guardados);
    `chave` = (competência, versão) de cada competência guardada, só para renovar o cache."""
    return ultima_ddp_completa()


# Memória (07/10/2026): a cada interação o `st.cache_data` devolve CÓPIAS das bases (DataFrames
# inteiros), que ficam presas em referências circulares; o coletor do Python dispara pela quantidade de
# objetos, não pelo tamanho, e a sessão subia ~0,25 GB por interação (1,6 → 5,2 GB em 20). Coleta no
# início (lixo da interação anterior, em qualquer caminho — inclusive os `st.stop()`) e no fim. Custo
# ~0,1 s por coleta; nenhum dado é alterado (mesma correção da Consulta de Empenhos).
gc.collect()

# Escopo desta página: o componente tem o espaçamento de 32px do HTML original.
st.html("""<style>
.stMainBlockContainer:has(.st-key-dp_painel) {max-width:none; padding:0 0 5rem;}
.stMainBlockContainer:has(.st-key-dp_painel) [data-testid="stTabs"] [role="tablist"] {padding:0 32px;}
.st-key-dp_aba_formulas, .st-key-dp_aba_historico, .st-key-dp_aba_aviso, .st-key-dp_faixa, .st-key-dp_aba_ddp {padding:8px 32px 0;}
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

aba_painel, aba_ddp, aba_formulas, aba_historico = st.tabs(
    ["Acompanhamento", "Folha (DDP)", "Fórmulas de projeção", "Exercícios anteriores"]
)
# A aba de fórmulas é montada antes do painel: os parâmetros dela alimentam o cálculo.
with aba_formulas, st.container(key="dp_aba_formulas"):
    parametros, erro_parametros = render_formulas()
ajustes_formulas = diferencas_do_padrao(parametros)

# DDP guardada (27/10/2026): prioridade liquidação > DDP guardada > projeção. `mensal` segue sendo a base REAL
# (aba Folha (DDP), conferências); `mensal_painel` é a cópia com o mês da DDP como realizado provisório,
# quando a liquidação ainda não fechou o mês.
try:
    ddp_guardada = _cached_ddp_guardada(chave_ddp_guardada())
    erro_ddp_guardada = None
except ArquivoGuardadoInvalido as erro:
    ddp_guardada, erro_ddp_guardada = None, str(erro)
resultado_ddp = aplicar_ddp(mensal, anual, ddp_guardada, parametros)
mensal_painel = resultado_ddp.mensal
meses_disponiveis = sorted(mensal_painel["ano_mes"].dropna().unique().tolist())  # inclui o mês da DDP aplicada

mes_padrao = (resultado_ddp.competencia if resultado_ddp.aplicada
              else ultimo_mes_fechado(mensal, parametros)) or meses_disponiveis[-1]
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
    render_exercicios_anteriores(anual, mensal_painel, dotacao, ano_corrente, procedencia_bases,
                                 parametros=parametros, mes_referencia_padrao=ano_mes_referencia % 100,
                                 formulas_ajustadas=bool(ajustes_formulas))

with aba_painel:
    if erro_parametros or ajustes_formulas:
        with st.container(key="dp_aba_aviso"):
            if erro_parametros:
                st.error("Parâmetro inválido na aba Fórmulas de projeção — painel calculado com as fórmulas padrão.")
            else:
                st.warning("Projeção com fórmulas ajustadas nesta sessão: " + "; ".join(ajustes_formulas) + ".")

    aviso_ddp = aviso_ddp_aplicada(resultado_ddp, erro_ddp_guardada, ano_mes_referencia)
    if aviso_ddp:
        with st.container(key="dp_aba_aviso"):
            getattr(st, aviso_ddp[0])(aviso_ddp[1])

    bruta = grade_mensal(mensal_painel, anual, ano, ano_mes_referencia, parametros)
    if bruta.linhas.empty:
        st.info("Não há despesas de pessoal nas ações acompanhadas para esta referência.")
        st.stop()
    grade_base = substituir_beneficios_por_plano_orcamentario(
        consolidar_relatorio_ativo(consolidar_por_elemento(bruta)), mensal_painel, anual, parametros,
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
    # Faixa histórica (26/10/2026): calculada uma vez — alimenta os cartões e o aviso "Cenário histórico" do
    # componente (novo visual, 27/10/2026) e o quadro abaixo dele. Só leitura; não entra na projeção nem no saldo.
    faixa = calcular_faixa_historica(mensal_painel, ano, ano_mes_referencia % 100)
    # Outros Benefícios por Ação, PO e Iduso (27/10/2026): mesma projeção do painel (com os ajustes da sessão),
    # dotação do exercício escolhido e empenhado do exercício — fecha com o grupo Outros Benefícios.
    quadro_beneficios = quadro_beneficios_por_po_iduso(
        mensal_painel, anual, dotacao, ano, ano_mes_referencia, ano_dotacao, parametros, projetado_beneficios_por_po(grade),
    )

    procedencia = procedencia_bases + (
        " Fórmulas ajustadas nesta sessão: " + "; ".join(ajustes_formulas) + "."
        if ajustes_formulas else " Fórmulas de projeção: padrão da metodologia."
    ) + (
        f" {_mes_ano(resultado_ddp.competencia)} com valores da DDP do SIAPE (ainda não liquidados)."
        if resultado_ddp.aplicada and ano_mes_referencia == resultado_ddp.competencia else ""
    ) + (
        f" Patronal do RPPS projetado a {bruta.razao_patronal_rpps:.2%} da base do Ativo (vencimentos + gratificação), "
        .replace(".", ",") + ((f"razão do patronal da DDP de {MESES_NOMES[bruta.mes_razao_patronal_rpps - 1].lower()} (rubricas de PSS × 2)."
                               if bruta.patronal_pela_ddp else f"razão observada em {MESES_NOMES[bruta.mes_razao_patronal_rpps - 1].lower()}.")
                              if bruta.mes_razao_patronal_rpps else "razão informada.")
        if bruta.razao_patronal_rpps else ""
    )
    dados = montar_painel(grade, mensal_painel, anual, dotacao_grupo, ano_dotacao,
                          meses_disponiveis=meses_disponiveis, anos_dotacao=anos_dotacao,
                          procedencia=procedencia, editados=edicoes,
                          dotacao_por_plano_orcamentario=dotacao_por_po,
                          dotacao_por_acao_beneficios=dotacao_por_acao_beneficios, faixa=faixa,
                          quadro_beneficios=quadro_beneficios)
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

    with st.container(key="dp_faixa"):
        projetado_por_grupo = grade.total_por_grupo_por_mes().sum(axis=1, min_count=1)
        render_faixa_historica(faixa, ano, ano_mes_referencia % 100, projetado_por_grupo, dotacao_grupo, ano_dotacao)

# Folha (DDP) (27/10/2026): PDFs do SIAPE só em memória; a reserva dos meses seguintes vem da grade por
# natureza detalhada (`bruta`, antes da consolidação), com as fórmulas da sessão.
with aba_ddp, st.container(key="dp_aba_ddp"):
    render_ddp(mensal, bruta.linhas, ano, procedencia_bases, dotacao_grupo, dotacao, ano_dotacao)

gc.collect()  # ver o comentário no início da página
