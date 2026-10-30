"""Relatório da lista de Empenhos com Execução Retardada (PDF e Excel).

Camada: regra de relatório — recebe a lista já agregada por NE pela página
`app_pages/empenhos_execucao_retardada.py` (`saldo_por_ne(agregar_por_ne(...))` + `percentual_saldo`),
exatamente o recorte exibido na tela (pedido explícito, 28/09/2026: "o que está na tela" — só os
em destaque, ou todos os empenhos do escopo quando a visualização "Todos no escopo" estiver
escolhida). Não lê planilha nem recalcula saldo: só formata o que recebe.

Dois formatos (pedido explícito: "PDF e Excel"):

  * PDF (`gerar_pdf`) — documento para leitura/arquivo: cabeçalho com procedência (data de
    extração + hash do manifesto), visualização, cortes e filtros aplicados; tabela NE /
    Exercício / Favorecido / Processo / Empenhado / Liquidado / Saldo / % Saldo / Corte, com
    linha de total.
  * Excel (`gerar_xlsx`) — mesma lista com as colunas de classificação da despesa, para
    reprocessar. Valores numéricos ficam como número (não texto formatado); códigos
    orçamentários ficam como TEXTO (regra permanente: identificadores, zeros à esquerda
    preservados); nulo fica como célula vazia, distinto de zero. Totais e parâmetros ficam numa
    aba separada ("Parâmetros"), para a aba de dados continuar filtrável sem linha de total no
    meio.

Rastreabilidade: as duas saídas levam `ne_ccor` completo (Excel) ou a NE curta (PDF) e a
procedência da extração — reconciliáveis com a base de Execução Mensal de origem.

Modelos (30/10/2026, pedido explícito: relatórios mais personalizados), todos sobre a MESMA lista:
  * "Lista de empenhos" — `gerar_pdf` com as colunas escolhidas na tela (padrão: as 10 de antes)
    e `gerar_xlsx` completo (com aba "Resumo" quando agrupado);
  * "Resumo por grupo" — `gerar_pdf_resumo`/`gerar_xlsx_resumo`: só os subtotais do agrupamento;
  * "Análise de anulação" — `gerar_pdf_analise`/`gerar_xlsx_analise`: indicação de anulação e as
    colunas "Decisão"/"Justificativa" em branco, para a unidade preencher.

Contrato público:
    ContextoRelatorio (dataclass)
    ordenar_lista(lista, ordenar_por, ascendente, agrupar_por, ordem_grupos) -> pd.DataFrame
    montar_lista_relatorio(visivel, em_destaque, *, cortes_ligados, todos, ordenar_por, ascendente, agrupar_por, ordem_grupos) -> pd.DataFrame
    resumo_por_grupo(lista) -> pd.DataFrame
    gerar_pdf(lista, contexto, colunas=None) -> bytes
    gerar_xlsx(lista, contexto) -> bytes
    gerar_pdf_resumo / gerar_xlsx_resumo / gerar_pdf_analise / gerar_xlsx_analise (lista, contexto) -> bytes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from openpyxl.worksheet.datavalidation import DataValidation
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.execucao_ne_utils import ne_curta

TITULO = "EMPENHOS COM EXECUÇÃO RETARDADA"

#: coluna auxiliar (booleana/nula) que a página acrescenta à lista: passa ou não do(s) corte(s)
#: ligado(s). Nula quando nenhum corte está ligado — "sem corte", não "não passa".
COLUNA_PASSA_CORTE = "passa_corte"

#: coluna auxiliar acrescentada por `ordenar_lista` quando há agrupamento (rótulo do grupo da linha).
COLUNA_GRUPO = "grupo_lista"
ROTULO_SEM_GRUPO = "—"


@dataclass(frozen=True)
class ContextoRelatorio:
    """Parâmetros do recorte que geraram a lista — impressos no cabeçalho do PDF e na aba
    "Parâmetros" do Excel, para quem lê o relatório saber exatamente de onde saiu cada linha."""

    visualizacao: str
    descricao_corte: str | None
    data_extracao: str
    hash_manifesto: str
    data_emissao: str
    busca: str = ""
    #: (rótulo do filtro, rótulos selecionados) — só filtros com alguma seleção.
    filtros: list[tuple[str, list[str]]] = field(default_factory=list)
    #: texto da ordenação e do agrupamento escolhidos na tela (vazio = padrão / sem agrupamento).
    ordenacao: str = ""
    agrupamento: str = ""
    #: (indicação, regra com os limites em uso) — `candidatos_anulacao.descrever_parametros`.
    indicacoes: list[tuple[str, str]] = field(default_factory=list)


#: (coluna da lista, cabeçalho na planilha) — códigos como texto, valores como número.
_COLUNAS_XLSX: list[tuple[str, str]] = [
    (COLUNA_GRUPO, "Grupo"),  # só presente quando a lista foi agrupada
    ("_ne_curta", "NE"),
    ("ne_ccor", "NE (código completo)"),
    ("ano", "Exercício"),
    ("ne_favorecido", "Favorecido"),
    ("ne_descricao", "Descrição"),
    ("processo_ne", "Nº do Processo"),
    ("acao_cod", "Ação"),
    ("acao_desc", "Ação - Descrição"),
    ("ptres", "PTRES"),
    ("fonte_cod", "Fonte"),
    ("fonte_desc", "Fonte - Descrição"),
    ("gnd_cod", "Grupo de Despesa"),
    ("natureza_despesa_cod", "Natureza de Despesa"),
    ("natureza_despesa_desc", "Natureza de Despesa - Descrição"),
    ("natureza_detalhada_label", "Natureza Detalhada"),
    ("subitem_resumo", "Subitem"),
    ("pi_cod", "PI"),
    ("pi_desc", "PI - Descrição"),
    ("ugr_cod", "UGR"),
    ("ugr_desc", "UGR - Descrição"),
    ("ug_executora_cod", "UG Executora"),
    ("ne_informacao_complementar", "NE - Informação Complementar"),
    ("empenhada", "Empenhado"),
    ("liquidada", "Liquidado"),
    ("saldo", "Saldo"),
    ("percentual_saldo", "% Saldo"),
    ("idade_meses", "Idade do saldo (meses)"),  # só exercício da extração; vazio nos demais
    ("meses_sem_liquidacao", "Meses sem liquidação"),  # idem
    ("indicacoes_anulacao", "Indicações para anulação"),
    ("indicacao_principal", "Indicação principal"),
    ("_passa_corte_texto", "Passa do corte"),
]
_COLUNAS_INTEIRAS = {"ano", "idade_meses", "meses_sem_liquidacao"}

_COLUNAS_NUMERICAS = {"empenhada", "liquidada", "saldo", "percentual_saldo"}


def ordenar_lista(
    lista: pd.DataFrame,
    ordenar_por: str = "saldo",
    ascendente: bool = False,
    agrupar_por: str | None = None,
    ordem_grupos: list[str] | None = None,
) -> pd.DataFrame:
    """Ordena a lista por `ordenar_por` (nulo SEMPRE por último, em qualquer direção — nulo não é
    zero nem negativo) e, se `agrupar_por` vier, deixa as linhas de cada grupo contíguas.

    Com agrupamento, acrescenta `COLUNA_GRUPO` (rótulo do grupo; valor nulo vira `ROTULO_SEM_GRUPO`)
    e ordena os grupos pelo saldo somado, do maior para o menor (grupo sem nenhum saldo e o
    grupo "sem valor" por último), desempatando pelo nome; dentro do grupo vale `ordenar_por`.
    Com `ordem_grupos` (faixas), os grupos seguem essa ordem; rótulo fora dela vai depois, pelo saldo.
    Só reordena e rotula: nenhuma linha é descartada nem tem valor alterado. Não altera `lista`."""

    base = lista.copy()
    chaves: list[str] = []
    ascendentes: list[bool] = []
    if agrupar_por:
        grupo = base[agrupar_por].astype("string").fillna(ROTULO_SEM_GRUPO)
        base[COLUNA_GRUPO] = grupo.astype(object)
        base["_grupo_sem_valor"] = base[COLUNA_GRUPO] == ROTULO_SEM_GRUPO
        base["_grupo_saldo"] = base.groupby(COLUNA_GRUPO)["saldo"].transform(lambda s: s.sum(min_count=1))
        posicao = {rotulo: i for i, rotulo in enumerate(ordem_grupos or [])}
        base["_grupo_posicao"] = base[COLUNA_GRUPO].map(posicao).fillna(len(posicao)).astype(int)
        chaves += ["_grupo_sem_valor", "_grupo_posicao", "_grupo_saldo", COLUNA_GRUPO]
        ascendentes += [True, True, False, True]
    chaves.append(ordenar_por)
    ascendentes.append(ascendente)

    def _chave(serie: pd.Series) -> pd.Series:
        # texto sem diferenciar maiúsculas; números e booleanos seguem o próprio valor
        return serie.str.lower() if serie.dtype == object or str(serie.dtype) == "string" else serie

    base = base.sort_values(chaves, ascending=ascendentes, na_position="last", kind="stable", key=_chave)
    return base.drop(columns=["_grupo_sem_valor", "_grupo_posicao", "_grupo_saldo"], errors="ignore").reset_index(drop=True)


def montar_lista_relatorio(
    visivel: pd.DataFrame,
    em_destaque: pd.Series,
    *,
    cortes_ligados: bool,
    todos: bool,
    ordenar_por: str = "saldo",
    ascendente: bool = False,
    agrupar_por: str | None = None,
    ordem_grupos: list[str] | None = None,
) -> pd.DataFrame:
    """Lista exibida na tela E enviada ao relatório — uma função só para as duas não divergirem
    (pedido explícito: o relatório é "o que está na tela").

    `todos=True` ("Todos no escopo") devolve todas as linhas de `visivel`; `todos=False` só as
    marcadas em `em_destaque` (máscara booleana, mesmo índice de `visivel`). Acrescenta
    `COLUNA_PASSA_CORTE`: o valor da máscara quando há corte ligado, nulo quando não há —
    "sem corte", não "não passa". Ordena conforme `ordenar_lista` (padrão: saldo decrescente,
    nulo por último, sem agrupamento) e reinicia o índice. Não altera `visivel`."""

    passa = em_destaque.astype(object) if cortes_ligados else pd.Series(pd.NA, index=visivel.index, dtype=object)
    base = visivel if todos else visivel[em_destaque.fillna(False).astype(bool)]
    return ordenar_lista(
        base.assign(**{COLUNA_PASSA_CORTE: passa.reindex(base.index)}),
        ordenar_por=ordenar_por,
        ascendente=ascendente,
        agrupar_por=agrupar_por,
        ordem_grupos=ordem_grupos,
    )


def _texto_passa_corte(valor: object) -> str | None:
    if valor is None or pd.isna(valor):
        return None
    return "Sim" if bool(valor) else "Não"


def _ne_curta_ou_original(valor: object) -> str | None:
    if valor is None or pd.isna(valor):
        return None
    return ne_curta(str(valor))


def _preparada(lista: pd.DataFrame) -> pd.DataFrame:
    """Cópia derivada com as colunas auxiliares de exibição — nunca altera `lista`."""

    base = lista.copy()
    base["_ne_curta"] = base["ne_ccor"].map(_ne_curta_ou_original)
    passa = base[COLUNA_PASSA_CORTE] if COLUNA_PASSA_CORTE in base.columns else pd.Series(pd.NA, index=base.index)
    base["_passa_corte_texto"] = passa.map(_texto_passa_corte)
    return base


def _formatar_brl(valor: object) -> str:
    """Pontuação pt-BR com centavos; nulo vira "—" (distinto de "0,00")."""

    if valor is None or pd.isna(valor):
        return "—"
    return f"{float(valor):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _formatar_pct(valor: object) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return f"{float(valor):.1f}%".replace(".", ",")


def _formatar_idade(valor: object) -> str:
    """Idade do saldo em meses; nula (exercício anterior ou coluna ausente) vira "—"."""

    if valor is None or pd.isna(valor):
        return "—"
    return str(int(valor))


def _soma(serie: pd.Series) -> float | None:
    """`min_count=1`: coluna só com nulos soma nulo, não zero."""

    total = serie.sum(min_count=1)
    return None if pd.isna(total) else float(total)


def _linhas_parametros(contexto: ContextoRelatorio) -> list[tuple[str, str]]:
    linhas = [
        ("Visualização", contexto.visualizacao),
        ("Cortes de destaque", contexto.descricao_corte or "nenhum corte ligado"),
        ("Busca livre", contexto.busca or "—"),
    ]
    if contexto.ordenacao:
        linhas.append(("Ordenação", contexto.ordenacao))
    if contexto.agrupamento:
        linhas.append(("Agrupamento", contexto.agrupamento))
    if contexto.filtros:
        for rotulo, valores in contexto.filtros:
            linhas.append((rotulo, "; ".join(valores)))
    else:
        linhas.append(("Filtros", "nenhum (todos os registros)"))
    for nome, regra in contexto.indicacoes:
        linhas.append((f"Indicação: {nome}", regra))
    linhas.append(("Procedência", f"extração de {contexto.data_extracao} · hash {contexto.hash_manifesto}"))
    linhas.append(("Emitido em", contexto.data_emissao))
    return linhas


# ------------------------------------------------------------------------------ Excel
#: modelo "Análise de anulação" (30/10/2026): colunas em branco para a unidade preencher.
COLUNA_DECISAO = "Decisão"
COLUNA_JUSTIFICATIVA = "Justificativa"
OPCOES_DECISAO = ("Manter", "Anular", "Reforçar")


def _dados_xlsx(base: pd.DataFrame) -> pd.DataFrame:
    dados = pd.DataFrame(index=base.index)
    for coluna, cabecalho in _COLUNAS_XLSX:
        if coluna not in base.columns:
            continue
        serie = base[coluna]
        if coluna in _COLUNAS_NUMERICAS:
            dados[cabecalho] = pd.to_numeric(serie, errors="coerce").astype("float64")
        elif coluna in _COLUNAS_INTEIRAS:
            dados[cabecalho] = pd.to_numeric(serie, errors="coerce").astype("Int64")
        else:
            # identificadores/textos como string — preserva zeros à esquerda; nulo continua nulo.
            dados[cabecalho] = serie.map(lambda v: None if v is None or pd.isna(v) else str(v)).astype(object)
    return dados


def _totais(base: pd.DataFrame) -> list[tuple[str, str]]:
    return [
        ("Empenhos listados", str(len(base))),
        ("Total empenhado", _formatar_brl(_soma(base["empenhada"]))),
        ("Total liquidado", _formatar_brl(_soma(base["liquidada"]))),
        ("Total saldo", _formatar_brl(_soma(base["saldo"]))),
    ]


_CABECALHOS_INTEIROS = {"Exercício", "Idade do saldo (meses)", "Meses sem liquidação", "Empenhos"}
_CABECALHOS_PCT = {"% Saldo", "% liquidado", "% do saldo do relatório"}


def _formatar_planilha(planilha, cabecalhos: list[str]) -> None:
    for indice, cabecalho in enumerate(cabecalhos, start=1):
        letra = planilha.cell(row=1, column=indice).column_letter
        if cabecalho in ("Empenhado", "Liquidado", "Saldo"):
            formato = "#,##0.00"
        elif cabecalho in _CABECALHOS_PCT:
            formato = "0.0"
        else:
            formato = None if cabecalho in _CABECALHOS_INTEIROS else "@"
        if formato:
            for celula in planilha[letra][1:]:
                celula.number_format = formato
        planilha.column_dimensions[letra].width = min(max(len(cabecalho), 12) + 2, 45)
    planilha.freeze_panes = "B2"


def _gravar_xlsx(abas: list[tuple[str, pd.DataFrame]], parametros: list[tuple[str, str]], *, analise: bool = False) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for nome, dados in abas:
            dados.to_excel(writer, sheet_name=nome, index=False)
            _formatar_planilha(writer.sheets[nome], list(dados.columns))
        pd.DataFrame(parametros, columns=["Parâmetro", "Valor"]).to_excel(writer, sheet_name="Parâmetros", index=False)
        writer.sheets["Parâmetros"].column_dimensions["A"].width = 28
        writer.sheets["Parâmetros"].column_dimensions["B"].width = 90
        if analise:
            nome, dados = abas[0]
            planilha = writer.sheets[nome]
            cabecalhos = list(dados.columns)
            letra = planilha.cell(row=1, column=cabecalhos.index(COLUNA_DECISAO) + 1).column_letter
            validacao = DataValidation(type="list", formula1='"' + ",".join(OPCOES_DECISAO) + '"', allow_blank=True)
            planilha.add_data_validation(validacao)
            if len(dados):
                validacao.add(f"{letra}2:{letra}{len(dados) + 1}")
            for cabecalho, largura in ((COLUNA_DECISAO, 14), (COLUNA_JUSTIFICATIVA, 60)):
                letra = planilha.cell(row=1, column=cabecalhos.index(cabecalho) + 1).column_letter
                planilha.column_dimensions[letra].width = largura
    return buffer.getvalue()


def gerar_xlsx(lista: pd.DataFrame, contexto: ContextoRelatorio) -> bytes:
    """Modelo "Lista de empenhos": todas as colunas (para reprocessar) e, quando a lista está
    agrupada, a aba "Resumo" com os subtotais de `resumo_por_grupo`."""

    base = _preparada(lista)
    abas = [("Empenhos", _dados_xlsx(base))]
    if COLUNA_GRUPO in base.columns:
        abas.append(("Resumo", resumo_por_grupo(lista)))
    return _gravar_xlsx(abas, _linhas_parametros(contexto) + _totais(base))


def gerar_xlsx_analise(lista: pd.DataFrame, contexto: ContextoRelatorio) -> bytes:
    """Modelo "Análise de anulação": as mesmas colunas do Excel completo mais "Decisão" (lista
    suspensa Manter/Anular/Reforçar) e "Justificativa", em branco, para a unidade preencher."""

    base = _preparada(lista)
    dados = _dados_xlsx(base)
    dados[COLUNA_DECISAO] = pd.Series(None, index=dados.index, dtype=object)
    dados[COLUNA_JUSTIFICATIVA] = pd.Series(None, index=dados.index, dtype=object)
    return _gravar_xlsx([("Empenhos", dados)], _linhas_parametros(contexto) + _totais(base), analise=True)


def resumo_por_grupo(lista: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por grupo (na ordem da lista) e a linha TOTAL: empenhos, empenhado, liquidado,
    saldo, % liquidado e participação no saldo. Sem agrupamento, só a linha TOTAL. Somas com
    `min_count=1` (grupo só com nulos soma nulo, não zero); % nulo quando o divisor é nulo ou zero."""

    def linha(rotulo: str, parte: pd.DataFrame, saldo_total: float | None) -> dict[str, object]:
        empenhado, liquidado, saldo = _soma(parte["empenhada"]), _soma(parte["liquidada"]), _soma(parte["saldo"])
        return {
            "Grupo": rotulo,
            "Empenhos": int(len(parte)),
            "Empenhado": empenhado,
            "Liquidado": liquidado,
            "Saldo": saldo,
            "% liquidado": (liquidado or 0.0) / empenhado * 100 if empenhado else None,
            "% do saldo do relatório": saldo / saldo_total * 100 if saldo is not None and saldo_total else None,
        }

    saldo_total = _soma(lista["saldo"])
    linhas = []
    if COLUNA_GRUPO in lista.columns:
        for rotulo, parte in lista.groupby(COLUNA_GRUPO, sort=False):
            linhas.append(linha(str(rotulo), parte, saldo_total))
    linhas.append(linha("TOTAL", lista, saldo_total))
    resumo = pd.DataFrame(linhas)
    for coluna in ("Empenhado", "Liquidado", "Saldo", "% liquidado", "% do saldo do relatório"):
        resumo[coluna] = pd.to_numeric(resumo[coluna], errors="coerce").astype("float64")
    return resumo


