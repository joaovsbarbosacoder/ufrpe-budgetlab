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

Contrato público:
    ContextoRelatorio (dataclass)
    montar_lista_relatorio(visivel, em_destaque, *, cortes_ligados, todos) -> pd.DataFrame
    gerar_pdf(lista, contexto) -> bytes
    gerar_xlsx(lista, contexto) -> bytes
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
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.execucao_ne_utils import ne_curta

TITULO = "EMPENHOS COM EXECUÇÃO RETARDADA"

#: coluna auxiliar (booleana/nula) que a página acrescenta à lista: passa ou não do(s) corte(s)
#: ligado(s). Nula quando nenhum corte está ligado — "sem corte", não "não passa".
COLUNA_PASSA_CORTE = "passa_corte"


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


#: (coluna da lista, cabeçalho na planilha) — códigos como texto, valores como número.
_COLUNAS_XLSX: list[tuple[str, str]] = [
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
    ("_passa_corte_texto", "Passa do corte"),
]

_COLUNAS_NUMERICAS = {"empenhada", "liquidada", "saldo", "percentual_saldo"}


def montar_lista_relatorio(
    visivel: pd.DataFrame, em_destaque: pd.Series, *, cortes_ligados: bool, todos: bool
) -> pd.DataFrame:
    """Lista exibida na tela E enviada ao relatório — uma função só para as duas não divergirem
    (pedido explícito: o relatório é "o que está na tela").

    `todos=True` ("Todos no escopo") devolve todas as linhas de `visivel`; `todos=False` só as
    marcadas em `em_destaque` (máscara booleana, mesmo índice de `visivel`). Acrescenta
    `COLUNA_PASSA_CORTE`: o valor da máscara quando há corte ligado, nulo quando não há —
    "sem corte", não "não passa". Ordena por saldo decrescente (nulo por último) e reinicia o
    índice. Não altera `visivel`."""

    passa = em_destaque.astype(object) if cortes_ligados else pd.Series(pd.NA, index=visivel.index, dtype=object)
    base = visivel if todos else visivel[em_destaque.fillna(False).astype(bool)]
    return (
        base.assign(**{COLUNA_PASSA_CORTE: passa.reindex(base.index)})
        .sort_values("saldo", ascending=False, na_position="last")
        .reset_index(drop=True)
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
    if contexto.filtros:
        for rotulo, valores in contexto.filtros:
            linhas.append((rotulo, "; ".join(valores)))
    else:
        linhas.append(("Filtros", "nenhum (todos os registros)"))
    linhas.append(("Procedência", f"extração de {contexto.data_extracao} · hash {contexto.hash_manifesto}"))
    linhas.append(("Emitido em", contexto.data_emissao))
    return linhas


# ------------------------------------------------------------------------------ Excel
def gerar_xlsx(lista: pd.DataFrame, contexto: ContextoRelatorio) -> bytes:
    base = _preparada(lista)
    dados = pd.DataFrame(index=base.index)
    for coluna, cabecalho in _COLUNAS_XLSX:
        if coluna not in base.columns:
            continue
        serie = base[coluna]
        if coluna in _COLUNAS_NUMERICAS:
            dados[cabecalho] = pd.to_numeric(serie, errors="coerce").astype("float64")
        elif coluna == "ano":
            dados[cabecalho] = serie.astype("Int64")
        else:
            # identificadores/textos como string — preserva zeros à esquerda; nulo continua nulo.
            dados[cabecalho] = serie.map(lambda v: None if v is None or pd.isna(v) else str(v)).astype(object)

    parametros = _linhas_parametros(contexto) + [
        ("Empenhos listados", str(len(base))),
        ("Total empenhado", _formatar_brl(_soma(base["empenhada"]))),
        ("Total liquidado", _formatar_brl(_soma(base["liquidada"]))),
        ("Total saldo", _formatar_brl(_soma(base["saldo"]))),
    ]

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        dados.to_excel(writer, sheet_name="Empenhos", index=False)
        pd.DataFrame(parametros, columns=["Parâmetro", "Valor"]).to_excel(
            writer, sheet_name="Parâmetros", index=False
        )
        planilha = writer.sheets["Empenhos"]
        for indice, cabecalho in enumerate(dados.columns, start=1):
            letra = planilha.cell(row=1, column=indice).column_letter
            if cabecalho in ("Empenhado", "Liquidado", "Saldo"):
                formato = "#,##0.00"
            elif cabecalho == "% Saldo":
                formato = "0.0"
            else:
                formato = "@" if cabecalho != "Exercício" else None
            if formato:
                for celula in planilha[letra][1:]:
                    celula.number_format = formato
            planilha.column_dimensions[letra].width = min(max(len(cabecalho), 12) + 2, 45)
        planilha.freeze_panes = "B2"
        writer.sheets["Parâmetros"].column_dimensions["A"].width = 28
        writer.sheets["Parâmetros"].column_dimensions["B"].width = 90
    return buffer.getvalue()


# -------------------------------------------------------------------------------- PDF
#: landscape(A4) com 12mm de margem (~774pt úteis).
_CABECALHO_PDF = ["NE", "EXERCÍCIO", "FAVORECIDO", "PROCESSO", "EMPENHADO (R$)", "LIQUIDADO (R$)", "SALDO (R$)", "% SALDO", "CORTE"]
_LARGURAS_PDF = [70, 45, 220, 95, 80, 80, 80, 48, 42]


def gerar_pdf(lista: pd.DataFrame, contexto: ContextoRelatorio) -> bytes:
    base = _preparada(lista)
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=TITULO,
    )
    estilos = getSampleStyleSheet()
    estilo_celula = estilos["Normal"].clone("celula_retardada")
    estilo_celula.fontSize = 7
    estilo_celula.leading = 8.5
    estilo_parametro = estilos["Normal"].clone("parametro_retardada")
    estilo_parametro.fontSize = 8
    estilo_parametro.leading = 10

    elementos: list = [Paragraph(TITULO, estilos["Heading3"])]
    for rotulo, valor in _linhas_parametros(contexto):
        elementos.append(Paragraph(f"<b>{escape(rotulo)}:</b> {escape(valor)}", estilo_parametro))
    elementos.append(Spacer(1, 8))

    tabela_dados: list[list[object]] = [_CABECALHO_PDF]
    for _, linha in base.iterrows():
        tabela_dados.append(
            [
                linha["_ne_curta"] or "—",
                "—" if pd.isna(linha["ano"]) else str(int(linha["ano"])),
                Paragraph(escape("—" if pd.isna(linha["ne_favorecido"]) else str(linha["ne_favorecido"])), estilo_celula),
                Paragraph(escape("—" if pd.isna(linha["processo_ne"]) else str(linha["processo_ne"])), estilo_celula),
                _formatar_brl(linha["empenhada"]),
                _formatar_brl(linha["liquidada"]),
                _formatar_brl(linha["saldo"]),
                _formatar_pct(linha["percentual_saldo"]),
                linha["_passa_corte_texto"] or "—",
            ]
        )
    tabela_dados.append(
        [
            f"TOTAL ({len(base)})", "", "", "",
            _formatar_brl(_soma(base["empenhada"])),
            _formatar_brl(_soma(base["liquidada"])),
            _formatar_brl(_soma(base["saldo"])),
            "", "",
        ]
    )

    tabela = Table(tabela_dados, colWidths=_LARGURAS_PDF, repeatRows=1)
    tabela.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDDDDD")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (4, 0), (7, -1), "RIGHT"),
                ("ALIGN", (8, 0), (8, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F5F5")]),
            ]
        )
    )
    elementos.append(tabela)
    documento.build(elementos)
    return buffer.getvalue()
