"""Página inicial do UFRPE BudgetLab."""

import streamlit as st

from src.design_tokens import NEGATIVE, WARNING
from src.prazos_orcamentarios import carregar_prazos, prazos_com_criticidade
from src.ui_theme import render_page_header

render_page_header(
    "UFRPE BudgetLab",
    "Ambiente institucional para gestão e análise orçamentária.",
    "Gestão orçamentária",
)


def _render_card_prazos() -> None:
    """Card só aparece quando há prazo vencido ou dentro da antecedência de alerta (pedido
    explícito) — mesmo princípio de "só aparece o que precisa de ação" de
    `app_pages/alertas_gerenciais.py`. Lê o mesmo cadastro/classificação do Painel de Prazos
    Orçamentários (`src/prazos_orcamentarios.py`), sem duplicar a regra aqui."""

    prazos = prazos_com_criticidade(carregar_prazos())
    if prazos.empty:
        return
    pendentes = prazos[~prazos["concluido"]]
    vencidos = int((pendentes["criticidade"] == "Vencido").sum())
    em_alerta = int((pendentes["criticidade"] == "Em alerta").sum())
    if not vencidos and not em_alerta:
        return

    cor = NEGATIVE if vencidos else WARNING
    with st.container(border=True):
        st.markdown(f"<span style='color:{cor};font-weight:600'>⏰ Prazos Orçamentários</span>", unsafe_allow_html=True)
        partes = []
        if vencidos:
            partes.append(f"**{vencidos}** vencido(s)")
        if em_alerta:
            partes.append(f"**{em_alerta}** em alerta")
        st.markdown(" · ".join(partes))
        st.page_link("app_pages/painel_prazos.py", label="Ver painel de prazos", icon=":material/arrow_forward:")


_render_card_prazos()

with st.container(border=True):
    st.subheader("Visão geral")
    st.write(
        "Cada base tem importação própria e versionada, com manifesto e "
        "rastreabilidade completa até a célula de origem. A reimportação "
        "acontece na página \"Atualizar Planilhas\" (menu Administração)."
    )

with st.container(border=True):
    st.subheader("Módulos disponíveis")
    st.markdown(
        "- Dotação Orçamentária (Dotação Anual)\n"
        "- Painel por Ação de Governo (Dotação Anual)\n"
        "- Execução Orçamentária (Execução Anual)"
    )

st.caption("As funcionalidades futuras serão habilitadas conforme suas regras de negócio forem confirmadas.")
