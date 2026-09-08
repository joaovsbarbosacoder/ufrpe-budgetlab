"""Captação de Demandas Orçamentárias — "Minhas Demandas" (visão do representante de
setor).

Sem autenticação real nesta versão (briefing, seção 3): "quem sou eu" é resolvido
escolhendo o próprio setor numa lista, guardado em `st.session_state` pela sessão do
navegador — a Unidade solicitante do formulário vem dessa escolha, não é
re-selecionável dentro dele (evita representante de um setor submeter em nome de
outro).

O formulário de nova demanda usa widgets soltos (não `st.form`): o Total precisa
recalcular a cada tecla em Quantidade/Valor unitário, e `st.form` só reavalia ao
submeter — ver `src/demandas_orcamentarias.py` para a justificativa completa do
schema/persistência.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.demandas_orcamentarias import (
    STATUS_BADGE_COLOR,
    STATUS_LABELS,
    STATUS_RASCUNHO,
    TIPOS_DESPESA,
    carregar_demandas,
    carregar_metas_pdi_pls,
    carregar_setores,
    enviar,
    nova_demanda,
    salvar,
    validar_para_envio,
)
from src.ui_theme import format_brl_compact, format_brl_full, render_page_header

EXERCICIOS_DISPONIVEIS = (2026, 2027, 2028)
EXERCICIO_PADRAO = 2027


def _ou_traco(valor: object) -> object:
    """`valor` se for utilizável, "—" se for None/NaN — campo opcional de um rascunho
    ainda incompleto vira NaN (não None) ao passar por `carregar_demandas()`
    (`pd.DataFrame.from_records`), e NaN é *verdadeiro* em Python (`nan or "—"` avalia
    pra `nan`, não pra "—") — por isso o `or` sozinho não bastava aqui."""

    return "—" if pd.isna(valor) else valor


def _mapa_setores(setores: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """Rótulo buscável → (código, nome). Mesmo padrão de `_option_mapping` em
    `app_pages/dotacao_orcamentaria.py`, replicado aqui (não compartilhado entre
    páginas — cada página do projeto mantém seus próprios helpers pequenos)."""

    return {
        f"{linha['nome']}": (linha["codigo"], linha["nome"])
        for _, linha in setores.sort_values("nome").iterrows()
    }


def _mapa_metas(metas: pd.DataFrame) -> dict[str, dict[str, str]]:
    return {
        f"[{linha['plano']}] {linha['descricao']}": {
            "codigo": linha["codigo"],
            "descricao": linha["descricao"],
        }
        for _, linha in metas.sort_values(["plano", "descricao"]).iterrows()
    }


def _selecionar_meu_setor(setores: pd.DataFrame) -> tuple[str, str] | None:
    mapa = _mapa_setores(setores)
    rotulo_atual = st.session_state.get("demandas_meu_setor_rotulo")
    rotulo = st.selectbox(
        "Meu setor",
        options=list(mapa),
        index=list(mapa).index(rotulo_atual) if rotulo_atual in mapa else None,
        placeholder="Digite para buscar seu setor...",
        key="demandas_meu_setor_rotulo",
        help="Identificação simples nesta versão, sem login — escolha o setor que você representa.",
    )
    if rotulo is None:
        return None
    return mapa[rotulo]


def _iniciar_nova_demanda(unidade_codigo: str, unidade_nome: str) -> None:
    demanda = nova_demanda(unidade_codigo, unidade_nome, EXERCICIO_PADRAO)
    st.session_state["demandas_editando_id"] = demanda["id"]
    st.session_state["demandas_editando_dados"] = demanda


def _abrir_para_edicao(demanda: dict) -> None:
    st.session_state["demandas_editando_id"] = demanda["id"]
    st.session_state["demandas_editando_dados"] = demanda


def _fechar_formulario() -> None:
    st.session_state.pop("demandas_editando_id", None)
    st.session_state.pop("demandas_editando_dados", None)


def _renderizar_lista(demandas_setor: pd.DataFrame) -> None:
    if demandas_setor.empty:
        st.info("Nenhuma demanda registrada por este setor ainda.")
        return

    for _, demanda in demandas_setor.sort_values("criado_em", ascending=False).iterrows():
        with st.container(border=True):
            cabecalho, acao = st.columns([5, 1], vertical_alignment="center")
            with cabecalho:
                descricao = demanda["descricao_necessidade"] or "(sem descrição ainda)"
                st.markdown(f"**{descricao[:120]}**")
                st.badge(
                    STATUS_LABELS.get(demanda["status"], demanda["status"]),
                    color=STATUS_BADGE_COLOR.get(demanda["status"], "gray"),
                )
            with acao:
                if demanda["status"] == STATUS_RASCUNHO:
                    if st.button("Editar", key=f"demandas_editar_{demanda['id']}", width="stretch"):
                        _abrir_para_edicao(demanda.to_dict())
                        st.rerun()

            detalhes = st.columns(4)
            detalhes[0].caption("Unidade")
            detalhes[0].write(demanda["unidade_nome"])
            detalhes[1].caption("Tipo")
            detalhes[1].write(_ou_traco(demanda["tipo_despesa"]))
            detalhes[2].caption("Valor total")
            valor_total = demanda["valor_total"]
            detalhes[2].write(format_brl_compact(valor_total) if not pd.isna(valor_total) else "—")
            metas = demanda["metas_pdi_pls"] or []
            detalhes[3].caption("Metas PDI/PLS")
            detalhes[3].write(", ".join(meta["codigo"] for meta in metas) if metas else "—")


def _renderizar_formulario(metas_pdi_pls: pd.DataFrame, unidade_nome: str) -> None:
    dados = st.session_state["demandas_editando_dados"]
    demanda_id = dados["id"]
    somente_leitura = dados["status"] != STATUS_RASCUNHO

    with st.container(border=True):
        topo, fechar = st.columns([5, 1], vertical_alignment="center")
        topo.subheader("Enviada — somente leitura" if somente_leitura else "Nova demanda")
        if fechar.button("Fechar", key=f"demandas_fechar_{demanda_id}", width="stretch"):
            _fechar_formulario()
            st.rerun()

        st.caption(f"Unidade solicitante: **{unidade_nome}**")

        exercicio = st.selectbox(
            "Exercício de referência",
            options=EXERCICIOS_DISPONIVEIS,
            index=EXERCICIOS_DISPONIVEIS.index(dados["exercicio"])
            if dados["exercicio"] in EXERCICIOS_DISPONIVEIS
            else EXERCICIOS_DISPONIVEIS.index(EXERCICIO_PADRAO),
            key=f"demandas_exercicio_{demanda_id}",
            disabled=somente_leitura,
        )

        mapa_metas = _mapa_metas(metas_pdi_pls)
        rotulos_por_codigo = {valor["codigo"]: rotulo for rotulo, valor in mapa_metas.items()}
        metas_atuais = [
            rotulos_por_codigo[meta["codigo"]]
            for meta in dados["metas_pdi_pls"]
            if meta["codigo"] in rotulos_por_codigo
        ]
        rotulos_metas = st.multiselect(
            "Vínculo com planejamento institucional (PDI/PLS)",
            options=list(mapa_metas),
            default=metas_atuais,
            placeholder="Selecione uma ou mais metas...",
            key=f"demandas_metas_{demanda_id}",
            disabled=somente_leitura,
            help="Uma demanda pode atender mais de uma meta ao mesmo tempo.",
        )

        tipo_despesa = st.radio(
            "Tipo de despesa",
            options=TIPOS_DESPESA,
            index=TIPOS_DESPESA.index(dados["tipo_despesa"]) if dados["tipo_despesa"] in TIPOS_DESPESA else None,
            key=f"demandas_tipo_{demanda_id}",
            horizontal=True,
            disabled=somente_leitura,
        )

        col_qtd, col_valor, col_total = st.columns(3)
        quantidade = col_qtd.number_input(
            "Quantidade",
            min_value=0.0,
            step=1.0,
            value=float(dados["quantidade"] or 0.0),
            key=f"demandas_quantidade_{demanda_id}",
            disabled=somente_leitura,
        )
        valor_unitario = col_valor.number_input(
            "Valor unitário (R$)",
            min_value=0.0,
            step=100.0,
            format="%.2f",
            value=float(dados["valor_unitario"] or 0.0),
            key=f"demandas_valor_unitario_{demanda_id}",
            disabled=somente_leitura,
        )
        total = quantidade * valor_unitario
        col_total.metric("Total", format_brl_full(total))

        descricao = st.text_area(
            "Descrição da necessidade",
            value=dados["descricao_necessidade"],
            key=f"demandas_descricao_{demanda_id}",
            disabled=somente_leitura,
        )
        justificativa = st.text_area(
            "Justificativa",
            value=dados["justificativa"],
            key=f"demandas_justificativa_{demanda_id}",
            disabled=somente_leitura,
        )

        with st.expander("Classificação avançada (opcional)", expanded=False):
            st.caption(
                "Classificação orçamentária fina — Ação de Governo, PI, GND, Natureza "
                "de Despesa. Fica em segundo plano nesta versão; não é obrigatória."
            )
            classificacao = dados.get("classificacao_avancada") or {}
            col_acao, col_pi = st.columns(2)
            acao = col_acao.text_input(
                "Ação de Governo",
                value=classificacao.get("acao_codigo") or "",
                key=f"demandas_acao_{demanda_id}",
                disabled=somente_leitura,
            )
            pi = col_pi.text_input(
                "PI",
                value=classificacao.get("pi_codigo") or "",
                key=f"demandas_pi_{demanda_id}",
                disabled=somente_leitura,
            )
            col_gnd, col_natureza = st.columns(2)
            gnd = col_gnd.text_input(
                "GND",
                value=classificacao.get("gnd_codigo") or "",
                key=f"demandas_gnd_{demanda_id}",
                disabled=somente_leitura,
            )
            natureza = col_natureza.text_input(
                "Natureza de Despesa",
                value=classificacao.get("natureza_detalhada_codigo") or "",
                key=f"demandas_natureza_{demanda_id}",
                disabled=somente_leitura,
            )

        if somente_leitura:
            return

        dados_atuais = {
            **dados,
            "exercicio": exercicio,
            "metas_pdi_pls": [mapa_metas[rotulo] for rotulo in rotulos_metas],
            "tipo_despesa": tipo_despesa,
            "quantidade": quantidade or None,
            "valor_unitario": valor_unitario or None,
            "valor_total": total or None,
            "descricao_necessidade": descricao,
            "justificativa": justificativa,
            "classificacao_avancada": {
                "acao_codigo": acao or None,
                "acao_descricao": None,
                "pi_codigo": pi or None,
                "pi_descricao": None,
                "gnd_codigo": gnd or None,
                "gnd_descricao": None,
                "natureza_detalhada_codigo": natureza or None,
                "natureza_detalhada_descricao": None,
            },
        }
        st.session_state["demandas_editando_dados"] = dados_atuais

        col_rascunho, col_enviar = st.columns(2)
        if col_rascunho.button("Salvar rascunho", key=f"demandas_salvar_{demanda_id}", width="stretch"):
            salvar(dados_atuais)
            _fechar_formulario()
            st.success("Rascunho salvo.")
            st.rerun()
        if col_enviar.button(
            "Enviar", key=f"demandas_enviar_{demanda_id}", type="primary", width="stretch"
        ):
            erros = validar_para_envio(dados_atuais)
            if erros:
                st.error("Preencha antes de enviar: " + "; ".join(erros))
            else:
                enviar(dados_atuais)
                _fechar_formulario()
                st.success("Demanda enviada.")
                st.rerun()


render_page_header(
    "Minhas Demandas",
    "Registro e acompanhamento das demandas orçamentárias do seu setor.",
    "Demandas",
)

setores = carregar_setores()
setor_selecionado = _selecionar_meu_setor(setores)
if setor_selecionado is None:
    st.info("Selecione seu setor acima para ver e registrar demandas.")
    st.stop()

unidade_codigo, unidade_nome = setor_selecionado
metas_pdi_pls = carregar_metas_pdi_pls()

if "demandas_editando_id" not in st.session_state:
    if st.button("+ Nova demanda", type="primary", icon=":material/add:"):
        _iniciar_nova_demanda(unidade_codigo, unidade_nome)
        st.rerun()
else:
    _renderizar_formulario(metas_pdi_pls, unidade_nome)

st.divider()

todas_demandas = carregar_demandas()
demandas_setor = todas_demandas[todas_demandas["unidade_codigo"] == unidade_codigo]
_renderizar_lista(demandas_setor)
