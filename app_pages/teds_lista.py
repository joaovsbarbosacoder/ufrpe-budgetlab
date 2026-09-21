"""TEDs — lista e detalhe. Segunda página do grupo "TEDs" (ver `app.py`).

Uma página só, não duas, porque o mockup mostra o detalhe como um "drill-down" da lista
(breadcrumb "TEDs / TED 17352", não uma entrada própria na barra lateral) — controlado por
`st.session_state["teds_chave_selecionada"]`: presente -> mostra o detalhe; ausente -> mostra
a lista. `app_pages/teds_visao_geral.py` e a Central de Alertas navegam pra cá já preenchendo
essa chave antes de `st.switch_page`.

Tudo aqui é dado real (ver docstring de `src/teds_ui.py`), exceto "Registrar observação" no
detalhe do TED, que fica desabilitado com nota — não existe campo de observação manual no
schema hoje, seria uma regra nova não aprovada nesta rodada.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src import design_tokens
from src.teds_normalizacao import texto_para_valor
from src.teds_ui import (
    alertas_de_ne_para_ted,
    anos_disponiveis,
    badge,
    brl,
    carregar_alertas,
    carregar_teds,
    conexao,
    cor_estado_ted,
    cor_gravidade,
    dash,
    documentos_nc,
    documentos_pf,
    filtrar_por_exercicio,
    historico_lotes_do_ted,
    injetar_css,
    pct,
    render_kpi_strip,
    rotulo_gravidade,
    rotulo_tipo_alerta,
    soma_tg_por_teds,
    vinculos_ne,
)
from src.ui_theme import render_page_header

injetar_css()
conn = conexao()
teds_df = carregar_teds(conn)

if teds_df.empty:
    render_page_header("TEDs", "Lista de TEDs importados.", "TEDs")
    st.info('Nenhum TED importado ainda. Vá em "Importações" e envie a extração do SIMEC.')
    st.stop()


# ========================================================================================
# Detalhe (quando há um TED selecionado)
# ========================================================================================

def _situacao_vigencia(fim_vigencia: str | None) -> str:
    if not fim_vigencia:
        return "—"
    try:
        fim = date.fromisoformat(fim_vigencia)
    except ValueError:
        return "—"
    dias = (fim - date.today()).days
    if dias < 0:
        return "Vencido"
    if dias <= 90:
        return "A vencer em 90 dias"
    return "Vigente"


def _render_detalhe(chave_ted: str) -> None:
    linha = teds_df[teds_df["chave_ted"] == chave_ted]
    if linha.empty:
        st.error("TED não encontrado.")
        if st.button("Voltar para a lista"):
            del st.session_state["teds_chave_selecionada"]
            st.rerun()
        return
    linha = linha.iloc[0]

    col_bread, _ = st.columns([4, 1])
    with col_bread:
        if st.button("← TEDs", key="detalhe_voltar"):
            del st.session_state["teds_chave_selecionada"]
            st.rerun()

    st.markdown(f"## TED {linha['ted']}")
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.6, 2])
    c1.markdown(f"**SIAFI**  \n{linha['codigo_siafi']}")
    c2.markdown(badge(dash(linha["estado_atual"]), cor_estado_ted(linha["estado_atual"])), unsafe_allow_html=True)
    c3.markdown(f"**UG Descentralizadora**  \n{dash(linha['ug_descentralizadora'])}")
    c4.markdown(f"**Vigência**  \n{dash(linha['inicio_vigencia'])} a {dash(linha['fim_vigencia'])} ({_situacao_vigencia(linha['fim_vigencia'])})")
    if linha["descricao"]:
        st.caption(linha["descricao"])

    acao_exportar, acao_obs, acao_alertas = st.columns(3)
    with acao_exportar:
        nc = pd.DataFrame(documentos_nc(conn, chave_ted), columns=["numero_nc", "ug_emitente", "operacao", "data_emissao", "valor_assinado_total", "quantidade_linhas", "status_relacionamento"])
        pf = pd.DataFrame(documentos_pf(conn, chave_ted), columns=["numero_pf", "ug_emitente", "operacao", "data_emissao", "valor_assinado"])
        ne = pd.DataFrame(vinculos_ne(conn, chave_ted), columns=["numero_ne", "ug_emitente", "gestao_emitente", "valor_ne", "status_validacao", "chave_empenho"])
        buffer = pd.concat(
            [
                nc.assign(tipo="NC").rename(columns={"numero_nc": "numero", "valor_assinado_total": "valor"}),
                pf.assign(tipo="PF").rename(columns={"numero_pf": "numero", "valor_assinado": "valor"}),
                ne.assign(tipo="NE").rename(columns={"numero_ne": "numero", "valor_ne": "valor"}),
            ],
            ignore_index=True,
        )
        st.download_button(
            "⬇ Exportar dados",
            data=buffer.to_csv(index=False).encode("utf-8"),
            file_name=f"ted_{linha['ted']}_documentos.csv",
            mime="text/csv",
            width="stretch",
        )
    with acao_obs:
        st.button("💬 Registrar observação", width="stretch", disabled=True, help="Não implementado — não há campo de observação manual no schema ainda.")
    with acao_alertas:
        if st.button("⚠ Abrir alertas", width="stretch"):
            st.session_state["alertas_filtro_chave_ted"] = chave_ted
            st.switch_page("app_pages/teds_central_alertas.py")

    nc_liquida = texto_para_valor(linha["total_nc_descentralizacao"] or "0") - texto_para_valor(linha["total_nc_devolucao"] or "0")
    pf_liquida = texto_para_valor(linha["total_pf_repasse"] or "0") - texto_para_valor(linha["total_pf_devolucao"] or "0")
    liquidado, pago, tem_tg = soma_tg_por_teds(conn, {chave_ted})

    col_orc, col_fin = st.columns(2)
    with col_orc:
        with st.container(border=True):
            st.markdown("**Execução orçamentária**")
            frac, texto = pct(linha["empenhado"], nc_liquida)
            st.write(f"Empenhado de NC líquida ({brl(nc_liquida)}) — {texto}")
            st.progress(frac)
            st.caption(brl(linha["empenhado"]))
    with col_fin:
        with st.container(border=True):
            st.markdown("**Execução financeira**")
            if tem_tg:
                frac, texto = pct(pago, pf_liquida)
                st.write(f"Pago de PF líquida ({brl(pf_liquida)}) — {texto}")
                st.progress(frac)
                st.caption(brl(pago))
            else:
                st.write(f"PF líquida — {brl(pf_liquida)}")
                st.caption("Pago: sem dado do Tesouro Gerencial para as NEs deste TED.")

    aba_geral, aba_nc, aba_pf, aba_ne, aba_liq, aba_alertas, aba_hist = st.tabs(
        ["Visão geral", "Notas de crédito", "Programações financeiras", "Empenhos",
         "Liquidação por competência", "Alertas", "Histórico"]
    )

    with aba_geral:
        st.markdown("**Documentos relacionados**")
        linhas_doc = []
        for n in documentos_nc(conn, chave_ted):
            linhas_doc.append(("NC", n[0], f"Documentos NC{' · ' + str(n[5]) + ' linhas' if n[5] > 1 else ''}", brl(n[4]), dash(n[3]), "SIMEC"))
        for n in documentos_pf(conn, chave_ted):
            linhas_doc.append(("PF", n[0], "Programação financeira", brl(n[4]), dash(n[3]), "SIMEC"))
        for n in vinculos_ne(conn, chave_ted):
            linhas_doc.append(("NE", n[0], "Empenho", brl(n[3]), "—", "SIMEC"))
        if not linhas_doc:
            st.caption("Nenhum documento vinculado a este TED ainda.")
        else:
            st.dataframe(
                pd.DataFrame(linhas_doc, columns=["Tipo", "Número", "Descrição", "Valor (R$)", "Data de emissão", "Fonte"]),
                hide_index=True, width="stretch",
            )

    with aba_nc:
        docs = documentos_nc(conn, chave_ted)
        if not docs:
            st.caption("Nenhuma NC vinculada a este TED.")
        for numero_nc, ug_emitente, operacao, data_emissao, valor_total, qtd_linhas, status in docs:
            cor = cor_gravidade("media") if status == "PARCIAL" else "inherit"
            texto_status = "UG emitente ausente" if status == "PARCIAL" else "Completo"
            cdoc, cval = st.columns([3, 1])
            cdoc.markdown(
                f"**{numero_nc}** ({operacao}) — {dash(data_emissao)} — UG emitente: {dash(ug_emitente)}  \n"
                f"<span style='color:{cor};font-size:12px'>{texto_status}</span>"
                + (f" · {qtd_linhas} linhas de origem" if qtd_linhas > 1 else ""),
                unsafe_allow_html=True,
            )
            cval.markdown(f"<div style='text-align:right'>{brl(valor_total)}</div>", unsafe_allow_html=True)

    with aba_pf:
        docs = documentos_pf(conn, chave_ted)
        if not docs:
            st.caption("Nenhuma Programação Financeira vinculada a este TED.")
        for numero_pf, ug_emitente, operacao, data_emissao, valor_assinado in docs:
            cdoc, cval = st.columns([3, 1])
            cdoc.write(f"**{numero_pf}** ({operacao}) — {dash(data_emissao)} — UG {ug_emitente}")
            cval.markdown(f"<div style='text-align:right'>{brl(valor_assinado)}</div>", unsafe_allow_html=True)

    with aba_ne:
        docs = vinculos_ne(conn, chave_ted)
        if not docs:
            st.caption("Nenhum empenho vinculado a este TED.")
        for numero_ne, ug_emitente, gestao_emitente, valor_ne, status_val, chave_empenho in docs:
            rotulos_status = {
                "pendente": "Vínculo múltiplo — conferência necessária",
                "descartado": "Não contabilizado — decisão registrada",
                "ok": "Ok",
            }
            cor = cor_gravidade("alta") if status_val == "pendente" else "inherit"
            cdoc, cval = st.columns([3, 1])
            cdoc.markdown(
                f"**{numero_ne}** — UG {ug_emitente} / gestão {gestao_emitente}  \n"
                f"<span style='color:{cor};font-size:12px'>"
                f"{rotulos_status.get(status_val, status_val)}</span>",
                unsafe_allow_html=True,
            )
            cval.markdown(f"<div style='text-align:right'>{brl(valor_ne)}</div>", unsafe_allow_html=True)

    with aba_liq:
        if not tem_tg:
            st.info(
                "Sem dado — nenhuma extração do Tesouro Gerencial foi importada ainda para as "
                "NEs deste TED (layout daquele leitor ainda não foi confirmado com extração real)."
            )
        else:
            st.metric("Liquidado", brl(liquidado))
            st.metric("Pago", brl(pago))

    with aba_alertas:
        diretos = carregar_alertas(conn, chave_ted=chave_ted)
        indiretos = alertas_de_ne_para_ted(conn, chave_ted)
        todos = diretos + indiretos
        if not todos:
            st.success("Nenhum alerta para este TED.")
        for a in todos:
            with st.container(border=True):
                st.markdown(
                    f"{badge(rotulo_gravidade(a.gravidade), cor_gravidade(a.gravidade))} &nbsp; "
                    f"**{rotulo_tipo_alerta(a.tipo)}** — {badge(a.status, 'inherit')}  \n"
                    f"<span class='teds-muted'>{a.descricao}</span>",
                    unsafe_allow_html=True,
                )

    with aba_hist:
        historico = historico_lotes_do_ted(conn, chave_ted)
        if historico.empty:
            st.caption("Nenhum lote de importação identificado para este TED.")
        else:
            st.dataframe(historico, hide_index=True, width="stretch")


chave_selecionada = st.session_state.get("teds_chave_selecionada")
if chave_selecionada:
    _render_detalhe(chave_selecionada)
    st.stop()


# ========================================================================================
# Lista
# ========================================================================================

render_page_header("TEDs", "Lista de TEDs — busque, filtre e abra o detalhe de cada um.", "TEDs")

col_busca, col_exercicio, col_estado, col_vigencia, col_alerta = st.columns([2.2, 1, 1.3, 1.3, 1.3])
with col_busca:
    busca = st.text_input("Busca", key="lst_busca", placeholder="TED, SIAFI, descrição…", label_visibility="collapsed")
anos = anos_disponiveis(teds_df)
with col_exercicio:
    exercicio = st.selectbox("Exercício", ["Todos"] + [str(a) for a in anos], key="lst_exercicio")
estados = sorted(teds_df["estado_atual"].dropna().unique())
with col_estado:
    estado = st.selectbox("Estado atual", ["Todos"] + list(estados), key="lst_estado")
with col_vigencia:
    vigencia = st.selectbox("Vigência", ["Todas", "Vigente", "A vencer em 90 dias", "Vencido"], key="lst_vigencia")
with col_alerta:
    com_alerta = st.selectbox("Com alertas", ["Todos", "Com alertas", "Sem alertas"], key="lst_alerta")

alertas_por_ted: dict[str, int] = {}
for a in carregar_alertas(conn, status=None):
    if a.status != "resolvido" and a.chave_ted:
        alertas_por_ted[a.chave_ted] = alertas_por_ted.get(a.chave_ted, 0) + 1

visivel = teds_df.copy()
if busca:
    alvo = busca.strip().lower()
    visivel = visivel[
        visivel["ted"].astype(str).str.lower().str.contains(alvo, na=False)
        | visivel["codigo_siafi"].astype(str).str.lower().str.contains(alvo, na=False)
        | visivel["descricao"].astype(str).str.lower().str.contains(alvo, na=False)
    ]
if exercicio != "Todos":
    visivel = filtrar_por_exercicio(visivel, int(exercicio))
if estado != "Todos":
    visivel = visivel[visivel["estado_atual"] == estado]
if vigencia != "Todas":
    visivel = visivel[visivel["fim_vigencia"].apply(_situacao_vigencia) == vigencia]
if com_alerta == "Com alertas":
    visivel = visivel[visivel["chave_ted"].isin(alertas_por_ted.keys())]
elif com_alerta == "Sem alertas":
    visivel = visivel[~visivel["chave_ted"].isin(alertas_por_ted.keys())]

em_execucao = visivel[visivel["estado_atual"].astype(str).str.contains("Execução", case=False, na=False)]
render_kpi_strip([
    {"label": "TEDs encontrados", "value": len(visivel), "icon": "▤", "tone": design_tokens.ACCENT},
    {"label": "Em execução", "value": len(em_execucao), "icon": "▥", "tone": design_tokens.POSITIVE},
    {"label": "Com alertas", "value": int(visivel["chave_ted"].isin(alertas_por_ted.keys()).sum()), "icon": "!", "tone": design_tokens.NEGATIVE},
])

st.markdown("#### Lista de TEDs")
if visivel.empty:
    st.warning("Nenhum TED encontrado com os filtros informados.")
    st.stop()

col_pag, _ = st.columns([1, 4])
with col_pag:
    por_pagina = st.selectbox("Resultados por página", [10, 25, 50], key="lst_por_pagina")

total_paginas = max(1, -(-len(visivel) // por_pagina))
pagina = st.session_state.setdefault("lst_pagina", 1)
pagina = min(pagina, total_paginas)

inicio = (pagina - 1) * por_pagina
pagina_df = visivel.sort_values("ted").iloc[inicio : inicio + por_pagina]

cabecalho = st.columns([0.7, 0.9, 2.6, 1.1, 1.1, 1.2, 1.2, 1.2, 0.6, 0.7])
for coluna, rotulo in zip(
    cabecalho,
    ["TED", "SIAFI", "Descrição", "Estado atual", "Fim vigência", "NC líquida", "PF líquida", "Empenhado", "Alertas", ""],
):
    coluna.markdown(f"**{rotulo}**" if rotulo else "")
for posicao, linha in pagina_df.reset_index(drop=True).iterrows():
    c = st.columns([0.7, 0.9, 2.6, 1.1, 1.1, 1.2, 1.2, 1.2, 0.6, 0.7])
    c[0].write(linha["ted"])
    c[1].write(linha["codigo_siafi"])
    c[2].write(dash(linha["descricao"]))
    c[3].markdown(badge(dash(linha["estado_atual"]), cor_estado_ted(linha["estado_atual"])), unsafe_allow_html=True)
    c[4].write(dash(linha["fim_vigencia"]))
    c[5].write(brl(texto_para_valor(linha["total_nc_descentralizacao"] or "0") - texto_para_valor(linha["total_nc_devolucao"] or "0")))
    c[6].write(brl(texto_para_valor(linha["total_pf_repasse"] or "0") - texto_para_valor(linha["total_pf_devolucao"] or "0")))
    c[7].write(brl(linha["empenhado"]))
    n_alertas = alertas_por_ted.get(linha["chave_ted"], 0)
    c[8].markdown(badge(str(n_alertas), cor_gravidade("alta") if n_alertas else "inherit") if n_alertas else "—", unsafe_allow_html=True)
    if c[9].button("Abrir", key=f"lst_abrir_{posicao}"):
        st.session_state["teds_chave_selecionada"] = linha["chave_ted"]
        st.rerun()

col_ant, col_info, col_prox = st.columns([1, 3, 1])
with col_ant:
    if st.button("‹ Anterior", disabled=pagina <= 1):
        st.session_state["lst_pagina"] = pagina - 1
        st.rerun()
with col_info:
    st.caption(f"Página {pagina} de {total_paginas} — mostrando {len(pagina_df)} de {len(visivel)} TEDs")
with col_prox:
    if st.button("Próxima ›", disabled=pagina >= total_paginas):
        st.session_state["lst_pagina"] = pagina + 1
        st.rerun()
