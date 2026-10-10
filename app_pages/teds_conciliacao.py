"""TEDs — Conciliação. Quinta página do grupo "TEDs" (ver `app.py`).

Compara, por TED, o valor/quantidade de NEs registrados no SIMEC (`vinculo_ne`, real) contra o
Tesouro Gerencial (`execucao_tg`, cruzado por `numero_completo_ne` — ver docstring de
`src/teds_importacao_tesouro_gerencial.py`). A comparação em si é real; "Fonte ausente"
aparece enquanto a Execução Mensal não foi sincronizada (botão "Sincronizar" na página
Importações) ou quando a NE não consta nela — não é fictício, é ausência de dado.

A situação "Conferência necessária" tanto pode vir de uma divergência de valor acima da
tolerância quanto do alerta já existente de NE-em-múltiplos-TEDs (`src/teds_alertas.py`) — as
duas fontes de divergência aparecem juntas nesta tela, sem inventar uma terceira regra.

Tolerância monetária é lida de `st.session_state["teds_tolerancia_monetaria"]` — configurável
na página Configurações; sem ela definida ainda nesta sessão, usa R$ 0,01 (mesmo valor do
mockup).
"""

from __future__ import annotations

from decimal import Decimal
from html import escape

import pandas as pd
import streamlit as st

from src import design_tokens
from src.teds_normalizacao import texto_para_valor
from src.teds_controle_nc import (
    SITUACAO_AMBIGUA, SITUACAO_CONFERE, SITUACAO_DIVERGE, SITUACAO_SEM_PLANILHA, conferir_controle,
    gerar_xlsx_conferencia, justificativa_sugerida, ler_controle_nc,
)
from src.teds_ui import STATUS_RESOLVIDO, anos_disponiveis, atualizar_status_alerta, badge, brl, carregar_teds, conexao, data_br, cor_situacao_conciliacao, filtrar_por_exercicio, html_linha, injetar_css, paginar, render_doc_list, render_kpi_strip, situacao_conciliacao
from src.ui_theme import render_page_header

injetar_css()
render_page_header("Conciliação", "Compare informações entre as fontes e identifique divergências nos TEDs.", "TEDs")

conn = conexao()
teds_df = carregar_teds(conn)
if teds_df.empty:
    st.info('Nenhum TED importado ainda. Vá em "Importações".')
    st.stop()

tolerancia = st.session_state.get("teds_tolerancia_monetaria", Decimal("0.01"))

col_exercicio, col_ted, col_tipo, col_situacao = st.columns(4)
anos = anos_disponiveis(teds_df)
with col_exercicio:
    exercicio = st.selectbox("Exercício", ["Todos"] + [str(a) for a in anos], key="cc_exercicio")
with col_ted:
    ted_sel = st.selectbox("TED", ["Todos"] + sorted(teds_df["ted"].tolist()), key="cc_ted")
with col_tipo:
    tipo_sel = st.selectbox("Tipo de divergência", ["Todos", "Valor das NEs", "Quantidade de NEs"], key="cc_tipo")
with col_situacao:
    situacao_sel = st.selectbox("Situação", ["Todas", "Conciliado", "Conferência necessária", "Fonte ausente"], key="cc_situacao")

filtrado = teds_df
if exercicio != "Todos":
    filtrado = filtrar_por_exercicio(filtrado, int(exercicio))
if ted_sel != "Todos":
    filtrado = filtrado[filtrado["ted"] == ted_sel]


def _linhas_ne(chave_ted: str) -> list[tuple]:
    return conn.execute(
        "SELECT numero_ne, valor_ne, status_validacao FROM vinculo_ne WHERE chave_ted = ?", (chave_ted,)
    ).fetchall()


def _tg_por_numeros(numeros_ne: set[str]) -> list[tuple]:
    if not numeros_ne:
        return []
    marcadores = ",".join("?" * len(numeros_ne))
    return conn.execute(
        f"SELECT numero_completo_ne, empenhado FROM execucao_tg WHERE numero_completo_ne IN ({marcadores})",
        list(numeros_ne),
    ).fetchall()


