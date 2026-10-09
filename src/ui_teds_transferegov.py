"""Telas dos TEDs do TransfereGov (`src/teds_transferegov.py`) dentro do grupo "TEDs": lista e detalhe
(chamados por `app_pages/teds_lista.py`, origem "TransfereGov") e o resumo da Visão geral.

Nenhuma soma de NC ou PF aparece aqui: o significado dos códigos de evento da NC e da situação contábil da
TRF não foi confirmado (ver docstring de `src/teds_transferegov.py`), então cada valor é mostrado ao lado do
seu código, como veio da API. As NEs são só indícios por célula orçamentária, nunca vínculo."""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from src import design_tokens
from src.teds_transferegov import (
    carregar_teds_transferegov,
    indicios_ne,
    notas_do_plano,
    pfs_do_plano,
    ultimo_lote_transferegov,
)
from src.teds_ui import badge, brl, dash, html_linha, paginar, render_doc_list, render_kpi_strip

CHAVE_SELECIONADO = "teds_tg_selecionado"
ORIGEM_SIMEC = "SIMEC (MEC)"
ORIGEM_TRANSFEREGOV = "TransfereGov (outros órgãos)"

AVISO_CODIGOS = (
    "Valores como vieram da API, sem sinal: o significado dos códigos de evento da NC (300300, 300302…) e da "
    "situação contábil da TRF (TRF003, TRF004…) não foi confirmado, então nenhum total é calculado."
)

_ROTULO_SITUACAO = {
    "EM_EXECUCAO": "Em execução",
    "CUMPRIMENTO_OBJETO_INICIADO": "Cumprimento do objeto iniciado",
}


def rotulo_situacao(situacao_termo: str | None, situacao_plano: str | None) -> str:
    if situacao_termo:
        return _ROTULO_SITUACAO.get(situacao_termo, situacao_termo.replace("_", " ").capitalize())
    if situacao_plano:
        return "Plano: " + situacao_plano.replace("_", " ").lower()
    return "—"


def _cor_situacao(situacao_termo: str | None) -> str:
    if situacao_termo == "EM_EXECUCAO":
        return design_tokens.POSITIVE
    if situacao_termo:
        return design_tokens.WARNING
    return design_tokens.TEXT_MUTED


def _titulo(linha: pd.Series) -> str:
    return f"TED {linha['instrumento']}" if linha["instrumento"] else f"Plano de ação {linha['id_plano_acao']} (sem termo)"


def _valor_ou_sem(valor: str | None) -> str:
    return brl(valor) if valor is not None else "sem valor"


def render_resumo_visao_geral(conn) -> None:
    """Bloco da Visão geral: quantidades (sem valores) e atalho para a lista."""

    st.markdown("#### TEDs de outros órgãos (TransfereGov)")
    lote = ultimo_lote_transferegov(conn)
    if lote is None:
        st.caption(
            "Os TEDs do MEC vêm do SIMEC; os de outros órgãos (MDA, INCRA, MPA…) tramitam no TransfereGov e "
            "ainda não foram sincronizados — use **Sincronizar com o TransfereGov** em Importações."
        )
        return
    teds = carregar_teds_transferegov(conn)
    render_kpi_strip([
        {"label": "Planos de ação", "value": len(teds), "icon": "▤", "tone": design_tokens.ACCENT},
        {"label": "Termos em execução", "value": int((teds["situacao_termo"] == "EM_EXECUCAO").sum()), "icon": "▥", "tone": design_tokens.POSITIVE},
        {"label": "Órgãos concedentes", "value": teds["sigla_concedente"].nunique(), "icon": "◎", "tone": design_tokens.ACCENT},
        {"label": "Notas de crédito", "value": int(teds["qtd_nc"].sum()), "icon": "≋", "tone": design_tokens.POSITIVE},
        {"label": "Programações financeiras", "value": int(teds["qtd_pf"].sum()), "icon": "▥", "tone": design_tokens.ACCENT},
    ])
    st.caption(
        f"Sincronizado em {pd.Timestamp(lote[1]).strftime('%d/%m/%Y %H:%M')} (lote #{lote[0]}). Sem totais em "
        "reais: o sinal dos eventos de NC e da TRF não está confirmado."
    )
    if st.button("Ver TEDs do TransfereGov", key="vg_ver_transferegov"):
        st.session_state["lst_origem"] = ORIGEM_TRANSFEREGOV
        st.switch_page("app_pages/teds_lista.py")


