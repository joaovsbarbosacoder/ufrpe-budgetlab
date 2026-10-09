"""Diário Oficial (DOU) — baixa as edições do DOU pelo INLABS e lista as matérias que citam a
UFRPE (ou os termos que o usuário acrescentar).

Toda a lógica (download incremental, leitura dos ZIPs, busca) vive em `src/dou_inlabs.py`;
esta página só monta a interface.

Credenciais: só das variáveis de ambiente `INLABS_EMAIL`/`INLABS_SENHA` (ver
`docs/dou_inlabs.md`). A página não pede nem guarda senha — sem elas, o botão fica
desabilitado e a página continua mostrando o que já foi baixado.

Termos de busca: dois grupos — "Termos de busca" (a matéria cita algum deles) e "Refinar"
(opcional: também precisa citar algum destes), ver `dou_inlabs._Busca`. Pedido de 09/10/2026: um
termo geral como "pregão" sozinho trazia o país inteiro; com "Refinar", vira "pregões da UFRPE".
As duas listas são salvas em `data/dou/termos.json` a cada mudança (persistência aprovada em
09/10/2026) e lidas uma vez por sessão; "Restaurar termos padrão" volta aos padrões. Como a busca
roda sobre os ZIPs já baixados, um termo novo também alcança os dias anteriores, sem novo
download.

Desempenho: cada ZIP é lido e filtrado XML a XML (`ler_e_filtrar_zip`), em cache por
(arquivo, sha256, termos) — trocar o período reaproveita o cache; trocar os termos relê os ZIPs
do período (um dia do DOU tem milhares de matérias, não cabem todas em memória).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from src import dou_inlabs
from src.dou_inlabs import TERMOS_UFRPE_PADRAO, ClienteInlabs, ErroInlabs
from src.ui_theme import render_alert, render_metric_grid, render_page_header

FUSO = ZoneInfo("America/Recife")
_CHAVE_MENSAGEM = "dou_mensagem"
_PERIODO_PADRAO_DIAS = 30


@st.cache_data(show_spinner=False, max_entries=512)
def _ler_filtrado(caminho: str, sha256: str, termos: tuple[str, ...], refinar: tuple[str, ...]) -> pd.DataFrame:
    # sha256 entra só na chave do cache: um ZIP diferente gravado no mesmo caminho não
    # aproveitaria o resultado antigo.
    return dou_inlabs.ler_e_filtrar_zip(caminho, termos, refinar)


_CHAVE_TERMOS = "dou_termos"
_CHAVE_REFINAR = "dou_refinar"
_CHAVE_AVISO_TERMOS = "dou_termos_aviso"


def _iniciar_termos() -> None:
    """Uma vez por sessão: os widgets de termos partem do que está salvo em disco."""

    if _CHAVE_TERMOS in st.session_state:
        return
    salvos = dou_inlabs.carregar_termos(dou_inlabs.DIRETORIO_TERMOS)
    st.session_state[_CHAVE_TERMOS] = list(salvos.termos)
    st.session_state[_CHAVE_REFINAR] = list(salvos.refinar)
    st.session_state[_CHAVE_AVISO_TERMOS] = salvos.aviso


def _salvar_termos() -> None:
    try:
        dou_inlabs.salvar_termos(
            st.session_state.get(_CHAVE_TERMOS, []),
            st.session_state.get(_CHAVE_REFINAR, []),
            dou_inlabs.DIRETORIO_TERMOS,
        )
    except OSError as erro:
        st.session_state[_CHAVE_AVISO_TERMOS] = f"Não foi possível salvar os termos ({type(erro).__name__})."
    else:
        st.session_state[_CHAVE_AVISO_TERMOS] = None


def _restaurar_termos() -> None:
    st.session_state[_CHAVE_TERMOS] = list(TERMOS_UFRPE_PADRAO)
    st.session_state[_CHAVE_REFINAR] = []
    _salvar_termos()


def _opcoes(chave: str, base: tuple[str, ...] = ()) -> list[str]:
    # termos acrescentados em sessões anteriores precisam estar entre as opções do widget
    return list(dict.fromkeys([*base, *st.session_state.get(chave, [])]))


def _sem_vazio(serie: pd.Series) -> pd.Series:
    return serie.where(serie.fillna("").str.strip() != "")


def _hoje() -> date:
    return datetime.now(FUSO).date()


def _credenciais_ok() -> bool:
    try:
        dou_inlabs.credenciais_do_ambiente()
    except ErroInlabs:
        return False
    return True


def _texto_resumo(resumo: dou_inlabs.ResumoAtualizacao) -> tuple[str, str]:
    partes = []
    if resumo.dias_consultados:
        partes.append(
            f"{len(resumo.dias_consultados)} dia(s) consultado(s), {len(resumo.arquivos)} arquivo(s) baixado(s)"
        )
    if resumo.dias_sem_publicacao:
        dias = ", ".join(d.strftime("%d/%m") for d in resumo.dias_sem_publicacao)
        partes.append(f"sem publicação em {dias}")
    if resumo.restantes:
        partes.append(f"faltam {resumo.restantes} dia(s) — clique de novo para continuar")
    if resumo.erro:
        prefixo = "; ".join(partes)
        return ("error", f"Atualização interrompida: {resumo.erro}" + (f" (antes disso: {prefixo})" if prefixo else ""))
    if not partes:
        return ("info", "Nada a atualizar.")
    return ("success", "Atualização concluída: " + "; ".join(partes) + ".")


def _baixar() -> None:
    barra = st.progress(0.0, text="Entrando no INLABS…")
    try:
        cliente = ClienteInlabs()
        cliente.autenticar(*dou_inlabs.credenciais_do_ambiente())
    except ErroInlabs as erro:
        barra.empty()
        st.session_state[_CHAVE_MENSAGEM] = ("error", str(erro))
        return

    def progresso(indice: int, total: int, dia: date) -> None:
        barra.progress(indice / total, text=f"Baixando {dia.strftime('%d/%m/%Y')} ({indice + 1} de {total})…")

    resumo = dou_inlabs.atualizar(cliente, _hoje(), dou_inlabs.DIRETORIO_PADRAO, progresso=progresso)
    barra.empty()
    st.session_state[_CHAVE_MENSAGEM] = _texto_resumo(resumo)


render_page_header(
    "Diário Oficial (DOU)",
    "Matérias do Diário Oficial da União que citam a UFRPE, baixadas pelo INLABS.",
)

# `get`, não `pop`: o navegador às vezes dispara um segundo rerun logo após o `st.rerun`
# (widgets enviando o valor inicial) e a mensagem sumia antes de ser vista (constatado em
# 08/10/2026). Fica até a próxima atualização, que a substitui.
mensagem = st.session_state.get(_CHAVE_MENSAGEM)
if mensagem:
    render_alert(mensagem[1], mensagem[0])

baixados = dou_inlabs.dias_baixados(dou_inlabs.DIRETORIO_PADRAO)
credenciais_ok = _credenciais_ok()
pendentes = dou_inlabs.dias_pendentes(_hoje(), dou_inlabs.DIRETORIO_PADRAO)

ultimo = max(baixados) if baixados else None
verificado = baixados[ultimo].get("verificado_em") if ultimo else None
render_metric_grid([
    {"label": "Dias consultados", "value": str(len(baixados))},
    {"label": "Último dia", "value": ultimo.strftime("%d/%m/%Y") if ultimo else "—"},
    {
        "label": "Última consulta",
        "value": datetime.fromisoformat(verificado).strftime("%d/%m %H:%M") if verificado else "—",
    },
], columns=3)

if not credenciais_ok:
    render_alert(
        "Credenciais do INLABS não configuradas: defina as variáveis de ambiente INLABS_EMAIL e "
        "INLABS_SENHA (passo a passo em docs/dou_inlabs.md) e reinicie o BudgetLab.",
        "warning",
    )

rotulo_pendentes = (
    f"{len(pendentes)} dia(s) a consultar, de {pendentes[0].strftime('%d/%m')} a {pendentes[-1].strftime('%d/%m')}"
    if pendentes else "Nada a consultar"
)
if st.button(
    "Baixar atualizações do DOU",
    type="primary",
    icon=":material/download:",
    disabled=not credenciais_ok,
    help=rotulo_pendentes,
):
    _baixar()
    st.rerun()
st.caption(
    f"{rotulo_pendentes}. No máximo {dou_inlabs.LIMITE_DIAS_POR_ATUALIZACAO} dias por clique; "
    "os arquivos baixados nunca são sobrescritos."
)

if not baixados:
    st.info("Nenhum dia baixado ainda.")
    st.stop()

st.divider()

primeiro = min(baixados)
inicio_padrao = max(primeiro, ultimo - timedelta(days=_PERIODO_PADRAO_DIAS - 1))
col_periodo, col_secao = st.columns([1, 1])
with col_periodo:
    periodo = st.date_input(
        "Período",
        value=(inicio_padrao, ultimo),
        min_value=primeiro,
        max_value=ultimo,
        format="DD/MM/YYYY",
        # chave muda quando chegam dias novos: senão o campo continuava mostrando o período
        # de antes do download (constatado em 08/10/2026).
        key=f"dou_periodo_{primeiro.isoformat()}_{ultimo.isoformat()}",
    )
with col_secao:
    secoes = st.multiselect("Seção", ["DO1", "DO2", "DO3"], default=["DO1", "DO2", "DO3"], key="dou_secoes",
                            help="Edições extras entram junto com a seção correspondente.")
_iniciar_termos()
_AJUDA_TERMO = (
    "Digite um termo novo e tecle Enter para acrescentá-lo. A busca ignora acentos e maiúsculas; "
    "códigos numéricos não casam dentro de outro número. Vale para os dias já baixados, sem novo "
    "download. Salvo automaticamente."
)
col_termos, col_refinar = st.columns([3, 2])
with col_termos:
    termos = dou_inlabs.limpar_termos(st.multiselect(
        "Termos de busca — a matéria cita algum destes",
        _opcoes(_CHAVE_TERMOS, TERMOS_UFRPE_PADRAO),
        accept_new_options=True,
        key=_CHAVE_TERMOS,
        on_change=_salvar_termos,
        help=_AJUDA_TERMO,
    ))
with col_refinar:
    refinar = dou_inlabs.limpar_termos(st.multiselect(
        "Refinar — e também cita algum destes (opcional)",
        _opcoes(_CHAVE_REFINAR),
        accept_new_options=True,
        key=_CHAVE_REFINAR,
        on_change=_salvar_termos,
        placeholder="Ex.: pregão, dispensa, aditivo",
        help="Vazio: vale só a primeira lista. Preenchido: a matéria precisa citar algum termo da "
             "primeira lista E algum desta. " + _AJUDA_TERMO,
    ))
st.button("Restaurar termos padrão", icon=":material/restart_alt:", on_click=_restaurar_termos)
aviso_termos = st.session_state.get(_CHAVE_AVISO_TERMOS)
if aviso_termos:
    render_alert(aviso_termos, "warning")

if not isinstance(periodo, tuple) or len(periodo) != 2:
    st.info("Escolha a data final do período.")
    st.stop()
if not termos:
    st.info("Informe ao menos um termo de busca.")
    st.stop()

arquivos = dou_inlabs.arquivos_baixados(dou_inlabs.DIRETORIO_PADRAO, periodo[0], periodo[1])
with st.spinner("Procurando nas matérias baixadas…"):
    quadros = [_ler_filtrado(str(caminho), sha, termos, refinar) for caminho, sha in arquivos]
materias = pd.concat(quadros, ignore_index=True) if quadros else pd.DataFrame()

if not materias.empty:
    secao_base = materias["pub_name"].fillna("").str.upper().str.extract(r"^(DO\d)", expand=False)
    materias = materias[secao_base.isin(secoes)]

st.subheader(f"{len(materias)} matéria(s) encontrada(s)")
if materias.empty:
    st.caption("Nenhuma matéria com esses termos no período.")
    st.stop()

tabela = pd.DataFrame({
    "Data": materias["data_publicacao"],
    "Seção": materias["pub_name"],
    "Tipo": materias["art_type"],
    "Identificação": _sem_vazio(materias["identifica"]).fillna(_sem_vazio(materias["titulo"])).fillna(materias["name"]),
    "Ementa": materias["ementa"],
    "Órgão": materias["art_category"],
    "Termos": materias["termos_encontrados"].map(", ".join),
    "Link": materias["pdf_page"].where(materias["pdf_page"].fillna("").str.startswith("http")),
}).sort_values(["Data", "Seção"], ascending=[False, True], na_position="last")

st.dataframe(
    tabela,
    hide_index=True,
    width="stretch",
    column_config={
        "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
        "Link": st.column_config.LinkColumn(display_text="Abrir"),
    },
)
