"""Execução Mensal — base MENSAL da Execução da Despesa, a partir de 2026 (BI CPOC).

Complementar à página "Execução Orçamentária" (base ANUAL, 2023-2026) — não a substitui.
Lê `src/tesouro_execucao_mensal.py`, um arquivo fixo em `data/raw/` (`CAMINHO_EXECUCAO_MENSAL`,
mesmo caminho usado por `app_pages/consulta_empenhos.py` para a busca por item), sem manifesto
versionado (fora do escopo — ver docs/base_execucao_mensal.md, seção 7). Atualizável pela
página "Atualizar Planilhas" como planilha de trabalho (`src/atualizar_planilhas.py`, spec
`execucao_mensal`) — substituição direta com backup por carimbo de data/hora, sem detecção de
delta/retroatividade.

Empenhado usa sempre `valor_empenhado_por_bloco()` (nunca a soma direta das linhas): o valor
de um (NE, Natureza Detalhada, Subitem, mês) repete em cada linha de item daquele bloco —
somar direto multiplicaria o Empenhado pela quantidade de itens (ver docstring de
`src/tesouro_execucao_mensal.py`). Liquidado/Pago não sofrem essa duplicação (só existem nas
linhas de item de execução, uma por NE × mês) e são somados direto.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.design_tokens import ACCENT, ACCENT_STRONG, BORDER, POSITIVE, TEXT, TEXT_MUTED
from src.tesouro_execucao_mensal import ler_execucao_mensal, valor_empenhado_por_bloco
from src.ui_theme import format_brl_compact, format_brl_full, render_metric_grid, render_page_header

#: mesmo arquivo usado por `app_pages/consulta_empenhos.py` para a busca por item — base
#: MENSAL (só 2026+), sem importação versionada ainda.
CAMINHO_EXECUCAO_MENSAL = Path("data/raw") / "BI CPOC - EXEC. DESPESAS - Mensal.xlsx"

MESES_ABREV = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}

# nome do filtro -> (rótulo, coluna código, coluna descrição | None) — só dimensões que
# `valor_empenhado_por_bloco` também devolve (ver `_DIMENSOES_EXTRA_BLOCO`), para a composição
# por dimensão poder usar exatamente o mesmo recorte dos cards/gráfico.
FILTER_FIELDS = (
    ("gnd", "Grupo de Despesa (GND)", "gnd_cod", "gnd_desc"),
    ("fonte", "Fonte de Recursos", "fonte_cod", "fonte_desc"),
    ("acao", "Ação de Governo", "acao_cod", "acao_desc"),
    ("elemento", "Elemento de Despesa", "elemento_cod", "elemento_desc"),
    ("ugr", "UGR - Gestão", "ugr_cod", "ugr_desc"),
)


@st.cache_data(show_spinner="Lendo a base de Execução Mensal...")
def _cached_leitura(caminho: str, mtime: float) -> pd.DataFrame:
    return ler_execucao_mensal(caminho)


def _rotulo_mes(ano_mes: int) -> str:
    ano, mes = divmod(int(ano_mes), 100)
    return f"{MESES_ABREV.get(mes, mes)}/{ano}"


def _pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value * 100:.1f}%".replace(".", ",")


def _option_mapping(dataframe: pd.DataFrame, code_column: str, description_column: str | None) -> dict[str, object]:
    columns = [code_column] + ([description_column] if description_column else [])
    options = dataframe.loc[:, columns].drop_duplicates().sort_values(code_column, na_position="last", kind="stable")
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
    selected_labels = st.session_state.get(key, [])
    st.session_state[key] = [rotulo for rotulo in selected_labels if rotulo in mapping]
    labels = st.multiselect(label, options=list(mapping), key=key, placeholder="Todos")
    return [mapping[rotulo] for rotulo in labels]


def _apply_filters(dataframe: pd.DataFrame, selections: dict[str, list[object]]) -> pd.DataFrame:
    filtrado = dataframe
    for nome, _, coluna, _desc in FILTER_FIELDS:
        valores = selections.get(nome)
        if valores:
            filtrado = filtrado[filtrado[coluna].isin(valores)]
    valores_mes = selections.get("mes")
    if valores_mes:
        filtrado = filtrado[filtrado["ano_mes"].isin(valores_mes)]
    return filtrado


def _render_filtros(dataframe: pd.DataFrame, source_key: str) -> dict[str, list[object]]:
    selections: dict[str, list[object]] = {}

    meses_disponiveis = sorted(dataframe["ano_mes"].unique())
    mapa_meses = {_rotulo_mes(am): am for am in meses_disponiveis}
    meses_selecionados = _selected_values("Mês", mapa_meses, key=f"execucao_mensal_mes_{source_key}")
    if meses_selecionados:
        selections["mes"] = meses_selecionados

    colunas = st.columns(len(FILTER_FIELDS))
    for coluna, (nome, label, code_col, desc_col) in zip(colunas, FILTER_FIELDS, strict=True):
        disponivel = _apply_filters(dataframe, selections)
        mapping = _option_mapping(disponivel, code_col, desc_col)
        with coluna:
            valores = _selected_values(label, mapping, key=f"execucao_mensal_{nome}_{source_key}")
        if valores:
            selections[nome] = valores
    return selections


def _totais(df_filtrado: pd.DataFrame, dedup: pd.DataFrame) -> dict[str, float]:
    liquidado_pago = df_filtrado.loc[df_filtrado["tipo_linha"] == "item_execucao"]
    return {
        "empenhada": float(dedup["empenhada"].sum()),
        "liquidada": float(liquidado_pago["liquidada"].sum(min_count=1) or 0.0),
        "paga": float(liquidado_pago["paga"].sum(min_count=1) or 0.0),
    }


def _render_cards(df_filtrado: pd.DataFrame, dedup: pd.DataFrame) -> None:
    totais = _totais(df_filtrado, dedup)
    liquidado_pct = totais["liquidada"] / totais["empenhada"] if totais["empenhada"] else None
    pago_pct = totais["paga"] / totais["liquidada"] if totais["liquidada"] else None

    render_metric_grid(
        [
            {"label": "Empenhado", "value": format_brl_compact(totais["empenhada"])},
            {"label": "Liquidado", "value": format_brl_compact(totais["liquidada"])},
            {"label": "Pago", "value": format_brl_compact(totais["paga"])},
            {"label": "% Liquidado/Empenhado", "value": _pct(liquidado_pct)},
            {"label": "% Pago/Liquidado", "value": _pct(pago_pct)},
        ],
        columns=5,
    )


SERIE_MEDIDAS = (
    ("empenhada", "Empenhado", ACCENT),
    ("liquidada", "Liquidado", ACCENT_STRONG),
    ("paga", "Pago", POSITIVE),
)


def _por_mes(df_filtrado: pd.DataFrame, dedup: pd.DataFrame) -> pd.DataFrame:
    emp_mes = dedup.groupby("ano_mes")["empenhada"].sum()
    liquidado_pago = df_filtrado.loc[df_filtrado["tipo_linha"] == "item_execucao"]
    lp_mes = liquidado_pago.groupby("ano_mes")[["liquidada", "paga"]].sum(min_count=1)
    resultado = pd.DataFrame({"empenhada": emp_mes}).join(lp_mes, how="outer").fillna(0.0)
    return resultado.reset_index().sort_values("ano_mes")


def _render_serie_mensal(por_mes: pd.DataFrame) -> None:
    if por_mes.empty:
        st.info("Nenhum mês no recorte para montar a série.")
        return

    rotulos = [_rotulo_mes(am) for am in por_mes["ano_mes"]]
    figure = go.Figure()
    for coluna, nome, cor in SERIE_MEDIDAS:
        valores = [float(v) for v in por_mes[coluna]]
        figure.add_bar(
            name=nome, x=rotulos, y=valores, marker=dict(color=cor),
            hovertext=[f"{nome} {rotulo}: {format_brl_full(v)}" for rotulo, v in zip(rotulos, valores)],
            hovertemplate="%{hovertext}<extra></extra>",
        )
    figure.update_layout(
        barmode="group",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, family="sans-serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(type="category", showgrid=False, zeroline=False, color=TEXT_MUTED),
        yaxis=dict(showgrid=True, gridcolor=BORDER, zeroline=False, tickformat="~s", color=TEXT_MUTED),
        height=420, margin=dict(t=40, b=10, l=10, r=10),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


LIMITE_RANKING = 15


def _composicao(df_filtrado: pd.DataFrame, dedup: pd.DataFrame, coluna_cod: str, coluna_desc: str | None) -> pd.DataFrame:
    colunas_grupo = [coluna_cod] + ([coluna_desc] if coluna_desc else [])
    emp = dedup.groupby(colunas_grupo, dropna=False)["empenhada"].sum()
    liquidado_pago = df_filtrado.loc[df_filtrado["tipo_linha"] == "item_execucao"]
    lp = liquidado_pago.groupby(colunas_grupo, dropna=False)[["liquidada", "paga"]].sum(min_count=1)
    resultado = pd.DataFrame({"empenhada": emp}).join(lp, how="outer").fillna(0.0).reset_index()
    return resultado.sort_values("empenhada", ascending=False).reset_index(drop=True)


def _rotulo_categoria(row: pd.Series, coluna_cod: str, coluna_desc: str | None) -> str:
    codigo = row[coluna_cod]
    codigo_texto = str(codigo) if pd.notna(codigo) else "—"
    if coluna_desc:
        descricao = row.get(coluna_desc)
        if pd.notna(descricao) and str(descricao) != codigo_texto:
            return f"{codigo_texto} — {descricao}"
    return codigo_texto


def _render_composicao(df_filtrado: pd.DataFrame, dedup: pd.DataFrame, source_key: str) -> None:
    dimensoes = {label: (cod, desc) for _, label, cod, desc in FILTER_FIELDS}
    dimensao = st.selectbox("Dimensão", options=list(dimensoes), key=f"execucao_mensal_composicao_{source_key}")
    coluna_cod, coluna_desc = dimensoes[dimensao]

    tabela = _composicao(df_filtrado, dedup, coluna_cod, coluna_desc)
    total_categorias = len(tabela)
    exibidas = tabela.head(LIMITE_RANKING)
    if exibidas.empty:
        st.info("Nenhuma categoria no recorte atual para esta dimensão.")
        return

    rotulos = [_rotulo_categoria(row, coluna_cod, coluna_desc) for _, row in exibidas.iterrows()]
    rotulos_grafico, empenhado_grafico = rotulos[::-1], exibidas["empenhada"].tolist()[::-1]

    figure = go.Figure()
    figure.add_bar(
        x=empenhado_grafico, y=rotulos_grafico, orientation="h",
        marker=dict(color=ACCENT, cornerradius=4),
        hovertext=[format_brl_full(v) for v in empenhado_grafico],
        hovertemplate="%{y}: %{hovertext}<extra></extra>",
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, family="sans-serif"),
        xaxis=dict(showgrid=True, gridcolor=BORDER, zeroline=False, tickformat="~s", color=TEXT_MUTED),
        yaxis=dict(showgrid=False, zeroline=False, color=TEXT_MUTED),
        height=max(320, 32 * len(exibidas) + 80), margin=dict(t=20, b=10, l=10, r=10),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})

    st.dataframe(
        pd.DataFrame(
            {
                dimensao: rotulos,
                "Empenhado": exibidas["empenhada"].tolist(),
                "Liquidado": exibidas["liquidada"].tolist(),
                "Pago": exibidas["paga"].tolist(),
            }
        ),
        hide_index=True, width="stretch",
        column_config={
            "Empenhado": st.column_config.NumberColumn(format="R$ %.2f"),
            "Liquidado": st.column_config.NumberColumn(format="R$ %.2f"),
            "Pago": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )
    if total_categorias > LIMITE_RANKING:
        st.caption(f"Mostrando as {LIMITE_RANKING} categorias com maior Empenhado, de {total_categorias} no total.")
    else:
        st.caption(f"{total_categorias} categorias no recorte atual.")


# ---------------------------------------------------------------------- página
render_page_header(
    "Execução Mensal",
    "Execução da Despesa por mês (BI CPOC), a partir de 2026 — complementar à Execução "
    "Orçamentária (anual, 2023-2026).",
    "Execução",
)

if not CAMINHO_EXECUCAO_MENSAL.exists():
    st.info(
        f"A base mensal não foi encontrada em '{CAMINHO_EXECUCAO_MENSAL}'. Copie a extração "
        "atual (BI CPOC, variante com quebra mensal) para essa pasta para usar esta página."
    )
    st.stop()

try:
    dataframe = _cached_leitura(str(CAMINHO_EXECUCAO_MENSAL), CAMINHO_EXECUCAO_MENSAL.stat().st_mtime)
except Exception as error:
    st.error(f"Não foi possível ler a base de Execução Mensal: {error}")
    st.stop()

st.caption(
    "Leitura direta de arquivo — esta base ainda não tem manifesto/importação versionada "
    "(ver docs/base_execucao_mensal.md)."
)

source_key = str(int(CAMINHO_EXECUCAO_MENSAL.stat().st_mtime))
selections = _render_filtros(dataframe, source_key)
filtrado = _apply_filters(dataframe, selections)

if filtrado.empty:
    st.warning("Nenhum registro corresponde à combinação de filtros selecionada.")
    st.stop()

dedup = valor_empenhado_por_bloco(filtrado)
if dedup.empty:
    st.warning("Nenhuma linha de empenho no recorte atual (só linhas de item de execução).")
    st.stop()

_render_cards(filtrado, dedup)

with st.container(border=True):
    st.subheader("Por mês")
    st.caption("Empenhado, Liquidado e Pago por mês, sobre o mesmo recorte filtrado acima.")
    _render_serie_mensal(_por_mes(filtrado, dedup))

with st.container(border=True):
    st.subheader("Composição")
    st.caption("Empenhado, Liquidado e Pago por categoria de uma dimensão, sobre o mesmo recorte filtrado acima.")
    _render_composicao(filtrado, dedup, source_key)

st.caption(
    f"Fonte: '{CAMINHO_EXECUCAO_MENSAL.name}' · {dataframe['linha_origem'].nunique()} linhas "
    "brutas na planilha completa · Empenhado sempre deduplicado por (NE, Natureza Detalhada, "
    "Subitem, mês) — ver docs/base_execucao_mensal.md."
)
