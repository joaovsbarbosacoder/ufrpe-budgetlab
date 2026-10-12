"""
Exportação (Excel e PDF) da visão consolidada da conciliação por competência — todos os contratos (12/10/2026).

Camada: regra de relatório. Não lê planilha nem importa Streamlit. Entrada: as linhas de
`src.pendencias_conciliacao.consolidar_exercicio` acrescidas de `ano` e `credor` (nome do credor/fornecedor do cadastro
de Contratos Contínuos; ausente = "—"). Só LÊ o que a tela já calcula.

Regras: o valor da célula do mês é o do relatório de competência (ou, quando só há nota do gov, a nota); sem registro é
NULO ("—"), nunca zero; zero de verdade continua zero. O total das notas usa o valor AJUSTADO por decisão do usuário
(nota indicada como cancelada numa decisão confirmada) — o bruto de cada mês fica na aba "Detalhe mensal".

Contrato público:
    tabela_matriz(linhas) -> DataFrame
    tabela_detalhe(linhas) -> DataFrame
    gerar_xlsx(linhas, ano, gerado_em) -> bytes
    gerar_pdf(linhas, ano, gerado_em) -> bytes
"""

from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.conciliacao_competencia_gov import CLASSES

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
COLUNAS_MATRIZ = ["Contrato", "Credor", *MESES, "Total relatório", "Total notas"]
COLUNAS_DETALHE = [
    "Contrato", "Credor", "Competência", "Situação", "Valor no relatório", "Valor nas notas", "Valor das notas ajustado",
    "Diferença", "Ação sugerida",
]
AVISO_AJUSTE = "* valor das notas ajustado por decisão do usuário (nota indicada como cancelada); o bruto está no detalhe mensal."

#: cor de cada situação na matriz do PDF (mesma lógica da tela)
_COR_CLASSE = {
    "batem": "#c9ecd6", "confirmada": "#c9ecd6", "deslocamento": "#cfe2f7", "cancelamento": "#cfe2f7",
    "nota_pendente": "#cfe2f7", "ambiguo": "#f6cfd2", "sem_explicacao": "#f6cfd2", "rejeitada": "#f6cfd2",
    "so_notas": "#f8e0bd", "so_relatorio": "#f8e0bd",
}


def _credor(linha: dict) -> str:
    credor = linha.get("credor")
    if credor is None or (isinstance(credor, float) and pd.isna(credor)) or not str(credor).strip():
        return "—"
    return str(credor).strip()


def _valor_do_mes(mes: dict) -> float | None:
    """Relatório; só nota quando o relatório não tem o mês (a nota ajustada, se houver); senão nulo."""
    if mes["relatorio"] is not None:
        return mes["relatorio"]
    ajustada = mes.get("notas_ajustadas")
    return ajustada if ajustada is not None else mes["notas"]


def tabela_matriz(linhas: list[dict]) -> pd.DataFrame:
    registros = []
    for linha in linhas:
        registro = {"Contrato": str(linha["contrato"]), "Credor": _credor(linha)}
        for mes in linha["meses"]:
            registro[MESES[mes["mes"] - 1]] = _valor_do_mes(mes)
        registro["Total relatório"] = linha["total_relatorio"]
        registro["Total notas"] = linha.get("total_notas_ajustado", linha["total_notas"])
        registros.append(registro)
    numericas = [*MESES, "Total relatório", "Total notas"]
    return pd.DataFrame(registros, columns=COLUNAS_MATRIZ).astype({c: "float64" for c in numericas})


def tabela_detalhe(linhas: list[dict]) -> pd.DataFrame:
    """Uma linha por contrato e mês COM algum dado (relatório ou nota), com situação, valores nas duas fontes, o ajustado
    por decisão e a diferença (notas − relatório; nula se faltar um dos lados)."""

    registros = []
    for linha in linhas:
        ano = linha.get("ano", "")
        for mes in linha["meses"]:
            rel, notas = mes["relatorio"], mes["notas"]
            if rel is None and notas is None:
                continue
            registros.append({
                "Contrato": str(linha["contrato"]), "Credor": _credor(linha), "Competência": f"{mes['mes']:02d}/{ano}",
                "Situação": CLASSES[mes["classe"]], "Valor no relatório": rel, "Valor nas notas": notas,
                "Valor das notas ajustado": mes.get("notas_ajustadas"),
                "Diferença": None if rel is None or notas is None else round(notas - rel, 2),
                "Ação sugerida": mes.get("acao", ""),
            })
    numericas = ["Valor no relatório", "Valor nas notas", "Valor das notas ajustado", "Diferença"]
    return pd.DataFrame(registros, columns=COLUNAS_DETALHE).astype({c: "float64" for c in numericas})


