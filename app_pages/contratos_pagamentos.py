"""Pagamentos de Contratos — consolidação mensal, deduplicação e conciliação.

Adaptação do handoff de design (`painel_pagamentos.py`: cartão por lançamento, linha do
tempo de pagamento vs. média mensal, medição de referência de empenho) para o leitor e os
tokens reais deste projeto — não `data_loader_pagamentos.py`/`design_tokens.py` do pacote de
handoff.

Fonte: abas "{Mês} - Planilha - {ano}" da planilha "CONTRATOS - CONTROLE - 2020" (mantida
manualmente) — `src/contratos_pagamentos.py`, validado contra a extração de 15/08/2026.

Diferenças deliberadas em relação ao handoff:
  * Leitor real e testado (`src/contratos_pagamentos.py`, com fixture congelada em
    `tests/fixtures/contratos_pagamentos_2026-08-15.xlsx`) — o `data_loader_pagamentos.py`
    do handoff nunca foi validado contra a planilha real.
  * Escopo só 2026 (pedido explícito, decidido depois de investigar): o layout de colunas
    muda entre anos (2023-2025 usam "DH" onde 2026 usa "NP"/coluna sem nome; a aba de 2023
    tem estrutura bem diferente, sem "PROCESSO"). Cobrir vários anos exigiria reconciliar
    esses layouts — fora de escopo por ora.
  * NP/NS/TED (números de nota de pagamento/nota de sistema/TED) ficam de fora do esquema
    (pedido explícito: "desconsidere a necessidade dos documentos de OB e NP ou
    congêneres... no máximo, se apegue ao número do empenho") — só `empenho` é mantido como
    identificador de documento.
  * `CTO` (contrato) tem uma corrupção conhecida na origem — o Excel reinterpretou números de
    contrato no formato "MM/AAAA" como data (sempre com dia 1, 81 células nas 8 abas de 2026
    conferidas). `src/contratos_pagamentos.py::_normalizar_contrato` recupera o valor
    original a partir do mês/ano da data, em vez de descartar essas linhas.
  * Os tokens de cor/tipografia são os reais do projeto (`src/design_tokens.py`).
  * "Medição a referência de empenho" (comparação do mês medido contra a média mensal do
    próprio contrato) é a mesma métrica do handoff — não substitui nem se confunde com a
    necessidade de reforço de empenho de `src/necessidade_empenho.py` (baseada em Contratos
    Contínuos/execução, não em pagamentos realizados).
  * Um cartão por fornecedor/credor, não por pagamento (pedido explícito) — cada cartão traz
    um cabeçalho agregado (nome, CNPJ, nº de contratos, valor total não-duplicado) seguido dos
    pagamentos do fornecedor SEGMENTADOS POR CONTRATO (pedido explícito — não é uma lista
    única sem ordem: cada contrato tem seu próprio subtotal/contagem e sua própria mini-tabela
    de Mês/Valor/Empenho/Status, contrato de maior valor primeiro), sem esconder nenhum
    pagamento atrás de outro clique ("de modo a exibir todos os pagamentos encontrados nas
    planilhas"). Substitui o antigo cartão por lançamento do handoff; a antiga
    `_render_timeline` (comparação por cartão contra a média do contrato) foi removida por não
    fazer sentido agrupada por fornecedor — essa comparação já existe, por contrato, em
    "Medição à referência de empenho" mais abaixo na página.
  * Filtro "Ano de referência (empenho)" (pedido explícito): o campo `EMPENHO` cita o ano do
    empenho no formato "XXXXNEYYYYYY"/"XXNEYYYYYY" — `anos_do_empenho`/a coluna
    `anos_empenho` de `src/contratos_pagamentos.py` extraem esse ano. O filtro esconde, por
    padrão (ano = exercício corrente), pagamentos cujo empenho é de exercício anterior mesmo
    aparecendo numa aba mensal do ano corrente (ex.: nota de 2025 lançada numa aba de 2026);
    pagamentos sem ano de empenho reconhecível permanecem sempre visíveis, independente do
    filtro escolhido.
  * Checkbox "Somente empenhos relacionados a Contratos Contínuos" (pedido explícito, ligado
    por padrão quando a planilha de Contratos Contínuos está disponível) — casa o(s) NE(s)
    completo(s) do pagamento (`nes_do_empenho`/coluna `nes_empenho` de
    `src/contratos_pagamentos.py`) contra `ne_curta` de `src/contratos_continuos.py`. Ao
    contrário do filtro de ano de referência, aqui um pagamento sem NE explícito reconhecível
    NÃO fica visível por padrão — sem NE não dá para confirmar a relação, e o pedido foi
    justamente restringir a apresentação aos empenhos já relacionados, não manter tudo visível
    por incerteza.
  * Colunas "Mês pagamento" e "Mês competência" na mini-tabela de cada contrato (pedido
    explícito) — a primeira é o mês da própria aba onde o lançamento está (`mes_pagamento`);
    a segunda vem do texto livre de `COMPETENCIA` (`mes_competencia`, ver
    `mes_competencia_de` em `src/contratos_pagamentos.py`), incluindo o caso de período
    fracionado ("DD/MM/AAAA A DD/MM/AAAA"), onde o mês escolhido é o que tem mais dias
    dentro do período, não o de início nem o de fim. "—" quando o texto de competência não é
    reconhecível (formato livre demais, ex. "REPACTUAÇÃO JAN A MAI/25") — nunca um palpite.
  * Seção "Conciliação com Execução Anual" (pedido explícito, para checar se um pagamento
    marcado "Duplicado" é mesmo um erro ou um pagamento legítimo): compara, por NE, a soma
    desta planilha (`soma_por_ne` em `src/contratos_pagamentos.py`, todas as linhas — inclusive
    duplicadas) contra o valor oficial pago segundo a Execução Anual
    (`indice_valor_pago_por_ne_curta` em `src/execucao_anual.py`). Só sinaliza a NE para
    revisão manual quando os totais não batem — NÃO decide sozinha qual base está certa nem
    altera o status "Duplicado" automaticamente, porque qualquer uma das duas planilhas
    (mantidas de forma independente) pode estar mais atualizada que a outra num dado momento;
    decidir isso automaticamente arriscaria "consertar" um status que já estava certo.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.contratos_continuos import ler_contratos_continuos
from src.contratos_pagamentos import MESES_ORDEM, ler_pagamentos, serie_por_contrato, soma_por_ne
from src.design_tokens import ACCENT_STRONG, BORDER, FONT_HEADING, NEGATIVE, POSITIVE, SURFACE, TEXT_MUTED
from src.execucao_anual import agregar_por_ne, indice_valor_pago_por_ne_curta
from src.importacao_execucao import DIRETORIO_MANIFESTOS_PADRAO, NOME_PONTEIRO, Manifesto, carregar_atual
from src.ui_theme import render_page_header

DIRETORIO_DADOS_BRUTOS = Path("data/raw")
CAMINHO_BASE = DIRETORIO_DADOS_BRUTOS / "CONTRATOS - CONTROLE 2020 - Pagamentos.xlsx"
CAMINHO_CONTRATOS_CONTINUOS = DIRETORIO_DADOS_BRUTOS / "SERVIÇOS CONTÍNUOS - 2026 - AGO A DEZ.xlsm"
ANO = 2026

STATUS_COR = {"Publicado": POSITIVE, "Alerta": ACCENT_STRONG, "Bloqueado": NEGATIVE, "Duplicado": TEXT_MUTED}


@st.cache_data(show_spinner="Lendo os pagamentos de contratos...")
def _cached_leitura(caminho: str, mtime: float, ano: int) -> pd.DataFrame:
    """`mtime` só participa da chave de cache — força reler se o arquivo mudar."""

    return ler_pagamentos(caminho, ano)


@st.cache_data(show_spinner=False)
def _cached_nes_continuos(caminho: str, mtime: float) -> set[str]:
    """NEs (formato "AAAANEnnnnnn") de todos os contratos contínuos, usados para restringir a
    apresentação de pagamentos aos empenhos já relacionados nessa aba (pedido explícito)."""

    return set(ler_contratos_continuos(caminho)["ne_curta"].dropna().unique())


@st.cache_data(show_spinner=False)
def _cached_valor_pago_execucao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.Series:
    """Valor oficial pago por NE (Execução Anual), indexado pela NE curta — base da
    reconciliação da seção "Conciliação com Execução Anual" mais abaixo na página.
    `caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache — `carregar_atual` já
    devolve a base composta por ano (ver `src/importacao_execucao.py`)."""

    return indice_valor_pago_por_ne_curta(agregar_por_ne(carregar_atual()))


def _brl(v: object) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    negativo = v < 0
    texto = "R$ " + f"{abs(round(v)):,.0f}".replace(",", ".")
    return ("−" if negativo else "") + texto


def _ou_vazio(valor: object) -> str:
    return "" if pd.isna(valor) else str(valor)


def _fmt_mes(valor: object) -> str:
    """"mmm/aa" a partir de um Timestamp truncado ao mês (`mes_pagamento`/`mes_competencia`
    de `src/contratos_pagamentos.py`) — abreviação em português (MESES_ORDEM), não a de
    `strftime("%b")`, que sai em inglês no locale padrão desta máquina (ex. "Aug", não "Ago")."""

    if valor is None or pd.isna(valor):
        return "—"
    return f"{MESES_ORDEM[valor.month - 1][:3]}/{valor.year % 100:02d}"


def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .pg-kicker {{ font-family: {FONT_HEADING}; font-size: 10px; letter-spacing: .16em; text-transform: uppercase; color: {TEXT_MUTED}; }}
        .pg-badge {{ display: inline-block; font-family: {FONT_HEADING}; font-size: 9.5px; letter-spacing: .05em;
          text-transform: uppercase; padding: 2px 8px; border-radius: 3px; margin: 2px 4px 0 0; }}
        .pg-col-label {{ font-size: 9.5px; color: {TEXT_MUTED}; }}
        .st-key-pg_cards div[data-testid="stVerticalBlockBorderWrapper"] {{ border: 1px solid {BORDER} !important; border-radius: 8px; background: {SURFACE}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _badge(texto: str, cor: str) -> str:
    return f"<span class='pg-badge' style='background:{cor}22;color:{cor}'>{texto}</span>"


def _render_card_fornecedor(fornecedor: str, grupo: pd.DataFrame) -> None:
    """Um cartão por credor (fornecedor), não por pagamento — pedido explícito, para reduzir
    a quantidade de cartões (~380 pagamentos viravam ~380 cartões; agora um por fornecedor,
    ~33 no total) sem esconder nenhum pagamento: todos os lançamentos do fornecedor aparecem
    listados dentro do próprio cartão, não atrás de mais um clique."""

    with st.container(border=True):
        cnpjs = grupo["cnpj"].dropna()
        cnpj = cnpjs.iloc[0] if len(cnpjs) else None
        principais = grupo[~grupo["duplicado"]]

        c1, c2 = st.columns([4, 1.4])
        c1.markdown(
            f"<div style='font-family:{FONT_HEADING};font-size:15px'>{_ou_vazio(fornecedor) or '(sem nome)'}</div>"
            f"<div style='font-size:12.5px;color:{TEXT_MUTED}'>CNPJ: {_ou_vazio(cnpj) or '—'} · "
            f"{grupo['contrato'].nunique()} contrato(s)</div>",
            unsafe_allow_html=True,
        )
        c2.markdown(
            f"<div style='text-align:right;font-size:15px;font-weight:600'>{_brl(principais['valor'].sum())}</div>"
            f"<div style='text-align:right;font-size:11px;color:{TEXT_MUTED}'>{len(grupo)} pagamento(s)</div>",
            unsafe_allow_html=True,
        )

        contagem_status = grupo["status"].value_counts()
        st.markdown(
            "".join(
                _badge(f"{qtd} {status}", STATUS_COR.get(status, TEXT_MUTED))
                for status, qtd in contagem_status.items()
            ),
            unsafe_allow_html=True,
        )

        # segmentado por contrato dentro do cartão (pedido explícito) — não é mais uma lista
        # única sem ordem; contrato com maior valor principal pago primeiro.
        totais_por_contrato = grupo[~grupo["duplicado"]].groupby("contrato")["valor"].sum()
        contratos_do_grupo = sorted(
            grupo["contrato"].unique(), key=lambda c: -totais_por_contrato.get(c, 0.0)
        )
        for i, numero_contrato in enumerate(contratos_do_grupo):
            linhas_contrato = grupo[grupo["contrato"] == numero_contrato].sort_values("mes_ordem")
            if i > 0:
                st.markdown("<hr style='margin:6px 0;border-color:" + BORDER + "22'>", unsafe_allow_html=True)
            ch1, ch2 = st.columns([3, 1.4])
            ch1.markdown(
                f"<span class='pg-col-label' style='font-size:11.5px'>Contrato {numero_contrato}</span>",
                unsafe_allow_html=True,
            )
            ch2.markdown(
                f"<div style='text-align:right;font-size:11.5px;color:{TEXT_MUTED}'>"
                f"{_brl(totais_por_contrato.get(numero_contrato, 0.0))} · {len(linhas_contrato)} pagamento(s)</div>",
                unsafe_allow_html=True,
            )
            cabecalho = st.columns([1, 1, 1, 1.3, 0.9])
            for col, rotulo in zip(cabecalho, ["Mês pagamento", "Mês competência", "Valor", "Empenho", "Status"]):
                col.markdown(f"<span class='pg-col-label'>{rotulo}</span>", unsafe_allow_html=True)
            for _, linha in linhas_contrato.iterrows():
                c = st.columns([1, 1, 1, 1.3, 0.9])
                c[0].write(_fmt_mes(linha["mes_pagamento"]))
                c[1].write(_fmt_mes(linha["mes_competencia"]))
                c[2].write(_brl(linha["valor"]))
                c[3].write(_ou_vazio(linha["empenho"]) or "—")
                cor = STATUS_COR.get(linha["status"], TEXT_MUTED)
                c[4].markdown(_badge(linha["status"], cor), unsafe_allow_html=True)


def _render_conciliacao_execucao(pagamentos: pd.DataFrame, valor_pago_execucao: pd.Series) -> None:
    """Compara, por NE, quanto esta planilha de pagamentos registra (`soma_por_ne`, todas as
    linhas — inclusive as marcadas duplicado) contra o valor oficial pago segundo a Execução
    Anual (pedido explícito, para checar se uma linha marcada "Duplicado" é mesmo um erro de
    duplicidade ou um pagamento legítimo).

    Deliberadamente NÃO decide sozinha se a linha "Duplicado" está certa ou errada, nem altera
    esse status automaticamente: qualquer uma das duas bases pode estar desatualizada em
    relação à outra num dado momento (ex.: a Execução Anual já reflete um pagamento que esta
    planilha, mantida manualmente, ainda não lançou, ou vice-versa) — decidir isso sozinho
    correria o risco de "consertar" um status que na verdade estava certo. Em vez disso, só
    sinaliza a NE para revisão humana quando os dois totais não batem (diferença > R$ 0,01)."""

    soma_planilha = soma_por_ne(pagamentos)
    if soma_planilha.empty or valor_pago_execucao.empty:
        st.info("Sem NEs com um único empenho reconhecido em comum entre as duas bases para conciliar.")
        return

    cruzado = pd.DataFrame({"soma_planilha": soma_planilha}).join(
        valor_pago_execucao.rename("valor_pago_execucao"), how="inner"
    )
    if cruzado.empty:
        st.info("Nenhuma NE em comum entre os pagamentos e a Execução Anual.")
        return

    cruzado["diferenca"] = cruzado["soma_planilha"] - cruzado["valor_pago_execucao"]
    cruzado["_diverge"] = cruzado["diferenca"].abs() > 0.01
    divergentes = cruzado[cruzado["_diverge"]].sort_values("diferenca", key=lambda s: s.abs(), ascending=False)

    st.caption(
        f"{len(cruzado)} NEs em comum entre esta planilha e a Execução Anual · "
        f"{len(divergentes)} com diferença entre o total registrado aqui e o valor oficial pago "
        "(diferença maior que R$ 0,01)"
    )
    st.caption(
        "Não decide sozinho qual base está certa nem altera o status \"Duplicado\" automaticamente "
        "— qualquer uma das duas planilhas pode estar mais atualizada que a outra num dado momento. "
        "Serve para apontar qual NE revisar manualmente."
    )

    if divergentes.empty:
        st.markdown(_badge("Nenhuma divergência acima de R$ 0,01", POSITIVE), unsafe_allow_html=True)
        return

    larguras = [1.6, 1.3, 1.3, 1.3]
    with st.container(key="pg_conciliacao"):
        header = st.columns(larguras)
        for col, label in zip(header, ["NE", "Soma nesta planilha", "Valor pago (Execução Anual)", "Diferença"]):
            col.markdown(f"<span class='pg-col-label'>{label}</span>", unsafe_allow_html=True)
        for ne, linha in divergentes.iterrows():
            c = st.columns(larguras)
            c[0].write(ne)
            c[1].write(_brl(linha["soma_planilha"]))
            c[2].write(_brl(linha["valor_pago_execucao"]))
            cor = NEGATIVE if linha["diferenca"] > 0 else ACCENT_STRONG
            c[3].markdown(
                f"<span style='color:{cor};font-weight:600'>{_brl(linha['diferenca'])}</span>",
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------- página
render_page_header(
    "Pagamentos de Contratos",
    f"Consolidação mensal, deduplicação e conciliação — exercício {ANO}",
    "Contratos",
)
_inject_css()

if not CAMINHO_BASE.exists():
    st.info(
        f"A planilha de pagamentos de contratos não foi encontrada em '{CAMINHO_BASE}'. "
        "Copie a extração atual para essa pasta antes de usar esta página."
    )
    st.stop()

mtime = CAMINHO_BASE.stat().st_mtime
try:
    pagamentos = _cached_leitura(str(CAMINHO_BASE), mtime, ANO)
except Exception as error:
    st.error(f"Não foi possível ler os dados: {error}")
    st.stop()

# usado pelo filtro "Somente empenhos relacionados a Contratos Contínuos" mais abaixo — vazio
# (não erro) quando a planilha de Contratos Contínuos não está disponível, e o filtro some.
if CAMINHO_CONTRATOS_CONTINUOS.exists():
    nes_continuos = _cached_nes_continuos(
        str(CAMINHO_CONTRATOS_CONTINUOS), CAMINHO_CONTRATOS_CONTINUOS.stat().st_mtime
    )
else:
    nes_continuos = set()

# usado pela seção "Conciliação com Execução Anual" mais abaixo — vazio (não erro) quando
# nenhuma Execução Anual foi importada ainda, e a seção mostra um aviso em vez da comparação.
manifesto_execucao = Manifesto.atual()
if manifesto_execucao is not None:
    caminho_ponteiro_execucao = DIRETORIO_MANIFESTOS_PADRAO / NOME_PONTEIRO
    valor_pago_execucao = _cached_valor_pago_execucao(
        str(caminho_ponteiro_execucao), caminho_ponteiro_execucao.stat().st_mtime
    )
else:
    valor_pago_execucao = pd.Series(dtype=float)

principais = pagamentos[~pagamentos["duplicado"]]

k = st.columns(5)
publicados = principais[principais["status"] == "Publicado"]
k[0].metric("Valor publicado", _brl(publicados["valor"].sum()), f"{len(publicados)} pagamentos")
k[1].metric("Pagamentos principais", len(principais), f"de {len(pagamentos)} linhas brutas")
k[2].metric("Contratos distintos", pagamentos["contrato"].nunique())
k[3].metric("Fornecedores distintos", pagamentos["cnpj"].nunique())
bloqueados = pagamentos[pagamentos["status"] == "Bloqueado"]
k[4].metric(
    "Valor bloqueado", _brl(bloqueados["valor"].sum()),
    f"{int(pagamentos['duplicado'].sum())} duplicado(s) em auditoria",
)

fc = st.columns([3, 1, 1, 1.2])
busca = fc[0].text_input(
    "Buscar", placeholder="Buscar por contrato, fornecedor, CNPJ, empenho, processo…", label_visibility="collapsed"
)
mes_sel = fc[1].selectbox("Mês", ["Todos"] + [m for m in MESES_ORDEM if m in pagamentos["mes_planilha"].unique()])
status_sel = fc[2].selectbox("Qualidade", ["Todos", "Publicado", "Alerta", "Bloqueado", "Duplicado"])

# "Ano de referência" filtra pelo ano citado no EMPENHO ("XXXX" de "XXXXNEYYYYYY", 2 ou 4
# dígitos — ver src/contratos_pagamentos.py::anos_do_empenho), não pelo mês da aba onde o
# pagamento foi lançado: um pagamento na aba de 2026 pode ser de um empenho de 2025 (pedido
# explícito — isso não interessa por padrão). Pagamentos cujo empenho não citou nenhum ano
# reconhecível continuam visíveis em qualquer filtro (não escondemos por falta de dado).
anos_encontrados = sorted({ano for conjunto in pagamentos["anos_empenho"] for ano in conjunto})
opcoes_ano_ref = ["Todos"] + [str(a) for a in anos_encontrados]
indice_padrao = opcoes_ano_ref.index(str(ANO)) if str(ANO) in opcoes_ano_ref else 0
ano_ref_sel = fc[3].selectbox("Ano de referência (empenho)", opcoes_ano_ref, index=indice_padrao)

# restringe a apresentação aos empenhos já relacionados na aba de Contratos Contínuos (pedido
# explícito) — casamento por NE completo (`nes_do_empenho`/`ne_curta`, ver
# src/contratos_pagamentos.py). Pagamento sem NE explícito reconhecível não pode ser
# confirmado como relacionado, então fica de fora quando o filtro está ativo.
somente_relacionados = True
if nes_continuos:
    somente_relacionados = st.checkbox(
        "Somente empenhos relacionados a Contratos Contínuos",
        value=True,
        help="Restringe a lista aos pagamentos cujo empenho casa com uma NE já cadastrada na aba Contratos Contínuos.",
    )

filtrado = pagamentos
if busca:
    alvo = busca.lower()
    campos = ["contrato", "fornecedor", "cnpj", "empenho", "processo"]
    mascara = filtrado[campos].astype(str).apply(lambda col: col.str.lower().str.contains(alvo, na=False))
    filtrado = filtrado[mascara.any(axis=1)]
if mes_sel != "Todos":
    filtrado = filtrado[filtrado["mes_planilha"] == mes_sel]
if status_sel != "Todos":
    filtrado = filtrado[filtrado["status"] == status_sel]
if ano_ref_sel != "Todos":
    ano_ref_int = int(ano_ref_sel)
    filtrado = filtrado[filtrado["anos_empenho"].apply(lambda anos: not anos or ano_ref_int in anos)]
if somente_relacionados and nes_continuos:
    filtrado = filtrado[filtrado["nes_empenho"].apply(lambda nes: bool(nes & nes_continuos))]

st.caption(
    f"{len(filtrado)} de {len(pagamentos)} pagamentos, agrupados em "
    f"{filtrado['fornecedor'].nunique()} fornecedor(es) · duplicidades não são somadas nos KPIs"
)

with st.container(key="pg_cards"):
    if filtrado.empty:
        st.markdown("<div class='pg-kicker'>Nenhum pagamento encontrado.</div>", unsafe_allow_html=True)
    else:
        # "(sem nome)" no lugar de NaN evita comparação de NaN como chave de agrupamento
        # (NaN nunca é igual a si mesmo — quebraria o agrupamento/ordenação por fornecedor).
        agrupavel = filtrado.copy()
        agrupavel["fornecedor"] = agrupavel["fornecedor"].fillna("(sem nome)")
        # maior valor pago primeiro — mais útil que ordem alfabética ou ordem de aparição; um
        # fornecedor só com pagamentos duplicados (sem nenhum principal) entra com total 0,
        # não some da lista.
        totais_principais = agrupavel[~agrupavel["duplicado"]].groupby("fornecedor")["valor"].sum()
        ordem_fornecedores = sorted(
            agrupavel["fornecedor"].unique(), key=lambda f: -totais_principais.get(f, 0.0)
        )
        for fornecedor in ordem_fornecedores:
            grupo = agrupavel[agrupavel["fornecedor"] == fornecedor]
            _render_card_fornecedor(fornecedor, grupo)

st.markdown("#### Conciliação com Execução Anual")
if manifesto_execucao is None:
    st.info(
        "Nenhuma base de Execução Anual foi importada ainda — é dela que vem o valor oficial "
        "pago por NE, usado para checar as NEs com pagamentos marcados \"Duplicado\"."
    )
else:
    _render_conciliacao_execucao(pagamentos, valor_pago_execucao)

st.markdown("#### Medição à referência de empenho")
st.caption("Referência mensal calculada como a média mensal do próprio contrato — ainda não homologada.")
contratos_disponiveis = sorted(pagamentos["contrato"].unique().tolist())
cc = st.columns(2)
contrato_sel = cc[0].selectbox("Contrato", contratos_disponiveis)
serie, media = serie_por_contrato(pagamentos, contrato_sel)
meses_disponiveis = serie["mes_planilha"].tolist()
if meses_disponiveis:
    mes_comp = cc[1].selectbox("Competência", meses_disponiveis)
    medido = float(serie[serie["mes_planilha"] == mes_comp]["pago"].iloc[0])
    diferenca = media - medido
    percentual = (medido / media * 100) if media else 0
    with st.container(border=True):
        m = st.columns(4)
        m[0].metric("Referência (média mensal)", _brl(media))
        m[1].metric("Valor medido", _brl(medido))
        m[2].metric("Diferença", _brl(abs(diferenca)) + (" abaixo" if diferenca >= 0 else " acima"))
        m[3].metric("% utilizado", f"{percentual:.0f}%")
        if percentual < 90:
            st.markdown(_badge("Atenção — medição mais de 10% abaixo da referência", NEGATIVE), unsafe_allow_html=True)
        else:
            st.markdown(_badge("Dentro da faixa esperada", POSITIVE), unsafe_allow_html=True)
else:
    st.info("Sem pagamentos registrados para este contrato.")

st.caption(
    "Base consolidada manualmente por aba mensal (não é uma extração única e versionada como "
    "Dotação/Execução Anual) — pagamentos duplicados (mesmo contrato + NF + valor em mais de "
    "um mês) ficam marcados para auditoria, não somam nos totais."
)
