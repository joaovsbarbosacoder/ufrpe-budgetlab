"""Visão gerencial da Dotação Anual, por ano de lançamento.

Lê o arquivo apontado pelo manifesto atual (`data/manifestos/dotacao_anual_atual.json`),
gerado por `src/importacao_dotacao.py` — mesmo padrão de importação versionada da Execução
Anual (ver `docs/base_execucao_anual.md`). A reimportação pela interface (seção "Reimportar
base", no final da página) reaproveita o mesmo componente `src/ui_reimportacao.py` que a
Execução Anual usa — upload, prévia com validação e delta, gravação só após confirmação
explícita quando há retroatividade ou exercício removido.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dotacao_anual_analysis import (
    KNOWN_ITEM_INDICATORS,
    apply_dotacao_anual_filters,
    build_dotacao_anual_year_analysis,
    build_item_indicators,
)
from src.importacao_dotacao import (
    DIRETORIO_MANIFESTOS_PADRAO,
    MEDIDAS,
    Manifesto,
    ROTULOS_MEDIDAS,
    importar,
    ler_dotacao_anual,
)
from src.ui_reimportacao import EspecificacaoReimportacao, render_reimportacao
from src.ui_theme import (
    format_brl_compact,
    format_brl_full,
    render_alert,
    render_metric_grid,
    render_page_header,
)


DIRETORIO_DADOS_BRUTOS = Path("data/raw")


@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_leitura(caminho: str, mtime: float) -> pd.DataFrame:
    """`mtime` só participa da chave de cache — força reler se o arquivo mudar."""

    return ler_dotacao_anual(caminho).workbook.consolidated_data


FILTERS = (
    ("ano", "Ano de lançamento", "ano_lancamento", None, None),
    ("acao_governo", "Ação Governo", "acao_codigo", "acao_descricao", None),
    ("ptres", "PTRES", "ptres_codigo", None, None),
    (
        "plano_orcamentario",
        "Plano Orçamentário",
        "plano_orcamentario_codigo",
        "plano_orcamentario_descricao",
        None,
    ),
    (
        "grupo_despesa",
        "Grupo de Despesa",
        "grupo_despesa_codigo",
        "grupo_despesa_descricao",
        None,
    ),
    (
        "fonte_recursos_detalhada",
        "Fonte de Recursos Detalhada",
        "fonte_recursos_detalhada_codigo",
        "fonte_recursos_detalhada_descricao",
        None,
    ),
    ("iduso", "IDUSO", "iduso_codigo", "iduso_descricao", None),
    (
        "resultado_primario",
        "Resultado Primário",
        "resultado_primario_codigo",
        "resultado_primario_descricao",
        None,
    ),
)

INDICATOR_DISPLAY_ORDER = (
    "dotacao_atualizada",
    "dotacao_inicial",
    "dotacao_suplementar",
    "dotacao_cancelada_remanejada",
)

INDICATOR_COLORS = {
    "dotacao_atualizada": "#4C8DFF",
    "dotacao_inicial": "#22D3B6",
    "dotacao_suplementar": "#A78BFA",
    "dotacao_cancelada_remanejada": "#F0576B",
}


def _option_mapping(
    dataframe: pd.DataFrame,
    value_column: str,
    description_column: str | None = None,
) -> dict[str, object]:
    columns = [value_column]
    if description_column:
        columns.append(description_column)

    options = dataframe.loc[:, columns].drop_duplicates()
    options = options.sort_values(value_column, na_position="last", kind="stable")

    mapping: dict[str, object] = {}
    for _, row in options.iterrows():
        raw_value = row[value_column]
        if pd.isna(raw_value):
            label = "(Valor nulo)"
            filter_value = None
        else:
            filter_value = int(raw_value) if value_column == "ano_lancamento" else raw_value
            value_text = str(filter_value)
            description = row.get(description_column, pd.NA)
            description_text = "" if pd.isna(description) else str(description)
            label = (
                f"{value_text} — {description_text}"
                if description_text and description_text != value_text
                else value_text
            )

        unique_label = label
        suffix = 2
        while unique_label in mapping and mapping[unique_label] != filter_value:
            unique_label = f"{label} ({suffix})"
            suffix += 1
        mapping[unique_label] = filter_value

    return mapping


def _selected_values(label: str, mapping: dict[str, object], key: str) -> list[object]:
    selected_labels = st.session_state.get(key, [])
    st.session_state[key] = [
        selected_label for selected_label in selected_labels if selected_label in mapping
    ]
    labels = st.multiselect(label, options=list(mapping), key=key, placeholder="Todos")
    return [mapping[selected_label] for selected_label in labels]


def _build_selections(dataframe: pd.DataFrame, source_key: str) -> dict[str, list[object]]:
    selections: dict[str, list[object]] = {}
    with st.sidebar:
        st.header("Filtros")
        st.caption("As opções acompanham o recorte selecionado nos filtros anteriores.")
        for filter_name, label, value_column, description_column, _ in FILTERS:
            available = apply_dotacao_anual_filters(dataframe, selections)
            mapping = _option_mapping(available, value_column, description_column)
            selections[filter_name] = _selected_values(
                label, mapping, f"dotacao_anual_{filter_name}_{source_key}"
            )
    return selections


def _with_alpha(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    red, green, blue = (int(hex_color[index : index + 2], 16) for index in (0, 2, 4))
    return f"rgba({red},{green},{blue},{alpha})"


def _render_year_chart(filtered: pd.DataFrame, source_key: str, ano_extracao: int) -> None:
    year_analysis = build_dotacao_anual_year_analysis(filtered)
    year_analysis = year_analysis.dropna(subset=["ano_lancamento"])

    indicator_code = st.segmented_control(
        "Indicador",
        options=list(INDICATOR_DISPLAY_ORDER),
        format_func=lambda code: KNOWN_ITEM_INDICATORS[code],
        default="dotacao_atualizada",
        key=f"dotacao_anual_indicator_{source_key}",
    )
    if not indicator_code:
        indicator_code = "dotacao_atualizada"

    chart_data = year_analysis.dropna(subset=[indicator_code])
    if chart_data.empty:
        st.info("Nenhum valor de " + KNOWN_ITEM_INDICATORS[indicator_code] + " neste recorte.")
        return

    color = INDICATOR_COLORS[indicator_code]
    years = [str(int(ano)) for ano in chart_data["ano_lancamento"]]
    em_andamento = [int(ano) == ano_extracao for ano in chart_data["ano_lancamento"]]
    values = [float(value) for value in chart_data[indicator_code]]
    rotulos_eixo = [
        f"{ano} ⏳" if andamento else ano for ano, andamento in zip(years, em_andamento)
    ]

    figure = go.Figure(
        go.Scatter(
            x=years,
            y=values,
            mode="lines+markers",
            line=dict(shape="spline", smoothing=1.1, width=4, color=color),
            marker=dict(
                size=[17 if andamento else 13 for andamento in em_andamento],
                symbol=["diamond" if andamento else "circle" for andamento in em_andamento],
                color=color,
                line=dict(width=2, color="#0B1220"),
            ),
            fill="tozeroy",
            fillcolor=_with_alpha(color, 0.16),
            hovertemplate=f"%{{x}}<br>{KNOWN_ITEM_INDICATORS[indicator_code]}: "
            "%{customdata}<extra></extra>",
            customdata=[
                format_brl_full(value) + (" — exercício em andamento" if andamento else "")
                for value, andamento in zip(values, em_andamento)
            ],
        )
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=30, b=10, l=10, r=10),
        font=dict(color="#E7ECF5", family="sans-serif"),
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            color="#93A1B8",
            type="category",
            tickvals=years,
            ticktext=rotulos_eixo,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#1B2536",
            zeroline=False,
            tickformat="~s",
            color="#93A1B8",
        ),
        hoverlabel=dict(bgcolor="#121B2D", font_color="#E7ECF5", bordercolor=color),
        height=420,
        showlegend=False,
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def _linhas_resumo_dotacao(manifesto: Manifesto) -> str:
    contagens = manifesto.contagens
    return (
        f"{contagens.get('abas_reconhecidas')} aba(s) reconhecida(s) · "
        f"{contagens.get('linhas_normalizadas')} linhas normalizadas · "
        f"{contagens.get('nulos')} nulos · {contagens.get('zeros')} zeros · "
        f"{contagens.get('negativos')} negativos · "
        f"exercícios {', '.join(map(str, manifesto.anos))}"
    )


ESPECIFICACAO_REIMPORTACAO = EspecificacaoReimportacao(
    prefixo_estado="dotacao_anual_reimport",
    diretorio_dados_brutos=DIRETORIO_DADOS_BRUTOS,
    diretorio_manifestos=DIRETORIO_MANIFESTOS_PADRAO,
    medidas=MEDIDAS,
    importar=importar,
    linhas_resumo=_linhas_resumo_dotacao,
    formatar_medida=lambda medida: ROTULOS_MEDIDAS[medida],
)


render_page_header(
    "Dotação Orçamentária",
    "Visão gerencial da Dotação Anual validada, por ano de lançamento.",
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

caminho_base = DIRETORIO_DADOS_BRUTOS / manifesto.arquivo
if not caminho_base.exists():
    st.error(
        f"O arquivo da extração atual do manifesto não foi encontrado em "
        f"'{caminho_base}'."
    )
    st.stop()

try:
    dataframe = _cached_leitura(str(caminho_base), caminho_base.stat().st_mtime)
except Exception as error:
    st.error(f"Não foi possível ler a base de Dotação Anual: {error}")
    st.stop()

render_alert("Base de Dotação Anual carregada a partir do manifesto atual.", "success")

source_key = manifesto.sha256[:12]
ano_extracao = datetime.fromisoformat(manifesto.data_extracao).year
anos = sorted(str(int(value)) for value in dataframe["ano_lancamento"].dropna().unique())
st.caption(f"Anos: {', '.join(anos) or 'não informado'}")

selections = _build_selections(dataframe, source_key)
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
            "subtitle": (
                format_brl_full(item_row["valor_movimento_liquido"]) if has_records else None
            ),
        }
    )
render_metric_grid(metric_cards, columns=4)

anos_no_recorte = sorted(int(valor) for valor in filtered["ano_lancamento"].dropna().unique())
if ano_extracao in anos_no_recorte:
    st.caption(
        f"⚠ O recorte inclui {ano_extracao}, exercício em andamento na data da "
        "extração — não compare diretamente com exercícios fechados."
    )

with st.container(border=True):
    st.subheader("Evolução por ano")
    st.caption(
        "Cada indicador é somado isoladamente por ano de lançamento, sem relação "
        "algébrica entre eles. Os filtros à esquerda atualizam o gráfico "
        "automaticamente. O exercício em andamento aparece com marcador "
        "diferenciado e ⏳ no rótulo."
    )
    _render_year_chart(filtered, source_key, ano_extracao)

data_extracao_texto = datetime.fromisoformat(manifesto.data_extracao).strftime("%d/%m/%Y")
st.caption(f"Procedência: extração de {data_extracao_texto} · hash {manifesto.sha256[:8]}")

with st.expander("Reimportar base", expanded=False):
    render_reimportacao(ESPECIFICACAO_REIMPORTACAO)