def gerar_xlsx_resumo(lista: pd.DataFrame, contexto: ContextoRelatorio) -> bytes:
    return _gravar_xlsx([("Resumo", resumo_por_grupo(lista))], _linhas_parametros(contexto) + _totais(lista))


# -------------------------------------------------------------------------------- PDF
#: catálogo de colunas do PDF (30/10/2026, pedido explícito: escolher as colunas). chave ->
#: (cabeçalho, largura em pt, tipo). Tipos: "texto" (quebra linha), "curto" (sem quebra), "brl",
#: "pct", "inteiro", "centro". As larguras são reduzidas na mesma proporção se passarem da página.
_CATALOGO_PDF: dict[str, tuple[str, float, str]] = {
    "ne": ("NE", 70, "curto"),
    "exercicio": ("EXERCÍCIO", 45, "inteiro"),
    "favorecido": ("FAVORECIDO", 180, "texto"),
    "processo": ("PROCESSO", 95, "texto"),
    "acao": ("AÇÃO", 150, "texto"),
    "fonte": ("FONTE", 120, "texto"),
    "natureza": ("NATUREZA DE DESPESA", 140, "texto"),
    "pi": ("PI", 110, "texto"),
    "ptres": ("PTRES", 45, "curto"),
    "ugr": ("UGR", 120, "texto"),
    "uo": ("UNIDADE ORÇAMENTÁRIA", 130, "texto"),
    "empenhado": ("EMPENHADO (R$)", 80, "brl"),
    "liquidado": ("LIQUIDADO (R$)", 80, "brl"),
    "saldo": ("SALDO (R$)", 80, "brl"),
    "pct": ("% SALDO", 48, "pct"),
    "idade": ("IDADE (MESES)", 40, "inteiro"),
    "sem_liq": ("SEM LIQ. (MESES)", 45, "inteiro"),
    "indicacoes": ("INDICAÇÃO", 120, "texto"),
    "corte": ("CORTE", 42, "centro"),
    "decisao": ("DECISÃO", 60, "texto"),
    "justificativa": ("JUSTIFICATIVA", 170, "texto"),
}
#: chave do catálogo -> coluna da lista preparada (as duas colunas em branco não têm origem)
_ORIGEM_PDF: dict[str, str] = {
    "ne": "_ne_curta", "exercicio": "ano", "favorecido": "ne_favorecido", "processo": "processo_ne",
    "acao": "acao_desc", "fonte": "fonte_desc", "natureza": "natureza_despesa_desc", "pi": "pi_desc",
    "ptres": "ptres", "ugr": "ugr_desc", "uo": "unidade_orcamentaria_desc", "empenhado": "empenhada",
    "liquidado": "liquidada", "saldo": "saldo", "pct": "percentual_saldo", "idade": "idade_meses",
    "sem_liq": "meses_sem_liquidacao", "indicacoes": "indicacoes_anulacao", "corte": "_passa_corte_texto",
}
#: rótulos para escolher as colunas na tela (sem as duas em branco do modelo de análise)
ROTULOS_COLUNAS_PDF: dict[str, str] = {
    "ne": "NE", "exercicio": "Exercício", "favorecido": "Favorecido", "processo": "Nº do processo",
    "acao": "Ação de governo", "fonte": "Fonte de recursos", "natureza": "Natureza de despesa", "pi": "PI",
    "ptres": "PTRES", "ugr": "UGR", "uo": "Unidade orçamentária", "empenhado": "Empenhado",
    "liquidado": "Liquidado", "saldo": "Saldo", "pct": "% Saldo", "idade": "Idade do saldo",
    "sem_liq": "Meses sem liquidação", "indicacoes": "Indicação de anulação", "corte": "Passa do corte",
}
#: colunas que o PDF tinha antes da escolha de colunas — continuam sendo o padrão
COLUNAS_PDF_PADRAO = ["ne", "exercicio", "favorecido", "processo", "empenhado", "liquidado", "saldo", "pct", "idade", "corte"]
COLUNAS_PDF_ANALISE = ["ne", "favorecido", "saldo", "idade", "sem_liq", "indicacoes", "decisao", "justificativa"]
_LARGURA_UTIL_PDF = 774  # landscape(A4) com 12mm de margem


