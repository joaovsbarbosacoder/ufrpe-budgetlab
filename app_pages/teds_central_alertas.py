"""TEDs — Central de Alertas. Terceira página do grupo "TEDs" (ver `app.py`).

Lista + detalhe mestre-detalhe. A lista e as regras de negócio são reais (`src/teds_alertas.py`
— NE em múltiplos TEDs e NC sem UG emitente). O workflow de análise (marcar "em análise",
resolver com justificativa/responsável) também é real: o schema de `alerta`
(`src/teds_schema.py`) já tinha as colunas `status`/`responsavel`/`justificativa`/
`data_resolucao` reservadas pra isso — só não havia UI que as usasse. `responsavel` é texto
livre (não existe cadastro de usuários no projeto), não um seletor de pessoas cadastradas.
"""

from __future__ import annotations

import streamlit as st

from src import design_tokens
from src.teds_alertas import (
    TIPO_EMPENHO_MULTIPLOS_TEDS,
    carregar_decisoes_vinculo_ne,
    registrar_decisao_vinculo_ne,
    teds_vinculados_ao_empenho,
)
from src.teds_auditoria import ENTIDADE_ALERTA, ENTIDADE_VINCULO_NE, historico_auditoria
from src.teds_ui import (
    STATUS_ABERTO,
    STATUS_EM_ANALISE,
    STATUS_RESOLVIDO,
    alertas_de_ne_para_ted,
    atualizar_status_alerta,
    badge,
    carregar_alertas,
    conexao,
    cor_gravidade,
    cor_status_alerta,
    formatar_valor_auditoria,
    injetar_css,
    render_kpi_strip,
    rotulo_acao_auditoria,
    rotulo_gravidade,
    rotulo_status_alerta,
    rotulo_tipo_alerta,
)
from src.ui_theme import render_page_header

injetar_css()
render_page_header("Central de Alertas", "Exceções identificadas automaticamente no acompanhamento de TEDs.", "TEDs")

conn = conexao()
todos = carregar_alertas(conn, status=None)

if not todos:
    st.success("Nenhum alerta gerado ainda — importe as extrações do SIMEC em \"Importações\".")
    st.stop()

criticos = [a for a in todos if a.gravidade == "alta"]
atencao = [a for a in todos if a.gravidade == "media"]
informativos = [a for a in todos if a.gravidade == "baixa"]
em_analise = [a for a in todos if a.status == STATUS_EM_ANALISE]
resolvidos = [a for a in todos if a.status == STATUS_RESOLVIDO]

render_kpi_strip([
    {"label": "Críticos", "value": len(criticos), "icon": "!", "tone": design_tokens.NEGATIVE},
    {"label": "Atenção", "value": len(atencao), "icon": "!", "tone": design_tokens.WARNING},
    {"label": "Informativos", "value": len(informativos), "icon": "i", "tone": design_tokens.ACCENT},
    {"label": "Em análise", "value": len(em_analise), "icon": "◷", "tone": design_tokens.TEXT_MUTED},
    {"label": "Resolvidos", "value": len(resolvidos), "icon": "✓", "tone": design_tokens.POSITIVE},
])

col_grav, col_tipo, col_ted, col_status, col_resp = st.columns(5)
with col_grav:
    grav_sel = st.selectbox("Gravidade", ["Todas", "alta", "media", "baixa"], key="ca_grav", format_func=lambda v: "Todas" if v == "Todas" else rotulo_gravidade(v))
tipos_existentes = sorted({a.tipo for a in todos})
with col_tipo:
    tipo_sel = st.selectbox("Tipo", ["Todos"] + tipos_existentes, key="ca_tipo", format_func=lambda v: "Todos" if v == "Todos" else rotulo_tipo_alerta(v))
