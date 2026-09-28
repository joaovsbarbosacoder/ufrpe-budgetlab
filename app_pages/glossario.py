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
from datetime import date

import streamlit as st

from src import design_tokens
from src import glossario_cadastro
from src.glossario import TEMAS, TermoGlossario, buscar
from src.glossario_cadastro import ErroGlossario
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


def _separar_lista(texto: str) -> list[str]:
    return [item.strip() for item in texto.split(",") if item.strip()]


@st.dialog("Verbete do glossário", width="large")
def _dialogo_verbete(termo_atual: TermoGlossario | None, nomes_existentes: tuple[str, ...]) -> None:
    """Formulário de inclusão (`termo_atual is None`) ou edição de um verbete."""

    edicao = termo_atual is not None
    prefixo = f"glossario_form_{_slug(termo_atual.termo) if termo_atual else 'novo'}"
    st.caption(
        "A primeira frase da definição vira o resumo do cartão; o restante aparece em "
        "“Detalhes e referência”."
    )
    with st.form(f"{prefixo}_formulario", border=False):
        termo = st.text_input("Termo *", value=termo_atual.termo if termo_atual else "")
        sigla = st.text_input("Sigla", value=(termo_atual.sigla or "") if termo_atual else "")
        tema = st.selectbox(
            "Tema *",
            TEMAS,
            index=TEMAS.index(termo_atual.tema) if termo_atual else 0,
        )
        definicao = st.text_area(
            "Definição *", value=termo_atual.definicao if termo_atual else "", height=160
        )
        fonte = st.text_input(
            "Fonte *",
            value=termo_atual.fonte if termo_atual else "",
            help="Manual e página (ex.: MTO, p. 45). Se o conceito não vem do MCASP nem do MTO, "
            "comece por “Contexto do sistema” — isso o classifica fora de “MCASP/MTO”.",
        )
        uso = st.text_input(
            "Uso no BudgetLab",
            value=(termo_atual.uso_no_sistema or "") if termo_atual else "",
        )
        aliases = st.text_input(
            "Também encontrado por (separe por vírgula)",
            value=", ".join(termo_atual.aliases) if termo_atual else "",
        )
        opcoes_ver_tambem = tuple(
            nome
            for nome in nomes_existentes
            if not termo_atual or nome != termo_atual.termo
        )
        ver_tambem = st.multiselect(
            "Ver também",
            opcoes_ver_tambem,
            default=[
                nome for nome in (termo_atual.ver_tambem if termo_atual else ()) if nome in opcoes_ver_tambem
            ],
        )
        enviado = st.form_submit_button(
            "Salvar alterações" if edicao else "Incluir verbete",
            type="primary",
            icon=":material/save:",
        )

    if not enviado:
        return
    dados = {
        "termo": termo,
        "sigla": sigla,
        "tema": tema,
        "definicao": definicao,
        "fonte": fonte,
        "uso_no_sistema": uso,
        "aliases": _separar_lista(aliases),
        "ver_tambem": ver_tambem,
    }
    try:
        if termo_atual:
            ajustados = glossario_cadastro.atualizar(termo_atual.termo, dados)
            mensagem = f"Verbete “{termo.strip()}” atualizado."
            if ajustados:
                mensagem += " Referências em “Ver também” ajustadas em: " + ", ".join(ajustados) + "."
        else:
            glossario_cadastro.incluir(dados)
            mensagem = f"Verbete “{termo.strip()}” incluído."
    except ErroGlossario as erro:
        st.error(str(erro))
        return
    st.session_state["glossario_aviso"] = mensagem
    st.rerun()


@st.dialog("Excluir verbete")
def _dialogo_exclusao(termo: TermoGlossario) -> None:
    st.warning(
        f"Excluir **{termo.termo}** remove o verbete do cadastro. Para voltar à base padrão "
        "do glossário, apague o arquivo `data/glossario/cadastro.json`.",
        icon=":material/warning:",
    )
    if st.button("Excluir definitivamente", type="primary", key=f"glossario_confirma_{_slug(termo.termo)}"):
        try:
            glossario_cadastro.excluir(termo.termo)
        except ErroGlossario as erro:
            st.error(str(erro))
            return
        st.session_state["glossario_aviso"] = f"Verbete “{termo.termo}” excluído."
        st.rerun()


