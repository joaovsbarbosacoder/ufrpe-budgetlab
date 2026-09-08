"""Visão gerencial da Dotação Anual, por ano de lançamento.

Lê o arquivo apontado pelo manifesto atual (`data/manifestos/dotacao_anual_atual.json`),
gerado por `src/importacao_dotacao.py` — mesmo padrão de importação versionada da Execução
Anual (ver `docs/base_execucao_anual.md`). A reimportação pela interface não mora mais nesta
página — foi para "Atualizar Planilhas" (`app_pages/atualizar_planilhas.py`), pedido explícito
de um único lugar para atualizar qualquer base, versionada ou não. A especificação usada lá é
`src/reimportacao_especificacoes.py::ESPECIFICACAO_DOTACAO_ANUAL`.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.design_tokens import ACCENT, BORDER, NEGATIVE, POSITIVE, TEXT, TEXT_MUTED
from src.dotacao_anual_analysis import (
    KNOWN_ITEM_INDICATORS,
    apply_dotacao_anual_filters,
    build_dotacao_anual_year_analysis,
    build_item_indicators,
)
from src.importacao_dotacao import DIRETORIO_MANIFESTOS_PADRAO, NOME_PONTEIRO, Manifesto, carregar_atual
from src.importacao_execucao import (
    DIRETORIO_MANIFESTOS_PADRAO as DIRETORIO_MANIFESTOS_EXECUCAO,
    Manifesto as ManifestoExecucao,
    NOME_PONTEIRO as NOME_PONTEIRO_EXECUCAO,
    carregar_atual as carregar_execucao_atual,
)
from src.ui_theme import (
    format_brl_compact,
    format_brl_full,
    render_alert,
    render_metric_grid,
    render_page_header,
)


@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_leitura(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """`caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache — força reler
    quando o manifesto atual mudar. O DataFrame devolvido já é a base composta por ano (ver
    `importacao_dotacao.carregar_atual`), não só o arquivo do manifesto atual."""

    return carregar_atual()


@st.cache_data(show_spinner="Lendo a base de Execução Anual...")
def _cached_leitura_execucao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """Mesmo padrão de `_cached_leitura`, mas para a Execução Anual — usada só no bloco
    "Orçamento x Execução" (abaixo), que cruza as duas bases pelo Exercício."""

    return carregar_execucao_atual()


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

# UGR da própria UFRPE na Execução Anual (ugr_desc = "UNIVERSIDADE FEDERAL RURAL DE
# PERNAMBUCO") — a base de Execução também traz empenhos de orçamento descentralizado
# (emitidos por outras UGRs contra ações/PTRES que a UFRPE também usa, ex.: outras
# universidades federais). Sem esse filtro o Empenhado do bloco "Orçamento x Execução"
# fica sistematicamente maior que a Dotação Atualizada da UFRPE (confirmado nos 4 anos em
# comum entre as duas bases — 2023 a 2026) porque soma execução de fora do escopo
# orçamentário que a Dotação Anual representa.
UGR_UFRPE = "15239"

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


def _pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value * 100:.1f}%".replace(".", ",")


def _render_waterfall_chart(valores: dict[str, float]) -> None:
    """Formação da Dotação (Inicial→Suplementar→Cancelada/Remanejada→Atualizada) seguida do
    consumo pela Execução (Empenhado→Liquidado→Pago), num único gráfico em cascata.

    Da "Dotação Atualizada" em diante os marcadores são "total" (valor absoluto real de cada
    estágio, não um delta calculado) de propósito: Empenhado/Liquidado/Pago vêm de uma base
    independente (Execução Anual) e não há garantia de que fechem algebricamente com a
    Dotação — mostrar o valor real de cada estágio evita fabricar uma relação que os dados não
    sustentam (mesmo cuidado do comentário em `_render_year_chart` sobre os 4 indicadores de
    Dotação não terem relação algébrica garantida entre si nesta base).
    """

    labels = [
        "Dotação Inicial",
        "Suplementar",
        "Cancelada/Remanejada",
        "Dotação Atualizada",
        "Empenhado",
        "Liquidado",
        "Pago",
    ]
    # "absolute" (não "total"): fixa o valor real de cada âncora — "total" faria o Plotly
    # recalcular a barra como soma acumulada dos deltas anteriores, ignorando o valor real
    # informado (o que já causou uma barra de Empenhado/Liquidado/Pago com altura errada).
    measures = ["absolute", "relative", "relative", "absolute", "absolute", "absolute", "absolute"]
    values = [
        valores["inicial"],
        valores["suplementar"],
        valores["cancelada"],
        valores["atualizada"],
        valores["empenhado"],
        valores["liquidado"],
        valores["pago"],
    ]

    figure = go.Figure(
        go.Waterfall(
            x=labels,
            measure=measures,
            y=values,
            increasing=dict(marker=dict(color=POSITIVE)),
            decreasing=dict(marker=dict(color=NEGATIVE)),
            totals=dict(marker=dict(color=ACCENT)),
            connector=dict(line=dict(color=BORDER, width=1)),
            text=[format_brl_compact(valor) for valor in values],
            textposition="outside",
            textfont=dict(color=TEXT),
            hovertext=[format_brl_full(valor) for valor in values],
            hovertemplate="%{x}<br>%{hovertext}<extra></extra>",
        )
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, family="sans-serif"),
        showlegend=False,
        margin=dict(t=30, b=10, l=10, r=10),
        xaxis=dict(showgrid=False, zeroline=False, color=TEXT_MUTED),
        yaxis=dict(
            showgrid=True, gridcolor=BORDER, zeroline=False, tickformat="~s", color=TEXT_MUTED
        ),
        height=440,
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def _render_orcamento_execucao(
    dataframe: pd.DataFrame,
    execucao_dataframe: pd.DataFrame | None,
    ano_extracao: int,
    source_key: str,
) -> None:
    if execucao_dataframe is None:
        st.info(
            "Nenhuma base de Execução Anual foi importada ainda — este bloco cruza Dotação "
            "x Execução e precisa das duas bases. Importe a Execução Anual em 'Atualizar "
            "Planilhas' para habilitá-lo."
        )
        return

    anos_dotacao = {int(valor) for valor in dataframe["ano_lancamento"].dropna().unique()}
    anos_execucao = {int(valor) for valor in execucao_dataframe["ano"].dropna().unique()}
    anos_comuns = sorted(anos_dotacao & anos_execucao, reverse=True)
    if not anos_comuns:
        st.info("Nenhum exercício em comum entre Dotação Anual e Execução Anual para cruzar.")
        return

    indice_padrao = anos_comuns.index(ano_extracao) if ano_extracao in anos_comuns else 0
    ano = st.selectbox(
        "Exercício",
        options=anos_comuns,
        index=indice_padrao,
        key=f"dotacao_anual_orcamento_execucao_ano_{source_key}",
    )
    if ano == ano_extracao:
        st.caption(
            f"⚠ {ano} é o exercício em andamento na data da extração — Empenhado, Liquidado "
            "e Pago ainda vão crescer até o fechamento."
        )

    dotacao_ano = dataframe[dataframe["ano_lancamento"] == ano]
    indicadores = build_item_indicators(dotacao_ano).set_index("item_informacao_codigo")

    def _valor_dotacao(codigo: str) -> float:
        linha = indicadores.loc[codigo]
        if int(linha["quantidade_registros"]) == 0:
            return 0.0
        return float(linha["valor_movimento_liquido"])

    inicial = _valor_dotacao("dotacao_inicial")
    suplementar = _valor_dotacao("dotacao_suplementar")
    cancelada = _valor_dotacao("dotacao_cancelada_remanejada")
    atualizada = _valor_dotacao("dotacao_atualizada")

    execucao_ano = execucao_dataframe[
        (execucao_dataframe["ano"] == ano) & (execucao_dataframe["ugr_cod"] == UGR_UFRPE)
    ]
    totais_execucao = execucao_ano[["empenhada", "liquidada", "paga"]].sum(min_count=1)
    empenhado = float(totais_execucao["empenhada"]) if pd.notna(totais_execucao["empenhada"]) else 0.0
    liquidado = float(totais_execucao["liquidada"]) if pd.notna(totais_execucao["liquidada"]) else 0.0
    pago = float(totais_execucao["paga"]) if pd.notna(totais_execucao["paga"]) else 0.0

    if empenhado > atualizada + 0.01:
        # "\\$" escapa o cifrão: dois "R$" na mesma string do st.warning (que renderiza
        # Markdown) formam um par de delimitadores de LaTeX para o Streamlit, e tudo entre
        # eles vira fórmula matemática em vez de texto normal.
        empenhado_texto = format_brl_full(empenhado).replace("$", "\\$")
        atualizada_texto = format_brl_full(atualizada).replace("$", "\\$")
        st.warning(
            f"Empenhado ({empenhado_texto}) supera a Dotação Atualizada "
            f"({atualizada_texto}) neste exercício — Dotação e Execução são "
            "bases independentes; confira se os dois escopos são realmente comparáveis "
            "aqui antes de usar este número."
        )

    _render_waterfall_chart(
        {
            "inicial": inicial,
            "suplementar": suplementar,
            "cancelada": cancelada,
            "atualizada": atualizada,
            "empenhado": empenhado,
            "liquidado": liquidado,
            "pago": pago,
        }
    )

    saldo_a_empenhar = atualizada - empenhado
    saldo_a_liquidar = empenhado - liquidado
    saldo_a_pagar = liquidado - pago
    render_metric_grid(
        [
            {
                "label": "Saldo a empenhar",
                "value": format_brl_compact(saldo_a_empenhar),
                "subtitle": (
                    _pct(saldo_a_empenhar / atualizada) + " da Dotação Atualizada"
                    if atualizada
                    else None
                ),
            },
            {
                "label": "Saldo a liquidar",
                "value": format_brl_compact(saldo_a_liquidar),
                "subtitle": (
                    _pct(saldo_a_liquidar / empenhado) + " do Empenhado" if empenhado else None
                ),
            },
            {
                "label": "Saldo a pagar",
                "value": format_brl_compact(saldo_a_pagar),
                "subtitle": (
                    _pct(saldo_a_pagar / liquidado) + " do Liquidado" if liquidado else None
                ),
            },
        ],
        columns=3,
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

caminho_ponteiro = DIRETORIO_MANIFESTOS_PADRAO / NOME_PONTEIRO
try:
    dataframe = _cached_leitura(str(caminho_ponteiro), caminho_ponteiro.stat().st_mtime)
except Exception as error:
    st.error(f"Não foi possível ler a base de Dotação Anual: {error}")
    st.stop()

render_alert("Base de Dotação Anual carregada a partir do manifesto atual.", "success")

manifesto_execucao = ManifestoExecucao.atual()
execucao_dataframe: pd.DataFrame | None = None
if manifesto_execucao is not None:
    caminho_ponteiro_execucao = DIRETORIO_MANIFESTOS_EXECUCAO / NOME_PONTEIRO_EXECUCAO
    try:
        execucao_dataframe = _cached_leitura_execucao(
            str(caminho_ponteiro_execucao), caminho_ponteiro_execucao.stat().st_mtime
        )
    except Exception:
        execucao_dataframe = None

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

with st.container(border=True):
    st.subheader("Orçamento x Execução")
    st.caption(
        "Formação da Dotação (Inicial → Suplementar → Cancelada/Remanejada → Atualizada) "
        "seguida do consumo pela Execução (Empenhado → Liquidado → Pago) no exercício "
        "escolhido. Usa o exercício inteiro, sem os filtros de dimensão à esquerda. A "
        "Execução considera só a UGR Gestão UFRPE — orçamento descentralizado, executado "
        "por outras UGRs, fica fora deste comparativo."
    )
    _render_orcamento_execucao(dataframe, execucao_dataframe, ano_extracao, source_key)

data_extracao_texto = datetime.fromisoformat(manifesto.data_extracao).strftime("%d/%m/%Y")
st.caption(
    f"Última extração: {data_extracao_texto} · hash {manifesto.sha256[:8]} — exercícios não "
    "trazidos por ela usam a extração anterior que os trouxe (composição por ano)."
)
