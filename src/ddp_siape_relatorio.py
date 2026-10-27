"""Relatório em Excel da aba "Folha (DDP)": reforço de empenhos e necessidade de dotação (27/10/2026).

Substitui a planilha anterior, que gravava as tabelas internas como estavam (nomes técnicos de
coluna, números sem formato, sem totais). Cada aba tem título, explicação curta, cabeçalho em
português, valores em reais com centavos, totais por fórmula, filtro e cabeçalho fixo. Nenhum
cálculo novo: tudo vem de `src.ddp_siape` (as mesmas tabelas que a aba mostra). Gerado em
memória — nada é gravado no servidor.

Abas: Resumo · Reforço por empenho · Plano por item · Dotação por ação e PO · Painel × quadro ·
Detalhe por item · Conferência da DDP.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.ddp_siape import OPERACAO_REFORCO, OPERACAO_REMANEJAR, SEM_ACAO, SEM_EMPENHO

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MOEDA = '#,##0.00;[Red]-#,##0.00'
PERCENTUAL = '0.00%'
LINHA_CABECALHO = 4  # título na 1, explicação na 2, cabeçalho na 4, dados a partir da 5

_FONTE = "Calibri"
_normal = Font(name=_FONTE, size=10)
_negrito = Font(name=_FONTE, size=10, bold=True)
_titulo = Font(name=_FONTE, size=13, bold=True, color="1F3864")
_secao = Font(name=_FONTE, size=11, bold=True, color="1F3864")
_nota = Font(name=_FONTE, size=9, italic=True, color="595959")
_borda = Border(*(Side(style="thin", color="BFBFBF"),) * 4)
_cabecalho_fill = PatternFill("solid", fgColor="DDEBF7")
_total_fill = PatternFill("solid", fgColor="F2F2F2")
_alerta_fill = PatternFill("solid", fgColor="F8CBAD")
_ok_fill = PatternFill("solid", fgColor="E2EFDA")
_quebra = Alignment(wrap_text=True, vertical="top")
_centro = Alignment(horizontal="center", vertical="center", wrap_text=True)


@dataclass
class DadosRelatorio:
    competencia: int
    procedencia: str
    conferencia: pd.DataFrame
    natureza: pd.DataFrame          # ddp_por_natureza
    por_empenho: pd.DataFrame
    itens: pd.DataFrame
    plano: pd.DataFrame
    confronto: pd.DataFrame
    rpps_itens: pd.DataFrame | None = None
    rpps_por_empenho: pd.DataFrame | None = None
    acao_po: pd.DataFrame | None = None
    conciliacao: pd.DataFrame | None = None
    ano_dotacao: int | None = None
    variacao: pd.DataFrame | None = None
    competencia_anterior: int | None = None


def mes_ano(ano_mes: int | None) -> str:
    return "—" if ano_mes is None else f"{MESES[ano_mes % 100 - 1]}/{ano_mes // 100}"


def _nota_empenho(nes) -> str:
    """'153165152392026NE000041' → '2026NE000041'; vários empenhos separados por vírgula."""
    if not nes:
        return SEM_EMPENHO
    return ", ".join(str(ne)[-12:] for ne in nes)


def _notas_por_empenho(itens: pd.DataFrame) -> dict[str, str]:
    return {e: _nota_empenho(n) for e, n in itens.groupby("empenho")["nes"].first().items()} if len(itens) else {}


# ------------------------------------------------------------------ escrita genérica

def _titulo_aba(ws, titulo: str, explicacao: str) -> None:
    ws.sheet_view.showGridLines = False
    ws["A1"], ws["A1"].font = titulo, _titulo
    ws["A2"], ws["A2"].font = explicacao, _nota


def _tabela(ws, linha: int, colunas: list[tuple[str, str, int]], dados: pd.DataFrame,
            totais: dict[str, str] | None = None, filtro: bool = True) -> int:
    """Escreve `dados` a partir de `linha` (cabeçalho). `colunas` = (título, campo, largura);
    o formato vem do tipo do campo: moeda para números, percentual se o campo terminar em `_pct`.
    `totais` = {campo: "soma"} gera uma linha de total com fórmula. Devolve a próxima linha livre."""
    for j, (titulo, _, largura) in enumerate(colunas, 1):
        c = ws.cell(row=linha, column=j, value=titulo)
        c.font, c.alignment, c.border, c.fill = _negrito, _centro, _borda, _cabecalho_fill
        letra = get_column_letter(j)
        ws.column_dimensions[letra].width = max(ws.column_dimensions[letra].width or 0, largura)
    ws.row_dimensions[linha].height = 32
    inicio = linha + 1
    for i, registro in enumerate(dados.itertuples(index=False)):
        r = inicio + i
        valores = registro._asdict()
        for j, (_, campo, _) in enumerate(colunas, 1):
            valor = valores.get(campo)
            if valor is not None and not isinstance(valor, str) and pd.isna(valor):
                valor = None
            if isinstance(valor, float):
                valor = round(valor, 6 if campo.endswith("_pct") else 2)
            c = ws.cell(row=r, column=j, value=valor)
            c.font, c.border = _normal, _borda
            if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                c.number_format = PERCENTUAL if campo.endswith("_pct") else MOEDA
            else:
                c.alignment = _quebra
    fim = inicio + len(dados) - 1
    proxima = fim + 1
    if totais and len(dados):
        for j, (_, campo, _) in enumerate(colunas, 1):
            c = ws.cell(row=proxima, column=j)
            c.font, c.border, c.fill = _negrito, _borda, _total_fill
            if j == 1:
                c.value = "Total"
            elif campo in totais:
                letra = get_column_letter(j)
                c.value, c.number_format = f"=SUM({letra}{inicio}:{letra}{fim})", MOEDA
        proxima += 1
    if filtro and len(dados):
        ws.auto_filter.ref = f"A{linha}:{get_column_letter(len(colunas))}{fim}"
    return proxima + 1


def _paragrafos(ws, linha: int, textos: list[str], largura_colunas: int = 8) -> int:
    for texto in textos:
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=largura_colunas)
        c = ws.cell(row=linha, column=1, value=texto)
        c.font, c.alignment = _normal, _quebra
        ws.row_dimensions[linha].height = 15 * (1 + len(texto) // 150)
        linha += 1
    return linha + 1


# ------------------------------------------------------------------ abas

def _resumo(wb: Workbook, d: DadosRelatorio) -> None:
    ws = wb.active
    ws.title = "Resumo"
    _titulo_aba(ws, f"Reforço de empenhos da folha — {mes_ano(d.competencia)}",
                "DDP e Crédito Bancário do SIAPE × saldo dos empenhos. " + d.procedencia)
    rpps = d.rpps_por_empenho if d.rpps_por_empenho is not None else pd.DataFrame(columns=["reforco_mes", "reforco_ate_dezembro"])
    anulacoes = float(d.plano.loc[d.plano["operacao"] == OPERACAO_REMANEJAR, "valor"].sum()) if len(d.plano) else 0.0
    indicadores = pd.DataFrame([
        ("DDP líquida do mês (servidor + pensionista)", float(d.natureza["liquido"].sum())),
        ("Falta nos itens dos empenhos da folha", float(d.por_empenho["falta"].sum())),
        ("Coberto anulando sobra de outro item da mesma NE", anulacoes),
        ("Reforço do mês — empenhos da folha", float(d.por_empenho["reforco_mes"].sum())),
        ("Reforço do mês — RPPS patronal (projeção)", float(rpps["reforco_mes"].sum())),
        ("Reforço até dezembro — empenhos da folha", float(d.por_empenho["reforco_ate_dezembro"].sum())),
        ("Reforço até dezembro — RPPS patronal (projeção)", float(rpps["reforco_ate_dezembro"].sum())),
    ], columns=["indicador", "valor"])
    linha = _tabela(ws, LINHA_CABECALHO, [("Indicador", "indicador", 52), ("Valor (R$)", "valor", 20)], indicadores, filtro=False)

    if d.acao_po is not None and len(d.acao_po):
        faltas = d.acao_po.loc[d.acao_po["saldo_apos_reforco"].round(2) < 0].assign(
            falta=lambda t: -t["saldo_apos_reforco"])
        ws.cell(row=linha, column=1, value="Onde o reforço até dezembro não cabe na dotação ainda não empenhada").font = _secao
        if len(faltas):
            linha = _tabela(ws, linha + 1, [("Ação / PO", "rotulo", 52), ("Falta de dotação (R$)", "falta", 20)],
                            faltas.assign(rotulo=faltas["acao_cod"] + " / " + faltas["po_cod"]), totais={"falta": "soma"},
                            filtro=False)
        else:
            ws.cell(row=linha + 1, column=1, value="Em nenhuma ação/PO.").font = _normal
            linha += 3
    _paragrafos(ws, linha, [
        "Como ler: saldo a liquidar = Empenhado − Liquidado do exercício, por item (NE × natureza detalhada), só nos "
        "empenhos cujo favorecido é a própria UG. Falta = DDP − saldo. Sobra livre = saldo − DDP − reserva dos meses "
        "seguintes (projeção do painel). A falta de um item é coberta pela sobra livre de outro item da mesma NE "
        "(aba Plano por item); o que sobra é reforço novo.",
        "O RPPS patronal não está na DDP: o valor do mês e a reserva vêm da projeção do painel (patronal acompanhando "
        "vencimentos + gratificação do Ativo).",
        "Os valores da DDP são líquidos (bruto − descontos), não a liquidação do SIAFI. Ação/PO sem dotação na base "
        "fica em branco, não como zero.",
    ], largura_colunas=2)
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 60, 22


def _reforco_por_empenho(wb: Workbook, d: DadosRelatorio) -> None:
    ws = wb.create_sheet("Reforço por empenho")
    _titulo_aba(ws, "Reforço por empenho",
                "Saldo a liquidar × folha do mês. Reforço do mês = falta − o que se cobre anulando sobra de outro item da mesma "
                "NE. Reforço até dezembro = DDP + reserva dos meses seguintes − saldo, quando positivo.")
    colunas = [("Empenho", "empenho", 22), ("Nota de empenho", "nota", 26), ("Ação", "acao_cod", 8),
               ("Saldo a liquidar", "saldo", 17), ("Folha do mês", "ddp", 17), ("Falta nos itens", "falta", 16),
               ("Sobra livre nos itens", "sobra_livre", 17), ("Coberto na própria NE", "compensa", 17),
               ("Reforço do mês", "reforco_mes", 17), ("Reserva dos meses seguintes", "reserva", 18),
               ("Reforço até dezembro", "reforco_ate_dezembro", 18)]
    soma = {c: "soma" for _, c, _ in colunas[3:]}
    ws.cell(row=LINHA_CABECALHO - 1, column=1, value="Empenhos da folha (DDP)").font = _secao
    notas = _notas_por_empenho(d.itens)
    linha = _tabela(ws, LINHA_CABECALHO, colunas, d.por_empenho.assign(nota=d.por_empenho["empenho"].map(notas)), soma, filtro=False)
    if d.rpps_por_empenho is not None and len(d.rpps_por_empenho):
        ws.cell(row=linha, column=1, value="RPPS patronal — folha do mês = projeção do painel (não vem na DDP)").font = _secao
        notas_rpps = _notas_por_empenho(d.rpps_itens)
        _tabela(ws, linha + 1, colunas, d.rpps_por_empenho.assign(nota=d.rpps_por_empenho["empenho"].map(notas_rpps)),
                soma, filtro=False)
    ws.freeze_panes = ws.cell(row=LINHA_CABECALHO + 1, column=2)


def _plano(wb: Workbook, d: DadosRelatorio) -> None:
    ws = wb.create_sheet("Plano por item")
    _titulo_aba(ws, "Plano de anulação e reforço por item",
                "Em cada empenho, o item com maior falta recebe primeiro, da maior sobra livre; o que a sobra não cobre é "
                "reforço novo. Nenhum item cede mais que a sobra livre (todos mantêm a reserva dos meses seguintes).")
    descricao = (d.itens.dropna(subset=["descricao"]).drop_duplicates("natureza_detalhada")
                 .set_index("natureza_detalhada")["descricao"].to_dict()) if len(d.itens) else {}
    notas = _notas_por_empenho(d.itens)
    plano = d.plano.assign(
        nota=d.plano["empenho"].map(notas),
        operacao=d.plano["operacao"].str.capitalize(),
        origem_desc=d.plano["item_origem"].map(lambda n: descricao.get(n) if isinstance(n, str) else None),
        destino_desc=d.plano["item_destino"].map(descricao.get),
    )
    colunas = [("Empenho", "empenho", 20), ("Nota de empenho", "nota", 24), ("Operação", "operacao", 32),
               ("Anular do item", "item_origem", 12), ("Descrição (anular)", "origem_desc", 36),
               ("Reforçar o item", "item_destino", 12), ("Descrição (reforçar)", "destino_desc", 36), ("Valor (R$)", "valor", 17)]
    linha = _tabela(ws, LINHA_CABECALHO, colunas, plano, {"valor": "soma"})
    resumo = pd.DataFrame([
        ("Anular e reforçar no mesmo empenho", float(d.plano.loc[d.plano["operacao"] == OPERACAO_REMANEJAR, "valor"].sum())),
        ("Reforço novo", float(d.plano.loc[d.plano["operacao"] == OPERACAO_REFORCO, "valor"].sum())),
    ], columns=["tipo", "valor"]) if len(d.plano) else pd.DataFrame(columns=["tipo", "valor"])
    ws.cell(row=linha, column=1, value="Por tipo de operação").font = _secao
    _tabela(ws, linha + 1, [("Operação", "tipo", 20), ("Valor (R$)", "valor", 17)], resumo, {"valor": "soma"}, filtro=False)
    ws.freeze_panes = ws.cell(row=LINHA_CABECALHO + 1, column=1)


def _acao_po(wb: Workbook, d: DadosRelatorio) -> None:
    if d.acao_po is None or not len(d.acao_po):
        return
    ws = wb.create_sheet("Dotação por ação e PO")
    _titulo_aba(ws, f"O reforço cabe na dotação? (Dotação Atualizada de {d.ano_dotacao})",
                "Disponível = dotação − tudo o que já foi empenhado na Ação/PO no exercício. Entram só os reforços desta "
                f"planilha (folha e RPPS). “{SEM_ACAO}”: empenho agrupado com Ação/PO diferentes, ou natureza sem empenho.")
    tabela = d.acao_po.assign(situacao=d.acao_po["saldo_apos_reforco"].map(
        lambda v: "Sem dotação na base" if pd.isna(v) else ("Não cabe" if round(v, 2) < 0 else "Cabe")))
    colunas = [("Ação", "acao_cod", 9), ("PO", "po_cod", 8), ("Dotação atualizada", "dotacao", 18), ("Empenhado", "empenhado", 18),
               ("Disponível para empenhar", "disponivel", 18), ("Reforço do mês", "reforco_mes", 16),
               ("Reforço até dezembro", "reforco_ate_dezembro", 18), ("Disponível − reforço", "saldo_apos_reforco", 18),
               ("Situação", "situacao", 16), ("Sobra nos empenhos (anulável)", "sobra_empenhos", 18),
               ("Empenhos com reforço", "empenhos", 40)]
    _tabela(ws, LINHA_CABECALHO, colunas, tabela,
            {c: "soma" for c in ("dotacao", "empenhado", "disponivel", "reforco_mes", "reforco_ate_dezembro", "sobra_empenhos")})
    for r in range(LINHA_CABECALHO + 1, LINHA_CABECALHO + 1 + len(tabela)):
        situacao = ws.cell(row=r, column=9)
        situacao.fill = _alerta_fill if situacao.value == "Não cabe" else (_ok_fill if situacao.value == "Cabe" else PatternFill())
    ws.freeze_panes = ws.cell(row=LINHA_CABECALHO + 1, column=3)


def _conciliacao(wb: Workbook, d: DadosRelatorio) -> None:
    if d.conciliacao is None or not len(d.conciliacao):
        return
    ws = wb.create_sheet("Painel × quadro")
    _titulo_aba(ws, "Do saldo do painel ao saldo do quadro, por ação",
                "Saldo do painel = dotação − total do ano projetado. Saldo do quadro = dotação − empenhado − reforço até dezembro. "
                "A diferença é a soma das parcelas; a última coluna deve ser zero.")
    colunas = [("Ação", "acao_cod", 9), ("Grupo", "grupo", 18), ("Dotação", "dotacao", 18), ("Total projetado no painel", "total_painel", 19),
               ("Saldo no painel", "saldo_painel", 17), ("+ Projeção fora do quadro", "projecao_fora", 18),
               ("+ Executado fora dos empenhos do quadro", "executado_fora", 20), ("− Empenhado fora dos quadros", "empenhado_fora", 19),
               ("− Sobra nos empenhos do quadro", "sobras", 18), ("= Saldo no quadro", "saldo_quadro", 17),
               ("Diferença não explicada", "diferenca", 15)]
    _tabela(ws, LINHA_CABECALHO, colunas, d.conciliacao, filtro=False)


def _detalhe(wb: Workbook, d: DadosRelatorio) -> None:
    ws = wb.create_sheet("Detalhe por item")
    _titulo_aba(ws, "Detalhe por item (nota de empenho × natureza detalhada)",
                "Critério: como a folha da natureza foi atribuída ao empenho. Reserva: de onde vem o consumo dos meses seguintes.")
    partes = [d.itens.assign(origem="Folha (DDP)")]
    if d.rpps_itens is not None and len(d.rpps_itens):
        partes.append(d.rpps_itens.assign(origem="RPPS patronal (projeção)"))
    itens = pd.concat(partes, ignore_index=True)
    itens = itens.assign(nota=itens["nes"].map(_nota_empenho))
    colunas = [("Origem", "origem", 18), ("Empenho", "empenho", 20), ("Nota de empenho", "nota", 24), ("Ação", "acao_cod", 8),
               ("Natureza", "natureza_detalhada", 11), ("Descrição", "descricao", 38), ("Empenhado", "empenhada", 17),
               ("Liquidado", "liquidada", 17), ("Saldo a liquidar", "saldo", 17), ("Folha do mês", "ddp", 16), ("Falta", "falta", 15),
               ("Reserva dos meses seguintes", "reserva", 17), ("Sobra livre", "sobra_livre", 16),
               ("Saldo depois de dezembro", "saldo_apos_ano", 17), ("Critério", "criterio", 30), ("Reserva por", "tipo_reserva", 20),
               ("Já liquidado no mês", "liquidado_no_mes", 16)]
    _tabela(ws, LINHA_CABECALHO, colunas, itens,
            {c: "soma" for c in ("empenhada", "liquidada", "saldo", "ddp", "falta", "reserva", "sobra_livre", "saldo_apos_ano")})
    ws.freeze_panes = ws.cell(row=LINHA_CABECALHO + 1, column=4)


def _conferencia(wb: Workbook, d: DadosRelatorio) -> None:
    ws = wb.create_sheet("Conferência da DDP")
    _titulo_aba(ws, "Conferência da DDP e confronto com a Liquidada",
                "Bruto − descontos = líquido = crédito bancário. Diferença em branco = termo não enviado (não é zero).")
    conf = d.conferencia.assign(competencia_txt=d.conferencia["competencia"].map(mes_ano),
                                publico=d.conferencia["publico"].str.title())
    linha = _tabela(ws, LINHA_CABECALHO, [
        ("Competência", "competencia_txt", 12), ("Público", "publico", 14), ("Bruto", "bruto", 18), ("Descontos", "desconto", 18),
        ("Líquido", "liquido", 18), ("Crédito bancário", "credito_bancario", 18), ("Dif. crédito − líquido", "dif_credito", 16),
        ("Dif. bruto − descontos − líquido", "dif_bruto_menos_desconto", 18), ("Dif. naturezas − bruto", "dif_naturezas_bruto", 16),
    ], conf, filtro=False)
    if d.variacao is not None and len(d.variacao):
        ws.cell(row=linha, column=1, value=f"O que mudou de {mes_ano(d.competencia_anterior)} para {mes_ano(d.competencia)}").font = _secao
        situacoes = {"nova": "Nova", "saiu": "Não veio neste mês", "alta": "Alta", "queda": "Queda", "sem variação": "Sem variação"}
        linha = _tabela(ws, linha + 1, [
            ("Natureza", "natureza_detalhada", 12), ("Descrição", "descricao", 40), ("Mês anterior", "anterior", 18),
            ("Mês atual", "atual", 18), ("Variação", "variacao", 18), ("Situação", "situacao_txt", 18),
        ], d.variacao.assign(situacao_txt=d.variacao["situacao"].map(situacoes)), {"anterior": "soma", "atual": "soma", "variacao": "soma"},
            filtro=False)
    ws.cell(row=linha, column=1, value=f"DDP × Liquidada na base em {mes_ano(d.competencia)}").font = _secao
    _tabela(ws, linha + 1, [("Natureza", "natureza_detalhada", 12), ("Descrição", "descricao", 40), ("DDP líquida", "ddp", 18),
                            ("Liquidada na base", "liquidado_no_mes", 18), ("Diferença (base − DDP)", "diferenca", 18)],
            d.confronto, {"ddp": "soma", "liquidado_no_mes": "soma", "diferenca": "soma"}, filtro=False)


def relatorio_excel(d: DadosRelatorio) -> bytes:
    wb = Workbook()
    _resumo(wb, d)
    _reforco_por_empenho(wb, d)
    _plano(wb, d)
    _acao_po(wb, d)
    _conciliacao(wb, d)
    _detalhe(wb, d)
    _conferencia(wb, d)
    for ws in wb.worksheets:
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    arquivo = BytesIO()
    wb.save(arquivo)
    return arquivo.getvalue()
