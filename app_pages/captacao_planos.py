"""Captação de Demandas — "Planos de Referência" (Etapa 3): carga das listas do PDI e do
PLS e consulta por código ou palavra-chave.

A planilha enviada é lida só em memória (nunca gravada nem alterada); a carga é tudo ou
nada e mostra cada erro com a linha da planilha. Ver `src/captacao/planos.py`.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.captacao import planos
from src.captacao.planos import ErroCarga
from src.captacao.schema import conectar
from src.ui_theme import render_page_header

render_page_header(
    "Planos de Referência",
    "Objetivos do PDI e metas do PLS usados no vínculo obrigatório de cada demanda.",
    "Captação",
)

conexao = conectar()
try:
    # Sem login no BudgetLab, o responsável é um nome informado aqui; vai para o histórico
    # de cada alteração (exigido para editar, incluir e desativar).
    responsavel = st.text_input(
        "Responsável pelas alterações",
        placeholder="Seu nome (registrado no histórico)",
        key="captacao_planos_responsavel",
    )

    with st.container(border=True):
        st.subheader("Carregar listas oficiais")
        st.caption(
            "Envie a planilha modelo com as abas PDI e PLS preenchidas. A carga é tudo ou nada: "
            "havendo erro, nada é gravado. Recarregar uma versão atualiza os itens existentes, "
            "mantém os vínculos das demandas e desativa (sem excluir) o que saiu da lista."
        )
        arquivo = st.file_uploader("Planilha (.xlsx)", type=["xlsx"], key="captacao_planos_arquivo")
        colunas = st.columns(2)
        versao_pdi = colunas[0].text_input("Versão do PDI", placeholder="Ex.: PDI 2025–2030", key="captacao_versao_pdi")
        versao_pls = colunas[1].text_input("Versão do PLS", placeholder="Ex.: PLS 2025–2027", key="captacao_versao_pls")

        if arquivo is not None:
            try:
                leitura_pdi, leitura_pls = planos.ler_planilha(arquivo)
            except Exception as erro:  # arquivo ilegível/corrompido: informa, não derruba a página
                st.error(f"Não foi possível ler a planilha: {erro}")
                leitura_pdi = leitura_pls = None

            if leitura_pdi is not None:
                for rotulo, leitura in (("PDI", leitura_pdi), ("PLS", leitura_pls)):
                    st.markdown(f"**{rotulo}** — {len(leitura.linhas)} linha(s) válida(s), {len(leitura.erros)} erro(s)")
                    for erro in leitura.erros:
                        st.error(erro)
                    for aviso in leitura.avisos:
                        st.warning(aviso)

                pode_carregar = not leitura_pdi.erros and not leitura_pls.erros
                faltam_versoes = not versao_pdi.strip() or not versao_pls.strip()
                if pode_carregar and faltam_versoes:
                    st.info("Informe a versão do PDI e a do PLS para carregar.")
                if st.button(
                    "Carregar listas",
                    type="primary",
                    disabled=not pode_carregar or faltam_versoes,
                    key="captacao_planos_carregar",
                ):
                    try:
                        resultado_pdi = planos.carregar_pdi(conexao, leitura_pdi, versao_pdi, responsavel.strip() or None)
                        resultado_pls = planos.carregar_pls(conexao, leitura_pls, versao_pls, responsavel.strip() or None)
                    except ErroCarga as erro:
                        for motivo in erro.erros:
                            st.error(motivo)
                    else:
                        for rotulo, resultado in (("PDI", resultado_pdi), ("PLS", resultado_pls)):
                            st.success(
                                f"{rotulo}: {resultado.inseridos} inserido(s), {resultado.atualizados} atualizado(s), "
                                f"{resultado.inalterados} inalterado(s), {resultado.desativados} desativado(s)."
                            )
                            if resultado.descricoes_alteradas:
                                st.dataframe(
                                    pd.DataFrame(resultado.descricoes_alteradas, columns=["Código", "Antes", "Depois"]),
                                    hide_index=True,
                                    width="stretch",
                                )

    with st.container(border=True):
        st.subheader("Consultar")
        busca = st.text_input("Buscar por código ou palavra-chave", key="captacao_planos_busca")
        incluir_inativos = st.checkbox("Incluir itens desativados", key="captacao_planos_inativos")

        aba_pdi, aba_pls = st.tabs(["Objetivos do PDI", "Metas do PLS"])
        with aba_pdi:
            objetivos = planos.buscar_objetivos_pdi(conexao, busca, apenas_ativos=not incluir_inativos)
            if not objetivos:
                st.info("Nenhum objetivo do PDI encontrado. Carregue a lista ou ajuste a busca.")
            else:
                st.caption(f"{len(objetivos)} objetivo(s)")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Código": o["codigo"],
                                "Dimensão": o["dimensao"],
                                "Descrição": o["descricao"],
                                "Versão": o["versao_pdi"],
                                "Ativo": "Sim" if o["ativo"] else "Não",
                            }
                            for o in objetivos
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
        with aba_pls:
            eixos = [r["eixo"] for r in conexao.execute("SELECT DISTINCT eixo FROM meta_pls WHERE eixo IS NOT NULL ORDER BY eixo")]
            eixo = st.selectbox("Eixo", ["Todos os eixos", *eixos], key="captacao_planos_eixo")
            metas = planos.buscar_metas_pls(
                conexao, busca, eixo=None if eixo == "Todos os eixos" else eixo, apenas_ativas=not incluir_inativos
            )
            if not metas:
                st.info("Nenhuma meta do PLS encontrada. Carregue a lista ou ajuste a busca.")
            else:
                st.caption(f"{len(metas)} meta(s)")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Código": m["codigo"],
                                "Eixo": m["eixo"],
                                "Objetivo": m["objetivo"],
                                "Descrição": m["descricao"],
                                "Versão": m["versao_pls"],
                                "Ativa": "Sim" if m["ativo"] else "Não",
                            }
                            for m in metas
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
    with st.container(border=True):
        st.subheader("Editar ou incluir")
        st.caption(
            "Altere código, texto, eixo ou objetivo; inclua itens novos; desative o que não vale mais "
            "(nada é excluído, então os vínculos das demandas continuam). Cada alteração fica no "
            "histórico com o valor antes e depois. Recarregar a planilha da mesma versão sobrescreve "
            "edições manuais, mas o valor anterior fica registrado."
        )
        if not responsavel.strip():
            st.info("Informe o responsável pelas alterações (campo no topo da página) para editar.")

        rotulo_tipo = st.radio("Lista", ["Objetivos do PDI", "Metas do PLS"], horizontal=True, key="captacao_edit_tipo")
        tipo = "pdi" if rotulo_tipo == "Objetivos do PDI" else "pls"
        config = planos.TIPOS[tipo]
        campos_extra = {"dimensao": "Dimensão (perspectiva)"} if tipo == "pdi" else {"eixo": "Eixo temático", "objetivo": "Objetivo"}

        itens = (
            planos.buscar_objetivos_pdi(conexao, apenas_ativos=False)
            if tipo == "pdi"
            else planos.buscar_metas_pls(conexao, apenas_ativas=False)
        )
        if not itens:
            st.info("Nenhum item carregado nesta lista ainda.")
        else:
            por_id = {i["id"]: i for i in itens}

            def _rotulo(item_id: int) -> str:
                i = por_id[item_id]
                resumo = i["descricao"] if len(i["descricao"]) <= 80 else i["descricao"][:77] + "..."
                return f"{i['codigo']} — {resumo}" + ("" if i["ativo"] else " (desativado)")

            item_id = st.selectbox("Item", list(por_id), format_func=_rotulo, key=f"captacao_edit_item_{tipo}")
            item = por_id[item_id]
            st.caption(f"Versão: {item[config['versao']]}")

            with st.form(key=f"captacao_edit_form_{tipo}_{item_id}"):
                codigo = st.text_input("Código", value=item["codigo"])
                novos = {c: st.text_input(rotulo, value=item[c] or "") for c, rotulo in campos_extra.items()}
                descricao = st.text_area("Descrição", value=item["descricao"], height=120)
                salvar = st.form_submit_button("Salvar alterações", type="primary", disabled=not responsavel.strip())
            if salvar:
                try:
                    alterados = planos.editar_item(
                        conexao, tipo, item_id, {"codigo": codigo, **novos, "descricao": descricao}, responsavel
                    )
                except ErroCarga as erro:
                    for motivo in erro.erros:
                        st.error(motivo)
                else:
                    st.success(f"Alterado: {', '.join(alterados)}." if alterados else "Nenhuma alteração a gravar.")

            ativo = bool(item["ativo"])
            if st.button(
                "Desativar item" if ativo else "Reativar item",
                disabled=not responsavel.strip(),
                key=f"captacao_edit_ativo_{tipo}_{item_id}",
            ):
                try:
                    planos.alterar_ativo(conexao, tipo, item_id, not ativo, responsavel)
                except ErroCarga as erro:
                    for motivo in erro.erros:
                        st.error(motivo)
                else:
                    st.rerun()

            with st.expander("Histórico deste item"):
                registros = planos.historico_item(conexao, tipo, item_id)
                if not registros:
                    st.caption("Sem registros.")
                else:
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

        with st.expander("Incluir novo item"):
            versoes = [r[0] for r in conexao.execute(f"SELECT DISTINCT {config['versao']} FROM {config['tabela']} ORDER BY 1")]
            if not versoes:
                st.info("Carregue uma lista primeiro: a versão do novo item vem da lista carregada.")
            else:
                with st.form(key=f"captacao_novo_form_{tipo}", clear_on_submit=True):
                    versao_nova = st.selectbox("Versão", versoes)
                    codigo_novo = st.text_input("Código")
                    extras_novos = {c: st.text_input(rotulo) for c, rotulo in campos_extra.items()}
                    descricao_nova = st.text_area("Descrição", height=100)
                    incluir = st.form_submit_button("Incluir", disabled=not responsavel.strip())
                if incluir:
                    try:
                        planos.criar_item(
                            conexao, tipo, versao_nova, {"codigo": codigo_novo, **extras_novos, "descricao": descricao_nova}, responsavel
                        )
                    except ErroCarga as erro:
                        for motivo in erro.erros:
                            st.error(motivo)
                    else:
                        st.toast(f"Item {codigo_novo.strip()!r} incluído.")
                        st.rerun()
finally:
    conexao.close()
