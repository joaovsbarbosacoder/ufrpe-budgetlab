"""Painel de Emendas Parlamentares com histórico estático e execução por PTRES.

A carga inicial preserva todos os exercícios disponíveis. Atualizações pelo
uploader são aceitas somente para 2026 em diante e são compostas por ano, sem
apagar os exercícios históricos. Empenhado, Liquidado e Pago de 2026+ vêm da
Execução Anual quando existe vínculo por ``(exercício, RP, PTRES)``.
"""

from __future__ import annotations

import html as html_lib
from collections.abc import Iterable

import pandas as pd
import streamlit as st

from src.design_tokens import (
    ACCENT,
    ACCENT_LINE,
    ACCENT_SOFT,
    ACCENT_STRONG,
    BORDER,
    BORDER_SOFT,
    CARD_PAD,
    FONT_BODY,
    FONT_HEADING,
    NEGATIVE,
    POSITIVE,
    RADIUS,
    SIZE,
    SPACE,
    SURFACE,
    TEXT,
    TEXT_MUTED,
    TRACK,
    WARNING,
)
from src.emendas_parlamentares import (
    ANO_INICIO_ATUALIZACAO,
    ErroPoliticaImportacao,
    ErroVinculoEmenda,
    RPS_EMENDA,
    carregar_emendas_cadastradas,
    compor_relatorio_com_cadastros,
    divergencias_dotacao,
    normalizar_ptres_texto,
    nova_emenda_acompanhamento,
    salvar,
    vincular_execucao_emendas,
)
from src.importacao_emendas import (
    DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_EMENDAS,
    NOME_PONTEIRO as PONTEIRO_EMENDAS,
    Manifesto as ManifestoEmendas,
    carregar_atual as carregar_emendas_atual,
)
from src.importacao_execucao import (
    DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_EXECUCAO,
    NOME_PONTEIRO as PONTEIRO_EXECUCAO,
    Manifesto as ManifestoExecucao,
    carregar_atual as carregar_execucao_atual,
)
from src.importacao_dotacao import (
    DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_DOTACAO,
    NOME_PONTEIRO as PONTEIRO_DOTACAO,
    Manifesto as ManifestoDotacao,
    carregar_atual as carregar_dotacao_atual,
)
from src.ui_theme import format_brl_full, render_page_header
from src.vinculos_emendas import carregar_eventos_vinculo, compor_relatorio_com_vinculos