def _documento(buffer: BytesIO, titulo: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=titulo,
    )


def _estilos():
    estilos = getSampleStyleSheet()
    celula = estilos["Normal"].clone("celula_retardada")
    celula.fontSize = 7
    celula.leading = 8.5
    parametro = estilos["Normal"].clone("parametro_retardada")
    parametro.fontSize = 8
    parametro.leading = 10
    return estilos, celula, parametro


def _cabecalho_pdf(titulo: str, contexto: ContextoRelatorio, estilos, estilo_parametro) -> list:
    elementos: list = [Paragraph(escape(titulo), estilos["Heading3"])]
    for rotulo, valor in _linhas_parametros(contexto):
        elementos.append(Paragraph(f"<b>{escape(rotulo)}:</b> {escape(valor)}", estilo_parametro))
    elementos.append(Spacer(1, 8))
    return elementos


def _celula(chave: str, linha: pd.Series, estilo_celula) -> object:
    tipo = _CATALOGO_PDF[chave][2]
    origem = _ORIGEM_PDF.get(chave)
    if origem is None:  # coluna em branco, para preencher à mão
        return ""
    valor = linha.get(origem)
    if tipo == "brl":
        return _formatar_brl(valor)
    if tipo == "pct":
        return _formatar_pct(valor)
    if tipo == "inteiro":
        return _formatar_idade(valor)
    texto = "—" if valor is None or pd.isna(valor) else str(valor)
    return Paragraph(escape(texto), estilo_celula) if tipo == "texto" else texto


