"""Glossário de termos orçamentários e contábeis do BudgetLab.

Conteúdo estático (ver `src/glossario.py`), condensado a partir do MCASP
(Manual de Contabilidade Aplicada ao Setor Público, STN, 11ª Edição) e do
MTO (Manual Técnico de Orçamento 2026, SOF/MPO, 7ª Versão). Não lê nenhuma
base do projeto — é só um guia de referência para quem usa o sistema.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from src.glossario import GLOSSARIO, TEMAS, TermoGlossario, buscar, termos_por_tema
from src.ui_theme import render_page_header

render_page_header(
    "Glossário",
    "Conceitos orçamentários e contábeis usados no sistema, com a definição "
    "condensada do MCASP e do MTO 2026 e a página de origem de cada uma.",
    "Referência",
)

st.info(
    "As definições aqui são um resumo dos manuais oficiais, não uma transcrição "
    "literal — para o texto integral, consulte a página indicada em cada verbete. "
    "Alguns códigos do dia a dia do SIAFI (UG, UGR, PI) não têm definição formal "
    "no MCASP nem no MTO; nesses casos o campo de fonte diz isso explicitamente.",
    icon=":material/menu_book:",
)

consulta = st.text_input(
    "Buscar termo",
    placeholder="Ex.: PTRES, empenho, restos a pagar, RP6...",
    label_visibility="collapsed",
)

resultados = buscar(consulta)
filtrando = bool(consulta.strip())

if filtrando:
    if resultados:
        st.caption(
            f"{len(resultados)} de {len(GLOSSARIO)} termo(s) encontrados para "
            f"“{consulta.strip()}”."
        )
    else:
        st.warning(
            f"Nenhum termo encontrado para “{consulta.strip()}”. Tente outra palavra "
            "ou parte do nome (a busca ignora acentos e maiúsculas/minúsculas).",
            icon=":material/search_off:",
        )

resultados_por_termo = {termo.termo: termo for termo in resultados}


def _renderiza_termo(termo: TermoGlossario) -> None:
    with st.container(border=True):
        titulo = escape(termo.termo)
        if termo.sigla:
            titulo += f' <span style="color:#526584;font-weight:600;">({escape(termo.sigla)})</span>'
        st.markdown(f"##### {titulo}", unsafe_allow_html=True)
        st.markdown(termo.definicao)
        if termo.ver_tambem:
            st.caption("Ver também: " + ", ".join(termo.ver_tambem))
        st.caption(f":material/book_4: Fonte: {termo.fonte}")


if filtrando:
    for termo in resultados:
        _renderiza_termo(termo)
else:
    for tema in TEMAS:
        termos_do_tema = termos_por_tema()[tema]
        if not termos_do_tema:
            continue
        with st.expander(f"{tema} ({len(termos_do_tema)})", expanded=False):
            for termo in termos_do_tema:
                _renderiza_termo(termo)

st.caption(
    f"{len(GLOSSARIO)} termos ao todo, organizados em {len(TEMAS)} temas. "
    "Fontes: MCASP — Manual de Contabilidade Aplicada ao Setor Público (STN, "
    "11ª Edição) e MTO — Manual Técnico de Orçamento 2026 (SOF/MPO, 7ª Versão)."
)