@st.cache_data(show_spinner="Lendo a base de Emendas...", max_entries=4)
def _cached_emendas(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_emendas_atual()


@st.cache_data(show_spinner="Lendo a Execução Anual...", max_entries=4)
def _cached_execucao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_execucao_atual()


@st.cache_data(show_spinner="Lendo a Dotação Anual...", max_entries=4)
def _cached_dotacao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame | None:
    return carregar_dotacao_atual()


def _valor_brl(valor: object) -> str:
    return "—" if valor is None or pd.isna(valor) else format_brl_full(float(valor))


def _total(series: pd.Series) -> object:
    total = series.sum(min_count=1)
    return pd.NA if pd.isna(total) else float(total)


#: campo do DataFrame `emendas` -> key de `st.session_state` do respectivo `st.multiselect`.
_CAMPOS_FILTRO_EMENDAS = {
    "ano": "emendas_filtro_ano",
    "resultado_primario_cod": "emendas_filtro_rp",
    "parlamentar": "emendas_filtro_parlamentar",
}


def _opcoes_filtro(dataframe: pd.DataFrame, campo: str) -> list[str]:
    if campo == "ano":
        return [str(ano) for ano in sorted(int(ano) for ano in dataframe[campo].dropna().unique())]
    return sorted(str(valor) for valor in dataframe[campo].dropna().unique())


def _selecoes_persistidas() -> dict[str, list[str]]:
    """Lê o que já está marcado em cada filtro (via `st.session_state`) para servir de base ao
    recorte cruzado de `_opcoes_disponiveis` — precisa ser lido ANTES de desenhar qualquer
    `st.multiselect` da rodada, senão um campo só enxergaria os campos desenhados antes dele
    (mesma cascata de mão única corrigida em `ui_filtros_execucao._todas_selecoes_atuais`)."""

    selecoes: dict[str, list[str]] = {}
    for campo, key in _CAMPOS_FILTRO_EMENDAS.items():
        valores = st.session_state.get(key, [])
        if valores:
            selecoes[campo] = valores
    return selecoes


def _opcoes_disponiveis(dataframe: pd.DataFrame, selecoes: dict[str, list[str]], campo: str) -> pd.DataFrame:
    """`dataframe` recortado pelos OUTROS filtros já selecionados (nunca pelo próprio `campo`,
    senão marcar um valor faria os demais valores já escolhidos no mesmo campo sumirem da
    lista) — assim escolher um Exercício já restringe as opções de RP e Parlamentar, e
    vice-versa, em qualquer ordem (pedido explícito: filtros combinados/cascata)."""

    filtrado = dataframe
    for outro_campo, valores in selecoes.items():
        if outro_campo == campo or not valores:
            continue
        filtrado = filtrado[filtrado[outro_campo].astype("string").isin(valores)]
    return filtrado


def _sanear_persistido(key: str, opcoes_validas: list[str]) -> None:
    """`st.multiselect` levanta erro se um valor persistido em `st.session_state` não estiver
    mais em `options` — a cascata muda as opções disponíveis a cada rerun conforme os outros
    filtros mudam, então precisa limpar antes de instanciar o widget."""

    persistido = st.session_state.get(key, [])
    valido = [valor for valor in persistido if valor in opcoes_validas]
    if valido != persistido:
        st.session_state[key] = valido


def _juntar_codigos(valores: object) -> str:
    if isinstance(valores, Iterable) and not isinstance(valores, (str, bytes)):
        return ", ".join(str(valor) for valor in valores)
    return "—" if valores is None or pd.isna(valores) else str(valores)


def _esc(value: object) -> str:
    return html_lib.escape(str(value))


def _resumo_tupla(valores: object) -> str:
    if not valores:
        return "—"
    return _esc(valores[0]) if len(valores) == 1 else f"{len(valores)} valores"


_ROTULOS_ORIGEM = {
    "relatorio_estatico": ("Histórico estático", TEXT_MUTED, "rgba(147,161,184,0.14)"),
    "execucao_anual": ("Execução Anual", POSITIVE, "rgba(34,197,94,0.14)"),
    "execucao_anual_parcial": ("Execução parcial", WARNING, "rgba(245,165,36,0.14)"),
    "sem_execucao": ("Sem execução", NEGATIVE, "rgba(240,87,107,0.14)"),
}


def _badge(rotulo: str, cor: str, fundo: str) -> str:
    return (
        f'<span class="em-badge" style="color:{cor};background:{fundo};border-color:{cor}55">'
        f"{_esc(rotulo)}</span>"
    )


def _badge_origem(origem: object) -> str:
    rotulo, cor, fundo = _ROTULOS_ORIGEM.get(
        str(origem), (str(origem), TEXT_MUTED, "rgba(147,161,184,0.14)")
    )
    return _badge(rotulo, cor, fundo)


def _inject_css() -> None:
    """Cartões HTML no mesmo idioma visual de `app_pages/painel_acoes.py` (`.po-*`) e
    `app_pages/consulta_empenhos.py` (`.ce-cons-*`) — nenhuma lista principal do app usa
    `st.dataframe` puro (ver LAYOUT.md §2), então a lista de Emendas segue o mesmo padrão de
    cartão HTML em vez da grade cinza padrão do Streamlit."""

    st.markdown(
        f"""
        <style>
        .em-card {{
            border: 1px solid {BORDER}; border-radius: {RADIUS};
            background: {SURFACE}; padding: {CARD_PAD};
            margin-bottom: {SPACE['xl']};
        }}
        .em-card-head {{
            display: grid; grid-template-columns: minmax(0,1fr) auto;
            gap: 24px; align-items: start; margin-bottom: {SPACE['md']};
        }}
        .em-kicker {{
            font-family: {FONT_HEADING}; font-size: {SIZE['value']};
            letter-spacing: {TRACK['kicker']}; color: {ACCENT}; text-transform: uppercase;
        }}
        .em-title {{
            margin: 3px 0 8px; font-family: {FONT_HEADING}; font-weight: 600;
            font-size: {SIZE['card_title']}; line-height: 1.12; color: {TEXT};
        }}
        .em-tags {{ display: flex; flex-wrap: wrap; gap: {SPACE['xs']}; }}
        .em-tag {{
            font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
            border: 1px solid {ACCENT_LINE}; border-radius: {RADIUS};
            padding: 2px 7px; background: {ACCENT_SOFT};
        }}
        .em-badge {{
            display: inline-block; font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: 0.06em; text-transform: uppercase;
            border: 1px solid; border-radius: {RADIUS}; padding: 2px 7px; white-space: nowrap;
        }}
        .em-metric-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .em-metric {{
            font-family: {FONT_HEADING}; font-size: {SIZE['metric']}; line-height: 1.1;
            color: {ACCENT_STRONG}; font-variant-numeric: tabular-nums;
        }}
        .em-stats {{
            display: grid; grid-template-columns: repeat(4, minmax(0,1fr));
            gap: {SPACE['md']}; margin-bottom: {SPACE['md']};
            padding: {SPACE['sm']} 0; border-top: 1px solid {BORDER}; border-bottom: 1px solid {BORDER};
        }}
        .em-stat-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .em-stat-value {{
            font-family: {FONT_HEADING}; font-size: {SIZE['value_strong']}; font-weight: 600;
            color: {TEXT}; font-variant-numeric: tabular-nums;
        }}
        .em-scroll {{ overflow-x: auto; padding-bottom: 2px; }}
        .em-row, .em-head {{
            display: grid;
            grid-template-columns: minmax(70px,0.7fr) minmax(60px,0.6fr) minmax(130px,1.1fr)
                minmax(110px,1fr) minmax(110px,1fr) minmax(110px,1fr) minmax(110px,1fr);
            gap: 8px; min-width: 850px;
        }}
        .em-head {{
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .em-row {{ padding: 9px 0; border-bottom: 1px solid {BORDER_SOFT}; align-items: baseline; }}
        .em-flat {{
            font-family: {FONT_HEADING}; font-size: {SIZE['small']};
            letter-spacing: 0.08em; color: {TEXT_MUTED}; white-space: nowrap;
        }}
        .em-val {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED}; white-space: nowrap;
        }}
        .em-val-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
            white-space: nowrap;
        }}
        .em-empty {{
            font-family: {FONT_HEADING}; font-size: 16px; letter-spacing: 0.1em;
            text-transform: uppercase; color: {TEXT_MUTED}; padding: 40px 0;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _html_linha_ptres(r) -> str:
    return (
        '<div class="em-row">'
        f'<span class="em-flat">{_esc(r.ptres)}</span>'
        f'<span class="em-flat">{_esc(_juntar_codigos(r.gnds))}</span>'
        + _badge_origem(r.origem_valores)
        + f'<span class="em-val">{_esc(_valor_brl(r.dotacao_atualizada))}</span>'
        f'<span class="em-val">{_esc(_valor_brl(r.empenhada))}</span>'
        f'<span class="em-val">{_esc(_valor_brl(r.liquidada))}</span>'
        f'<span class="em-val-strong">{_esc(_valor_brl(r.paga))}</span>'
        "</div>"
    )


def _html_dotacao_anual(linha) -> str:
    """Linha informativa com a Dotação Anual por PTRES — só existe para exercícios dinâmicos
    quando a Dotação Anual foi carregada. Nunca substitui a dotação do relatório/cadastro."""
    if not hasattr(linha, "dotacao_anual_ptres") or int(linha.ano) < ANO_INICIO_ATUALIZACAO:
        return ""
    if int(linha.ptres_com_dotacao_anual) == 0:
        texto = "Dotação Anual (por PTRES): sem dotação correspondente"
    else:
        texto = (
            f"Dotação Anual (por PTRES): {_valor_brl(linha.dotacao_anual_ptres)} · "
            f"{int(linha.ptres_com_dotacao_anual)} de {int(linha.ptres_total)} PTRES com dotação"
        )
    aviso = (
        _badge("Difere do informado", WARNING, "rgba(245,165,36,0.14)")
        if bool(linha.dotacao_divergente)
        else ""
    )
    return f'<div class="em-tags" style="margin-bottom:8px"><span class="em-tag">{_esc(texto)}</span>{aviso}</div>'


def _render_card_emenda(linha, vinculos_da_emenda: pd.DataFrame) -> None:
    parlamentar = (
        "(não informado)" if pd.isna(linha.parlamentar) else _esc(linha.parlamentar)
    )
    ptres_total = int(linha.ptres_total)
    tags_html = "".join(
        [
            f'<span class="em-tag">PTRES {ptres_total}</span>',
            f'<span class="em-tag">GND {_resumo_tupla(linha.gnds)}</span>',
            _badge_origem(linha.origem_valores),
        ]
    )
    linhas_html = "".join(_html_linha_ptres(row) for row in vinculos_da_emenda.itertuples())

    st.markdown(
        f"""
        <div class="em-card">
          <div class="em-card-head">
            <div style="min-width:0">
              <div class="em-kicker">RP{_esc(linha.resultado_primario_cod)} · EXERCÍCIO {int(linha.ano)}</div>
              <div class="em-title">{_esc(linha.emenda_numero)} — {parlamentar}</div>
              <div class="em-tags">{tags_html}</div>
            </div>
            <div style="text-align:right">
              <div class="em-metric-label">Dotação atualizada</div>
              <div class="em-metric">{_esc(_valor_brl(linha.dotacao_atualizada))}</div>
            </div>
          </div>
          <div class="em-stats">
            <div>
              <div class="em-stat-label">Empenhado</div>
              <div class="em-stat-value">{_esc(_valor_brl(linha.empenhada))}</div>
            </div>
            <div>
              <div class="em-stat-label">Liquidado</div>
              <div class="em-stat-value">{_esc(_valor_brl(linha.liquidada))}</div>
            </div>
            <div>
              <div class="em-stat-label">Pago</div>
              <div class="em-stat-value">{_esc(_valor_brl(linha.paga))}</div>
            </div>
            <div>
              <div class="em-stat-label">PTRES c/ execução</div>
              <div class="em-stat-value">{int(linha.ptres_com_execucao)} de {ptres_total}</div>
            </div>
          </div>
          {_html_dotacao_anual(linha)}
          <div class="em-scroll">
            <div class="em-head">
              <span>PTRES</span><span>GND</span><span>Status</span>
              <span style="text-align:right">Dotação</span>
              <span style="text-align:right">Empenhado</span>
              <span style="text-align:right">Liquidado</span>
              <span style="text-align:right">Pago</span>
            </div>
            {linhas_html}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.dialog("Cadastrar emenda")
def _dialog_cadastro_manual() -> None:
    st.caption(
        f"Cadastros manuais são permitidos somente a partir de "
        f"{ANO_INICIO_ATUALIZACAO}. Os PTRES serão reconciliados com a Execução Anual."
    )
    with st.form("emendas_cadastro_manual", border=False):
        exercicio = st.number_input(
            "Exercício",
            min_value=ANO_INICIO_ATUALIZACAO,
            step=1,
            value=ANO_INICIO_ATUALIZACAO,
        )
        rp_codigo = st.selectbox(
            "Resultado Primário",
            options=list(RPS_EMENDA),
            format_func=lambda codigo: f"RP{codigo} — {RPS_EMENDA[codigo]}",
        )
        numero = st.text_input("Número da emenda")
        parlamentar = st.text_input("Parlamentar")
        ptres_texto = st.text_area(
            "PTRES",
            placeholder="Separe múltiplos PTRES por vírgula ou quebra de linha",
        )
        gnd_codigo = st.text_input(
            "Código do GND",
            help="Código tratado como identificador; zeros iniciais são preservados.",
        )
        informar_dotacao = st.checkbox("Informar dotação atualizada")
        dotacao = st.number_input(
            "Dotação atualizada (R$)",
            step=1000.0,
            format="%.2f",
        )
        objeto = st.text_area("Objeto ou observação")
        responsavel = st.text_input("Responsável")
        enviado = st.form_submit_button(
            "Cadastrar emenda",
            type="primary",
            icon=":material/add:",
        )

    if not enviado:
        return
    try:
        emenda = nova_emenda_acompanhamento(
            exercicio=int(exercicio),
            parlamentar=parlamentar,
            numero=numero,
            rp_codigo=rp_codigo,
            ptres=normalizar_ptres_texto(ptres_texto),
            gnd_codigo=gnd_codigo,
            dotacao_atualizada=float(dotacao) if informar_dotacao else None,
            objeto=objeto,
            responsavel=responsavel,
        )
        salvar(emenda)
    except (ErroPoliticaImportacao, ErroVinculoEmenda, OSError, ValueError) as error:
        st.error(str(error))
        return
    st.success("Emenda cadastrada e incluída na reconciliação.")
    st.rerun()


render_page_header(
    "Emendas Parlamentares",
    "Histórico preservado · atualizações 2026+ · execução conciliada por PTRES.",
)
_inject_css()

manifesto_emendas = ManifestoEmendas.atual()
if manifesto_emendas is None:
    st.error(
        "A carga histórica inicial de Emendas ainda não foi registrada. "
        "Ela deve ser instalada uma única vez antes das atualizações de 2026+."
    )
    st.stop()

manifesto_execucao = ManifestoExecucao.atual()
if manifesto_execucao is None:
    st.info(
        "Importe a Execução Anual para reconciliar Empenhado, Liquidado e Pago "
        "das emendas de 2026 em diante."
    )
    st.stop()

caminho_ponteiro_emendas = DIR_MANIFESTOS_EMENDAS / PONTEIRO_EMENDAS
caminho_ponteiro_execucao = DIR_MANIFESTOS_EXECUCAO / PONTEIRO_EXECUCAO
relatorio_base = _cached_emendas(
    str(caminho_ponteiro_emendas),
    caminho_ponteiro_emendas.stat().st_mtime,
)
execucao = _cached_execucao(
    str(caminho_ponteiro_execucao),
    caminho_ponteiro_execucao.stat().st_mtime,
)

caminho_ponteiro_dotacao = DIR_MANIFESTOS_DOTACAO / PONTEIRO_DOTACAO
dotacao_anual = (
    _cached_dotacao(str(caminho_ponteiro_dotacao), caminho_ponteiro_dotacao.stat().st_mtime)
    if caminho_ponteiro_dotacao.exists()
    else None
)

try:
    cadastros_manuais = carregar_emendas_cadastradas()
    eventos_vinculo = carregar_eventos_vinculo()
    composicao = compor_relatorio_com_cadastros(
        relatorio_base,
        cadastros_manuais,
    )
    composicao_vinculos = compor_relatorio_com_vinculos(
        composicao.relatorio,
        cadastros_manuais,
        eventos_vinculo,
    )
    resultado = vincular_execucao_emendas(
        composicao_vinculos.relatorio, execucao, dotacao=dotacao_anual
    )
except (ErroPoliticaImportacao, ErroVinculoEmenda) as error:
    st.error(f"Não foi possível consolidar as Emendas: {error}")
    st.stop()

with st.container(horizontal=True):
    if st.button(
        "Cadastrar emenda",
        type="primary",
        icon=":material/add:",
    ):
        _dialog_cadastro_manual()

emendas = resultado.emendas.copy()

with st.container(border=True):
    st.markdown("**Filtros**")
    col_ano, col_rp, col_parlamentar = st.columns(3)
    selecoes_persistidas = _selecoes_persistidas()

    with col_ano:
        opcoes_ano = _opcoes_filtro(_opcoes_disponiveis(emendas, selecoes_persistidas, "ano"), "ano")
        _sanear_persistido(_CAMPOS_FILTRO_EMENDAS["ano"], opcoes_ano)
        anos_selecionados = st.multiselect(
            "Exercício",
            options=opcoes_ano,
            key=_CAMPOS_FILTRO_EMENDAS["ano"],
            placeholder="Todos",
        )
    with col_rp:
        opcoes_rp = _opcoes_filtro(
            _opcoes_disponiveis(emendas, selecoes_persistidas, "resultado_primario_cod"),
            "resultado_primario_cod",
        )
        _sanear_persistido(_CAMPOS_FILTRO_EMENDAS["resultado_primario_cod"], opcoes_rp)
        rps_selecionados = st.multiselect(
            "Resultado Primário",
            options=opcoes_rp,
            format_func=lambda codigo: f"RP{codigo}",
            key=_CAMPOS_FILTRO_EMENDAS["resultado_primario_cod"],
            placeholder="Todos",
        )
    with col_parlamentar:
        opcoes_parlamentar = _opcoes_filtro(
            _opcoes_disponiveis(emendas, selecoes_persistidas, "parlamentar"), "parlamentar"
        )
        _sanear_persistido(_CAMPOS_FILTRO_EMENDAS["parlamentar"], opcoes_parlamentar)
        parlamentares_selecionados = st.multiselect(
            "Parlamentar",
            options=opcoes_parlamentar,
            key=_CAMPOS_FILTRO_EMENDAS["parlamentar"],
            placeholder="Todos",
        )

filtradas = emendas
if anos_selecionados:
    filtradas = filtradas[filtradas["ano"].astype("string").isin(anos_selecionados)]
if rps_selecionados:
    filtradas = filtradas[filtradas["resultado_primario_cod"].isin(rps_selecionados)]
if parlamentares_selecionados:
    filtradas = filtradas[filtradas["parlamentar"].isin(parlamentares_selecionados)]
filtradas = filtradas.copy()

with st.container(horizontal=True):
    st.metric("Emendas", f"{len(filtradas):,}".replace(",", "."), border=True)
    st.metric(
        "Dotação atualizada",
        _valor_brl(_total(filtradas["dotacao_atualizada"])),
        border=True,
    )
    st.metric("Empenhado", _valor_brl(_total(filtradas["empenhada"])), border=True)
    st.metric("Liquidado", _valor_brl(_total(filtradas["liquidada"])), border=True)
    st.metric("Pago", _valor_brl(_total(filtradas["paga"])), border=True)


def _render_divergencias_dotacao(filtradas: pd.DataFrame, vinculos: pd.DataFrame) -> None:
    """Lista os PTRES cuja Dotação informada difere da Dotação Anual — só das emendas filtradas.
    Informativo: os dois valores aparecem lado a lado, sem dizer qual está correto."""
    divergencias = divergencias_dotacao(vinculos)
    if divergencias.empty or filtradas.empty:
        return
    chaves = filtradas[["ano", "resultado_primario_cod", "emenda_numero"]].drop_duplicates()
    divergencias = divergencias.merge(chaves, on=["ano", "resultado_primario_cod", "emenda_numero"])
    if divergencias.empty:
        return
    with st.container(border=True):
        st.markdown(f"**Dotação informada ≠ Dotação Anual por PTRES** — {len(divergencias)} PTRES")
        st.caption(
            "Os dois valores são exibidos sem indicar qual está correto: não há regra definida "
            "de prevalência. Confira na origem antes de decidir."
        )
        tabela = divergencias.assign(
            resultado_primario_cod=divergencias["resultado_primario_cod"].map("RP{}".format),
            dotacao_atualizada=divergencias["dotacao_atualizada"].map(_valor_brl),
            dotacao_anual_ptres=divergencias["dotacao_anual_ptres"].map(_valor_brl),
            diferenca_dotacao=divergencias["diferenca_dotacao"].map(_valor_brl),
        ).rename(
            columns={
                "ano": "Exercício",
                "resultado_primario_cod": "RP",
                "emenda_numero": "Emenda",
                "parlamentar": "Parlamentar",
                "ptres": "PTRES",
                "dotacao_atualizada": "Dotação informada",
                "dotacao_anual_ptres": "Dotação Anual (por PTRES)",
                "diferenca_dotacao": "Diferença",
            }
        )
        st.dataframe(tabela, hide_index=True, width="stretch")


_render_divergencias_dotacao(filtradas, resultado.vinculos)

if filtradas.empty:
    st.info("Nenhuma emenda corresponde aos filtros selecionados.")
else:
    ordenadas = filtradas.sort_values("dotacao_atualizada", ascending=False, na_position="last")
    for linha in ordenadas.itertuples():
        vinculos_da_emenda = resultado.vinculos[
            (resultado.vinculos["ano"] == linha.ano)
            & (resultado.vinculos["resultado_primario_cod"] == linha.resultado_primario_cod)
            & (resultado.vinculos["emenda_numero"] == linha.emenda_numero)
            & (resultado.vinculos["autor_emenda"] == linha.autor_emenda)
            & (resultado.vinculos["parlamentar"] == linha.parlamentar)
        ]
        _render_card_emenda(linha, vinculos_da_emenda)

st.caption(
    f"Base de Emendas: {manifesto_emendas.rotulo} · hash "
    f"{manifesto_emendas.sha256[:8]} · Execução Anual: hash "
    f"{manifesto_execucao.sha256[:8]}"
    + (
        ""
        if dotacao_anual is None
        else f" · Dotação Anual: hash {ManifestoDotacao.atual().sha256[:8]}"
    )
    + ". Valores anteriores a 2026 permanecem "
    "estáticos; valores executados de 2026+ são conciliados por RP e PTRES."
)
