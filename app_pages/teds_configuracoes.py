"""TEDs — Configurações. Sexta e última página do grupo "TEDs" (ver `app.py`).

Nenhum parâmetro de negócio novo foi aprovado nesta rodada (ver conversa de alinhamento) —
esta tela segue o mesmo princípio das demais: o que já tem uma regra/mecanismo real por trás
funciona de verdade; o resto fica visível (fiel ao layout do mockup) mas claramente marcado
como ainda não aplicado, nunca escondido nem fingido.

Real: tolerância monetária (usada de verdade por `app_pages/teds_conciliacao.py`, via
`st.session_state["teds_tolerancia_monetaria"]` — dura a sessão do navegador, não é
persistida em disco ainda) e as duas ações de "Dados e segurança" que não envolvem
sobrescrever nada (checar integridade do banco via `PRAGMA integrity_check`, exportar uma
cópia do arquivo `.db`).

Fictício/placeholder (widgets funcionam, mas não mudam nada fora desta tela): UG padrão,
Exercício padrão, formato de moeda, diretório de dados, alertas de vigência por prazo (esse
tipo de alerta ainda não existe em `src/teds_alertas.py`), a regra "PF superior à NC no mesmo
ano" (não implementada) e "Restaurar cópia" (desabilitado de propósito — sobrescrever o banco
é uma ação difícil de reverter, não implementada sem confirmação explícita à parte).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import streamlit as st

from src.teds_schema import CAMINHO_BANCO_PADRAO
from src.teds_ui import conexao, injetar_css
from src.ui_theme import render_page_header

injetar_css()
render_page_header("Configurações", "Parâmetros do acompanhamento e das validações.", "TEDs")

conn = conexao()

col_gerais, col_conciliacao = st.columns(2)

with col_gerais:
    with st.container(border=True):
        st.markdown("**Configurações gerais**")
        st.caption(
            "⚠ Fictício/placeholder nesta versão — os campos abaixo não mudam o comportamento "
            "de nenhuma outra página ainda."
        )
        st.selectbox("UG padrão", ["153165 — UFRPE"], disabled=True, key="cfg_ug_padrao")
        st.selectbox("Exercício padrão", ["2026"], disabled=True, key="cfg_exercicio_padrao")
        st.selectbox("Formato de moeda", ["Português (Brasil)"], disabled=True, key="cfg_formato_moeda")
        st.text_input("Diretório de dados", value=str(CAMINHO_BANCO_PADRAO.parent), disabled=True, key="cfg_diretorio")

    with st.container(border=True):
        st.markdown("**Alertas de vigência**")
        st.caption("⚠ Fictício/placeholder — não existe hoje um alerta de prazo de vigência em src/teds_alertas.py.")
        c1, c2 = st.columns(2)
        c1.number_input("Alerta crítico (dias)", value=30, disabled=True, key="cfg_alerta_critico")
        c2.number_input("Atenção — de (dias)", value=31, disabled=True, key="cfg_atencao_de")

with col_conciliacao:
    with st.container(border=True):
        st.markdown("**Regras de conciliação**")
        st.toggle("NE vinculada a mais de um TED", value=True, disabled=True, key="cfg_regra_ne", help="Regra real, sempre ativa nesta versão — ver src/teds_alertas.py::detectar_ne_em_multiplos_teds.")
        st.caption("Alerta crítico — sempre ativa (não desligável ainda).")
        st.toggle("PF superior à NC no mesmo ano", value=False, disabled=True, key="cfg_regra_pf_nc", help="Ainda não implementada.")
        st.caption("⚠ Fictício — regra ainda não implementada.")
        st.toggle("UG emitente da NC ausente", value=True, disabled=True, key="cfg_regra_nc_ug", help="Regra real, sempre ativa nesta versão — ver src/teds_alertas.py::detectar_documentos_nc_parciais.")
        st.caption("Advertência — sempre ativa (não desligável ainda).")

        tolerancia_atual = st.session_state.get("teds_tolerancia_monetaria", Decimal("0.01"))
        tolerancia_input = st.number_input(
            "Tolerância monetária (R$)", min_value=0.0, value=float(tolerancia_atual), step=0.01, format="%.2f",
            key="cfg_tolerancia", help="Usada de verdade pela página Conciliação para classificar divergências.",
        )

    with st.container(border=True):
        st.markdown("**Dados e segurança**")
        st.caption("Gerencie o arquivo SQLite do módulo de TEDs.")
        col_export, col_restore = st.columns(2)
        with col_export:
            caminho_banco = Path(CAMINHO_BANCO_PADRAO)
            if caminho_banco.exists():
                st.download_button(
                    "⬇ Exportar cópia de segurança",
                    data=caminho_banco.read_bytes(),
                    file_name="teds_backup.db",
                    mime="application/octet-stream",
                    width="stretch",
                )
            else:
                st.button("⬇ Exportar cópia de segurança", disabled=True, width="stretch")
        with col_restore:
            st.button(
                "⬆ Restaurar cópia", disabled=True, width="stretch",
                help="Não implementado de propósito — sobrescrever o banco é uma ação difícil de reverter.",
            )

        try:
            integro = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        except Exception:
            integro = False
        if integro:
            st.success(f"Banco íntegro — última verificação agora ({CAMINHO_BANCO_PADRAO}).")
        else:
            st.error("A verificação de integridade do banco encontrou um problema.")

col_descartar, col_salvar = st.columns(2)
with col_descartar:
    if st.button("Descartar alterações", width="stretch"):
        st.session_state.pop("teds_tolerancia_monetaria", None)
        st.rerun()
with col_salvar:
    if st.button("Salvar configurações", type="primary", width="stretch"):
        st.session_state["teds_tolerancia_monetaria"] = Decimal(str(tolerancia_input)).quantize(Decimal("0.01"))
        st.success("Tolerância monetária salva para esta sessão — as demais configurações desta tela ainda não são aplicadas (ver aviso de cada seção).")