def render_lista(conn) -> None:
    lote = ultimo_lote_transferegov(conn)
    teds = carregar_teds_transferegov(conn)
    if teds.empty:
        st.info(
            "Nenhum TED do TransfereGov sincronizado ainda. Vá em **Importações** e use "
            "**Sincronizar com o TransfereGov**."
        )
        return
    if lote is not None:
        st.caption(f"Fonte: API de Dados Abertos do TransfereGov · sincronizado em {pd.Timestamp(lote[1]).strftime('%d/%m/%Y %H:%M')}.")

    col_busca, col_concedente, col_situacao = st.columns([2.2, 1.3, 1.6])
    with col_busca:
        busca = st.text_input("Busca", key="tg_busca", placeholder="Instrumento, objeto, programa…", label_visibility="collapsed")
    with col_concedente:
        concedente = st.selectbox("Concedente", ["Todos"] + sorted(teds["sigla_concedente"].dropna().unique()), key="tg_concedente")
    situacoes = {rotulo_situacao(t, p) for t, p in zip(teds["situacao_termo"], teds["situacao_plano"])}
    with col_situacao:
        situacao = st.selectbox("Situação", ["Todas"] + sorted(situacoes), key="tg_situacao")

    visivel = teds.copy()
    if busca:
        alvo = busca.strip().lower()
        texto = (visivel["instrumento"].fillna("") + " " + visivel["objeto"].fillna("") + " "
                 + visivel["nome_programa"].fillna("") + " " + visivel["id_plano_acao"]).str.lower()
        visivel = visivel[texto.str.contains(alvo, regex=False)]
    if concedente != "Todos":
        visivel = visivel[visivel["sigla_concedente"] == concedente]
    if situacao != "Todas":
        visivel = visivel[[rotulo_situacao(t, p) == situacao for t, p in zip(visivel["situacao_termo"], visivel["situacao_plano"])]]

    render_kpi_strip([
        {"label": "Planos encontrados", "value": len(visivel), "icon": "▤", "tone": design_tokens.ACCENT},
        {"label": "Termos em execução", "value": int((visivel["situacao_termo"] == "EM_EXECUCAO").sum()), "icon": "▥", "tone": design_tokens.POSITIVE},
        {"label": "Sem termo (plano em tramitação)", "value": int(visivel["id_termo"].isna().sum()), "icon": "…", "tone": design_tokens.TEXT_MUTED},
    ])
    if visivel.empty:
        st.warning("Nenhum TED encontrado com os filtros informados.")
        return

    pagina, total_paginas, inicio, fim = paginar(len(visivel), 25, st.session_state.setdefault("tg_pagina", 1))
    for posicao, linha in visivel.iloc[inicio:fim].reset_index(drop=True).iterrows():
        with st.container(border=True):
            c_info, c_botao = st.columns([6, 1], vertical_alignment="center")
            c_info.markdown(
                html_linha(
                    _titulo(linha),
                    dash(linha["objeto"]),
                    [badge(escape(rotulo_situacao(linha["situacao_termo"], linha["situacao_plano"])), _cor_situacao(linha["situacao_termo"])),
                     badge(escape(dash(linha["sigla_concedente"])), design_tokens.ACCENT)],
                    [
                        ("Vigência", f"{dash(linha['inicio_vigencia'])} a {dash(linha['fim_vigencia'])}"),
                        ("Valor do plano (informado)", _valor_ou_sem(linha["valor_plano"])),
                        ("NCs", str(int(linha["qtd_nc"]))),
                        ("PFs", str(int(linha["qtd_pf"]))),
                    ],
                    tone=_cor_situacao(linha["situacao_termo"]),
                ),
                unsafe_allow_html=True,
            )
            if c_botao.button("Abrir", key=f"tg_abrir_{inicio + posicao}", width="stretch"):
                st.session_state[CHAVE_SELECIONADO] = linha["id_plano_acao"]
                st.rerun()

    col_ant, col_info, col_prox = st.columns([1, 3, 1])
    with col_ant:
        if st.button("‹ Anterior", key="tg_anterior", disabled=pagina <= 1):
            st.session_state["tg_pagina"] = pagina - 1
            st.rerun()
    with col_info:
        st.caption(f"Página {pagina} de {total_paginas} — mostrando {fim - inicio} de {len(visivel)} planos")
    with col_prox:
        if st.button("Próxima ›", key="tg_proxima", disabled=pagina >= total_paginas):
            st.session_state["tg_pagina"] = pagina + 1
            st.rerun()


