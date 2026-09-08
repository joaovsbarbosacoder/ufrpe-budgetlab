"""Captação de Demandas Orçamentárias — "Proposta Consolidada" (visão da equipe
orçamentária/PROPLAD).

Só demandas com status "Enviada" entram aqui — rascunho é assunto do setor que ainda
não terminou de preencher (briefing, seção 4: "não há tela de aprovação/rejeição nesta
versão — o que existe: registrar, enviar, e visualizar o consolidado").
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.demandas_orcamentarias import (
    STATUS_ENVIADA,
    TIPOS_DESPESA,
    carregar_demandas,
    explodir_por_meta,
)
from src.design_tokens import ACCENT, BORDER, TEXT, TEXT_MUTED
from src.ui_theme import (
    format_brl_compact,
    format_brl_full,
    render_metric_grid,
    render_page_header,
)


def _renderizar_filtros(demandas: pd.DataFrame) -> pd.DataFrame:
    setores = sorted(demandas["unidade_nome"].dropna().unique())
    exercicios = sorted(demandas["exercicio"].dropna().unique())

    col1, col2, col3 = st.columns(3)
    setores_selecionados = col1.multiselect(
        "Setor", options=setores, placeholder="Todos", key="consolidado_f_setor"
    )
    exercicios_selecionados = col2.multiselect(
        "Exercício", options=exercicios, placeholder="Todos", key="consolidado_f_exercicio"
    )
    tipos_selecionados = col3.multiselect(
        "Tipo de despesa", options=TIPOS_DESPESA, placeholder="Todos", key="consolidado_f_tipo"
    )

    metas_disponiveis = sorted(
        {meta["codigo"] for metas in demandas["metas_pdi_pls"] for meta in (metas or [])}
    )
    metas_selecionadas = st.multiselect(
        "Meta PDI/PLS", options=metas_disponiveis, placeholder="Todas", key="consolidado_f_meta"
    )

    filtrado = demandas
    if setores_selecionados:
        filtrado = filtrado[filtrado["unidade_nome"].isin(setores_selecionados)]
    if exercicios_selecionados:
        filtrado = filtrado[filtrado["exercicio"].isin(exercicios_selecionados)]
    if tipos_selecionados:
        filtrado = filtrado[filtrado["tipo_despesa"].isin(tipos_selecionados)]
    if metas_selecionadas:
        filtrado = filtrado[
            filtrado["metas_pdi_pls"].apply(
                lambda metas: any(meta["codigo"] in metas_selecionadas for meta in (metas or []))
            )
        ]
    return filtrado


def _renderizar_cards(demandas: pd.DataFrame) -> None:
    total_custeio = demandas.loc[demandas["tipo_despesa"] == "Custeio", "valor_total"].sum()
    total_capital = demandas.loc[demandas["tipo_despesa"] == "Capital", "valor_total"].sum()
    render_metric_grid(
        [
            {"label": "Total de demandas", "value": str(len(demandas))},
            {
                "label": "Valor total solicitado",
                "value": format_brl_compact(demandas["valor_total"].sum()),
                "subtitle": format_brl_full(demandas["valor_total"].sum()),
            },
            {"label": "Custeio", "value": format_brl_compact(total_custeio)},
            {"label": "Capital", "value": format_brl_compact(total_capital)},
        ],
        columns=4,
    )


def _renderizar_grafico_por_meta(demandas: pd.DataFrame) -> None:
    explodido = explodir_por_meta(demandas)
    explodido = explodido[explodido["meta_codigo"].notna()]
    if explodido.empty:
        st.info("Nenhuma demanda com meta PDI/PLS vinculada neste recorte.")
        return

    por_meta = (
        explodido.groupby("meta_codigo")["valor_total"]
        .sum()
        .sort_values(ascending=True)
    )

    figure = go.Figure(
        go.Bar(
            x=por_meta.values,
            y=por_meta.index,
            orientation="h",
            marker=dict(color=ACCENT),
            text=[format_brl_compact(valor) for valor in por_meta.values],
            textposition="outside",
            textfont=dict(color=TEXT),
            hovertext=[format_brl_full(valor) for valor in por_meta.values],
            hovertemplate="%{y}<br>%{hovertext}<extra></extra>",
        )
    )
    figure.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, family="sans-serif"),
        showlegend=False,
        margin=dict(t=20, b=10, l=10, r=40),
        xaxis=dict(showgrid=True, gridcolor=BORDER, zeroline=False, tickformat="~s", color=TEXT_MUTED),
        yaxis=dict(showgrid=False, zeroline=False, color=TEXT_MUTED),
        height=max(280, 44 * len(por_meta)),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def _renderizar_lista(demandas: pd.DataFrame) -> None:
    if demandas.empty:
        st.info("Nenhuma demanda enviada corresponde a este recorte.")
        return

    for _, demanda in demandas.sort_values("enviado_em", ascending=False).iterrows():
        with st.container(border=True):
            descricao = demanda["descricao_necessidade"] or "(sem descrição)"
            st.markdown(f"**{descricao[:140]}**")

            colunas = st.columns(5)
            colunas[0].caption("Setor")
            colunas[0].write(demanda["unidade_nome"])
            colunas[1].caption("Exercício")
            colunas[1].write(str(demanda["exercicio"]))
            colunas[2].caption("Tipo")
            colunas[2].write(demanda["tipo_despesa"])
            colunas[3].caption("Valor total")
            colunas[3].write(format_brl_compact(demanda["valor_total"]))
            metas = demanda["metas_pdi_pls"] or []
            colunas[4].caption("Metas PDI/PLS")
            colunas[4].write(", ".join(meta["codigo"] for meta in metas) if metas else "—")


render_page_header(
    "Proposta Consolidada",
    "Todas as demandas orçamentárias enviadas, de todos os setores.",
    "Demandas",
)

demandas = carregar_demandas()
enviadas = demandas[demandas["status"] == STATUS_ENVIADA]

if enviadas.empty:
    st.info("Nenhuma demanda enviada ainda.")
    st.stop()

filtrado = _renderizar_filtros(enviadas)
if filtrado.empty:
    st.warning("Nenhuma demanda corresponde à combinação de filtros selecionada.")
    st.stop()

_renderizar_cards(filtrado)

with st.container(border=True):
    st.subheader("Total consolidado por meta do PDI/PLS")
    st.caption(
        "Soma do valor total das demandas por meta — uma demanda vinculada a mais de "
        "uma meta conta o valor inteiro em cada uma (não é rateio)."
    )
    _renderizar_grafico_por_meta(filtrado)

with st.container(border=True):
    st.subheader("Demandas")
    _renderizar_lista(filtrado)
