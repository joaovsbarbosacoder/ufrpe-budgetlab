"""Visão conjunta, agregada e rastreável de Dotação e Execução."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dotacao_analysis import DOTACAO_ANALYSIS_SESSION_KEY, ValidatedDotacaoDataset
from src.execucao_analysis import EXECUCAO_ANALYSIS_SESSION_KEY, ValidatedExecucaoDataset
from src.visao_orcamentaria import (
    COMMON_DIMENSIONS,
    build_common_filter_options,
    build_visao_orcamentaria,
)


def _format_currency(value: object) -> str:
    if pd.isna(value):
        return "Valor nulo"
    return "R$ " + f"{float(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


st.title("Visão Orçamentária")
st.write(
    "Recorte conjunto de bases validadas, com cada indicador calculado "
    "separadamente em sua origem. Não há combinação direta, saldo ou "
    "identidade entre as medidas."
)

dotacao_dataset = st.session_state.get(DOTACAO_ANALYSIS_SESSION_KEY)
execucao_dataset = st.session_state.get(EXECUCAO_ANALYSIS_SESSION_KEY)
if not isinstance(dotacao_dataset, ValidatedDotacaoDataset) or not isinstance(execucao_dataset, ValidatedExecucaoDataset):
    st.info("Carregue uma base validada de Dotação e uma de Execução na página Importação de Bases.")
    st.stop()

with st.container(horizontal=True):
    st.metric("Dotação validada", dotacao_dataset.filename, border=True)
    st.metric("Execução validada", execucao_dataset.filename, border=True)

options = build_common_filter_options(dotacao_dataset.normalized_data, execucao_dataset.normalized_data)
labels = {
    "iduso": "IDUSO",
    "resultado_primario": "Resultado Primário",
    "acao_governo": "Ação Governo",
    "plano_orcamentario": "Plano Orçamentário",
    "grupo_despesa": "Grupo de Despesa",
    "fonte_recursos_detalhada": "Fonte de Recursos Detalhada",
    "ptres": "PTRES",
}
source_key = f"{dotacao_dataset.source_sha256[:8]}_{execucao_dataset.source_sha256[:8]}"
with st.sidebar:
    st.header("Filtros comuns")
    st.caption("As opções são a união dos códigos presentes nas duas bases.")
    with st.form(f"visao_orcamentaria_filters_{source_key}"):
        selections = {
            name: st.multiselect(labels[name], values, key=f"visao_{name}_{source_key}", placeholder="Todos")
            for name, values in options.items()
        }
        st.form_submit_button("Aplicar filtros", icon=":material/filter_alt:", type="primary")

result = build_visao_orcamentaria(dotacao_dataset, execucao_dataset, selections)
with st.container(horizontal=True):
    for _, indicator in result.indicadores.iterrows():
        value = "Sem valor" if indicator["quantidade_registros"] == 0 else _format_currency(indicator["valor_movimento_liquido"])
        st.metric(
            indicator["indicador"],
            value,
            border=True,
            help=f"Origem: {indicator['origem']}",
        )

st.subheader("Resumo dos indicadores")
resumo = result.indicadores.loc[:, ["indicador", "origem", "valor_movimento_liquido"]].rename(
    columns={"indicador": "Indicador", "origem": "Origem", "valor_movimento_liquido": "Valor"}
)
st.dataframe(
    resumo,
    hide_index=True,
    column_config={"Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f")},
    key=f"visao_resumo_{source_key}",
)
