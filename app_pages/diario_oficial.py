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

import html
import re
import unicodedata
from datetime import date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from src import design_tokens, dou_inlabs
from src.dou_inlabs import TERMOS_UFRPE_PADRAO, ClienteInlabs, ErroInlabs
from src.ui_theme import render_alert, render_page_header

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


_DIAS_SEMANA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
_PASSO_CARTOES = 20
_ATALHOS = ["7 dias", "30 dias", "Mês atual", "Tudo", "Personalizado"]
_TAG_HTML = re.compile(r"<[^>]+>")


def _inject_css() -> None:
    t = design_tokens
    st.markdown(
        f"""
        <style>
        /* Botões de seleção (período, seção, exibição): o ativo fica cheio e com ✓; o inativo, claro. */
        [data-testid="stButtonGroup"] button {{ background:{t.SURFACE} !important; color:{t.TEXT_MUTED} !important;
            border:1px solid {t.BORDER} !important; font-weight:500; }}
        [data-testid="stButtonGroup"] button p {{ color:inherit !important; }}
        [data-testid="stButtonGroup"] button[aria-checked="true"],
        [data-testid="stButtonGroup"] button[aria-pressed="true"] {{ background:{t.ACCENT} !important; color:#fff !important;
            border-color:{t.ACCENT_STRONG} !important; font-weight:700; box-shadow:0 2px 6px rgba(9,105,218,.25); }}
        [data-testid="stButtonGroup"] button[aria-checked="true"] p::before,
        [data-testid="stButtonGroup"] button[aria-pressed="true"] p::before {{ content:"✓ "; }}
        .dou-status {{ display:flex; align-items:center; gap:14px; }}
        .dou-dot {{ width:10px; height:10px; border-radius:50%; flex:none;
            background:var(--dot); box-shadow:0 0 0 4px color-mix(in srgb, var(--dot) 18%, transparent); }}
        .dou-status b {{ display:block; font-size:15px; color:{t.TEXT}; }}
        .dou-status span {{ font-size:13px; color:{t.TEXT_MUTED}; }}
        .dou-status-linha {{ display:flex; align-items:center; gap:28px; flex-wrap:wrap; }}
        .dou-status-linha .dou-status {{ flex:1; min-width:240px; }}
        .dou-mini {{ display:flex; gap:22px; }}
        .dou-mini div {{ font-size:12px; color:{t.TEXT_FAINT}; }}
        .dou-mini strong {{ display:block; font-size:18px; font-weight:600; color:{t.TEXT}; }}
        .dou-kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:8px 0 6px; }}
        @media (max-width:820px) {{ .dou-kpis {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
        .dou-kpi {{ background:{t.SURFACE}; border:1px solid {t.BORDER}; border-radius:{t.RADIUS};
            padding:14px 16px; box-shadow:0 2px 8px rgba(11,53,87,.05); }}
        .dou-kpi small {{ display:block; font-size:12px; color:{t.TEXT_MUTED}; }}
        .dou-kpi strong {{ display:block; font-size:26px; font-weight:600; margin-top:2px; color:{t.TEXT};
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
        .dou-kpi strong.txt {{ font-size:18px; padding-top:6px; }}
        .dou-kpi strong i {{ font-size:14px; font-weight:400; font-style:normal; color:{t.TEXT_FAINT}; }}
        .dou-bar {{ height:6px; border-radius:6px; background:{t.SURFACE_ALT}; margin-top:8px; display:flex; overflow:hidden; }}
        .dou-dia {{ display:flex; align-items:center; gap:12px; margin:22px 0 10px; }}
        .dou-dia b {{ font-size:14px; color:{t.TEXT}; }}
        .dou-dia span {{ font-size:12px; color:{t.TEXT_FAINT}; }}
        .dou-dia hr {{ flex:1; border:0; border-top:1px solid {t.BORDER}; margin:0; }}
        .dou-card {{ background:{t.SURFACE}; border:1px solid {t.BORDER}; border-left:4px solid var(--sec);
            border-radius:{t.RADIUS}; padding:16px 18px; margin-bottom:10px;
            box-shadow:0 2px 8px rgba(11,53,87,.05); }}
        .dou-top {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:6px; }}
        .dou-tag {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:6px;
            background:{t.SURFACE_ALT}; color:{t.TEXT_MUTED}; }}
        .dou-tag.sec {{ background:color-mix(in srgb, var(--sec) 14%, white); color:var(--sec); }}
        .dou-orgao {{ font-size:12px; color:{t.TEXT_FAINT}; margin-left:auto; text-align:right; }}
        .dou-card h3 {{ margin:0 0 4px; padding:0; font-size:16px; font-weight:600; color:{t.TEXT}; }}
        .dou-card p {{ margin:0; color:{t.TEXT_MUTED}; font-size:14px; display:-webkit-box;
            -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }}
        .dou-foot {{ display:flex; gap:6px; align-items:center; margin-top:10px; flex-wrap:wrap; }}
        .dou-foot .lbl {{ font-size:12px; color:{t.TEXT_FAINT}; }}
        .dou-foot a {{ margin-left:auto; font-size:13px; font-weight:600; color:{t.ACCENT}; text-decoration:none; }}
        .dou-chip {{ background:#E6F1FD; color:{t.ACCENT_STRONG}; border-radius:999px; padding:2px 10px; font-size:12px; }}
        .dou-chip.alt {{ background:#FFF1DC; color:#8A4A00; }}
        .dou-card mark {{ background:#FFE9A8; color:inherit; border-radius:3px; padding:0 2px; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _limpar_html(texto: str | None) -> str:
    return html.unescape(_TAG_HTML.sub(" ", texto or "")).strip()


def _normalizar_com_mapa(texto: str) -> tuple[str, list[int]]:
    """Mesma normalização de `dou_inlabs.normalizar_texto` (sem acentos, minúsculas), mas
    guardando de que posição do texto original veio cada caractere — para destacar o trecho
    original sem alterá-lo."""

    saida, mapa = [], []
    for posicao, caractere in enumerate(texto):
        decomposto = unicodedata.normalize("NFKD", caractere)
        for c in (c for c in decomposto if not unicodedata.combining(c)):
            for cc in c.casefold():
                saida.append(cc)
                mapa.append(posicao)
    return "".join(saida), mapa


def _destacar(texto: str, termos: tuple[str, ...]) -> str:
    """HTML do texto com os termos dentro de <mark>, na grafia original (a busca ignora
    acentos, caixa e, para códigos numéricos, não casa dentro de outro número)."""

    normalizado, mapa = _normalizar_com_mapa(texto)
    marcado = [False] * len(texto)
    for termo in termos:
        try:
            padrao = dou_inlabs._padrao(termo)  # mesma regra da busca
        except ValueError:
            continue
        for achado in padrao.finditer(normalizado):
            for posicao in range(mapa[achado.start()], mapa[achado.end() - 1] + 1):
                marcado[posicao] = True
    pedacos, i = [], 0
    while i < len(texto):
        j = i
        while j < len(texto) and marcado[j] == marcado[i]:
            j += 1
        trecho = escape(texto[i:j])
        pedacos.append(f"<mark>{trecho}</mark>" if marcado[i] else trecho)
        i = j
    return "".join(pedacos)


def _trecho(texto: str, termos: tuple[str, ...], raio: int = 150) -> str:
    """Pedaço do texto (limpo) ao redor da primeira ocorrência de um termo; o texto inteiro
    se for curto. Só para exibição — a matéria completa fica no link do DOU."""

    if len(texto) <= 2 * raio:
        return texto
    normalizado, mapa = _normalizar_com_mapa(texto)
    inicio = None
    for termo in termos:
        try:
            achado = dou_inlabs._padrao(termo).search(normalizado)
        except ValueError:
            continue
        if achado and (inicio is None or achado.start() < inicio):
            inicio = achado.start()
    centro = mapa[inicio] if inicio is not None else 0
    a, b = max(0, centro - raio), min(len(texto), centro + raio)
    return ("…" if a else "") + texto[a:b].strip() + ("…" if b < len(texto) else "")


def _cor_secao(secao: str | None) -> str:
    base = (secao or "").upper()[:3]
    return {"DO1": design_tokens.ACCENT, "DO2": "#7C5CE0", "DO3": design_tokens.WARNING}.get(base, design_tokens.TEXT_MUTED)


def _cartao(linha: pd.Series, termos: tuple[str, ...], refinar: tuple[str, ...]) -> str:
    achados = tuple(linha["Termos"])
    alternativos = {dou_inlabs.normalizar_texto(t) for t in refinar} - {dou_inlabs.normalizar_texto(t) for t in termos}
    chips = "".join(
        f'<span class="dou-chip{" alt" if dou_inlabs.normalizar_texto(t) in alternativos else ""}">{escape(t)}</span>'
        for t in achados
    )
    tipo = f'<span class="dou-tag">{escape(str(linha["Tipo"]))}</span>' if _tem(linha["Tipo"]) else ""
    orgao = escape(str(linha["Órgão"]).replace("/", " › ")) if _tem(linha["Órgão"]) else ""
    if _tem(linha["Ementa"]):
        resumo = _limpar_html(linha["Ementa"])
    else:  # contratos, avisos etc. costumam vir sem ementa: mostra o trecho que casou
        resumo = _trecho(_limpar_html(linha["_texto"]), achados) if _tem(linha["_texto"]) else ""
    corpo = f"<p>{_destacar(resumo, achados)}</p>" if resumo else ""
    link = linha["Link"]
    abrir = f'<a href="{escape(str(link), quote=True)}" target="_blank" rel="noopener">Abrir no DOU ↗</a>' if _tem(link) else ""
    secao = str(linha["Seção"]) if _tem(linha["Seção"]) else "—"
    return (
        f'<div class="dou-card" style="--sec:{_cor_secao(secao)}">'
        f'<div class="dou-top"><span class="dou-tag sec">{escape(secao)}</span>{tipo}'
        f'<span class="dou-orgao">{orgao}</span></div>'
        f'<h3>{escape(str(linha["Identificação"]))}</h3>{corpo}'
        f'<div class="dou-foot"><span class="lbl">Termos:</span>{chips}{abrir}</div></div>'
    )


def _tem(valor: object) -> bool:
    return valor is not None and not pd.isna(valor) and str(valor).strip() != ""


def _cabecalho_dia(dia: object, quantidade: int) -> str:
    if dia is None or pd.isna(dia):
        rotulo = "Sem data de publicação"
    else:
        rotulo = f"{_DIAS_SEMANA[dia.weekday()].capitalize()}, {dia.strftime('%d/%m/%Y')}"
    return (
        f'<div class="dou-dia"><b>{rotulo}</b><span>{quantidade} matéria(s)</span><hr></div>'
    )


def _periodo(atalho: str | None, primeiro: date, ultimo: date) -> tuple[date, date] | None:
    if atalho == "Personalizado":
        escolhido = st.date_input(
            "Datas",
            value=(max(primeiro, ultimo - timedelta(days=_PERIODO_PADRAO_DIAS - 1)), ultimo),
            min_value=primeiro,
            max_value=ultimo,
            format="DD/MM/YYYY",
            # chave muda quando chegam dias novos: senão o campo continuava mostrando o período
            # de antes do download (constatado em 08/10/2026).
            key=f"dou_periodo_{primeiro.isoformat()}_{ultimo.isoformat()}",
        )
        if not isinstance(escolhido, tuple) or len(escolhido) != 2:
            return None
        return escolhido
    if atalho == "7 dias":
        inicio = ultimo - timedelta(days=6)
    elif atalho == "Mês atual":
        inicio = ultimo.replace(day=1)
    elif atalho == "Tudo":
        inicio = primeiro
    else:
        inicio = ultimo - timedelta(days=_PERIODO_PADRAO_DIAS - 1)
    inicio = max(primeiro, inicio)
    st.caption(f"{inicio.strftime('%d/%m/%Y')} a {ultimo.strftime('%d/%m/%Y')}")
    return inicio, ultimo


_inject_css()
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
rotulo_pendentes = (
    f"{len(pendentes)} dia(s) a consultar, de {pendentes[0].strftime('%d/%m')} a {pendentes[-1].strftime('%d/%m')}"
    if pendentes else "Nada a consultar"
)
if not baixados:
    titulo_status, cor_status = "Nenhum dia baixado ainda", design_tokens.WARNING
elif pendentes:
    titulo_status, cor_status = f"Base com defasagem — última publicação em {ultimo.strftime('%d/%m/%Y')}", design_tokens.WARNING
else:
    titulo_status, cor_status = f"Base em dia até {ultimo.strftime('%d/%m/%Y')}", design_tokens.POSITIVE
detalhe_status = " · ".join(filter(None, [
    f"última consulta em {datetime.fromisoformat(verificado).strftime('%d/%m às %H:%M')}" if verificado else "",
    rotulo_pendentes,
]))

with st.container(border=True):
    col_status, col_botao = st.columns([3, 1], vertical_alignment="center")
    with col_status:
        st.markdown(
            f'<div class="dou-status-linha"><div class="dou-status" style="--dot:{cor_status}"><div class="dou-dot"></div>'
            f'<div><b>{escape(titulo_status)}</b><span>{escape(detalhe_status)}</span></div></div>'
            f'<div class="dou-mini"><div><strong>{len(baixados)}</strong>dias consultados</div>'
            f'<div><strong>{ultimo.strftime("%d/%m") if ultimo else "—"}</strong>último dia</div></div></div>',
            unsafe_allow_html=True,
        )
    with col_botao:
        if st.button(
            "Baixar atualizações do DOU",
            type="primary",
            icon=":material/download:",
            disabled=not credenciais_ok,
            help=rotulo_pendentes,
            width="stretch",
        ):
            _baixar()
            st.rerun()
    st.caption(
        f"No máximo {dou_inlabs.LIMITE_DIAS_POR_ATUALIZACAO} dias por clique; "
        "os arquivos baixados nunca são sobrescritos."
    )

if not credenciais_ok:
    render_alert(
        "Credenciais do INLABS não configuradas: defina as variáveis de ambiente INLABS_EMAIL e "
        "INLABS_SENHA (passo a passo em docs/dou_inlabs.md) e reinicie o BudgetLab.",
        "warning",
    )

if not baixados:
    st.info("Nenhum dia baixado ainda.")
    st.stop()

primeiro = min(baixados)
_iniciar_termos()
_AJUDA_TERMO = (
    "Digite um termo novo e tecle Enter para acrescentá-lo. A busca ignora acentos e maiúsculas; "
    "códigos numéricos não casam dentro de outro número. Vale para os dias já baixados, sem novo "
    "download. Salvo automaticamente."
)
with st.container(border=True):
    col_atalho, col_datas, col_secao = st.columns([3, 2, 2], vertical_alignment="top")
    with col_atalho:
        atalho = st.segmented_control("Período", _ATALHOS, default="30 dias", key="dou_atalho")
    with col_datas:
        periodo = _periodo(atalho, primeiro, ultimo)
    with col_secao:
        secoes = st.segmented_control(
            "Seção", ["DO1", "DO2", "DO3"], selection_mode="multi", default=["DO1", "DO2", "DO3"],
            key="dou_secoes", help="Edições extras entram junto com a seção correspondente.",
        ) or []
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
    col_legenda, col_restaurar = st.columns([4, 1], vertical_alignment="center")
    with col_legenda:
        st.caption("Busca ignora acentos e maiúsculas · salva automaticamente · vale para os dias já baixados.")
    with col_restaurar:
        st.button("Restaurar termos padrão", icon=":material/restart_alt:", on_click=_restaurar_termos,
                  type="tertiary", width="stretch")
aviso_termos = st.session_state.get(_CHAVE_AVISO_TERMOS)
if aviso_termos:
    render_alert(aviso_termos, "warning")

if periodo is None:
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

if materias.empty:
    st.subheader("0 matéria(s) encontrada(s)")
    st.caption("Nenhuma matéria com esses termos no período.")
    st.stop()

base = pd.DataFrame({
    "Data": materias["data_publicacao"],
    "Seção": materias["pub_name"],
    "Tipo": materias["art_type"],
    "Identificação": _sem_vazio(materias["identifica"]).fillna(_sem_vazio(materias["titulo"])).fillna(materias["name"]),
    "Ementa": materias["ementa"],
    "Órgão": materias["art_category"],
    "Termos": materias["termos_encontrados"],
    "Link": materias["pdf_page"].where(materias["pdf_page"].fillna("").str.startswith("http")),
    "_texto": materias["texto"],  # só para o trecho dos cartões; fora da tabela e do CSV
})

# --- Resumo ---------------------------------------------------------------------------------
dias_no_periodo = sum(1 for d in baixados if periodo[0] <= d <= periodo[1])
dias_com_materia = base["Data"].dropna().nunique()
contagem_secao = (
    base["Seção"].fillna("").str.upper().str.extract(r"^(DO\d)", expand=False).value_counts()
)
por_secao = " · ".join(str(int(contagem_secao.get(s, 0))) for s in ("DO1", "DO2", "DO3"))
frequencia_termos = base["Termos"].explode().value_counts()
_cores_secao = (design_tokens.ACCENT, "#7C5CE0", design_tokens.WARNING)
_contagens = [int(contagem_secao.get(sec, 0)) for sec in ("DO1", "DO2", "DO3")]
barra = "".join(
    f'<b style="width:{100 * n / max(sum(_contagens), 1):.1f}%;background:{cor}"></b>'
    for n, cor in zip(_contagens, _cores_secao, strict=True)
)
st.markdown(
    '<div class="dou-kpis">'
    f'<div class="dou-kpi"><small>Matérias encontradas</small><strong>{len(base)}</strong></div>'
    f'<div class="dou-kpi"><small>Dias com ocorrência</small><strong>{dias_com_materia} <i>de {dias_no_periodo}</i></strong></div>'
    f'<div class="dou-kpi"><small>DO1 · DO2 · DO3</small><strong>{por_secao}</strong><div class="dou-bar">{barra}</div></div>'
    f'<div class="dou-kpi"><small>Termo mais frequente</small>'
    f'<strong class="txt" title="{escape(str(frequencia_termos.index[0]), quote=True)}">{escape(str(frequencia_termos.index[0]))}</strong></div>'
    '</div>',
    unsafe_allow_html=True,
)

# --- Controles da lista ---------------------------------------------------------------------
col_titulo, col_visao, col_ordem, col_csv = st.columns([3, 2, 2, 1], vertical_alignment="center")
with col_titulo:
    st.subheader(f"{len(materias)} matéria(s) encontrada(s)")
with col_visao:
    visao = st.segmented_control(
        "Exibição", ["Cartões", "Tabela"], default="Cartões", key="dou_visao", label_visibility="collapsed",
    ) or "Cartões"
with col_ordem:
    ordem = st.selectbox("Ordenar", ["Mais recentes", "Mais antigas"], key="dou_ordem", label_visibility="collapsed")
mais_recentes = ordem == "Mais recentes"
base = base.sort_values(["Data", "Seção"], ascending=[not mais_recentes, True], na_position="last", kind="stable")

tabela = base.drop(columns="_texto").assign(Termos=base["Termos"].map(", ".join))
with col_csv:
    st.download_button(
        "CSV",
        data=tabela.to_csv(index=False, sep=";").encode("utf-8-sig"),
        file_name=f"dou_{periodo[0].isoformat()}_{periodo[1].isoformat()}.csv",
        mime="text/csv",
        icon=":material/download:",
        width="stretch",
        help="Exporta as matérias do recorte atual (separador ponto e vírgula).",
    )

if visao == "Tabela":
    st.dataframe(
        tabela,
        hide_index=True,
        width="stretch",
        column_config={
            "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Link": st.column_config.LinkColumn(display_text="Abrir"),
        },
    )
    st.stop()

# --- Cartões agrupados por dia --------------------------------------------------------------
assinatura = (periodo, termos, refinar, tuple(secoes), ordem)
if st.session_state.get("dou_assinatura") != assinatura:
    st.session_state["dou_assinatura"] = assinatura
    st.session_state["dou_limite"] = _PASSO_CARTOES
limite = st.session_state.get("dou_limite", _PASSO_CARTOES)

visiveis = base.iloc[:limite]
chave_dia = base["Data"].where(base["Data"].notna(), None)
contagem_dia = chave_dia.value_counts(dropna=False)
blocos, dia_anterior = [], "inicio"
for indice, linha in visiveis.iterrows():
    dia = chave_dia.loc[indice]
    if dia_anterior == "inicio" or dia != dia_anterior:
        blocos.append(_cabecalho_dia(dia, int(contagem_dia.get(dia, 0))))
        dia_anterior = dia
    blocos.append(_cartao(linha, termos, refinar))
st.markdown("".join(blocos), unsafe_allow_html=True)

if limite < len(base):
    restantes = len(base) - limite
    if st.button(f"Mostrar mais {min(_PASSO_CARTOES, restantes)} de {restantes} matéria(s)", key="dou_mais"):
        st.session_state["dou_limite"] = limite + _PASSO_CARTOES
        st.rerun()
