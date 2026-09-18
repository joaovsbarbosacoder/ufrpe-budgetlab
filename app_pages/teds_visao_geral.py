"""TEDs — Visão geral. Primeira das 6 páginas do módulo de TEDs (grupo "TEDs" na barra
lateral, ver `app.py`), layout adaptado de um handoff de design (mesmo espírito de
`alertas_gerenciais.py`/`emendas_parlamentares.py`): todo dado aqui é real, consultado direto
de `data/teds/teds.db` — não há placeholder fictício nesta tela específica, porque tudo que
ela mostra (TEDs, execução anual, empenhado, alertas) já existe no schema.

"Liquidado"/"Pago" (painel "Execução financeira") dependem do Tesouro Gerencial
(`src/teds_importacao_tesouro_gerencial.py`), cujo layout real ainda não foi confirmado (ver
docstring daquele módulo) — a consulta é real (cruza `vinculo_ne.numero_ne` com
`execucao_tg.numero_completo_ne`), só que hoje não há arquivo importado, então aparece "Sem
dado (Tesouro Gerencial)" em vez de um valor inventado.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from src.teds_normalizacao import texto_para_valor
from src.teds_ui import (
    anos_disponiveis,
    badge,
    brl,
    carregar_alertas,
    carregar_teds,
    conexao,
    cor_estado_ted,
    cor_gravidade,
    dash,
    filtrar_por_exercicio,
    injetar_css,
    pct,
    rotulo_gravidade,
    rotulo_tipo_alerta,
    soma_tg_por_teds,
)
from src.ui_theme import render_page_header

injetar_css()
render_page_header(
    "Visão geral",
    "Acompanhamento de descentralização de crédito via TED — execução, documentos e alertas.",
    "TEDs",
)

conn = conexao()
teds_df = carregar_teds(conn)

if teds_df.empty:
    st.info(
        'Nenhum TED importado ainda. Vá em "Importações" (barra lateral) e envie ao menos a '
        "planilha de Execução: Orçamentário e Financeiro."
    )
    st.stop()

# ---------------------------------------------------------------------- filtros
col_exercicio, col_ug, col_espaco, col_atualizado = st.columns([1, 1.4, 3, 1.6])
anos = anos_disponiveis(teds_df)
with col_exercicio:
    exercicio = st.selectbox("Exercício", ["Todos"] + [str(a) for a in anos], key="vg_exercicio")
ugs = sorted(teds_df["ug_descentralizadora"].dropna().unique())
with col_ug:
    ug = st.selectbox("UG Descentralizadora", ["Todas"] + list(ugs), key="vg_ug")
with col_atualizado:
    ultima = conn.execute("SELECT MAX(data_importacao) FROM import_batch").fetchone()[0]
    if ultima:
        st.caption(f"Atualizado em {pd.Timestamp(ultima).strftime('%d/%m/%Y %H:%M')}")

filtrado = teds_df
if exercicio != "Todos":
    filtrado = filtrar_por_exercicio(filtrado, int(exercicio))
if ug != "Todas":
    filtrado = filtrado[filtrado["ug_descentralizadora"] == ug]

if filtrado.empty:
    st.warning("Nenhum TED encontrado para o exercício/UG selecionados.")
    st.stop()

# ---------------------------------------------------------------------- KPIs
em_execucao = filtrado[filtrado["estado_atual"].astype(str).str.contains("Execução", case=False, na=False)]
nc_liquida_total = sum(
    (texto_para_valor(a) - texto_para_valor(b) for a, b in zip(
        filtrado["total_nc_descentralizacao"].fillna("0"), filtrado["total_nc_devolucao"].fillna("0")
    )),
    start=Decimal("0"),
)
pf_liquida_total = sum(
    (texto_para_valor(a) - texto_para_valor(b) for a, b in zip(
        filtrado["total_pf_repasse"].fillna("0"), filtrado["total_pf_devolucao"].fillna("0")
    )),
    start=Decimal("0"),
)
empenhado_total = sum(filtrado["empenhado"], start=Decimal("0"))

chaves_filtradas = set(filtrado["chave_ted"])
alertas_todos = carregar_alertas(conn, status=None)
alertas_criticos = [a for a in alertas_todos if a.gravidade == "alta" and a.status != "resolvido"]
alertas_abertos_filtrados = [
    a for a in alertas_todos if a.status != "resolvido" and (a.chave_ted in chaves_filtradas or a.chave_ted is None)
]

kpi_cols = st.columns(5)
kpi_cols[0].container(border=True).metric("TEDs em execução", str(len(em_execucao)))
kpi_cols[1].container(border=True).metric("NC líquida", brl(nc_liquida_total))
kpi_cols[2].container(border=True).metric("PF líquida", brl(pf_liquida_total))
kpi_cols[3].container(border=True).metric("Empenhado", brl(empenhado_total))
kpi_cols[4].container(border=True).metric("Alertas críticos", str(len(alertas_criticos)))

# ---------------------------------------------------------------------- execução orç./fin.
liquidado_total, pago_total, tem_dado_tg = soma_tg_por_teds(conn, chaves_filtradas)

col_orc, col_fin = st.columns(2)
with col_orc:
    with st.container(border=True):
        st.markdown("**Execução orçamentária**")
        st.caption("Valores em R$")
        st.write("NC líquida — 100%" if nc_liquida_total else "NC líquida — —")
        st.progress(1.0 if nc_liquida_total else 0.0)
        st.caption(brl(nc_liquida_total))
        frac, texto = pct(empenhado_total, nc_liquida_total)
        st.write(f"Empenhado — {texto}")
        st.progress(frac)
        st.caption(brl(empenhado_total))
        if tem_dado_tg:
            frac, texto = pct(liquidado_total, empenhado_total)
            st.write(f"Liquidado — {texto}")
            st.progress(frac)
            st.caption(brl(liquidado_total))
        else:
            st.write("Liquidado — sem dado")
            st.caption("Nenhuma extração do Tesouro Gerencial importada ainda para as NEs deste recorte.")

with col_fin:
    with st.container(border=True):
        st.markdown("**Execução financeira**")
        st.caption("Valores em R$")
        st.write("PF líquida — 100%" if pf_liquida_total else "PF líquida — —")
        st.progress(1.0 if pf_liquida_total else 0.0)
        st.caption(brl(pf_liquida_total))
        if tem_dado_tg:
            frac, texto = pct(pago_total, pf_liquida_total)
            st.write(f"Pago — {texto}")
            st.progress(frac)
            st.caption(brl(pago_total))
        else:
            st.write("Pago — sem dado")
            st.caption("Nenhuma extração do Tesouro Gerencial importada ainda para as NEs deste recorte.")
        st.caption("Diferença NC−PF")
        st.markdown(f"**{brl(nc_liquida_total - pf_liquida_total)}**")

# ---------------------------------------------------------------------- alertas prioritários
st.markdown("#### Alertas prioritários")
if not alertas_abertos_filtrados:
    st.success("Nenhum alerta aberto para o recorte selecionado.")
else:
    for alerta in alertas_abertos_filtrados[:3]:
        cor = cor_gravidade(alerta.gravidade)
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            c1.markdown(
                f"{badge(rotulo_gravidade(alerta.gravidade), cor)} &nbsp; **{rotulo_tipo_alerta(alerta.tipo)}**  \n"
                f"<span class='teds-muted'>{alerta.descricao}</span>",
                unsafe_allow_html=True,
            )
    if len(alertas_abertos_filtrados) > 3:
        st.caption(f"+ {len(alertas_abertos_filtrados) - 3} outros alertas — veja a Central de Alertas.")

# ---------------------------------------------------------------------- TEDs que exigem atenção
st.markdown("#### TEDs que exigem atenção")
contagem_alertas_por_ted: dict[str, int] = {}
for a in alertas_abertos_filtrados:
    if a.chave_ted:
        contagem_alertas_por_ted[a.chave_ted] = contagem_alertas_por_ted.get(a.chave_ted, 0) + 1

atencao = filtrado[filtrado["chave_ted"].isin(contagem_alertas_por_ted.keys())].copy()
if atencao.empty:
    st.caption("Nenhum TED com alerta direto no recorte atual.")
else:
    atencao = atencao.sort_values("fim_vigencia", na_position="last")
    cabecalho = st.columns([0.8, 1, 3, 1.3, 1.3, 1.3, 0.7, 0.8])
    for coluna, rotulo in zip(
        cabecalho, ["TED", "SIAFI", "Descrição", "Fim vigência", "NC líquida", "PF líquida", "Alertas", ""]
    ):
        coluna.markdown(f"**{rotulo}**" if rotulo else "")
    for posicao, linha in atencao.reset_index(drop=True).iterrows():
        c = st.columns([0.8, 1, 3, 1.3, 1.3, 1.3, 0.7, 0.8])
        c[0].write(linha["ted"])
        c[1].write(linha["codigo_siafi"])
        c[2].write(dash(linha["descricao"]))
        c[3].write(dash(linha["fim_vigencia"]))
        c[4].write(brl(texto_para_valor(linha["total_nc_descentralizacao"] or "0") - texto_para_valor(linha["total_nc_devolucao"] or "0")))
        c[5].write(brl(texto_para_valor(linha["total_pf_repasse"] or "0") - texto_para_valor(linha["total_pf_devolucao"] or "0")))
        c[6].markdown(badge(str(contagem_alertas_por_ted.get(linha["chave_ted"], 0)), cor_estado_ted(None)), unsafe_allow_html=True)
        if c[7].button("Ver", key=f"vg_ver_{posicao}"):
            st.session_state["teds_chave_selecionada"] = linha["chave_ted"]
            st.switch_page("app_pages/teds_lista.py")