teds_existentes = sorted(
    {a.chave_ted for a in todos if a.chave_ted}
    | {
        chave_ted
        for (chave_ted,) in conn.execute(
            "SELECT DISTINCT chave_ted FROM vinculo_ne ORDER BY chave_ted"
        ).fetchall()
    }
)
ted_pre_selecionado = st.session_state.pop("alertas_filtro_chave_ted", None)
with col_ted:
    opcoes_ted = ["Todos"] + teds_existentes
    indice_padrao = opcoes_ted.index(ted_pre_selecionado) if ted_pre_selecionado in opcoes_ted else 0
    ted_sel = st.selectbox("TED", opcoes_ted, index=indice_padrao, key="ca_ted")
with col_status:
    status_sel = st.selectbox("Status", ["Todos", STATUS_ABERTO, STATUS_EM_ANALISE, STATUS_RESOLVIDO], key="ca_status", format_func=lambda v: "Todos" if v == "Todos" else rotulo_status_alerta(v))
responsaveis_existentes = sorted({a.responsavel for a in todos if a.responsavel})
with col_resp:
    resp_sel = st.selectbox("Responsável", ["Todos", "Não atribuído"] + responsaveis_existentes, key="ca_resp")

filtrados = todos
if grav_sel != "Todas":
    filtrados = [a for a in filtrados if a.gravidade == grav_sel]
if tipo_sel != "Todos":
    filtrados = [a for a in filtrados if a.tipo == tipo_sel]
if ted_sel != "Todos":
    alertas_indiretos = {a.id for a in alertas_de_ne_para_ted(conn, ted_sel)}
    filtrados = [a for a in filtrados if a.chave_ted == ted_sel or a.id in alertas_indiretos]
if status_sel != "Todos":
    filtrados = [a for a in filtrados if a.status == status_sel]
if resp_sel == "Não atribuído":
    filtrados = [a for a in filtrados if not a.responsavel]
elif resp_sel != "Todos":
    filtrados = [a for a in filtrados if a.responsavel == resp_sel]

col_lista, col_detalhe = st.columns([3, 2])

with col_lista:
    st.markdown(f"#### Lista de alertas — {len(filtrados)} registro(s)")
    selecionado_id = st.session_state.get("ca_selecionado")
    if filtrados and selecionado_id not in {a.id for a in filtrados}:
        selecionado_id = filtrados[0].id
        st.session_state["ca_selecionado"] = selecionado_id

    for a in filtrados:
        ativo = a.id == selecionado_id
        with st.container(border=True):
            cinfo, cbtn = st.columns([5, 1])
            cinfo.markdown(
                f"{badge(rotulo_gravidade(a.gravidade), cor_gravidade(a.gravidade))} "
                f"{badge(rotulo_status_alerta(a.status), cor_status_alerta(a.status))} &nbsp; "
                f"**{rotulo_tipo_alerta(a.tipo)}**  \n"
                f"<span class='teds-muted'>{a.documento} — {a.data_identificacao[:10]}</span>",
                unsafe_allow_html=True,
            )
            if cbtn.button("Ver" if not ativo else "●", key=f"ca_ver_{a.id}"):
                st.session_state["ca_selecionado"] = a.id
                st.rerun()