linhas_comparacao = []
for _, ted_row in filtrado.iterrows():
    chave_ted = ted_row["chave_ted"]
    ne_linhas = _linhas_ne(chave_ted)
    ne_contabilizaveis = [linha for linha in ne_linhas if linha[2] == "ok"]
    numeros_ne = {n for n, _, _ in ne_contabilizaveis}
    tg_linhas = _tg_por_numeros(numeros_ne)
    tem_pendencia = any(status == "pendente" for _, _, status in ne_linhas)

    valor_simec = sum(
        (texto_para_valor(valor) for _, valor, _ in ne_contabilizaveis),
        start=Decimal("0"),
    )
    qtd_simec = len(ne_contabilizaveis)
    if tg_linhas:
        valor_tg = sum((texto_para_valor(v) for _, v in tg_linhas if v is not None), start=Decimal("0"))
        qtd_tg = len({n for n, _ in tg_linhas})
        fonte_ausente = False
    else:
        valor_tg, qtd_tg, fonte_ausente = None, None, True

    for metrica, valor_a, valor_b, ausente in (
        ("Valor das NEs", valor_simec, valor_tg, fonte_ausente),
        ("Quantidade de NEs", Decimal(qtd_simec), Decimal(qtd_tg) if qtd_tg is not None else None, fonte_ausente),
    ):
        diferenca = None if ausente else valor_a - valor_b
        situacao = situacao_conciliacao(
            tem_pendencia=tem_pendencia,
            fonte_ausente=ausente,
            diferenca=diferenca,
            tolerancia=tolerancia,
        )
        linhas_comparacao.append(
            {
                "chave_ted": chave_ted, "ted": ted_row["ted"], "siafi": ted_row["codigo_siafi"],
                "metrica": metrica, "simec": valor_a, "documentos": qtd_simec, "tg": valor_b,
                "diferenca": diferenca, "situacao": situacao,
            }
        )

comparacao = pd.DataFrame(linhas_comparacao)
if tipo_sel != "Todos":
    comparacao = comparacao[comparacao["metrica"] == tipo_sel]
if situacao_sel != "Todas":
    comparacao = comparacao[comparacao["situacao"] == situacao_sel]

diferenca_total = sum(
    (abs(d) for d in comparacao.loc[comparacao["metrica"] == "Valor das NEs", "diferenca"].dropna()), start=Decimal("0")
)
render_kpi_strip([
    {"label": "Conciliados", "value": int((comparacao["situacao"] == "Conciliado").sum()), "icon": "✓", "tone": design_tokens.POSITIVE},
    {"label": "Conferência necessária", "value": int((comparacao["situacao"] == "Conferência necessária").sum()), "icon": "!", "tone": design_tokens.NEGATIVE},
    {"label": "Fonte ausente", "value": int((comparacao["situacao"] == "Fonte ausente").sum()), "icon": "□", "tone": design_tokens.WARNING},
    {"label": "Diferença total", "value": brl(diferenca_total), "icon": "▥", "tone": design_tokens.ACCENT},
])

st.markdown("#### Comparação entre fontes")
if comparacao.empty:
    st.caption("Nenhum registro para os filtros selecionados.")
else:
    _POR_PAGINA = 25
    assinatura_filtros = (exercicio, ted_sel, tipo_sel, situacao_sel)
    if st.session_state.get("cc_assinatura") != assinatura_filtros:
        st.session_state["cc_assinatura"] = assinatura_filtros
        st.session_state["cc_pagina"] = 1  # filtro novo volta para a primeira página
    pagina, total_paginas, inicio, fim = paginar(len(comparacao), _POR_PAGINA, st.session_state.get("cc_pagina", 1))
    st.session_state["cc_pagina"] = pagina
    # `posicao` continua sendo o índice na lista completa: a chave do botão e a evidência não mudam com a página.
    for posicao, linha in comparacao.reset_index(drop=True).iloc[inicio:fim].iterrows():
        eh_valor = linha["metrica"] == "Valor das NEs"
        tem_tg = not pd.isna(linha["tg"])
        with st.container(border=True):
            c_info, c_botao = st.columns([6, 1], vertical_alignment="center")
            c_info.markdown(
                html_linha(
                    f"TED {linha['ted']} · SIAFI {linha['siafi']} · {linha['metrica']}",
                    None,
                    [badge(escape(linha["situacao"]), cor_situacao_conciliacao(linha["situacao"]))],
                    [
                        ("SIMEC", brl(linha["simec"]) if eh_valor else str(int(linha["simec"]))),
                        ("Tesouro Gerencial", ("—" if not tem_tg else brl(linha["tg"]) if eh_valor else str(int(linha["tg"])))),
                        ("Diferença", ("—" if not tem_tg else brl(linha["diferenca"]) if eh_valor else str(int(linha["diferenca"])))),
                        ("NEs contabilizadas", str(linha["documentos"])),
                    ],
                    tone=cor_situacao_conciliacao(linha["situacao"]),
                ),
                unsafe_allow_html=True,
            )
            if linha["situacao"] == "Conferência necessária":
                if c_botao.button("Analisar", key=f"cc_analisar_{posicao}", width="stretch"):
                    st.session_state["cc_evidencia"] = (linha["chave_ted"], linha["metrica"])

    col_ant, col_info, col_prox = st.columns([1, 3, 1])
    with col_ant:
        if st.button("‹ Anterior", key="cc_ant", disabled=pagina <= 1):
            st.session_state["cc_pagina"] = pagina - 1
            st.rerun()
    with col_info:
        st.caption(f"Página {pagina} de {total_paginas} — mostrando {fim - inicio} de {len(comparacao)} comparações")
    with col_prox:
        if st.button("Próxima ›", key="cc_prox", disabled=pagina >= total_paginas):
            st.session_state["cc_pagina"] = pagina + 1
            st.rerun()