def gerar_xlsx(linhas: list[dict], ano: int, gerado_em: str) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
        tabela_matriz(linhas).to_excel(escritor, sheet_name="Matriz", index=False, startrow=2)
        tabela_detalhe(linhas).to_excel(escritor, sheet_name="Detalhe mensal", index=False, startrow=2)
        for aba, texto in (("Matriz", AVISO_AJUSTE), ("Detalhe mensal", "Valores em R$; vazio = sem registro.")):
            planilha = escritor.sheets[aba]
            planilha["A1"] = f"Conciliação por competência — todos os contratos — exercício {ano} (gerado em {gerado_em})"
            planilha["A2"] = texto
            for coluna in planilha.iter_cols(min_row=3):
                tamanhos = [len(str(c.value)) for c in coluna if c.value is not None]
                planilha.column_dimensions[coluna[0].column_letter].width = min(48, max(10, *tamanhos)) if tamanhos else 10
            for linha_celulas in planilha.iter_rows(min_row=4):
                for celula in linha_celulas:
                    if isinstance(celula.value, float):
                        celula.number_format = "#,##0.00"
    return buffer.getvalue()


def _brl(valor: float | None) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return f"{valor:,.0f}".replace(",", ".")


def gerar_pdf(linhas: list[dict], ano: int, gerado_em: str) -> bytes:
    """Matriz contrato/credor × 12 meses, paisagem; valores em R$ sem centavos (o exato está no Excel); célula colorida
    pela situação do mês (`*` = ajustado por decisão); linha de totais por mês; legenda das cores."""

    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=landscape(A4), leftMargin=8 * mm, rightMargin=8 * mm, topMargin=8 * mm, bottomMargin=8 * mm,
        title=f"Conciliação por competência — {ano}",
    )
    estilos = getSampleStyleSheet()
    pequeno = estilos["Normal"].clone("conc_pequeno", fontSize=6, leading=7)
    cabecalho = estilos["Normal"].clone("conc_cab", fontSize=6.5, leading=7.5, textColor=colors.white)
    elementos = [
        Paragraph(f"<b>Conciliação por competência — todos os contratos — exercício {ano}</b>", estilos["Heading3"]),
        Paragraph(
            "Valor liquidado por competência de cada contrato (relatório do Tesouro; quando só há nota do Contratos.gov, a "
            f"nota), em R$, ação 20RK. Gerado em {escape(gerado_em)}. {escape(AVISO_AJUSTE)}", pequeno,
        ),
        Spacer(1, 3 * mm),
    ]
    dados = [[Paragraph(f"<b>{c}</b>", cabecalho) for c in ["Contrato / credor", *MESES, "Total relat.", "Total notas"]]]
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b8c2cc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("FONTSIZE", (1, 1), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]
    totais: list[float | None] = [None] * 12
    for numero_linha, linha in enumerate(linhas, start=1):
        celulas = [Paragraph(f"<b>{escape(str(linha['contrato']))}</b><br/>{escape(_credor(linha))}", pequeno)]
        for mes in linha["meses"]:
            valor = _valor_do_mes(mes)
            if valor is not None:
                totais[mes["mes"] - 1] = (totais[mes["mes"] - 1] or 0.0) + valor
            marca = "*" if mes.get("notas_ajustadas") is not None else ""
            celulas.append(_brl(valor) + marca)
            cor = _COR_CLASSE.get(mes["classe"])
            if cor:
                estilo.append(("BACKGROUND", (mes["mes"], numero_linha), (mes["mes"], numero_linha), colors.HexColor(cor)))
        celulas += [_brl(linha["total_relatorio"]), _brl(linha.get("total_notas_ajustado", linha["total_notas"]))]
        dados.append(celulas)
    if linhas:
        soma = sum(v for v in totais if v is not None) if any(v is not None for v in totais) else None
        dados.append(["Total (relatório)", *[_brl(v) for v in totais], _brl(soma), ""])
        estilo.append(("FONTNAME", (0, len(dados) - 1), (-1, len(dados) - 1), "Helvetica-Bold"))
        estilo.append(("LINEABOVE", (0, len(dados) - 1), (-1, len(dados) - 1), 0.8, colors.black))
    primeira = 52 * mm
    restantes = (landscape(A4)[0] - 16 * mm - primeira) / 14
    tabela = Table(dados, colWidths=[primeira] + [restantes] * 14, repeatRows=1)
    tabela.setStyle(TableStyle(estilo))
    elementos.append(tabela)
    legenda = " · ".join(
        f'<font backColor="{cor}">&nbsp;{escape(CLASSES[c])}&nbsp;</font>'
        for c, cor in (("batem", "#c9ecd6"), ("deslocamento", "#cfe2f7"), ("ambiguo", "#f6cfd2"), ("so_notas", "#f8e0bd"))
    )
    elementos += [Spacer(1, 2 * mm), Paragraph(f"Cores: {legenda} (sem cor = sem registro).", pequeno)]
    documento.build(elementos)
    return buffer.getvalue()