with col_detalhe:
    alvo = next((a for a in filtrados if a.id == selecionado_id), None)
    st.markdown("#### Detalhe do alerta")
    if alvo is None:
        st.caption("Selecione um alerta na lista.")
    else:
        with st.container(border=True):
            st.markdown(badge(rotulo_gravidade(alvo.gravidade), cor_gravidade(alvo.gravidade)), unsafe_allow_html=True)
            st.markdown(f"**{rotulo_tipo_alerta(alvo.tipo)}**")
            st.write(alvo.descricao)

            st.markdown("**Regra de negócio**")
            regra = {
                "empenho_multiplos_teds": "Uma Nota de Empenho (NE) não deve estar vinculada a mais de um TED "
                "simultaneamente — a execução fica fora dos totais consolidados de todos os TEDs envolvidos até "
                "a pendência ser resolvida (ver src/teds_alertas.py::detectar_ne_em_multiplos_teds).",
                "nc_ug_emitente_ausente": "Toda NC deveria trazer a UG emitente na extração do SIMEC, para "
                "permitir a conciliação externa por UG — quando ausente em todas as linhas do documento, a "
                "conciliação fica parcial até a UG ser identificada manualmente "
                "(ver src/teds_alertas.py::detectar_documentos_nc_parciais).",
                "nc_liquida_diverge_consolidado": "A NC líquida somada dos documentos importados deve coincidir "
                "com o Total Descentralizado do relatório consolidado (tolerância R$ 0,01). A diferença pode vir "
                "de extração incompleta ou de outro período — o sistema não decide qual fonte está certa.",
                "pf_liquida_diverge_consolidado": "O PF líquido somado dos documentos importados (com o sinal da "
                "operação) deve coincidir com o Total Repassado do relatório consolidado (tolerância R$ 0,01).",
                "pf_liquida_maior_que_nc": "O repasse financeiro líquido não deve superar o crédito líquido "
                "descentralizado do TED — conferir crédito de exercício anterior ao período importado.",
                "ted_vigencia_invertida": "O início da vigência do TED não pode ser posterior ao fim.",
                "siafi_em_multiplos_teds": "Um código SIAFI identifica um único TED; associado a mais de um "
                "número, exige justificativa.",
                "ted_sem_ug_descentralizadora": "Todo TED deve informar a UG descentralizadora no cadastro.",
                "documento_fora_da_vigencia": "NC e PF devem ser emitidas dentro da vigência do TED; pode haver "
                "casos legítimos, que pedem justificativa — o documento nunca é excluído.",
                "ted_vencido_em_execucao": "TED com vigência encerrada não deveria continuar no estado "
                "\"Termo em Execução\" — conferir prorrogação ou encerramento.",
                "ted_sem_movimentacao": "TED em execução deveria ter NC ou PF emitida dentro do prazo (padrão 180 "
                "dias); o prazo é uma escolha inicial, não uma regra do briefing, e a NE não conta por não ter "
                "data no banco.",
                "ne_liquidado_maior_que_empenhado": "O liquidado acumulado de uma NE não pode superar o "
                "empenhado acumulado no Tesouro Gerencial (tolerância R$ 0,01; soma de todos os meses, "
                "estornos com sinal).",
                "ne_pago_maior_que_liquidado": "O pago acumulado de uma NE não pode superar o liquidado "
                "acumulado no Tesouro Gerencial (tolerância R$ 0,01; soma de todos os meses, estornos com sinal).",
                "ne_simec_difere_tesouro": "O valor da NE informado no SIMEC deveria coincidir com o empenhado "
                "acumulado no Tesouro Gerencial (tolerância R$ 0,01). A diferença pode ser legítima — ex.: NE "
                "só em parte vinculada ao TED — e pede conferência, não correção automática.",
            }.get(alvo.tipo, "—")
            st.caption(regra)

            st.markdown("**Rastreabilidade**")
            st.caption(f"Origem dos dados: SIMEC  \nIdentificado em: {alvo.data_identificacao}")
            if alvo.chave_ted:
                st.caption(f"TED: {alvo.chave_ted}")

            st.markdown("**Linha do tempo**")
            st.caption(f"🔴 Alerta identificado — {alvo.data_identificacao}")
            if alvo.status in (STATUS_EM_ANALISE, STATUS_RESOLVIDO):
                st.caption("🟡 Em análise")
            if alvo.status == STATUS_RESOLVIDO:
                st.caption(f"🟢 Resolvido — {alvo.data_resolucao}")

            st.markdown("**Trilha de auditoria**")
            registros = historico_auditoria(conn, ENTIDADE_ALERTA, alvo.id)
            if alvo.tipo == TIPO_EMPENHO_MULTIPLOS_TEDS:
                registros += historico_auditoria(conn, ENTIDADE_VINCULO_NE, alvo.documento)
            if not registros:
                st.caption("Nenhuma ação humana registrada para este alerta.")
            for registro in sorted(registros, key=lambda r: r.data_hora):
                with st.container(border=True):
                    st.caption(
                        f"{registro.data_hora[:19].replace('T', ' ')} UTC — {registro.usuario} — "
                        f"{rotulo_acao_auditoria(registro.acao)}"
                    )
                    st.caption(
                        f"De: {formatar_valor_auditoria(registro.valor_anterior)}  \n"
                        f"Para: {formatar_valor_auditoria(registro.valor_novo)}"
                    )
                    if registro.motivo:
                        st.write(registro.motivo)

            if alvo.tipo == TIPO_EMPENHO_MULTIPLOS_TEDS:
                decisoes = carregar_decisoes_vinculo_ne(conn, alvo.documento)
                if decisoes:
                    st.markdown("**Histórico de decisões**")
                    for decisao in decisoes:
                        st.caption(
                            f"{decisao.data_decisao} — TED escolhido: "
                            f"{decisao.chave_ted_escolhida} — responsável: {decisao.responsavel}"
                        )
                        st.write(decisao.justificativa)

                st.markdown("**Decisão sobre o vínculo**")
                teds_vinculados = teds_vinculados_ao_empenho(conn, alvo.documento)
                with st.form(f"ca_decisao_{alvo.id}", border=False):
                    ted_escolhido = st.selectbox(
                        "TED que deve contabilizar a NE",
                        teds_vinculados,
                        key=f"ca_ted_escolhido_{alvo.id}",
                    )
                    responsavel = st.text_input(
                        "Responsável pela decisão",
                        value=alvo.responsavel or "",
                        key=f"ca_resp_txt_{alvo.id}",
                    )
                    justificativa = st.text_area(
                        "Justificativa da decisão",
                        value=alvo.justificativa or "",
                        key=f"ca_just_{alvo.id}",
                        placeholder="Explique por que a NE pertence ao TED selecionado.",
                    )
                    decidiu = st.form_submit_button(
                        "Registrar decisão e resolver",
                        type="primary",
                        disabled=alvo.status == STATUS_RESOLVIDO,
                        width="stretch",
                    )
                if decidiu:
                    try:
                        registrar_decisao_vinculo_ne(
                            conn,
                            alerta_id=alvo.id,
                            chave_empenho=alvo.documento,
                            chave_ted_escolhida=ted_escolhido,
                            responsavel=responsavel,
                            justificativa=justificativa,
                        )
                    except ValueError as erro:
                        st.error(str(erro))
                    else:
                        st.success("Decisão registrada. Somente o TED escolhido será contabilizado.")
                        st.rerun()

                if st.button(
                    "Marcar em análise",
                    key=f"ca_analisar_{alvo.id}",
                    disabled=alvo.status == STATUS_RESOLVIDO,
                    width="stretch",
                ):
                    atualizar_status_alerta(
                        conn,
                        alvo.id,
                        STATUS_EM_ANALISE,
                        responsavel=responsavel.strip() or None,
                    )
                    st.rerun()
            else:
                st.markdown("**Análise do alerta**")
                justificativa = st.text_area(
                    "Justificativa da análise", value=alvo.justificativa or "", key=f"ca_just_{alvo.id}",
                    placeholder="Descreva a análise, observações ou o motivo da resolução…",
                )
                responsavel = st.text_input("Responsável", value=alvo.responsavel or "", key=f"ca_resp_txt_{alvo.id}")

                cbtn1, cbtn2 = st.columns(2)
                with cbtn1:
                    if st.button("Marcar em análise", disabled=alvo.status == STATUS_RESOLVIDO, width="stretch"):
                        atualizar_status_alerta(conn, alvo.id, STATUS_EM_ANALISE, responsavel=responsavel or None)
                        st.rerun()
                with cbtn2:
                    if st.button("Resolver alerta", type="primary", width="stretch"):
                        if not justificativa.strip():
                            st.error("Informe a justificativa antes de resolver o alerta.")
                        else:
                            atualizar_status_alerta(
                                conn, alvo.id, STATUS_RESOLVIDO,
                                responsavel=responsavel or None, justificativa=justificativa,
                            )
                            st.rerun()
