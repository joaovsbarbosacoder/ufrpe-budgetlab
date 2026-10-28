"""Relatório em Excel da aba "Folha (DDP)": reforço de empenhos e necessidade de dotação (27/10/2026).

Cada aba tem título, explicação curta, cabeçalho em português claro, valores em reais com
centavos, totais por fórmula, filtro e cabeçalho fixo. Nenhum cálculo novo: tudo vem de
`src.ddp_siape` (as mesmas tabelas que a aba mostra). Gerado em memória — nada é gravado.

Três visões do mesmo problema (pedido do usuário, 27/10/2026: a anulação será feita, mas talvez
não seja o momento):
- Somente reforço — reforçar agora o valor inteiro de cada item com falta, sem anular nada;
- Sugestões de anulação — o que pode ser anulado sem faltar em novembro e dezembro;
- Anulação + reforço — o plano combinado (a falta é coberta primeiro pela sobra da mesma NE).

Abas: Resumo · Somente reforço · Sugestões de anulação · Anulação + reforço · Por empenho (com
anulação) · Dotação por ação e PO · Conciliação com o painel · Detalhe por item · Conferência da DDP.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from src.ddp_siape import (
    OPERACAO_REFORCO, OPERACAO_REMANEJAR, SEM_ACAO, SEM_EMPENHO, por_empenho_somente_reforco, somente_reforco,
    sugestoes_anulacao,
)

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MOEDA = '#,##0.00;[Red]-#,##0.00'
PERCENTUAL = '0.00%'
LINHA_CABECALHO = 4  # título na 1, explicação na 2, cabeçalho na 4, dados a partir da 5

#: rótulos de tela/relatório para os valores internos (as constantes de cálculo não mudam)
OPERACOES = {OPERACAO_REMANEJAR: "Remanejar entre itens do empenho", OPERACAO_REFORCO: "Reforçar o empenho (valor novo)"}
CRITERIOS = {"fora da DDP": "item sem folha no mês"}

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
    #: `reforco_por_acao_po` com `por_empenho_somente_reforco` (cenário sem anulação agora)
    acao_po_somente_reforco: pd.DataFrame | None = None
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


def _notas_por_empenho(itens: pd.DataFrame | None) -> dict[str, str]:
    if itens is None or not len(itens):
        return {}
    return {e: _nota_empenho(n) for e, n in itens.groupby("empenho")["nes"].first().items()}


def _situacao(valor) -> str:
    return "Sem dotação na base" if pd.isna(valor) else ("Não cabe" if round(valor, 2) < 0 else "Cabe")


# ------------------------------------------------------------------ escrita genérica

def _titulo_aba(ws, titulo: str, explicacao: str) -> None:
    ws.sheet_view.showGridLines = False
    ws["A1"], ws["A1"].font = titulo, _titulo
    ws["A2"], ws["A2"].font = explicacao, _nota


def _tabela(ws, linha: int, colunas: list[tuple[str, str, int]], dados: pd.DataFrame,
            totais: set[str] | None = None, filtro: bool = True) -> int:
    """Escreve `dados` a partir de `linha` (cabeçalho). `colunas` = (título, campo, largura); número
    vira moeda (percentual se o campo terminar em `_pct`). `totais` = campos somados por fórmula
    numa linha "Total". Devolve a próxima linha livre (com uma em branco)."""
    for j, (titulo, _, largura) in enumerate(colunas, 1):
        c = ws.cell(row=linha, column=j, value=titulo)
        c.font, c.alignment, c.border, c.fill = _negrito, _centro, _borda, _cabecalho_fill
        letra = get_column_letter(j)
        ws.column_dimensions[letra].width = max(ws.column_dimensions[letra].width or 0, largura)
    ws.row_dimensions[linha].height = 42
    inicio = linha + 1
    for i, registro in enumerate(dados.itertuples(index=False)):
        valores = registro._asdict()
        for j, (_, campo, _) in enumerate(colunas, 1):
            valor = valores.get(campo)
            if valor is not None and not isinstance(valor, (str, tuple)) and pd.isna(valor):
                valor = None
            if isinstance(valor, float):
                valor = round(valor, 6 if campo.endswith("_pct") else 2)
            c = ws.cell(row=inicio + i, column=j, value=valor)
            c.font, c.border = _normal, _borda
            if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                c.number_format = PERCENTUAL if campo.endswith("_pct") else MOEDA
            else:
                c.alignment = _quebra
            if campo == "situacao" and valor in ("Não cabe", "Cabe"):
                c.fill = _alerta_fill if valor == "Não cabe" else _ok_fill
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


def _secao_titulo(ws, linha: int, texto: str) -> int:
    ws.cell(row=linha, column=1, value=texto).font = _secao
    return linha + 1


def _paragrafos(ws, linha: int, textos: list[str], colunas: int) -> int:
    for texto in textos:
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=colunas)
        c = ws.cell(row=linha, column=1, value=texto)
        c.font, c.alignment = _normal, _quebra
        ws.row_dimensions[linha].height = 15 * (1 + len(texto) // 130)
        linha += 1
    return linha + 1


def _com_origem(d: DadosRelatorio, tabela_folha: pd.DataFrame, tabela_rpps: pd.DataFrame | None) -> pd.DataFrame:
    partes = [tabela_folha.assign(origem="Folha (DDP)")]
    if tabela_rpps is not None and len(tabela_rpps):
        partes.append(tabela_rpps.assign(origem="RPPS patronal (projeção)"))
    tabela = pd.concat(partes, ignore_index=True)
    return tabela.assign(nota=tabela["nes"].map(_nota_empenho)) if "nes" in tabela else tabela


def _colunas_dotacao(saldo_titulo: str) -> list[tuple[str, str, int]]:
    return [("Ação", "acao_cod", 9), ("PO", "po_cod", 8), ("Dotação atualizada", "dotacao", 18), ("Empenhado", "empenhado", 18),
            ("Dotação ainda não empenhada", "disponivel", 18), ("Reforço necessário para o mês", "reforco_mes", 16),
            ("Reforço necessário até dezembro", "reforco_ate_dezembro", 18), (saldo_titulo, "saldo_apos_reforco", 20),
            ("Situação", "situacao", 16), ("Sobra prevista em dezembro nos empenhos", "sobra_empenhos", 19),
            ("Notas de empenho que precisam de reforço", "empenhos", 40)]


# ------------------------------------------------------------------ abas

def _resumo(wb: Workbook, d: DadosRelatorio, mes: str, ano: int) -> None:
    ws = wb.active
    ws.title = "Resumo"
    _titulo_aba(ws, f"Reforço de empenhos da folha — {mes}", "DDP e Crédito Bancário do SIAPE × saldo dos empenhos. " + d.procedencia)
    rpps = d.rpps_por_empenho if d.rpps_por_empenho is not None else pd.DataFrame(columns=["reforco_mes", "reforco_ate_dezembro"])
    so = por_empenho_somente_reforco(d.itens)
    anulacoes = float(d.plano.loc[d.plano["operacao"] == OPERACAO_REMANEJAR, "valor"].sum()) if len(d.plano) else 0.0
    cenarios = pd.DataFrame([
        (f"Reforço necessário para {mes} — empenhos da folha", float(so["reforco_mes"].sum()), float(d.por_empenho["reforco_mes"].sum())),
        (f"Reforço necessário para {mes} — RPPS patronal", float(rpps["reforco_mes"].sum()), float(rpps["reforco_mes"].sum())),
        (f"Reforço necessário até dez/{ano} — empenhos da folha", float(so["reforco_ate_dezembro"].sum()),
         float(d.por_empenho["reforco_ate_dezembro"].sum())),
        (f"Reforço necessário até dez/{ano} — RPPS patronal", float(rpps["reforco_ate_dezembro"].sum()),
         float(rpps["reforco_ate_dezembro"].sum())),
        ("Anulações (remanejamento entre itens do mesmo empenho)", 0.0, anulacoes),
        ("Sobra que ficaria parada nos empenhos em dezembro", float(so["sobra_parada"].sum()),
         float(d.por_empenho["saldo_apos_ano"].clip(lower=0).sum())),
    ], columns=["indicador", "somente", "misto"])
    linha = _secao_titulo(ws, LINHA_CABECALHO - 1, "Cenários")
    linha = _tabela(ws, linha, [("Indicador", "indicador", 58), ("Somente reforço (sem anular agora)", "somente", 22),
                                ("Anulação + reforço", "misto", 22)], cenarios, filtro=False)
    gerais = pd.DataFrame([
        ("Folha do mês pela DDP (servidor + pensionista, bruta: sem abater as despesas a anular)", float(d.natureza["despesa"].sum())),
        ("Sobra que pode ser anulada sem faltar em nov e dez (aba Sugestões de anulação)", float(d.itens["sobra_livre"].sum())),
    ], columns=["indicador", "valor"])
    linha = _tabela(ws, linha, [("Outros totais", "indicador", 58), ("Valor (R$)", "valor", 22)], gerais, filtro=False)

    for titulo, tabela in (("Onde o reforço não cabe na dotação — somente reforço", d.acao_po_somente_reforco),
                           ("Onde o reforço não cabe na dotação — anulação + reforço", d.acao_po)):
        if tabela is None or not len(tabela):
            continue
        faltas = tabela.loc[tabela["saldo_apos_reforco"].round(2) < 0]
        linha = _secao_titulo(ws, linha, titulo)
        if len(faltas):
            faltas = faltas.assign(rotulo=faltas["acao_cod"] + " / " + faltas["po_cod"], falta=-faltas["saldo_apos_reforco"])
            linha = _tabela(ws, linha, [("Ação / PO", "rotulo", 58), ("Falta de dotação (R$)", "falta", 22)], faltas, {"falta"}, filtro=False)
        else:
            ws.cell(row=linha, column=1, value="Em nenhuma ação/PO.").font = _normal
            linha += 2
    _paragrafos(ws, linha, [
        "Somente reforço: cada item com falta recebe o valor inteiro, sem anular nada agora. Os itens com sobra (por "
        "exemplo, o 13º) continuam empenhados, e essa sobra fica parada até ser anulada.",
        "Anulação + reforço: a falta de um item é coberta primeiro pela sobra de outro item do mesmo empenho (aba "
        "Anulação + reforço); o que a sobra não cobre é reforço novo. Quando a anulação for feita, a necessidade cai do "
        "primeiro cenário para este.",
        "Saldo do empenho = empenhado − liquidado no exercício, por item (nota de empenho × natureza). O RPPS patronal não "
        "é natureza da DDP: o valor do mês vem das rubricas de PSS da DDP de servidores × 2 (ou da projeção do painel, sem elas). O valor da folha usado no reforço é o BRUTO da DDP "
        "(seção de despesas correntes): as despesas a anular não reduzem a necessidade de reforço do empenho.",
    ], colunas=3)


def _somente_reforco(wb: Workbook, d: DadosRelatorio, mes: str, ano: int) -> None:
    ws = wb.create_sheet("Somente reforço")
    _titulo_aba(ws, "Somente reforço (sem anulação agora)",
                "Reforço do valor inteiro de cada item com falta, sem usar a sobra de outro item. Quando a anulação for "
                "feita, a necessidade cai para a da aba Anulação + reforço.")
    itens = _com_origem(d, somente_reforco(d.itens), somente_reforco(d.rpps_itens) if d.rpps_itens is not None else None)
    linha = _tabela(ws, LINHA_CABECALHO, [
        ("Origem", "origem", 18), ("Nota de empenho", "nota", 24), ("Ação", "acao_cod", 8), ("Natureza", "natureza_detalhada", 11),
        ("Descrição", "descricao", 36), ("Saldo do empenho (empenhado − liquidado)", "saldo", 18), (f"Folha de {mes}", "ddp", 17),
        ("Necessidade de nov e dez (projeção)", "reserva", 18), (f"Reforço necessário para {mes}", "reforco_mes", 18),
        (f"Reforço necessário até dez/{ano}", "reforco_ate_dezembro", 18),
    ], itens, {"saldo", "ddp", "reserva", "reforco_mes", "reforco_ate_dezembro"})
    partes = [por_empenho_somente_reforco(d.itens).assign(origem="Folha (DDP)")]
    if d.rpps_itens is not None and len(d.rpps_itens):
        partes.append(por_empenho_somente_reforco(d.rpps_itens).assign(origem="RPPS patronal (projeção)"))
    por_empenho = pd.concat(partes, ignore_index=True)
    notas = {**_notas_por_empenho(d.itens), **_notas_por_empenho(d.rpps_itens)}
    por_empenho = por_empenho.assign(nota=por_empenho["empenho"].map(notas))
    linha = _secao_titulo(ws, linha, "Por nota de empenho")
    linha = _tabela(ws, linha, [
        ("Origem", "origem", 18), ("Nota de empenho", "nota", 24), ("Ação", "acao_cod", 8),
        (f"Reforço necessário para {mes}", "reforco_mes", 18), (f"Reforço necessário até dez/{ano}", "reforco_ate_dezembro", 18),
        ("Sobra que ficaria parada em dezembro (sem anular)", "sobra_parada", 20),
    ], por_empenho, {"reforco_mes", "reforco_ate_dezembro", "sobra_parada"}, filtro=False)
    if d.acao_po_somente_reforco is not None and len(d.acao_po_somente_reforco):
        linha = _secao_titulo(ws, linha, f"O reforço cabe na dotação? (Dotação Atualizada de {d.ano_dotacao}, sem anulação)")
        tabela = d.acao_po_somente_reforco.assign(situacao=d.acao_po_somente_reforco["saldo_apos_reforco"].map(_situacao))
        _tabela(ws, linha, _colunas_dotacao("Sobra (+) ou falta (−) de dotação após o reforço"), tabela,
                {"dotacao", "empenhado", "disponivel", "reforco_mes", "reforco_ate_dezembro", "sobra_empenhos"}, filtro=False)
    ws.freeze_panes = ws.cell(row=LINHA_CABECALHO + 1, column=3)


def _sugestoes_anulacao(wb: Workbook, d: DadosRelatorio, mes: str) -> None:
    ws = wb.create_sheet("Sugestões de anulação")
    _titulo_aba(ws, "Sugestões de anulação",
                "Itens que podem ser anulados sem faltar em novembro e dezembro: saldo − folha do mês − necessidade de nov e "
                "dez. “Usado no plano” é a parte que a aba Anulação + reforço usa para cobrir faltas do mesmo empenho.")
    tabela = sugestoes_anulacao(d.itens, d.plano)
    tabela = tabela.assign(nota=tabela["nes"].map(_nota_empenho))
    _tabela(ws, LINHA_CABECALHO, [
        ("Nota de empenho", "nota", 24), ("Ação", "acao_cod", 8), ("Natureza", "natureza_detalhada", 11), ("Descrição", "descricao", 36),
        ("Saldo do empenho (empenhado − liquidado)", "saldo", 18), (f"Folha de {mes}", "ddp", 17),
        ("Necessidade de nov e dez (projeção)", "reserva", 18), ("Pode ser anulado", "pode_anular", 17),
        ("Usado no plano Anulação + reforço", "usado_no_plano", 18), ("Restante após o plano", "restante", 17),
    ], tabela, {"saldo", "ddp", "reserva", "pode_anular", "usado_no_plano", "restante"})
    ws.freeze_panes = ws.cell(row=LINHA_CABECALHO + 1, column=2)


def _anulacao_reforco(wb: Workbook, d: DadosRelatorio) -> None:
    ws = wb.create_sheet("Anulação + reforço")
    _titulo_aba(ws, "Anulação + reforço, item a item",
                "Em cada empenho, o item com maior falta recebe primeiro, do item com maior sobra; o que a sobra não cobre é "
                "reforço novo. Nenhum item cede mais do que pode sem faltar em novembro e dezembro.")
    descricao = (d.itens.dropna(subset=["descricao"]).drop_duplicates("natureza_detalhada")
                 .set_index("natureza_detalhada")["descricao"].to_dict()) if len(d.itens) else {}
    notas = _notas_por_empenho(d.itens)
    plano = d.plano.assign(
        nota=d.plano["empenho"].map(notas), operacao=d.plano["operacao"].map(OPERACOES),
        origem_desc=d.plano["item_origem"].map(lambda n: descricao.get(n) if isinstance(n, str) else None),
        destino_desc=d.plano["item_destino"].map(descricao.get),
    )
    linha = _tabela(ws, LINHA_CABECALHO, [
        ("Nota de empenho", "nota", 24), ("Operação", "operacao", 30), ("Item que cede (anular)", "item_origem", 12),
        ("Descrição do item que cede", "origem_desc", 36), ("Item que recebe (reforçar)", "item_destino", 12),
        ("Descrição do item que recebe", "destino_desc", 36), ("Valor (R$)", "valor", 17),
    ], plano, {"valor"})
    resumo = pd.DataFrame([
        (OPERACOES[OPERACAO_REMANEJAR], float(d.plano.loc[d.plano["operacao"] == OPERACAO_REMANEJAR, "valor"].sum())),
        (OPERACOES[OPERACAO_REFORCO], float(d.plano.loc[d.plano["operacao"] == OPERACAO_REFORCO, "valor"].sum())),
    ], columns=["tipo", "valor"]) if len(d.plano) else pd.DataFrame(columns=["tipo", "valor"])
    linha = _secao_titulo(ws, linha, "Por tipo de operação")
    _tabela(ws, linha, [("Operação", "tipo", 24), ("Valor (R$)", "valor", 30)], resumo, {"valor"}, filtro=False)
    ws.freeze_panes = ws.cell(row=LINHA_CABECALHO + 1, column=2)


def _por_empenho(wb: Workbook, d: DadosRelatorio, mes: str, ano: int) -> None:
    ws = wb.create_sheet("Por empenho (com anulação)")
    _titulo_aba(ws, "Por nota de empenho — anulação + reforço",
                "Reforço necessário para o mês = falta − o que se cobre remanejando dentro do empenho. Até dezembro = folha do "
                "mês + necessidade de nov e dez − saldo, quando positivo.")
    colunas = [("Nota de empenho", "nota", 26), ("Ação", "acao_cod", 8), ("Saldo do empenho (empenhado − liquidado)", "saldo", 18),
               (f"Folha de {mes}", "ddp", 17), ("Falta para pagar a folha do mês", "falta", 17), ("Sobra que pode ser anulada", "sobra_livre", 17),
               ("Coberto por remanejamento dentro do empenho", "compensa", 19), (f"Reforço necessário para {mes}", "reforco_mes", 18),
               ("Necessidade de nov e dez (projeção)", "reserva", 18), (f"Reforço necessário até dez/{ano}", "reforco_ate_dezembro", 18)]
    soma = {c for _, c, _ in colunas[2:]}
    linha = _secao_titulo(ws, LINHA_CABECALHO - 1, "Empenhos da folha (DDP)")
    notas = _notas_por_empenho(d.itens)
    linha = _tabela(ws, linha, colunas, d.por_empenho.assign(nota=d.por_empenho["empenho"].map(notas)), soma, filtro=False)
    if d.rpps_por_empenho is not None and len(d.rpps_por_empenho):
        linha = _secao_titulo(ws, linha, f"RPPS patronal — a folha de {mes} vem das rubricas de PSS da DDP × 2 (ou da projeção do painel, sem elas)")
        notas_rpps = _notas_por_empenho(d.rpps_itens)
        _tabela(ws, linha, colunas, d.rpps_por_empenho.assign(nota=d.rpps_por_empenho["empenho"].map(notas_rpps)), soma, filtro=False)
    ws.freeze_panes = ws.cell(row=LINHA_CABECALHO + 1, column=2)


def _acao_po(wb: Workbook, d: DadosRelatorio) -> None:
    if d.acao_po is None or not len(d.acao_po):
        return
    ws = wb.create_sheet("Dotação por ação e PO")
    _titulo_aba(ws, f"O reforço cabe na dotação? (Dotação Atualizada de {d.ano_dotacao}, com anulação)",
                "Dotação ainda não empenhada = dotação − tudo o que já foi empenhado na Ação/PO no exercício. Entram só os "
                f"reforços deste relatório (folha e RPPS). “{SEM_ACAO}”: empenho agrupado com Ação/PO diferentes ou natureza sem empenho.")
    tabela = d.acao_po.assign(situacao=d.acao_po["saldo_apos_reforco"].map(_situacao))
    _tabela(ws, LINHA_CABECALHO, _colunas_dotacao("Sobra (+) ou falta (−) de dotação após o reforço"), tabela,
            {"dotacao", "empenhado", "disponivel", "reforco_mes", "reforco_ate_dezembro", "sobra_empenhos"})
    ws.freeze_panes = ws.cell(row=LINHA_CABECALHO + 1, column=3)


def _conciliacao(wb: Workbook, d: DadosRelatorio) -> None:
    if d.conciliacao is None or not len(d.conciliacao):
        return
    ws = wb.create_sheet("Conciliação com o painel")
    _titulo_aba(ws, "Conciliação com o painel, por ação",
                "Por que o saldo deste relatório (dotação − empenhado − reforço) difere do saldo do painel (dotação − despesa "
                "projetada no ano): a soma das parcelas explica a diferença, e a última coluna deve ser zero.")
    _tabela(ws, LINHA_CABECALHO, [
        ("Ação", "acao_cod", 9), ("Grupo", "grupo", 18), ("Dotação", "dotacao", 18), ("Despesa projetada no ano (painel)", "total_painel", 19),
        ("Saldo da dotação pela projeção do painel", "saldo_painel", 19), ("+ Despesa projetada fora dos empenhos da folha", "projecao_fora", 20),
        ("+ Já liquidado por outras notas da ação", "executado_fora", 19), ("− Empenhado em outras notas da ação", "empenhado_fora", 19),
        ("− Sobra prevista nos empenhos da folha", "sobras", 18), ("= Saldo da dotação após os reforços", "saldo_quadro", 19),
        ("Diferença (deve ser zero)", "diferenca", 14),
    ], d.conciliacao, filtro=False)


def _detalhe(wb: Workbook, d: DadosRelatorio, mes: str) -> None:
    ws = wb.create_sheet("Detalhe por item")
    _titulo_aba(ws, "Detalhe por item (nota de empenho × natureza)",
                "Como a folha foi atribuída ao empenho e de onde vem a necessidade de novembro e dezembro.")
    itens = _com_origem(d, d.itens, d.rpps_itens)
    itens = itens.assign(criterio=itens["criterio"].map(lambda c: CRITERIOS.get(c, c)))
    _tabela(ws, LINHA_CABECALHO, [
        ("Origem", "origem", 18), ("Nota de empenho", "nota", 24), ("Ação", "acao_cod", 8), ("Natureza", "natureza_detalhada", 11),
        ("Descrição", "descricao", 36), ("Empenhado", "empenhada", 17), ("Liquidado", "liquidada", 17),
        ("Saldo do empenho (empenhado − liquidado)", "saldo", 18), (f"Folha de {mes}", "ddp", 16),
        ("Falta para pagar a folha do mês", "falta", 16), ("Necessidade de nov e dez (projeção)", "reserva", 18),
        ("Sobra que pode ser anulada", "sobra_livre", 16), ("Sobra (+) ou falta (−) em dezembro", "saldo_apos_ano", 18),
        ("Como a folha foi atribuída ao empenho", "criterio", 30), ("Base da necessidade de nov e dez", "tipo_reserva", 20),
        (f"Já liquidado em {mes}", "liquidado_no_mes", 16),
    ], itens, {"empenhada", "liquidada", "saldo", "ddp", "falta", "reserva", "sobra_livre", "saldo_apos_ano"})
    ws.freeze_panes = ws.cell(row=LINHA_CABECALHO + 1, column=3)


def _conferencia(wb: Workbook, d: DadosRelatorio, mes: str) -> None:
    ws = wb.create_sheet("Conferência da DDP")
    _titulo_aba(ws, "Conferência da DDP e confronto com o liquidado",
                "Bruto − descontos = líquido = crédito bancário. Diferença em branco = documento não enviado (não é zero).")
    conf = d.conferencia.assign(competencia_txt=d.conferencia["competencia"].map(mes_ano), publico=d.conferencia["publico"].str.title())
    linha = _tabela(ws, LINHA_CABECALHO, [
        ("Competência", "competencia_txt", 12), ("Público", "publico", 14), ("Bruto", "bruto", 18), ("Descontos", "desconto", 18),
        ("Líquido", "liquido", 18), ("Crédito bancário", "credito_bancario", 18), ("Diferença: crédito − líquido", "dif_credito", 16),
        ("Diferença: bruto − descontos − líquido", "dif_bruto_menos_desconto", 18), ("Diferença: naturezas − bruto", "dif_naturezas_bruto", 16),
    ], conf, filtro=False)
    if d.variacao is not None and len(d.variacao):
        linha = _secao_titulo(ws, linha, f"O que mudou de {mes_ano(d.competencia_anterior)} para {mes}")
        situacoes = {"nova": "Nova", "saiu": "Não veio neste mês", "alta": "Alta", "queda": "Queda", "sem variação": "Sem variação"}
        linha = _tabela(ws, linha, [
            ("Natureza", "natureza_detalhada", 12), ("Descrição", "descricao", 40), (f"DDP de {mes_ano(d.competencia_anterior)}", "anterior", 18),
            (f"DDP de {mes}", "atual", 18), ("Variação", "variacao", 18), ("Situação", "situacao_txt", 18),
        ], d.variacao.assign(situacao_txt=d.variacao["situacao"].map(situacoes)), {"anterior", "atual", "variacao"}, filtro=False)
    linha = _secao_titulo(ws, linha, f"DDP × liquidado na base em {mes}")
    _tabela(ws, linha, [("Natureza", "natureza_detalhada", 12), ("Descrição", "descricao", 40), ("DDP bruta", "ddp", 18),
                        ("Liquidado na base", "liquidado_no_mes", 18), ("Diferença (liquidado − DDP)", "diferenca", 18)],
            d.confronto, {"ddp", "liquidado_no_mes", "diferenca"}, filtro=False)


def relatorio_excel(d: DadosRelatorio) -> bytes:
    mes, ano = mes_ano(d.competencia), d.competencia // 100
    wb = Workbook()
    _resumo(wb, d, mes, ano)
    _somente_reforco(wb, d, mes, ano)
    _sugestoes_anulacao(wb, d, mes)
    _anulacao_reforco(wb, d)
    _por_empenho(wb, d, mes, ano)
    _acao_po(wb, d)
    _conciliacao(wb, d)
    _detalhe(wb, d, mes)
    _conferencia(wb, d, mes)
    for ws in wb.worksheets:
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    arquivo = BytesIO()
    wb.save(arquivo)
    return arquivo.getvalue()