def gerar_pdf(
    lista: pd.DataFrame, contexto: ContextoRelatorio, colunas: list[str] | None = None, *, titulo: str = TITULO
) -> bytes:
    """Lista em PDF com as `colunas` escolhidas (chaves de `_CATALOGO_PDF`, na ordem recebida;
    padrão `COLUNAS_PDF_PADRAO`). Chave desconhecida é ignorada; sem nenhuma válida, vale o padrão."""

    chaves = [c for c in (colunas or COLUNAS_PDF_PADRAO) if c in _CATALOGO_PDF] or list(COLUNAS_PDF_PADRAO)
    base = _preparada(lista)
    buffer = BytesIO()
    documento = _documento(buffer, titulo)
    estilos, estilo_celula, estilo_parametro = _estilos()
    elementos = _cabecalho_pdf(titulo, contexto, estilos, estilo_parametro)

    larguras = [_CATALOGO_PDF[c][1] for c in chaves]
    fator = min(1.0, _LARGURA_UTIL_PDF / sum(larguras))
    larguras = [w * fator for w in larguras]
    vazio = [""] * (len(chaves) - 1)

    tabela_dados: list[list[object]] = [[_CATALOGO_PDF[c][0] for c in chaves]]
    linhas_grupo: list[int] = []
    grupo_atual: object = None
    for _, linha in base.iterrows():
        if COLUNA_GRUPO in base.columns and (not linhas_grupo or linha[COLUNA_GRUPO] != grupo_atual):
            grupo_atual = linha[COLUNA_GRUPO]
            do_grupo = base[base[COLUNA_GRUPO] == grupo_atual]
            linhas_grupo.append(len(tabela_dados))
            tabela_dados.append([
                Paragraph(
                    f"<b>{escape(str(grupo_atual))}</b> — {len(do_grupo)} empenhos · saldo R$ {escape(_formatar_brl(_soma(do_grupo['saldo'])))}",
                    estilo_celula,
                ),
                *vazio,
            ])
        tabela_dados.append([_celula(c, linha, estilo_celula) for c in chaves])

    total: list[object] = []
    for i, chave in enumerate(chaves):
        if chave in ("empenhado", "liquidado", "saldo"):
            total.append(_formatar_brl(_soma(base[_ORIGEM_PDF[chave]])))
        else:
            total.append(f"TOTAL ({len(base)})" if i == 0 else "")
    tabela_dados.append(total)

    estilo = [
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDDDDD")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F5F5")]),
    ]
    for i, chave in enumerate(chaves):
        tipo = _CATALOGO_PDF[chave][2]
        if tipo in ("brl", "pct", "inteiro"):
            estilo.append(("ALIGN", (i, 0), (i, -1), "RIGHT"))
        elif tipo == "centro":
            estilo.append(("ALIGN", (i, 0), (i, -1), "CENTER"))
    for indice in linhas_grupo:
        estilo += [
            ("SPAN", (0, indice), (-1, indice)),
            ("BACKGROUND", (0, indice), (-1, indice), colors.HexColor("#DCE8F5")),
            ("ALIGN", (0, indice), (0, indice), "LEFT"),
        ]
    tabela = Table(tabela_dados, colWidths=larguras, repeatRows=1)
    tabela.setStyle(TableStyle(estilo))
    elementos.append(tabela)
    documento.build(elementos)
    return buffer.getvalue()


