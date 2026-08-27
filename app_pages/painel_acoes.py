"""Painel por Ação de Governo — um cartão por ação, subdivisões dentro do cartão.

Adaptação do protótipo em `design_handoff_streamlit/painel_acoes.py` (em vez do
`data_loader.py` do pacote, que lê um caminho fixo em disco com forward fill e descarta
linhas sem valor — ambos incompatíveis com as regras deste projeto). Ver decisão registrada
no histórico da conversa.

Lê o arquivo apontado pelo manifesto atual de Dotação Anual (`src/importacao_dotacao.py`,
mesmo padrão da Execução Anual), não mais `st.session_state`.

Sem gráficos: só valores tabulares dentro de cada cartão, com todas as
subdivisões visíveis de uma vez (sem truncar nem exigir um clique extra).
Os cartões usam HTML injetado (`st.markdown(..., unsafe_allow_html=True)`)
porque a grade de 10 colunas com par código/nome por célula não existe em
`st.dataframe` nem em `st.columns` sem virar uma grade frouxa; os filtros
são nativos.
"""

from __future__ import annotations

import html as html_lib
from datetime import datetime

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
    RADIUS,
    SIZE,
    SPACE,
    SUBDIV_COLUMNS,
    SUBDIV_GAP,
    SURFACE,
    TABLE_MIN_WIDTH,
    TEXT,
    TEXT_MUTED,
    TRACK,
)
from src.dotacao_anual_analysis import (
    KNOWN_ITEM_INDICATORS,
    apply_dotacao_anual_filters,
    build_dotacao_anual_subdivision_analysis,
    build_item_indicators,
)
from src.importacao_dotacao import DIRETORIO_MANIFESTOS_PADRAO, NOME_PONTEIRO, Manifesto, carregar_atual
from src.ui_theme import format_brl_compact, render_alert, render_metric_grid, render_page_header


