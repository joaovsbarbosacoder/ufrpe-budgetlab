"""Pop-up "Linha do tempo mensal" — Empenhado/Liquidado/Pago por mês, a partir da base
MENSAL (`src/tesouro_execucao_mensal.py`, 2026+).

Extraído de `app_pages/consulta_empenhos.py` (implementação original) para ser reutilizado por
qualquer página que já tenha a evolução mensal de uma NE em mãos (`linha_do_tempo_por_ne`) e
queira o mesmo pop-up — pedido explícito ao adicionar o mesmo recurso em
`app_pages/bolsas_auxilios.py` ("quero que esse pop-up tenha o mesmo formato implementado na
consulta de empenhos"), para as duas páginas nunca divergirem visualmente uma da outra.

Camada: componente de interface (importa Streamlit) — não lê nenhuma planilha, não conhece
NE/CCor nem bolsa: só recebe o DataFrame já pronto (colunas `ano_mes`, `empenhada`,
`liquidada`, `paga`) e um texto de legenda livre, que cada página monta do seu jeito (NE
completa numa, "programa (NE curta)" na outra).

Contrato público:
    abrir_linha_do_tempo(legenda, tempo) -> None   (decorado com @st.dialog, abre um pop-up)
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import design_tokens
from src.ui_theme import format_brl_full

MESES_ABREV = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


def rotulo_ano_mes(ano_mes: int) -> str:
    ano, mes = divmod(int(ano_mes), 100)
    return f"{MESES_ABREV.get(mes, mes)}/{ano}"


@st.dialog("Linha do tempo mensal", width="large")
def abrir_linha_do_tempo(legenda: str, tempo: pd.DataFrame) -> None:
    """`tempo`: uma linha por mês (`ano_mes`, `empenhada`, `liquidada`, `paga`) — já pronta,
    normalmente o resultado de `src.tesouro_execucao_mensal.linha_do_tempo_por_ne` filtrado
    para uma única NE. `legenda` aparece como `st.caption` no topo do pop-up (livre — cada
    página decide o que identificar: NE completa, bolsa/programa, etc.)."""

    # Cores lidas como atributo do módulo (não `from design_tokens import ACCENT`, que
    # ficaria travada no tema de quando este módulo de apoio foi carregado pela primeira
    # vez no processo — ver docstring de `design_tokens.py`) para acompanhar o alternador
    # de tema claro/escuro a cada abertura deste pop-up.
    d = design_tokens
    st.caption(legenda)
    tempo = tempo.sort_values("ano_mes")
    rotulos = [rotulo_ano_mes(am) for am in tempo["ano_mes"]]

    figure = go.Figure()
    for coluna, nome, cor in (
        ("empenhada", "Empenhado", d.ACCENT), ("liquidada", "Liquidado", d.ACCENT_STRONG), ("paga", "Pago", d.POSITIVE),
    ):
        valores = [float(v) for v in tempo[coluna]]
        figure.add_bar(
            name=nome, x=rotulos, y=valores, marker=dict(color=cor),
            hovertext=[f"{nome} {rotulo}: {format_brl_full(v)}" for rotulo, v in zip(rotulos, valores)],
            hovertemplate="%{hovertext}<extra></extra>",
        )
    figure.update_layout(
        barmode="group",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=d.TEXT, family="sans-serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(type="category", showgrid=False, zeroline=False, color=d.TEXT_MUTED),
        yaxis=dict(showgrid=True, gridcolor=d.BORDER, zeroline=False, tickformat="~s", color=d.TEXT_MUTED),
        height=360, margin=dict(t=40, b=10, l=10, r=10),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})

    # Grade HTML própria — não `st.dataframe` (cara de planilha; `st.column_config.
    # NumberColumn` também não agrupa milhar em pt-BR). Classes `.ce-tempo-*` (definidas em
    # `app_pages/consulta_empenhos.py::_inject_css`, a página onde esse formato nasceu) —
    # cada página que usa este pop-up precisa injetar esse mesmo bloco de CSS.
    linhas_html = "".join(
        '<div class="ce-tempo-row">'
        f'<span class="ce-tempo-mes">{rotulo}</span>'
        f'<span class="ce-tempo-val">{format_brl_full(empenhada)}</span>'
        f'<span class="ce-tempo-val">{format_brl_full(liquidada)}</span>'
        f'<span class="ce-tempo-val-strong">{format_brl_full(paga)}</span>'
        "</div>"
        for rotulo, empenhada, liquidada, paga in zip(
            rotulos, tempo["empenhada"], tempo["liquidada"], tempo["paga"]
        )
    )
    cabecalho_html = "".join(
        f'<span style="text-align:{alinhamento}">{texto}</span>'
        for texto, alinhamento in (("Mês", "left"), ("Empenhado", "right"), ("Liquidado", "right"), ("Pago", "right"))
    )
    st.markdown(f'<div class="ce-tempo-head">{cabecalho_html}</div>{linhas_html}', unsafe_allow_html=True)
    st.caption(
        "Empenhado já deduplicado entre Naturezas Detalhadas/Subitens diferentes da mesma NE "
        "(ver docs/base_execucao_mensal.md) — não é a soma direta das linhas de item."
    )