evidencia = st.session_state.get("cc_evidencia")
if evidencia:
    chave_ted_ev, metrica_ev = evidencia
    ted_row = teds_df[teds_df["chave_ted"] == chave_ted_ev]
    if not ted_row.empty:
        ted_row = ted_row.iloc[0]
        with st.container(border=True):
            col_titulo, col_fechar = st.columns([5, 1])
            col_titulo.markdown(f"#### Evidências da divergência — TED {ted_row['ted']} · {metrica_ev}")
            if col_fechar.button("Fechar"):
                del st.session_state["cc_evidencia"]
                st.rerun()

            ne_linhas = _linhas_ne(chave_ted_ev)
            pendentes = [n for n, _, s in ne_linhas if s == "pendente"]
            if pendentes:
                st.warning(f"NE(s) com pendência de NE-em-múltiplos-TEDs neste TED: {', '.join(pendentes)}.")

            col_simec, col_tg = st.columns(2)
            with col_simec:
                render_doc_list(
                    "SIMEC", [{"main": n, "meta": f"status: {s}", "value": brl(v)} for n, v, s in ne_linhas],
                    tone=design_tokens.ACCENT, empty="Nenhuma NE vinculada a este TED.",
                )
            with col_tg:
                tg_linhas = _tg_por_numeros({n for n, _, _ in ne_linhas})
                render_doc_list(
                    "Tesouro Gerencial", [{"main": n, "meta": "lançamento no Tesouro", "value": brl(v)} for n, v in tg_linhas],
                    tone=design_tokens.POSITIVE, empty="Sem dado — nenhuma extração do Tesouro Gerencial importada para estas NEs.",
                )


# --- Conferir com a planilha de controle de NCs -------------------------------------------------
# Decisão (08/10/2026, spec teds-alertas-e-controle-nc §5): a planilha manual é ferramenta de consulta
# para sanear pendências, não fonte contínua. Ela é lida em memória a cada execução da tela e NUNCA
# gravada no banco; a única escrita possível é a resolução de um alerta, clicada pelo usuário e feita
# pelo fluxo auditado `atualizar_status_alerta`.
_TIPOS_ALERTA_PLANILHA = (
    "nc_ug_emitente_ausente", "pf_liquida_maior_que_nc", "pf_liquida_diverge_consolidado",
    "ted_credito_sem_empenho",
)
_ROTULO_SITUACAO = {
    SITUACAO_CONFERE: "Confere", SITUACAO_DIVERGE: "Diverge", SITUACAO_AMBIGUA: "Ambígua",
    SITUACAO_SEM_PLANILHA: "Sem planilha",
}


def _linhas_planilha_df(linhas) -> pd.DataFrame:
    return pd.DataFrame([
        {"Aba": l.aba, "Linha": l.linha_origem, "NC": l.nc, "Data": data_br(l.data), "UG emitente": l.ug_emitente,
         "TED": l.ted, "Valor": brl(l.valor), "Processo": l.processo, "Observação": l.observacao}
        for l in linhas
    ])