@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_leitura(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """`caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache — força reler
    quando o manifesto atual mudar. O DataFrame devolvido já é a base composta por ano (ver
    `importacao_dotacao.carregar_atual`), não só o arquivo do manifesto atual."""

    return carregar_atual()


INDICATOR_DISPLAY_ORDER = (
    "dotacao_inicial",
    "dotacao_suplementar",
    "dotacao_cancelada_remanejada",
    "dotacao_atualizada",
)

# nome do filtro -> (rótulo, coluna código, coluna descrição | None)
FILTER_FIELDS = (
    ("iduso", "IDUSO", "iduso_codigo", "iduso_descricao"),
    (
        "resultado_primario",
        "Res. Primário Lei",
        "resultado_primario_codigo",
        "resultado_primario_descricao",
    ),
    ("grupo_despesa", "Grupo de Despesa", "grupo_despesa_codigo", "grupo_despesa_descricao"),
    ("acao_governo", "Ação Governo", "acao_codigo", "acao_descricao"),
    ("ptres", "PTRES", "ptres_codigo", None),
    (
        "fonte_recursos_detalhada",
        "Fonte Detalhada",
        "fonte_recursos_detalhada_codigo",
        "fonte_recursos_detalhada_descricao",
    ),
    (
        "plano_orcamentario",
        "Plano Orçamentário",
        "plano_orcamentario_codigo",
        "plano_orcamentario_descricao",
    ),
)


# ---------------------------------------------------------------- formatação
def _esc(value: object) -> str:
    return html_lib.escape(str(value))


def _dash(value: object) -> str:
    return "—" if pd.isna(value) else _esc(value)


def _num(value: object) -> str:
    if pd.isna(value):
        return "—"
    return f"{round(float(value)):,}".replace(",", ".")


def _resumo_atributo(values: pd.Series) -> str:
    unicos = sorted({str(value) for value in values if pd.notna(value)})
    if not unicos:
        return "—"
    return _esc(unicos[0]) if len(unicos) == 1 else f"{len(unicos)} valores"


# ------------------------------------------------------------------- filtros
def _option_mapping(
    dataframe: pd.DataFrame,
    code_column: str,
    description_column: str | None,
) -> dict[str, object]:
    columns = [code_column] + ([description_column] if description_column else [])
    options = dataframe.loc[:, columns].drop_duplicates()
    options = options.sort_values(code_column, na_position="last", kind="stable")

    mapping: dict[str, object] = {}
    for _, row in options.iterrows():
        code = row[code_column]
        if pd.isna(code):
            continue
        label = str(code)
        if description_column:
            description = row.get(description_column, pd.NA)
            if pd.notna(description) and str(description) != label:
                label = f"{label} — {description}"
        mapping[label] = code
    return mapping


def _selected_values(label: str, mapping: dict[str, object], key: str) -> list[object]:
    """Caixa de múltipla seleção: vazio equivale a 'todos' (placeholder)."""

    selected_labels = st.session_state.get(key, [])
    st.session_state[key] = [
        selected_label for selected_label in selected_labels if selected_label in mapping
    ]
    labels = st.multiselect(label, options=list(mapping), key=key, placeholder="Todos")
    return [mapping[selected_label] for selected_label in labels]


def _render_filters(
    dataframe: pd.DataFrame, source_key: str, ano_extracao: int
) -> tuple[int, dict[str, list[object]]]:
    """Dois filtros por linha (4 colunas), não oito espremidos numa só.

    Com sete filtros de dimensão em uma única linha, cada caixa ficava
    estreita demais para os rótulos "código — descrição" (alguns com mais
    de 60 caracteres): os valores marcados quebravam em várias linhas e a
    lista de opções cortava o texto. Duas linhas de quatro dobra a largura
    disponível para cada filtro.
    """

    anos = sorted(int(value) for value in dataframe["ano_lancamento"].dropna().unique())
    row1 = st.columns(4)
    row2 = st.columns(4)
    filter_columns = [row1[1], row1[2], row1[3], row2[0], row2[1], row2[2], row2[3]]

    with row1[0]:
        ano = st.selectbox(
            "Ano",
            anos,
            index=len(anos) - 1,
            key=f"painel_acoes_ano_{source_key}",
            format_func=lambda valor: f"{valor} ⏳" if valor == ano_extracao else str(valor),
        )

    selections: dict[str, list[object]] = {"ano": [ano]}
    for column, (filter_name, label, code_column, description_column) in zip(
        filter_columns, FILTER_FIELDS, strict=True
    ):
        available = apply_dotacao_anual_filters(dataframe, selections)
        # Uma combinação de dimensões pode existir na planilha só porque teve
        # dado em outro ano — sem isso, ela não representa nenhuma dotação no
        # recorte atual e não deve aparecer como opção selecionável (mesmo
        # critério usado para ocultar subdivisões vazias dos cartões).
        with_real_value = available[
            available["item_informacao_codigo"].isin(KNOWN_ITEM_INDICATORS)
            & available["valor_movimento_liquido"].notna()
        ]
        mapping = _option_mapping(with_real_value, code_column, description_column)
        key = f"painel_acoes_{filter_name}_{source_key}"
        with column:
            values = _selected_values(label, mapping, key)
        if values:
            selections[filter_name] = values

    return ano, selections


# ------------------------------------------------------------------- estilos
def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .po-card {{
            border: 1px solid {BORDER}; border-radius: {RADIUS};
            background: {SURFACE}; padding: {CARD_PAD};
            margin-bottom: {SPACE['xl']};
        }}
        .po-card-head {{
            display: grid; grid-template-columns: minmax(0,1fr) auto;
            gap: 24px; align-items: start; margin-bottom: {SPACE['md']};
        }}
        .po-kicker {{
            font-family: {FONT_HEADING}; font-size: {SIZE['value']};
            letter-spacing: {TRACK['kicker']}; color: {ACCENT}; text-transform: uppercase;
        }}
        .po-title {{
            margin: 3px 0 8px; font-family: {FONT_HEADING}; font-weight: 600;
            font-size: {SIZE['card_title']}; line-height: 1.12; color: {TEXT};
            text-transform: uppercase; text-wrap: pretty;
        }}
        .po-tags {{ display: flex; flex-wrap: wrap; gap: {SPACE['xs']}; }}
        .po-tag {{
            font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
            border: 1px solid {ACCENT_LINE}; border-radius: {RADIUS};
            padding: 2px 7px; background: {ACCENT_SOFT};
        }}
        .po-metric-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .po-metric {{
            font-family: {FONT_HEADING}; font-size: {SIZE['metric']}; line-height: 1.1;
            color: {ACCENT_STRONG}; font-variant-numeric: tabular-nums;
        }}
        .po-scroll {{ overflow-x: auto; padding-bottom: 2px; }}
        .po-row, .po-head, .po-foot {{
            display: grid; grid-template-columns: {SUBDIV_COLUMNS};
            gap: {SUBDIV_GAP}; min-width: {TABLE_MIN_WIDTH};
        }}
        .po-head {{
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .po-row {{
            padding: 9px 0; border-bottom: 1px solid {BORDER_SOFT}; align-items: baseline;
        }}
        .po-foot {{ padding-top: 9px; font-family: {FONT_HEADING}; align-items: baseline; }}
        .po-name {{
            font-family: {FONT_BODY}; font-size: {SIZE['body']}; line-height: 1.25; color: {TEXT};
            overflow-wrap: normal; word-break: normal;
        }}
        .po-name-sm {{
            font-family: {FONT_BODY}; font-size: {SIZE['small']}; line-height: 1.25; color: {TEXT};
            overflow-wrap: normal; word-break: normal;
        }}
        .po-code {{
            font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: {TRACK['label']}; color: {TEXT_MUTED};
            white-space: nowrap;
        }}
        .po-flat {{
            font-family: {FONT_HEADING}; font-size: {SIZE['small']};
            letter-spacing: 0.08em; color: {TEXT_MUTED};
            white-space: nowrap;
        }}
        .po-val {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED};
            white-space: nowrap;
        }}
        .po-val-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
            white-space: nowrap;
        }}
        .po-foot-label {{
            grid-column: span 6; font-size: {SIZE['label']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .po-foot-val {{
            text-align: right; font-size: {SIZE['body']}; font-variant-numeric: tabular-nums; color: {TEXT};
            white-space: nowrap;
        }}
        .po-foot-total {{
            text-align: right; font-size: 15px; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
            white-space: nowrap;
        }}
        .po-empty {{
            font-family: {FONT_HEADING}; font-size: 16px; letter-spacing: 0.1em;
            text-transform: uppercase; color: {TEXT_MUTED}; padding: 40px 0;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


CABECALHO = [
    ("Plano orçamentário", ""), ("Fonte de recursos detalhada", ""),
    ("Grupo de despesa", ""), ("Res. prim. lei", ""), ("Iduso", ""), ("PTRES", ""),
    ("Inicial", "right"), ("Suplem.", "right"),
    ("Canc./remanej.", "right"), ("Atualizada", "right"),
]


def _html_cabecalho() -> str:
    celulas = "".join(
        f'<span style="text-align:{alinhamento or "left"}">{texto}</span>'
        for texto, alinhamento in CABECALHO
    )
    return f'<div class="po-head">{celulas}</div>'


def _par(nome: object, codigo: object, prefixo: str = "", classe: str = "po-name-sm") -> str:
    nome_texto = "(não informado)" if pd.isna(nome) else _esc(nome)
    return (
        f'<div><div class="{classe}">{nome_texto}</div>'
        f'<div class="po-code">{prefixo}{_dash(codigo)}</div></div>'
    )


def _html_linha(r) -> str:
    return (
        '<div class="po-row">'
        + _par(r.plano_orcamentario_descricao, r.plano_orcamentario_codigo, "PO ", "po-name")
        + _par(r.fonte_recursos_detalhada_descricao, r.fonte_recursos_detalhada_codigo)
        + _par(r.grupo_despesa_descricao, r.grupo_despesa_codigo, "GND ")
        + _par(r.resultado_primario_descricao, r.resultado_primario_codigo, "RP ")
        + f'<span class="po-flat">{_dash(r.iduso_codigo)}</span>'
        + f'<span class="po-flat">{_dash(r.ptres_codigo)}</span>'
        + f'<span class="po-val">{_num(r.dotacao_inicial)}</span>'
        + f'<span class="po-val">{_num(r.dotacao_suplementar)}</span>'
        + f'<span class="po-val">{_num(r.dotacao_cancelada_remanejada)}</span>'
        + f'<span class="po-val-strong">{_num(r.dotacao_atualizada)}</span>'
        + "</div>"
    )


def _render_card(codigo: str, nome: object, grupo: pd.DataFrame, source_key: str) -> None:
    tags = [
        ("PTRES", _resumo_atributo(grupo["ptres_codigo"])),
        ("IDUSO", _resumo_atributo(grupo["iduso_codigo"])),
        ("RP", _resumo_atributo(grupo["resultado_primario_codigo"])),
        ("GND", _resumo_atributo(grupo["grupo_despesa_codigo"])),
        ("Fontes", _resumo_atributo(grupo["fonte_recursos_detalhada_codigo"])),
        ("PO", _resumo_atributo(grupo["plano_orcamentario_codigo"])),
    ]
    tags_html = "".join(f'<span class="po-tag">{chave} {valor}</span>' for chave, valor in tags)

    total = grupo["dotacao_atualizada"].sum(min_count=1)
    total_texto = "Sem registros" if pd.isna(total) else format_brl_compact(total)
    n = len(grupo)

    ordenado = grupo.sort_values("dotacao_atualizada", ascending=False, na_position="last")
    linhas = "".join(_html_linha(row) for row in ordenado.itertuples())
    somas = {item: grupo[item].sum(min_count=1) for item in KNOWN_ITEM_INDICATORS}

    st.markdown(
        f"""
        <div class="po-card">
          <div class="po-card-head">
            <div style="min-width:0">
              <div class="po-kicker">AÇÃO DE GOVERNO {_esc(codigo)}</div>
              <div class="po-title">{_dash(nome)}</div>
              <div class="po-tags">{tags_html}</div>
            </div>
            <div style="text-align:right">
              <div class="po-metric-label">Dotação atualizada</div>
              <div class="po-metric">{total_texto}</div>
              <div class="po-metric-label" style="margin-top:4px">
                {n} {"subdivisão" if n == 1 else "subdivisões"}
              </div>
            </div>
          </div>
          <div class="po-scroll">
            {_html_cabecalho()}
            {linhas}
            <div class="po-foot">
              <span class="po-foot-label">Total da ação</span>
              <span class="po-foot-val">{_num(somas['dotacao_inicial'])}</span>
              <span class="po-foot-val">{_num(somas['dotacao_suplementar'])}</span>
              <span class="po-foot-val">{_num(somas['dotacao_cancelada_remanejada'])}</span>
              <span class="po-foot-total">{_num(somas['dotacao_atualizada'])}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------- página
render_page_header(
    "Painel por Ação de Governo",
    "Dotação Anual por ação de governo, com subdivisões dentro de cada cartão.",
    "Dotação",
)

manifesto = Manifesto.atual()
if manifesto is None:
    st.info(
        "Nenhuma base de Dotação Anual foi importada ainda. Rode a importação "
        "inicial (`python -m src.importacao_dotacao <arquivo>`) antes de usar "
        "esta página."
    )
    st.stop()

caminho_ponteiro = DIRETORIO_MANIFESTOS_PADRAO / NOME_PONTEIRO
try:
    dataframe = _cached_leitura(str(caminho_ponteiro), caminho_ponteiro.stat().st_mtime)
except Exception as error:
    st.error(f"Não foi possível ler a base de Dotação Anual: {error}")
    st.stop()

source_key = manifesto.sha256[:12]
ano_extracao = datetime.fromisoformat(manifesto.data_extracao).year
_inject_css()

render_alert("Base de Dotação Anual carregada a partir do manifesto atual.", "success")

ano, selections = _render_filters(dataframe, source_key, ano_extracao)
filtered = apply_dotacao_anual_filters(dataframe, selections)

if filtered.empty:
    st.warning("Nenhum registro corresponde à combinação de filtros selecionada.")
    st.stop()

indicators = build_item_indicators(filtered).set_index("item_informacao_codigo")
metric_cards = []
for item_code in INDICATOR_DISPLAY_ORDER:
    item_row = indicators.loc[item_code]
    has_records = int(item_row["quantidade_registros"]) > 0
    metric_cards.append(
        {
            "label": KNOWN_ITEM_INDICATORS[item_code],
            "value": (
                format_brl_compact(item_row["valor_movimento_liquido"])
                if has_records
                else "Sem registros"
            ),
        }
    )
render_metric_grid(metric_cards, columns=4)

subdivisions = build_dotacao_anual_subdivision_analysis(filtered)
subdivisions = subdivisions[subdivisions["acao_codigo"].notna()]

# Uma subdivisão sem nenhum dos quatro indicadores conhecidos não tem
# nenhuma informação a mostrar no recorte (ano/filtros) atual — a linha
# existe na base porque a combinação de dimensões existe em outro ano, não
# porque haja dado para exibir aqui. Isso não descarta dado algum: a base
# normalizada em memória continua completa, só a apresentação omite linhas
# vazias.
has_any_indicator = subdivisions[list(KNOWN_ITEM_INDICATORS)].notna().any(axis=1)
subdivisions = subdivisions[has_any_indicator]

acao_groups = subdivisions.groupby(["acao_codigo", "acao_descricao"], dropna=False, sort=False)
st.caption(
    f"{acao_groups.ngroups} ações · {len(subdivisions)} subdivisões · ano {ano}"
)
if ano == ano_extracao:
    st.caption(
        f"⚠ {ano_extracao} é o exercício em andamento na data da extração — não "
        "compare diretamente com exercícios fechados."
    )

if acao_groups.ngroups == 0:
    st.markdown(
        '<div class="po-empty">Nenhuma ação com dotação para os filtros selecionados.</div>',
        unsafe_allow_html=True,
    )
    st.stop()

ordem = (
    acao_groups["dotacao_atualizada"]
    .apply(lambda serie: serie.sum(min_count=1))
    .fillna(0.0)
    .sort_values(ascending=False)
    .index
)
for codigo, nome in ordem:
    grupo = subdivisions[subdivisions["acao_codigo"] == codigo]
    _render_card(codigo, nome, grupo, source_key)

data_extracao_texto = datetime.fromisoformat(manifesto.data_extracao).strftime("%d/%m/%Y")
st.caption(
    f"Última extração: {data_extracao_texto} · hash {manifesto.sha256[:8]} — exercícios não "
    "trazidos por ela usam a extração anterior que os trouxe (composição por ano)."
)
