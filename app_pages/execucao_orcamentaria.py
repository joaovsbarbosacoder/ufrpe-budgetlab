"""Execução Orçamentária — base Anual (BI CPOC), filtros e indicadores.

Lê o arquivo apontado pelo manifesto atual (`data/manifestos/execucao_anual_atual.json`),
gerado por `src/importacao_execucao.py` — importação versionada própria, o padrão adotado por
toda base do projeto (ver também Dotação Anual, `src/importacao_dotacao.py`). A reimportação
(upload manual OU a pasta de entrada compartilhada, ver `src/ui_reimportacao.py`) não mora mais
nesta página — foi para "Atualizar Planilhas" (`app_pages/atualizar_planilhas.py`), pedido
explícito de um único lugar para atualizar qualquer base, versionada ou não. A especificação
usada lá é `src/reimportacao_especificacoes.py::ESPECIFICACAO_EXECUCAO_ANUAL`.

Implementa os quatro blocos da seção 8 de `docs/base_execucao_anual.md`:
filtros no topo, faixa de cards, série histórica, composição por dimensão e rastreabilidade.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.design_tokens import ACCENT, ACCENT_STRONG, BG, BORDER, POSITIVE, TEXT, TEXT_MUTED
from src.execucao_anual import (
    DIMENSOES_ANALITICAS,
    MEDIDAS,
    agregar,
    detalhar_nota_empenho,
)
from src.importacao_execucao import DIRETORIO_MANIFESTOS_PADRAO, NOME_PONTEIRO, Manifesto, carregar_atual
from src.ui_theme import (
    format_brl_compact,
    format_brl_full,
    render_alert,
    render_metric_grid,
    render_page_header,
)


# nome do filtro -> (rótulo, coluna código, coluna descrição | None)
FILTER_FIELDS = (
    ("ano", "Exercício", "ano", None),
    ("gnd", "Grupo de Despesa (GND)", "gnd_cod", "gnd_desc"),
    ("fonte", "Fonte de Recursos", "fonte_cod", "fonte_desc"),
    (
        "resultado_primario",
        "Resultado Primário",
        "resultado_primario_cod",
        "resultado_primario_desc",
    ),
    ("ugr", "UGR", "ugr_cod", "ugr_desc"),
)


@st.cache_data(show_spinner="Lendo a base de Execução Anual...")
def _cached_leitura(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """`caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache — força reler
    quando o manifesto atual mudar (toda importação nova, mesmo parcial, reescreve o
    ponteiro). O DataFrame devolvido já é a base composta por ano (ver
    `importacao_execucao.carregar_atual`), não só o arquivo do manifesto atual."""

    return carregar_atual()


def _pct(value: float | None) -> str:
    if pd.isna(value):
        return "—"
    return f"{value * 100:.1f}%".replace(".", ",")


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


def _apply_filters(dataframe: pd.DataFrame, selections: dict[str, list[object]]) -> pd.DataFrame:
    filtered = dataframe
    for filter_name, _, column, _description_column in FILTER_FIELDS:
        values = selections.get(filter_name)
        if not values:
            continue
        filtered = filtered[filtered[column].isin(values)]
    return filtered


def _render_filters(dataframe: pd.DataFrame, source_key: str) -> dict[str, list[object]]:
    columns = st.columns(len(FILTER_FIELDS))
    selections: dict[str, list[object]] = {}
    for column, (filter_name, label, code_column, description_column) in zip(
        columns, FILTER_FIELDS, strict=True
    ):
        available = _apply_filters(dataframe, selections)
        mapping = _option_mapping(available, code_column, description_column)
        key = f"execucao_anual_{filter_name}_{source_key}"
        with column:
            values = _selected_values(label, mapping, key)
        if values:
            selections[filter_name] = values
    return selections


def _render_cards(filtered: pd.DataFrame, por_ano: pd.DataFrame, ano_extracao: int) -> None:
    totais = {medida: float(por_ano[medida].sum(min_count=1)) for medida in MEDIDAS}
    tem_dado = {medida: bool(filtered[medida].notna().any()) for medida in MEDIDAS}

    liquidado_pct = (
        totais["liquidada"] / totais["empenhada"] if totais["empenhada"] else None
    )
    pago_pct = totais["paga"] / totais["liquidada"] if totais["liquidada"] else None

    cards = [
        {
            "label": "Empenhado",
            "value": format_brl_compact(totais["empenhada"]) if tem_dado["empenhada"] else "Sem registros",
        },
        {
            "label": "Liquidado",
            "value": format_brl_compact(totais["liquidada"]) if tem_dado["liquidada"] else "Sem registros",
        },
        {
            "label": "Pago",
            "value": format_brl_compact(totais["paga"]) if tem_dado["paga"] else "Sem registros",
        },
        {"label": "% Liquidado/Empenhado", "value": _pct(liquidado_pct)},
        {"label": "% Pago/Liquidado", "value": _pct(pago_pct)},
    ]
    render_metric_grid(cards, columns=5)

    anos_no_recorte = sorted(int(valor) for valor in filtered["ano"].dropna().unique())
    if ano_extracao in anos_no_recorte:
        st.caption(
            f"⚠ O recorte inclui {ano_extracao}, exercício em andamento na data da "
            "extração — não compare diretamente com exercícios fechados."
        )


SERIE_MEDIDAS = (
    ("empenhada", "Empenhado", ACCENT),
    ("liquidada", "Liquidado", ACCENT_STRONG),
    ("paga", "Pago", POSITIVE),
)


def _render_serie_historica(por_ano: pd.DataFrame, ano_extracao: int) -> None:
    """Barras agrupadas Empenhado × Liquidado × Pago por exercício.

    Reaproveita `por_ano` (calculado uma vez com `agregar()` sobre o
    recorte filtrado e compartilhado com os cards) e o mesmo `ano_extracao`
    derivado do manifesto. O exercício em andamento recebe textura
    listrada nas barras e um marcador no rótulo do eixo — nunca fica
    visualmente igual a um exercício fechado.
    """

    if por_ano.empty:
        st.info("Nenhum exercício no recorte para montar a série histórica.")
        return

    anos = [str(int(valor)) for valor in por_ano["ano"]]
    em_andamento = [int(valor) == ano_extracao for valor in por_ano["ano"]]
    formas = ["/" if andamento else "" for andamento in em_andamento]
    rotulos_eixo = [
        f"{ano} ⏳" if andamento else ano for ano, andamento in zip(anos, em_andamento)
    ]

    figure = go.Figure()
    for coluna, nome, cor in SERIE_MEDIDAS:
        valores = [float(valor) for valor in por_ano[coluna]]
        textos_hover = [
            f"{nome} {ano}: {format_brl_full(valor)}"
            + (" — exercício em andamento" if andamento else "")
            for ano, valor, andamento in zip(anos, valores, em_andamento)
        ]
        figure.add_bar(
            name=nome,
            x=anos,
            y=valores,
            marker=dict(
                color=cor,
                pattern=dict(shape=formas, fgcolor=BG, size=6, solidity=0.35),
            ),
            hovertext=textos_hover,
            hovertemplate="%{hovertext}<extra></extra>",
        )

    figure.update_layout(
        barmode="group",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, family="sans-serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(
            tickvals=anos,
            ticktext=rotulos_eixo,
            type="category",
            showgrid=False,
            zeroline=False,
            color=TEXT_MUTED,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            zeroline=False,
            tickformat="~s",
            color=TEXT_MUTED,
        ),
        height=420,
        margin=dict(t=40, b=10, l=10, r=10),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


# Nº máximo de categorias exibidas no ranking de composição. Aplicado de forma
# DINÂMICA — pela contagem real de categorias que `agregar()` devolve para a
# dimensão escolhida — e não por uma lista fixa de "dimensões de alta
# cardinalidade": a verificação feita sobre a base atual mostrou que "Ação de
# Governo" (53 categorias) e "Plano Orçamentário" (102) também estourariam
# esse limite, apesar de nenhuma das duas constar na lista de alta
# cardinalidade documentada em docs/base_execucao_anual.md (que cobre só
# Favorecido, Natureza Detalhada, PI, PTRES e UG Responsável). Uma lista fixa
# deixaria essas duas sem corte.
LIMITE_RANKING = 15


def _rotulo_composicao(row: pd.Series, colunas: list[str]) -> str:
    """Rótulo de exibição de uma categoria da dimensão escolhida.

    `po_acao_cod` é idêntico ao código da Ação (ver docs/base_execucao_anual.md,
    seção 4) e por isso fica fora do rótulo, mesmo participando do agrupamento.
    """

    colunas_exibiveis = [coluna for coluna in colunas if coluna != "po_acao_cod"]
    if len(colunas_exibiveis) >= 2:
        codigo, descricao = row[colunas_exibiveis[0]], row[colunas_exibiveis[1]]
        codigo_texto = str(codigo) if pd.notna(codigo) else "—"
        if pd.notna(descricao) and str(descricao) != codigo_texto:
            return f"{codigo_texto} — {descricao}"
        return codigo_texto
    valor = row[colunas_exibiveis[0]]
    return str(valor) if pd.notna(valor) else "—"


def _render_composicao(filtered: pd.DataFrame, source_key: str) -> None:
    dimensao = st.selectbox(
        "Dimensão",
        options=list(DIMENSOES_ANALITICAS),
        key=f"execucao_anual_composicao_dimensao_{source_key}",
    )
    colunas = DIMENSOES_ANALITICAS[dimensao]

    composicao = agregar(filtered, por=colunas, incluir_ano=False)
    composicao = composicao.sort_values("empenhada", ascending=False).reset_index(drop=True)

    total_categorias = len(composicao)
    exibidas = composicao.head(LIMITE_RANKING) if total_categorias > LIMITE_RANKING else composicao
    ocultas = total_categorias - len(exibidas)

    if exibidas.empty:
        st.info("Nenhuma categoria no recorte atual para esta dimensão.")
        return

    rotulos = [_rotulo_composicao(row, colunas) for _, row in exibidas.iterrows()]

    # eixo y do gráfico horizontal lê de baixo para cima — inverte para que a
    # maior categoria fique no topo.
    rotulos_grafico = rotulos[::-1]
    empenhado_grafico = exibidas["empenhada"].tolist()[::-1]

    figure = go.Figure()
    figure.add_bar(
        x=empenhado_grafico,
        y=rotulos_grafico,
        orientation="h",
        marker=dict(color=ACCENT, cornerradius=4),
        hovertext=[format_brl_full(valor) for valor in empenhado_grafico],
        hovertemplate="%{y}: %{hovertext}<extra></extra>",
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, family="sans-serif"),
        xaxis=dict(
            showgrid=True, gridcolor=BORDER, zeroline=False, tickformat="~s", color=TEXT_MUTED
        ),
        yaxis=dict(showgrid=False, zeroline=False, color=TEXT_MUTED),
        height=max(320, 32 * len(exibidas) + 80),
        margin=dict(t=20, b=10, l=10, r=10),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})

    tabela = pd.DataFrame(
        {
            dimensao: rotulos,
            "Empenhado": exibidas["empenhada"].tolist(),
            "Liquidado": exibidas["liquidada"].tolist(),
            "Pago": exibidas["paga"].tolist(),
            "% Liquidado/Empenhado": [_pct(v) for v in exibidas["execucao_liquidada_pct"]],
            "% Pago/Liquidado": [_pct(v) for v in exibidas["pagamento_pct"]],
        }
    )
    st.dataframe(
        tabela,
        hide_index=True,
        width="stretch",
        column_config={
            "Empenhado": st.column_config.NumberColumn(format="R$ %.2f"),
            "Liquidado": st.column_config.NumberColumn(format="R$ %.2f"),
            "Pago": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )

    if ocultas > 0:
        st.caption(
            f"Mostrando as {len(exibidas)} categorias com maior Empenhado (de "
            f"{total_categorias} no total) — {ocultas} ficaram fora do ranking. Os cards e a "
            "série histórica acima já refletem o recorte completo, sem esse limite."
        )
    else:
        st.caption(f"{total_categorias} categorias no recorte atual.")


def _opcoes_notas_empenho(filtered: pd.DataFrame) -> dict[str, str]:
    """{"rótulo": ne_ccor} das NEs presentes no recorte filtrado, para o seletor."""

    opcoes = (
        filtered[["ne_ccor", "ne_descricao"]]
        .dropna(subset=["ne_ccor"])
        .drop_duplicates(subset=["ne_ccor"])
        .sort_values("ne_ccor")
    )
    mapping: dict[str, str] = {}
    for _, row in opcoes.iterrows():
        codigo = row["ne_ccor"]
        descricao = row.get("ne_descricao")
        rotulo = (
            f"{codigo} — {descricao}"
            if pd.notna(descricao) and str(descricao).strip()
            else str(codigo)
        )
        mapping[rotulo] = codigo
    return mapping


COLUNAS_RASTREABILIDADE = [
    "linha_origem",
    "arquivo_origem",
    "tipo_linha",
    "ano",
    "empenhada",
    "liquidada",
    "paga",
]


def _render_rastreabilidade(dataframe: pd.DataFrame, filtered: pd.DataFrame, source_key: str) -> None:
    """Linhas de origem de uma NE, incluindo item(ns) de execução (anulações).

    Busca em `dataframe` (a base inteira, não o recorte filtrado): os filtros
    no topo recortam por GND/Fonte/exercício/etc., mas uma NE pode ter linhas
    de item de execução que só aparecem em outro ano ou combinação — omiti-las
    quebraria a rastreabilidade completa até a célula de origem. O seletor,
    porém, só lista NEs presentes no recorte filtrado, para manter a busca
    relevante ao que o usuário já está vendo.
    """

    mapping = _opcoes_notas_empenho(filtered)
    if not mapping:
        st.info("Nenhuma nota de empenho no recorte atual.")
        return

    rotulo = st.selectbox(
        "Nota de Empenho (NE)",
        options=list(mapping),
        key=f"execucao_anual_rastreabilidade_ne_{source_key}",
        index=None,
        placeholder="Digite para buscar uma NE...",
    )
    if rotulo is None:
        st.caption("Selecione uma NE para ver suas linhas de origem na planilha.")
        return

    ne_ccor = mapping[rotulo]
    linhas = detalhar_nota_empenho(dataframe, ne_ccor)
    st.dataframe(linhas[COLUNAS_RASTREABILIDADE], hide_index=True, width="stretch")
    st.caption(
        f"{len(linhas)} linha(s) de origem na planilha para a NE {ne_ccor} "
        "(inclui itens de execução/anulações, se houver)."
    )


# ---------------------------------------------------------------------- página
render_page_header(
    "Execução Orçamentária",
    "Execução Anual da Despesa (BI CPOC), por exercício.",
    "Execução",
)

manifesto = Manifesto.atual()
if manifesto is None:
    st.info(
        "Nenhuma base de Execução Anual foi importada ainda. Rode a importação "
        "inicial (ver docs/base_execucao_anual.md) antes de usar esta página."
    )
    st.stop()

caminho_ponteiro = DIRETORIO_MANIFESTOS_PADRAO / NOME_PONTEIRO
try:
    dataframe = _cached_leitura(str(caminho_ponteiro), caminho_ponteiro.stat().st_mtime)
except Exception as error:
    st.error(f"Não foi possível ler a base de Execução Anual: {error}")
    st.stop()

render_alert("Base de Execução Anual carregada a partir do manifesto atual.", "success")

source_key = manifesto.sha256[:12]
selections = _render_filters(dataframe, source_key)
filtered = _apply_filters(dataframe, selections)

if filtered.empty:
    st.warning("Nenhum registro corresponde à combinação de filtros selecionada.")
    st.stop()

ano_extracao = datetime.fromisoformat(manifesto.data_extracao).year
por_ano = agregar(filtered, por=[], incluir_ano=True)

_render_cards(filtered, por_ano, ano_extracao)

with st.container(border=True):
    st.subheader("Série histórica")
    st.caption(
        "Empenhado, Liquidado e Pago por exercício, sobre o mesmo recorte filtrado "
        "acima. O exercício em andamento aparece com textura listrada e ⏳ no rótulo."
    )
    _render_serie_historica(por_ano, ano_extracao)

with st.container(border=True):
    st.subheader("Composição")
    st.caption(
        "Empenhado, Liquidado e Pago por categoria de uma dimensão, sobre o mesmo recorte "
        "filtrado acima."
    )
    _render_composicao(filtered, source_key)

with st.container(border=True):
    st.subheader("Rastreabilidade")
    st.caption(
        "Selecione uma NE (nota de empenho) para ver suas linhas de origem na planilha, "
        "com o número da linha (linha_origem)."
    )
    _render_rastreabilidade(dataframe, filtered, source_key)

data_extracao_texto = datetime.fromisoformat(manifesto.data_extracao).strftime("%d/%m/%Y")
st.caption(
    f"Última extração: {data_extracao_texto} · hash {manifesto.sha256[:8]} — exercícios não "
    "trazidos por ela usam a extração anterior que os trouxe (composição por ano)."
)
