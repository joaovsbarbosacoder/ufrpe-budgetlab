"""Glossário navegável de conceitos e siglas usados no BudgetLab.

O conteúdo estático fica em ``src/glossario.py``. As definições baseadas no
MCASP (11ª edição) e no MTO 2026 informam a página consultada; termos
operacionais ou institucionais são identificados como contexto do sistema para
não atribuir aos manuais conceitos que eles não apresentam.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata

import streamlit as st

from src import design_tokens
from src.glossario import GLOSSARIO, TEMAS, TermoGlossario, buscar
from src.ui_theme import render_page_header


def _slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.casefold()).strip("_")


def _baseada_em_manual(termo: TermoGlossario) -> bool:
    return not (
        termo.fonte.startswith("Contexto")
        or termo.fonte.startswith("Portal UFRPE")
        or termo.fonte.startswith("Conceito operacional")
    )


def _renderizar_cartao(termo: TermoGlossario) -> None:
    with st.container(border=True, height="stretch", key=f"glossario_card_{_slug(termo.titulo)}"):
        st.caption(termo.tema)
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.markdown(f"#### {termo.termo}")
            if termo.sigla:
                st.badge(termo.sigla, color="blue")

        st.markdown(termo.resumo)

        if termo.uso_no_sistema:
            st.caption(f":material/visibility: **No BudgetLab:** {termo.uso_no_sistema}")

        with st.expander("Detalhes e referência", icon=":material/menu_book:"):
            if termo.detalhes:
                st.markdown(termo.detalhes)
            else:
                st.caption("A definição essencial está integralmente exibida no cartão.")

            if termo.aliases:
                st.caption("Também encontrado por: " + ", ".join(termo.aliases))
            if termo.ver_tambem:
                st.caption("Ver também: " + ", ".join(termo.ver_tambem))

            st.markdown("**Referência**")
            st.caption(termo.fonte)


st.html(
    f"""
    <style>
    .st-key-glossario_intro [data-testid="stVerticalBlockBorderWrapper"] {{
        background: linear-gradient(135deg, {design_tokens.SURFACE} 0%, {design_tokens.SURFACE_ALT} 100%);
        border-color: {design_tokens.BORDER};
    }}
    .st-key-glossario_controles [data-testid="stVerticalBlockBorderWrapper"] {{
        background: {design_tokens.SURFACE};
    }}
    [class*="st-key-glossario_card_"] [data-testid="stVerticalBlockBorderWrapper"] {{
        min-height: 250px;
    }}
    [class*="st-key-glossario_card_"] h4 {{
        margin: 0;
        line-height: 1.22;
    }}
    [class*="st-key-glossario_card_"] [data-testid="stCaptionContainer"] p {{
        line-height: 1.4;
    }}
    </style>
    """
)

render_page_header(
    "Glossário",
    "Encontre rapidamente os conceitos, siglas e sistemas que aparecem no BudgetLab. "
    "Cada verbete separa a explicação essencial, o uso no sistema e a referência de origem.",
    "Referência",
)

quantidade_siglas = sum(termo.sigla is not None for termo in GLOSSARIO)
quantidade_manuais = sum(_baseada_em_manual(termo) for termo in GLOSSARIO)

with st.container(border=True, key="glossario_intro"):
    st.markdown("#### Leitura rápida, com rastreabilidade")
    st.write(
        "A primeira frase de cada cartão responde **o que é**. Abra “Detalhes e referência” "
        "para ver o complemento, os conceitos relacionados e a página do manual. Quando uma "
        "sigla pertence ao uso operacional do sistema — e não ao MCASP ou ao MTO — isso fica "
        "declarado na própria fonte."
    )
    metricas = st.columns(3)
    metricas[0].metric("Verbetes", len(GLOSSARIO))
    metricas[1].metric("Siglas explicadas", quantidade_siglas)
    metricas[2].metric("Baseados nos manuais", quantidade_manuais)

with st.container(border=True, key="glossario_controles"):
    coluna_busca, coluna_tema = st.columns([1.7, 1])
    with coluna_busca:
        consulta = st.text_input(
            "Buscar no glossário",
            placeholder="Ex.: PTRES, PF, dotação, restos a pagar, SIAFI...",
            icon=":material/search:",
            key="glossario_busca",
        )
    with coluna_tema:
        tema_selecionado = st.selectbox(
            "Tema",
            ("Todos os temas",) + TEMAS,
            key="glossario_tema",
        )

    origem = st.segmented_control(
        "Origem da definição",
        ("Todas", "MCASP/MTO", "Contexto do sistema"),
        default="Todas",
        key="glossario_origem",
    )

resultados = list(buscar(consulta))
if tema_selecionado != "Todos os temas":
    resultados = [termo for termo in resultados if termo.tema == tema_selecionado]
if origem == "MCASP/MTO":
    resultados = [termo for termo in resultados if _baseada_em_manual(termo)]
elif origem == "Contexto do sistema":
    resultados = [termo for termo in resultados if not _baseada_em_manual(termo)]
resultados.sort(key=lambda termo: _slug(termo.termo))

if not resultados:
    st.warning(
        "Nenhum verbete corresponde à busca e aos filtros atuais. Tente uma sigla, uma "
        "palavra parcial ou selecione outra origem.",
        icon=":material/search_off:",
    )
else:
    filtro_ativo = bool(consulta.strip()) or tema_selecionado != "Todos os temas" or origem != "Todas"
    contexto_resultado = " no recorte atual" if filtro_ativo else " no glossário"
    st.markdown(f"### {len(resultados)} verbete(s){contexto_resultado}")
    st.caption("Os resultados são apresentados em ordem alfabética.")

    itens_por_pagina = 10
    total_paginas = max(1, math.ceil(len(resultados) / itens_por_pagina))
    area_cartoes = st.container()

    if total_paginas > 1:
        identidade_filtro = hashlib.sha1(
            f"{consulta}|{tema_selecionado}|{origem}".encode("utf-8")
        ).hexdigest()[:10]
        with st.container(horizontal_alignment="right"):
            pagina = st.pagination(
                total_paginas,
                key=f"glossario_pagina_{identidade_filtro}",
                max_visible_pages=7,
            )
    else:
        pagina = 1

    inicio = (pagina - 1) * itens_por_pagina
    pagina_atual = resultados[inicio : inicio + itens_por_pagina]

    with area_cartoes:
        for indice in range(0, len(pagina_atual), 2):
            colunas = st.columns(2)
            for coluna, termo in zip(colunas, pagina_atual[indice : indice + 2], strict=False):
                with coluna:
                    _renderizar_cartao(termo)

    if total_paginas > 1:
        st.caption(
            f"Página {pagina} de {total_paginas} · exibindo {inicio + 1}–"
            f"{min(inicio + itens_por_pagina, len(resultados))} de {len(resultados)} verbetes."
        )

st.caption(
    "Fontes principais: MCASP — Manual de Contabilidade Aplicada ao Setor Público "
    "(STN, 11ª edição) e MTO — Manual Técnico de Orçamento 2026 (SOF/MPO, 7ª versão). "
    "As definições são sínteses para consulta; o texto integral está nas páginas indicadas."
)
