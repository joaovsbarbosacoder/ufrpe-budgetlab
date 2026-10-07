"""Captação de Demandas — "Unidades" (Etapa 4): cadastro editável das unidades (UGR) que
participam do ciclo. Nada é excluído; desativar tira a unidade das listas de escolha.
Toda alteração exige o responsável e fica no histórico (`src/captacao/auditoria.py`).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.captacao import auditoria, unidades
from src.captacao.auditoria import ErroCadastro
from src.captacao.schema import conectar
from src.ui_theme import render_page_header

render_page_header(
    "Unidades da Captação",
    "Unidades (UGR) habilitadas a registrar demandas no ciclo.",
    "Captação",
)


def _mostrar_erros(erro: ErroCadastro) -> None:
    for motivo in erro.erros:
        st.error(motivo)


conexao = conectar()
try:
    responsavel = st.text_input(
        "Responsável pelas alterações",
        placeholder="Seu nome (registrado no histórico)",
        key="captacao_unidades_responsavel",
    )
    sem_responsavel = not responsavel.strip()
    if sem_responsavel:
        st.info("Informe o responsável pelas alterações para cadastrar, editar ou desativar.")

    with st.container(border=True):
        st.subheader("Unidades cadastradas")
        incluir_inativas = st.checkbox("Incluir unidades desativadas", key="captacao_unidades_inativas")
        lista = unidades.listar_unidades(conexao, apenas_ativas=not incluir_inativas)
        if not lista:
            st.info("Nenhuma unidade cadastrada ainda. Use \"Incluir unidade\" abaixo.")
        else:
            st.caption(f"{len(lista)} unidade(s)")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"UGR": u["ugr_codigo"], "Nome": u["nome"], "Sigla": u["sigla"], "Ativa": "Sim" if u["ativa"] else "Não"}
                        for u in lista
                    ]
                ),
                hide_index=True,
                width="stretch",
            )

    with st.container(border=True):
        st.subheader("Editar unidade")
        todas = unidades.listar_unidades(conexao)
        if not todas:
            st.caption("Cadastre uma unidade para poder editá-la.")
        else:
            por_id = {u["id"]: u for u in todas}
            unidade_id = st.selectbox(
                "Unidade",
                list(por_id),
                format_func=lambda i: f"{por_id[i]['ugr_codigo']} — {por_id[i]['nome']}" + ("" if por_id[i]["ativa"] else " (desativada)"),
                key="captacao_unidades_selecao",
            )
            unidade = por_id[unidade_id]
            with st.form(key=f"captacao_unidades_form_{unidade_id}"):
                codigo = st.text_input("Código da UGR", value=unidade["ugr_codigo"])
                nome = st.text_input("Nome", value=unidade["nome"])
                sigla = st.text_input("Sigla", value=unidade["sigla"] or "")
                salvar = st.form_submit_button("Salvar alterações", type="primary", disabled=sem_responsavel)
            if salvar:
                try:
                    alterados = unidades.editar_unidade(
                        conexao, unidade_id, {"ugr_codigo": codigo, "nome": nome, "sigla": sigla}, responsavel
                    )
                except ErroCadastro as erro:
                    _mostrar_erros(erro)
                else:
                    st.success(f"Alterado: {', '.join(alterados)}." if alterados else "Nenhuma alteração a gravar.")

            ativa = bool(unidade["ativa"])
            if st.button(
                "Desativar unidade" if ativa else "Reativar unidade",
                disabled=sem_responsavel,
                key=f"captacao_unidades_ativa_{unidade_id}",
            ):
                try:
                    unidades.alterar_ativa(conexao, unidade_id, not ativa, responsavel)
                except ErroCadastro as erro:
                    _mostrar_erros(erro)
                else:
                    st.rerun()

            with st.expander("Histórico desta unidade"):
                registros = auditoria.historico(conexao, "unidade", unidade_id)
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Quando (UTC)": r["criado_em"][:19].replace("T", " "),
                                "Ação": r["acao"],
                                "Campo": r["campo"],
                                "Antes": r["antes"],
                                "Depois": r["depois"],
                                "Responsável": r["usuario"],
                            }
                            for r in registros
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )

    with st.container(border=True):
        st.subheader("Incluir unidade")
        with st.form(key="captacao_unidades_novo", clear_on_submit=True):
            codigo_novo = st.text_input("Código da UGR")
            nome_novo = st.text_input("Nome")
            sigla_nova = st.text_input("Sigla")
            incluir = st.form_submit_button("Incluir", disabled=sem_responsavel)
        if incluir:
            try:
                unidades.criar_unidade(
                    conexao, {"ugr_codigo": codigo_novo, "nome": nome_novo, "sigla": sigla_nova}, responsavel
                )
            except ErroCadastro as erro:
                _mostrar_erros(erro)
            else:
                st.toast(f"Unidade {codigo_novo.strip()!r} incluída.")
                st.rerun()
finally:
    conexao.close()