def render_detalhe(conn, id_plano_acao: str) -> None:
    teds = carregar_teds_transferegov(conn)
    linha = teds[teds["id_plano_acao"] == id_plano_acao]
    if st.button("← TEDs do TransfereGov", key="tg_voltar"):
        st.session_state.pop(CHAVE_SELECIONADO, None)
        st.rerun()
    if linha.empty:
        st.error("Plano de ação não encontrado.")
        return
    linha = linha.iloc[0]

    st.markdown(f"## {escape(_titulo(linha))}")
    itens = [
        ("Concedente", f"{dash(linha['sigla_concedente'])} — {dash(linha['concedente'])}"),
        ("Situação", rotulo_situacao(linha["situacao_termo"], linha["situacao_plano"])),
        ("Vigência", f"{dash(linha['inicio_vigencia'])} a {dash(linha['fim_vigencia'])}"),
        ("Processo SEI", dash(linha["processo_sei"])),
        ("Plano de ação", linha["id_plano_acao"]),
        ("Valor do plano (informado)", _valor_ou_sem(linha["valor_plano"])),
    ]
    st.markdown(
        "<div class='teds-hero'>"
        + "".join(f"<div class='teds-hero-item'><span>{escape(r)}</span><strong>{escape(str(v))}</strong></div>" for r, v in itens)
        + "</div>",
        unsafe_allow_html=True,
    )
    if linha["objeto"]:
        st.caption(linha["objeto"])
    if linha["nome_programa"]:
        st.caption(f"Programa {dash(linha['codigo_programa'])}: {linha['nome_programa']}")

    notas = notas_do_plano(conn, id_plano_acao)
    pfs = pfs_do_plano(conn, id_plano_acao)
    indicios = indicios_ne(conn, id_plano_acao)

    aba_nc, aba_pf, aba_ne = st.tabs([
        f"Notas de crédito ({len(notas)})", f"Programações financeiras ({len(pfs)})",
        f"Empenhos com célula coincidente ({len({i.numero_ne for i in indicios})})",
    ])
    with aba_nc:
        st.caption(AVISO_CODIGOS)
        if not notas:
            st.info("Nenhuma NC deste plano no TransfereGov.")
        for nota in notas:
            render_doc_list(
                f"NC {dash(nota['numero_nc'])}",
                [
                    {
                        "main": f"Evento {dash(e['cd_evento'])}",
                        "meta": f"PTRES {dash(e['ptres'])} · fonte {dash(e['fonte_detalhada'])} · natureza {dash(e['natureza'])} · PI {dash(e['pi'])}",
                        "value": _valor_ou_sem(e["valor"]),
                    }
                    for e in nota["eventos"]
                ],
                tone=design_tokens.POSITIVE,
                empty="NC sem eventos na API.",
                note=" · ".join(filter(None, [
                    f"Emissão {dash(nota['data_emissao'])}", f"UG emitente {dash(nota['ug_emitente'])}",
                    f"UG favorecida {dash(nota['ug_favorecida'])}", dash(nota["situacao"]), nota["observacao"],
                ])),
            )
    with aba_pf:
        st.caption(AVISO_CODIGOS)
        if not pfs:
            st.info("Nenhuma PF deste plano no TransfereGov.")
        for pf in pfs:
            render_doc_list(
                f"PF {dash(pf['numero_pf'])}",
                [
                    {
                        "main": f"Situação contábil {dash(t['situacao_contabil'])}",
                        "meta": f"fonte {dash(t['fonte'])} · vinculação {dash(t['vinculacao'])} · categoria {dash(t['categoria_gasto'])}",
                        "value": _valor_ou_sem(t["valor"]),
                    }
                    for t in pf["trfs"]
                ],
                tone=design_tokens.ACCENT,
                empty="PF sem linhas TRF na API.",
                note=" · ".join(filter(None, [
                    f"Recebimento {dash(pf['data_recebimento'])}", f"UG emitente {dash(pf['ug_emitente'])}",
                    f"UG favorecida {dash(pf['ug_favorecida'])}", dash(pf["situacao"]), pf["observacao"],
                ])),
            )
    with aba_ne:
        st.caption(
            "NEs da Execução Mensal com a mesma célula (exercício, PTRES, fonte, natureza e PI) de um evento das NCs "
            "deste plano. É indício para conferência, não vínculo: a API do TransfereGov não traz NE. "
            "Empenhado, liquidado e pago são o acumulado da NE no Tesouro Gerencial."
        )
        if not indicios:
            st.info("Nenhuma NE com célula coincidente (ou a Execução Mensal ainda não foi sincronizada).")
        else:
            st.dataframe(
                pd.DataFrame([
                    {
                        "NE": i.numero_ne, "NC(s)": ", ".join(i.numeros_nc), "PTRES": i.ptres, "Fonte": i.fonte_detalhada,
                        "Natureza": i.natureza, "PI": i.pi or "—",
                        "Empenhado": brl(i.empenhado) if i.empenhado is not None else "sem dado",
                        "Liquidado": brl(i.liquidado) if i.liquidado is not None else "sem dado",
                        "Pago": brl(i.pago) if i.pago is not None else "sem dado",
                        "Já vinculada a TED do SIMEC": ", ".join(i.teds_simec) or "não",
                    }
                    for i in indicios
                ]),
                hide_index=True,
                width="stretch",
            )