st.divider()
st.markdown("#### Conferir com a planilha de controle")
st.caption("A planilha é lida só nesta tela e não é gravada no banco.")
arquivo_controle = st.file_uploader("Planilha de controle de NCs (.xlsx)", type=["xlsx"], key="cc_controle_upload")
if arquivo_controle is not None:
    try:
        leitura_controle = ler_controle_nc(arquivo_controle.getvalue())
    except Exception as erro:  # arquivo corrompido ou não-xlsx: mensagem em vez de quebrar a página
        st.error(f"Não foi possível ler a planilha: {erro}")
        st.stop()
    conferencia = conferir_controle(conn, leitura_controle)

    st.caption(
        f"{len(leitura_controle.linhas)} linha(s) lida(s), {len(leitura_controle.rejeitadas)} rejeitada(s), "
        f"{len(leitura_controle.abas_ignoradas)} aba(s) não lida(s)."
    )
    if leitura_controle.abas_ignoradas or leitura_controle.rejeitadas:
        with st.expander("Abas não lidas e linhas rejeitadas"):
            for aba, motivo in leitura_controle.abas_ignoradas:
                st.write(f"Aba **{aba}**: {motivo}")
            for aba, linha, motivo in leitura_controle.rejeitadas:
                st.write(f"Aba **{aba}**, linha {linha}: {motivo}")

    contagem = {rotulo: sum(1 for c in conferencia.por_nc if c.situacao == sit) for sit, rotulo in _ROTULO_SITUACAO.items()}
    colunas_contagem = st.columns(len(contagem))
    for coluna, (rotulo, total) in zip(colunas_contagem, contagem.items()):
        coluna.metric(rotulo, total)

    destaque = [c for c in conferencia.por_nc if c.situacao in (SITUACAO_DIVERGE, SITUACAO_AMBIGUA) or (c.ug_simec is None and c.ug_planilha)]
    st.markdown("**NCs que divergem, ambíguas ou com UG sugerida**")
    if destaque:
        st.dataframe(pd.DataFrame([
            {"NC": c.numero_nc, "TED": c.chave_ted, "Situação": _ROTULO_SITUACAO[c.situacao],
             "Valor SIMEC": brl(c.valor_simec) if c.valor_simec is not None else "—",
             "Valor planilha": brl(c.valor_planilha) if c.valor_planilha is not None else "—",
             "UG SIMEC": c.ug_simec or "—", "UG sugerida (planilha)": c.ug_planilha or "—"}
            for c in destaque
        ]), hide_index=True, width="stretch")
    else:
        st.caption("Nenhuma NC divergente, ambígua ou com UG sugerida.")

    st.markdown("**NC anterior ao consolidado**")
    if conferencia.nc_anterior_consolidado:
        st.dataframe(pd.concat([
            _linhas_planilha_df(linhas).assign(**{"TED (chave)": chave})
            for chave, linhas in conferencia.nc_anterior_consolidado.items()
        ]), hide_index=True, width="stretch")
    else:
        st.caption("Nenhuma NC da planilha anterior ao primeiro exercício do consolidado.")

    st.markdown("**Sem TED**")
    if conferencia.sem_ted:
        st.dataframe(_linhas_planilha_df(conferencia.sem_ted), hide_index=True, width="stretch")
    else:
        st.caption("Todas as linhas da planilha têm TED informado.")

    st.download_button(
        "Baixar conferência (Excel)", data=gerar_xlsx_conferencia(conferencia),
        file_name="conferencia_controle_nc.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="cc_controle_download",
    )

    st.markdown("**Alertas que a planilha ajuda a resolver**")
    marcadores = ",".join("?" * len(_TIPOS_ALERTA_PLANILHA))
    alertas_abertos = conn.execute(
        f"SELECT id, tipo, chave_ted, descricao FROM alerta WHERE status = 'aberto' AND tipo IN ({marcadores}) "
        "AND chave_ted IS NOT NULL ORDER BY id", _TIPOS_ALERTA_PLANILHA,
    ).fetchall()
    sugeridos = [(a, justificativa_sugerida(a[1], a[2], conferencia)) for a in alertas_abertos]
    sugeridos = [(a, texto) for a, texto in sugeridos if texto]
    if not sugeridos:
        st.caption("Nenhum alerta aberto com dado na planilha.")
    for (alerta_id, tipo, chave_ted, descricao), texto in sugeridos:
        with st.container(border=True):
            st.markdown(f"**TED {chave_ted.split('|')[0]}** · {tipo}")
            st.caption(descricao)
            justificativa = st.text_area("Justificativa", value=texto, key=f"cc_controle_just_{alerta_id}")
            responsavel = st.text_input("Responsável", key=f"cc_controle_resp_{alerta_id}")
            if st.button("Resolver", key=f"cc_controle_resolver_{alerta_id}", type="primary"):
                if not justificativa.strip():
                    st.error("Informe a justificativa antes de resolver o alerta.")
                else:
                    atualizar_status_alerta(
                        conn, alerta_id, STATUS_RESOLVIDO,
                        responsavel=responsavel.strip() or None, justificativa=justificativa.strip(),
                    )
                    st.rerun()
