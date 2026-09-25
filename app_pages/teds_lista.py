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
from decimal import Decimal
from html import escape

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
    cobertura_tg,
    conexao,
    cor_estado_ted,
    cor_gravidade,
    dash,
    documentos_nc,
    documentos_pf,
    filtrar_por_exercicio,
    historico_lotes_do_ted,
    html_linha,
    injetar_css,
    marcos_do_ted,
    paginar,
    pct,
    render_doc_list,
    render_execution_panel,
    render_kpi_strip,
    render_timeline,
    rotulo_gravidade,
    rotulo_tipo_alerta,
    soma_tg_por_teds,
    somar_valores,
    texto_cobertura_tg,
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


_ROTULO_STATUS_NE = {
    "pendente": "vínculo múltiplo — conferência necessária",
    "descartado": "não contabilizado — decisão registrada",
    "ok": "ok",
}


def _nota_sem_valor(sem_valor: int) -> str:
    return f"{sem_valor} documento(s) sem valor informado, fora da soma." if sem_valor else ""


def _nota_consolidado(soma, consolidado, origem: str, kpi: str) -> str:
    base = f"Soma dos documentos {origem} importados do SIMEC; o KPI de {kpi} usa o consolidado da Execução Anual."
    if abs(soma - consolidado) > Decimal("0.01"):
        return f"{base} Diferença em relação ao consolidado: {brl(soma - consolidado)} (ver alertas de conciliação)."
    return base


def _cartao_nc(docs: list[tuple], consolidado: Decimal) -> tuple[list[dict[str, str]], str, str]:
    linhas = []
    for numero, ug_emitente, operacao, data_emissao, valor_total, qtd_linhas, status in docs:
        meta = [dash(data_emissao), f"UG emitente: {dash(ug_emitente)}" if status != "PARCIAL" else "UG emitente ausente"]
        if qtd_linhas > 1:
            meta.append(f"{qtd_linhas} linhas de origem")
        linhas.append({"main": f"{numero} ({operacao})", "meta": " · ".join(meta), "value": brl(valor_total)})
    soma, sem_valor = somar_valores([d[4] for d in docs])
    nota = _nota_consolidado(soma, consolidado, "DOC NC", "NC líquida")
    return linhas, brl(soma), " ".join(filter(None, [nota, _nota_sem_valor(sem_valor)]))


def _cartao_pf(docs: list[tuple], consolidado: Decimal) -> tuple[list[dict[str, str]], str, str]:
    linhas = [
        {"main": f"{numero} ({operacao})", "meta": f"{dash(data_emissao)} · UG {dash(ug_emitente)}", "value": brl(valor)}
        for numero, ug_emitente, operacao, data_emissao, valor in docs
    ]
    soma, sem_valor = somar_valores([d[4] for d in docs])
    nota = _nota_consolidado(soma, consolidado, "DOC PF", "PF líquida")
    return linhas, brl(soma), " ".join(filter(None, [nota, _nota_sem_valor(sem_valor)]))