def _renderizar_cartao(termo: TermoGlossario, nomes_existentes: tuple[str, ...]) -> None:
    with st.container(border=True, height="stretch", key=f"glossario_card_{_slug(termo.titulo)}"):
        st.caption(termo.tema)
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.markdown(f"#### {termo.termo}")
            if termo.sigla:
                st.badge(termo.sigla, color="blue")
            if termo.personalizado:
                st.badge("Personalizado", color="green")

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
            if termo.atualizado_em:
                st.caption(f"Atualizado em {date.fromisoformat(termo.atualizado_em):%d/%m/%Y}")

        with st.container(horizontal=True, gap="small"):
            if st.button(
                "Editar",
                icon=":material/edit:",
                key=f"glossario_editar_{_slug(termo.termo)}",
            ):
                _dialogo_verbete(termo, nomes_existentes)
            if st.button(
                "Excluir",
                icon=":material/delete:",
                key=f"glossario_excluir_{_slug(termo.termo)}",
            ):
                _dialogo_exclusao(termo)


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

try:
    GLOSSARIO_VIGENTE = glossario_cadastro.carregar()
except ErroGlossario as erro:
    st.error(str(erro), icon=":material/error:")
    st.stop()

nomes_existentes = tuple(sorted((termo.termo for termo in GLOSSARIO_VIGENTE), key=_slug))

aviso = st.session_state.pop("glossario_aviso", None)
if aviso:
    st.toast(aviso, icon=":material/check_circle:")

quantidade_siglas = sum(termo.sigla is not None for termo in GLOSSARIO_VIGENTE)
quantidade_manuais = sum(_baseada_em_manual(termo) for termo in GLOSSARIO_VIGENTE)

with st.container(border=True, key="glossario_intro"):
    st.markdown("#### Leitura rápida, com rastreabilidade")
    st.write(
        "A primeira frase de cada cartão responde **o que é**. Abra “Detalhes e referência” "
        "para ver o complemento, os conceitos relacionados e a página do manual. Quando uma "
        "sigla pertence ao uso operacional do sistema — e não ao MCASP ou ao MTO — isso fica "
        "declarado na própria fonte."
    )
    metricas = st.columns(3)
    metricas[0].metric("Verbetes", len(GLOSSARIO_VIGENTE))
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

if st.button("Novo verbete", icon=":material/add:", type="primary", key="glossario_novo"):
    _dialogo_verbete(None, nomes_existentes)

with st.expander("Exportar e importar o glossário", icon=":material/swap_vert:"):
    st.caption(
        "Exporte o glossário atual (base + suas edições) para levá-lo a outro computador. "
        "A importação apenas mescla: acrescenta verbetes novos e nunca remove os que já existem."
    )
    st.download_button(
        "Exportar glossário (JSON)",
        data=glossario_cadastro.exportar(),
        file_name="glossario_budgetlab.json",
        mime="application/json",
        icon=":material/download:",
        key="glossario_exportar",
    )
    arquivo_importado = st.file_uploader(
        "Importar glossário (JSON exportado)", type=["json"], key="glossario_importar"
    )
    if arquivo_importado is not None:
        conteudo_importado = arquivo_importado.getvalue()
        try:
            plano = glossario_cadastro.analisar_importacao(conteudo_importado)
        except ErroGlossario as erro:
            st.error(str(erro))
        else:
            st.write(
                f"**{len(plano.novos)}** verbete(s) novo(s) · **{len(plano.iguais)}** já "
                f"idêntico(s) · **{len(plano.conflitos)}** com conteúdo diferente do atual."
            )
            substituir = False
            if plano.conflitos:
                st.caption(
                    "Verbetes com o mesmo termo e conteúdo diferente: "
                    + ", ".join(atual.termo for atual, _ in plano.conflitos)
                )
                substituir = st.checkbox(
                    "Substituir os verbetes atuais pelos do arquivo nesses casos",
                    key="glossario_importar_substituir",
                )
            if plano.novos or (substituir and plano.conflitos):
                if st.button("Confirmar importação", type="primary", key="glossario_importar_confirmar"):
                    try:
                        glossario_cadastro.aplicar_importacao(conteudo_importado, substituir)
                    except ErroGlossario as erro:
                        st.error(str(erro))
                    else:
                        st.session_state["glossario_aviso"] = "Importação concluída."
                        st.rerun()
            else:
                st.info("Nada a importar: o arquivo não traz verbetes novos nem substituições escolhidas.")

resultados = list(buscar(consulta, GLOSSARIO_VIGENTE))
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
                    _renderizar_cartao(termo, nomes_existentes)

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