def gerar_pdf_analise(lista: pd.DataFrame, contexto: ContextoRelatorio) -> bytes:
    """Modelo "Análise de anulação": NE, favorecido, saldo, idade, meses sem liquidação, indicação
    e as colunas "Decisão" e "Justificativa" em branco, para preencher à mão."""

    return gerar_pdf(lista, contexto, COLUNAS_PDF_ANALISE, titulo=f"{TITULO} — ANÁLISE DE ANULAÇÃO")


def gerar_pdf_resumo(lista: pd.DataFrame, contexto: ContextoRelatorio) -> bytes:
    """Modelo "Resumo por grupo": só os subtotais de `resumo_por_grupo`, numa tabela."""

    resumo = resumo_por_grupo(lista)
    buffer = BytesIO()
    titulo = f"{TITULO} — RESUMO POR GRUPO"
    documento = _documento(buffer, titulo)
    estilos, estilo_celula, estilo_parametro = _estilos()
    elementos = _cabecalho_pdf(titulo, contexto, estilos, estilo_parametro)
    tabela_dados: list[list[object]] = [
        ["GRUPO", "EMPENHOS", "EMPENHADO (R$)", "LIQUIDADO (R$)", "SALDO (R$)", "% LIQUIDADO", "% DO SALDO"]
    ]
    for _, linha in resumo.iterrows():
        tabela_dados.append([
            Paragraph(escape(str(linha["Grupo"])), estilo_celula),
            str(int(linha["Empenhos"])),
            _formatar_brl(linha["Empenhado"]),
            _formatar_brl(linha["Liquidado"]),
            _formatar_brl(linha["Saldo"]),
            _formatar_pct(linha["% liquidado"]),
            _formatar_pct(linha["% do saldo do relatório"]),
        ])
    tabela = Table(tabela_dados, colWidths=[300, 60, 90, 90, 90, 60, 60], repeatRows=1)
    tabela.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDDDDD")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))
    elementos.append(tabela)
    documento.build(elementos)
    return buffer.getvalue()