def _cartao_ne(docs: list[tuple]) -> tuple[list[dict[str, str]], str, str]:
    linhas = [
        {
            "main": numero_ne,
            "meta": f"UG {dash(ug)} / gestão {dash(gestao)} · {_ROTULO_STATUS_NE.get(status, status)}",
            "value": brl(valor),
        }
        for numero_ne, ug, gestao, valor, status, _ in docs
    ]
    contabilizaveis = [d[3] for d in docs if d[4] == "ok"]
    soma, sem_valor = somar_valores(contabilizaveis)
    fora = len(docs) - len(contabilizaveis)
    nota = f"Total considera só os vínculos confirmados; {fora} vínculo(s) pendente(s) ou descartado(s) ficam de fora." if fora else ""
    return linhas, brl(soma), " ".join(filter(None, [nota, _nota_sem_valor(sem_valor)]))


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
    st.markdown(
        "<div class='teds-hero'>"
        f"<div class='teds-hero-item'><span>SIAFI</span><strong>{escape(dash(linha['codigo_siafi']))}</strong></div>"
        f"<div class='teds-hero-item'><span>Estado</span>{badge(escape(dash(linha['estado_atual'])), cor_estado_ted(linha['estado_atual']))}</div>"
        f"<div class='teds-hero-item'><span>UG descentralizadora</span><strong>{escape(dash(linha['ug_descentralizadora']))}</strong></div>"
        f"<div class='teds-hero-item'><span>Vigência</span><strong>{escape(dash(linha['inicio_vigencia']))} a "
        f"{escape(dash(linha['fim_vigencia']))} ({escape(_situacao_vigencia(linha['fim_vigencia']))})</strong></div>"
        "</div>",
        unsafe_allow_html=True,
    )
    if linha["descricao"]:
        st.caption(linha["descricao"])

    docs_nc = documentos_nc(conn, chave_ted)
    docs_pf = documentos_pf(conn, chave_ted)
    docs_ne = vinculos_ne(conn, chave_ted)

    acao_exportar, acao_obs, acao_alertas = st.columns(3)
    with acao_exportar:
        nc = pd.DataFrame(docs_nc, columns=["numero_nc", "ug_emitente", "operacao", "data_emissao", "valor_assinado_total", "quantidade_linhas", "status_relacionamento"])
        pf = pd.DataFrame(docs_pf, columns=["numero_pf", "ug_emitente", "operacao", "data_emissao", "valor_assinado"])
        ne = pd.DataFrame(docs_ne, columns=["numero_ne", "ug_emitente", "gestao_emitente", "valor_ne", "status_validacao", "chave_empenho"])
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
    alertas_ted = carregar_alertas(conn, chave_ted=chave_ted) + alertas_de_ne_para_ted(conn, chave_ted)
    abertos = [a for a in alertas_ted if a.status != "resolvido"]

    render_kpi_strip([
        {"label": "NC líquida", "value": brl(nc_liquida), "icon": "≋", "tone": design_tokens.POSITIVE},
        {"label": "PF líquida", "value": brl(pf_liquida), "icon": "▥", "tone": design_tokens.ACCENT},
        {"label": "Empenhado", "value": brl(linha["empenhado"]), "icon": "□", "tone": design_tokens.WARNING},
        {"label": "Alertas abertos", "value": len(abertos), "icon": "!", "tone": design_tokens.NEGATIVE if abertos else design_tokens.POSITIVE},
    ])

    col_orc, col_fin = st.columns(2)
    with col_orc:
        frac_emp, pct_emp = pct(linha["empenhado"], nc_liquida)
        frac_liq, pct_liq = pct(liquidado, linha["empenhado"])
        render_execution_panel("Execução orçamentária", [
            {"label": "NC líquida", "fraction": 1 if nc_liquida else 0, "percent": "100%" if nc_liquida else "—", "value": brl(nc_liquida), "tone": design_tokens.POSITIVE},
            {"label": "Empenhado", "fraction": frac_emp, "percent": pct_emp, "value": brl(linha["empenhado"]), "tone": design_tokens.WARNING},
            {"label": "Liquidado", "fraction": frac_liq if tem_tg else 0, "percent": pct_liq if tem_tg else "Sem dado", "value": brl(liquidado) if tem_tg else "Tesouro Gerencial", "tone": design_tokens.ACCENT},
        ])
    with col_fin:
        frac_pago, pct_pago = pct(pago, pf_liquida)
        render_execution_panel("Execução financeira", [
            {"label": "PF líquida", "fraction": 1 if pf_liquida else 0, "percent": "100%" if pf_liquida else "—", "value": brl(pf_liquida), "tone": design_tokens.ACCENT},
            {"label": "Pago", "fraction": frac_pago if tem_tg else 0, "percent": pct_pago if tem_tg else "Sem dado", "value": brl(pago) if tem_tg else "Tesouro Gerencial", "tone": design_tokens.POSITIVE},
        ], difference=("Diferença NC−PF", brl(nc_liquida - pf_liquida)))
    aviso_tg = texto_cobertura_tg(*cobertura_tg(conn, chave_ted))
    if aviso_tg:
        st.caption(f"Tesouro Gerencial: {aviso_tg}")

    linhas_nc, total_nc, nota_nc = _cartao_nc(docs_nc, nc_liquida)
    linhas_pf, total_pf, nota_pf = _cartao_pf(docs_pf, pf_liquida)
    linhas_ne, total_ne, nota_ne = _cartao_ne(docs_ne)

    aba_geral, aba_nc, aba_pf, aba_ne, aba_liq, aba_alertas, aba_hist = st.tabs(
        ["Visão geral", f"Notas de crédito ({len(docs_nc)})", f"Programações financeiras ({len(docs_pf)})",
         f"Empenhos ({len(docs_ne)})", "Liquidação por competência", f"Alertas ({len(abertos)})", "Histórico"]
    )

    with aba_geral:
        c_nc, c_pf, c_ne = st.columns(3)
        with c_nc:
            render_doc_list("Notas de crédito", linhas_nc, total=total_nc, tone=design_tokens.POSITIVE, empty="Nenhuma NC vinculada a este TED.", note=nota_nc)
        with c_pf:
            render_doc_list("Programações financeiras", linhas_pf, total=total_pf, tone=design_tokens.ACCENT, empty="Nenhuma PF vinculada a este TED.", note=nota_pf)
        with c_ne:
            render_doc_list("Empenhos", linhas_ne, total=total_ne, tone=design_tokens.WARNING, empty="Nenhum empenho vinculado a este TED.", note=nota_ne)
        st.markdown("#### Linha do tempo")
        marcos = marcos_do_ted(linha["inicio_vigencia"], linha["fim_vigencia"], [d[3] for d in docs_nc], [d[3] for d in docs_pf])
        render_timeline(marcos, vazio="Nenhuma data disponível para este TED.")
        sem_data = sum(1 for d in docs_nc if not d[3]) + sum(1 for d in docs_pf if not d[3])
        if sem_data:
            st.caption(f"{sem_data} documento(s) sem data de emissão não aparecem na linha do tempo.")

    with aba_nc:
        render_doc_list("Notas de crédito", linhas_nc, total=total_nc, tone=design_tokens.POSITIVE, empty="Nenhuma NC vinculada a este TED.", note=nota_nc)

    with aba_pf:
        render_doc_list("Programações financeiras", linhas_pf, total=total_pf, tone=design_tokens.ACCENT, empty="Nenhuma PF vinculada a este TED.", note=nota_pf)

    with aba_ne:
        render_doc_list("Empenhos", linhas_ne, total=total_ne, tone=design_tokens.WARNING, empty="Nenhum empenho vinculado a este TED.", note=nota_ne)

    with aba_liq:
        if not tem_tg:
            st.info(aviso_tg or "Sem dado do Tesouro Gerencial para as NEs deste TED.")
        else:
            render_kpi_strip([
                {"label": "Liquidado", "value": brl(liquidado), "icon": "▥", "tone": design_tokens.ACCENT},
                {"label": "Pago", "value": brl(pago), "icon": "✓", "tone": design_tokens.POSITIVE},
            ])
            st.caption("Valores por mês de lançamento no Tesouro Gerencial, não de competência.")

    with aba_alertas:
        if not alertas_ted:
            st.success("Nenhum alerta para este TED.")
        for a in alertas_ted:
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

