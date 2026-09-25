"""TEDs — Células NC × NE. Página do grupo "TEDs" (ver `app.py`).

Para cada NE vinculada a um TED (extrato TED → NE do SIMEC), compara PTRES, fonte de recursos detalhada,
natureza da despesa (6 dígitos) e Plano Interno com o CONJUNTO de células das NCs do mesmo TED e exercício
(relatórios de NC do Tesouro Gerencial importados em "Importações"). Regras e decisões em
`src/teds_celula_orcamentaria.py` e `docs/base_teds.md` (seção 11).

Três situações, sempre visíveis: "Correspondente", "Divergência para conferência" (alerta, nunca conclusão
de uso irregular) e "NC não identificada ou base incompleta" — esta última NÃO é divergência: ausência de
dado nunca aparece como conformidade nem como irregularidade.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from src import design_tokens
from src.teds_celula_orcamentaria import (
    ESTADO_BASE_INCOMPLETA,
    ESTADO_CORRESPONDENTE,
    ESTADO_DIVERGENCIA,
    carregar_conciliacao_celulas,
    resultados_para_tabela,
)
from src.teds_ui import badge, conexao, html_linha, injetar_css, render_kpi_strip
from src.ui_theme import render_page_header

injetar_css()
render_page_header(
    "Células NC × NE",
    "Compare PTRES, fonte, natureza e Plano Interno das NEs com as NCs do mesmo TED.",
    "TEDs",
)

conn = conexao()
qtd_nc = conn.execute("SELECT COUNT(*) FROM nc_celula").fetchone()[0]
qtd_ne = conn.execute("SELECT COUNT(*) FROM ne_celula").fetchone()[0]
resultados = carregar_conciliacao_celulas(conn)

if not resultados:
    st.info('Nenhuma NE vinculada a TED ainda. Importe o extrato de NEs do SIMEC em "Importações".')
    st.stop()

if not qtd_nc:
    st.warning(
        'Nenhum relatório de NC do Tesouro Gerencial importado ainda ("Destaques Recebidos" e "NC 2026", em '
        '"Importações"). Sem eles todas as NEs aparecem como "NC não identificada ou base incompleta".'
    )
if not qtd_ne:
    st.warning(
        'As células das NEs vêm da Execução Mensal: use "Sincronizar com a Execução Mensal" em "Importações". '
        "Sem isso nenhuma NE tem célula para comparar."
    )

# A situação de uma NE é a pior entre as suas células: divergência > base incompleta > correspondente.
por_ne: dict[str, str] = {}
for r in resultados:
    atual = por_ne.get(r.numero_ne)
    if r.situacao == ESTADO_DIVERGENCIA or atual is None:
        por_ne[r.numero_ne] = r.situacao
    elif atual != ESTADO_DIVERGENCIA and r.situacao == ESTADO_BASE_INCOMPLETA:
        por_ne[r.numero_ne] = r.situacao


def _contar(situacao: str) -> int:
    return sum(1 for s in por_ne.values() if s == situacao)


render_kpi_strip([
    {"label": "NEs vinculadas", "value": len(por_ne), "icon": "▤", "tone": design_tokens.ACCENT},
    {"label": "Correspondentes", "value": _contar(ESTADO_CORRESPONDENTE), "icon": "✓", "tone": design_tokens.POSITIVE},
    {"label": "Divergências para conferência", "value": _contar(ESTADO_DIVERGENCIA), "icon": "!", "tone": design_tokens.NEGATIVE},
    {"label": "NC não identificada / base incompleta", "value": _contar(ESTADO_BASE_INCOMPLETA), "icon": "?", "tone": design_tokens.WARNING},
])

tabela = resultados_para_tabela(resultados)

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1:
    exercicio = st.selectbox("Exercício", ["Todos"] + sorted(str(x) for x in tabela["Exercício"].unique()), key="cel_exercicio")
with c2:
    ted = st.selectbox("TED", ["Todos"] + sorted(tabela["TED"].unique()), key="cel_ted")
with c3:
    transferencia = st.selectbox(
        "Transferência (SIAFI)", ["Todas"] + sorted(tabela["Transferência (SIAFI)"].unique()), key="cel_transf"
    )
with c4:
    nc = st.text_input("NC (número)", key="cel_nc", placeholder="ex.: 2025NC000408")
with c5:
    ne = st.text_input("NE (número)", key="cel_ne", placeholder="ex.: 2025NE000706")
with c6:
    situacao = st.selectbox(
        "Situação", ["Todas", ESTADO_CORRESPONDENTE, ESTADO_DIVERGENCIA, ESTADO_BASE_INCOMPLETA], key="cel_situacao"
    )

filtrado = tabela
if exercicio != "Todos":
    filtrado = filtrado[filtrado["Exercício"] == int(exercicio)]
if ted != "Todos":
    filtrado = filtrado[filtrado["TED"] == ted]
if transferencia != "Todas":
    filtrado = filtrado[filtrado["Transferência (SIAFI)"] == transferencia]
if nc.strip():
    filtrado = filtrado[filtrado["NCs consideradas"].str.contains(nc.strip(), case=False, regex=False)]
if ne.strip():
    filtrado = filtrado[filtrado["NE"].str.contains(ne.strip(), case=False, regex=False)]
if situacao != "Todas":
    filtrado = filtrado[filtrado["Situação"] == situacao]

st.markdown(f"#### Comparações — {len(filtrado)} registro(s)")
_TOM_SITUACAO = {
    ESTADO_CORRESPONDENTE: design_tokens.POSITIVE,
    ESTADO_DIVERGENCIA: design_tokens.NEGATIVE,
    ESTADO_BASE_INCOMPLETA: design_tokens.WARNING,
}
_LIMITE_CARTOES = 25
for _, r in filtrado.head(_LIMITE_CARTOES).iterrows():
    tom = _TOM_SITUACAO.get(r["Situação"], design_tokens.TEXT_MUTED)
    metricas = [
        ("Exercício", r["Exercício"]),
        ("Transferência (SIAFI)", r["Transferência (SIAFI)"]),
        ("Vínculo", r["Vínculo"]),
        ("Célula da NE (PTRES | fonte | natureza | PI)", r["Célula da NE (PTRES | fonte | natureza | PI)"]),
    ]
    if r["Campos divergentes"]:
        metricas.append(("Campos divergentes", r["Campos divergentes"]))
    with st.container(border=True):
        st.markdown(
            html_linha(f"NE {r['NE']} · TED {r['TED']}", r["Motivo"], [badge(escape(r["Situação"]), tom)], metricas, tone=tom),
            unsafe_allow_html=True,
        )
        with st.expander("Rastreabilidade"):
            for rotulo in (
                "Valores nas NCs para o campo divergente", "NCs consideradas", "Células das NCs",
                "NCs do TED ainda não identificadas no TG", "Linhas de origem (NC)", "Linhas de origem (NE)",
            ):
                st.caption(f"**{rotulo}:** {r[rotulo] if r[rotulo] != '' else '—'}")
if len(filtrado) > _LIMITE_CARTOES:
    st.caption(f"Mostrando os {_LIMITE_CARTOES} primeiros de {len(filtrado)} registros; refine os filtros ou use a tabela completa abaixo.")
with st.expander("Tabela completa (rastreável e ordenável)"):
    st.dataframe(filtrado, hide_index=True, width="stretch")
st.caption(
    "Cada linha é uma célula de NE de um vínculo TED × NE. A comparação é por códigos (texto, zeros à esquerda "
    "preservados), contra o conjunto de células das NCs do mesmo TED e exercício; em 2026 só as células DESTINO "
    "entram. Coincidência de célula nunca cria o vínculo da NE com um TED. Os valores das NCs não entram na "
    "comparação. \"Divergência para conferência\" gera alerta na Central de Alertas e não é conclusão de uso indevido."
)