pagina, total_paginas, inicio, fim = paginar(len(visivel), por_pagina, st.session_state.setdefault("lst_pagina", 1))
pagina_df = visivel.sort_values("ted").iloc[inicio:fim]

for posicao, linha in pagina_df.reset_index(drop=True).iterrows():
    n_alertas = alertas_por_ted.get(linha["chave_ted"], 0)
    selos = [badge(escape(dash(linha["estado_atual"])), cor_estado_ted(linha["estado_atual"]))]
    if n_alertas:
        selos.append(badge(f"{n_alertas} alerta(s)", cor_gravidade("alta")))
    with st.container(border=True):
        c_info, c_botao = st.columns([6, 1], vertical_alignment="center")
        c_info.markdown(
            html_linha(
                f"TED {linha['ted']} · SIAFI {linha['codigo_siafi']}",
                dash(linha["descricao"]),
                selos,
                [
                    ("Fim da vigência", dash(linha["fim_vigencia"])),
                    ("NC líquida", brl(texto_para_valor(linha["total_nc_descentralizacao"] or "0") - texto_para_valor(linha["total_nc_devolucao"] or "0"))),
                    ("PF líquida", brl(texto_para_valor(linha["total_pf_repasse"] or "0") - texto_para_valor(linha["total_pf_devolucao"] or "0"))),
                    ("Empenhado", brl(linha["empenhado"])),
                ],
                tone=cor_gravidade("alta") if n_alertas else cor_estado_ted(linha["estado_atual"]),
            ),
            unsafe_allow_html=True,
        )
        if c_botao.button("Abrir", key=f"lst_abrir_{posicao}", width="stretch"):
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
