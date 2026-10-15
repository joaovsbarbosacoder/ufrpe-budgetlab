"""Relatório "Sobra prevista de empenho" (Contratos Contínuos e Bolsas e Auxílios) — 15/10/2026.

Camada: regra de relatório. Não lê planilha nem importa Streamlit. Só LÊ os relatórios "Projeção pela Execução" já montados
(`relatorio_projecao_execucao.RelatorioProjecaoExecucao`, com os ajustes manuais vigentes): não altera cadastro, projeção,
Resultado Orçamentário nem o relatório de Anulação de Saldo de Empenho.

SOBRA PREVISTA de uma NE = max(0, saldo do empenho − despesa projetada até dezembro pela execução): o empenho que, pela
projeção, não será liquidado no exercício. Hoje o Resultado Orçamentário NÃO devolve esse valor — a necessidade da NE para em
zero e a sobra conta como consumida (explicação detalhada na conversa de 15/10/2026). Este relatório só a evidencia.

Nulo ≠ zero: saldo desconhecido, ou NE sem projeção calculável (valor mensal nulo), tem sobra nula (célula vazia), nunca 0,00.
`sobra_valor_cheio` repete a conta com a projeção pelo valor contratado/cadastrado cheio (fator 1, sem teto, sem ajuste): a
sobra que existe mesmo se o fornecedor faturar o valor cheio.

Faixas (confiança da sobra; não é recomendação de anular):
  1. contrato vencido/suspenso/encerrado/rescindido, ou NE sem nada projetado: a mais provável de virar anulação — conferir
     antes faturas pendentes de meses já prestados (a edição da projeção aceita o valor delas);
  2. NE com fator medido pela execução real (3 ou mais meses fechados);
  3. NE sem histórico, projetada pelo valor cheio limitado ao maior mês liquidado (teto): a mais frágil.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import BytesIO

import pandas as pd

from src.relatorio_projecao_execucao import (
    MESES,
    ORIGEM_EXECUCAO,
    TIPO_PROJETADO,
    TIPO_RESTANTE_ABERTO,
    RelatorioProjecaoExecucao,
)

TOLERANCIA = 0.005

FAIXA_1 = "1 · Encerrado/suspenso ou nada projetado"
FAIXA_2 = "2 · Execução medida (fator)"
FAIXA_3 = "3 · Sem histórico (projeção pelo teto/valor cheio)"
SEM_SOBRA = "—"

#: Faixas cuja sobra entra no Resultado Orçamentário como "anulação sugerida" (receita). Pedido de 15/10/2026: valem as TRÊS
#: faixas, para qualquer NE e para os empenhos futuros (a regra é por faixa, nunca por NE). A faixa 3 (NE sem histórico,
#: projetada pelo teto) é a mais frágil — a sobra some se o fornecedor faturar o valor cheio —, por isso a Composição
#: mostra quanto da anulação vem dela. Para tirar uma faixa da conta, basta removê-la desta tupla.
FAIXAS_NA_ANULACAO = (FAIXA_1, FAIXA_2, FAIXA_3)

#: situações de contrato em que nada mais é esperado do fornecedor
_SITUACOES_ENCERRADAS = {"VENCIDO", "SUSPENSO", "ENCERRADO", "RESCINDIDO"}

COL_SOBRA = "SOBRA PREVISTA (saldo − projetado)"
COL_PROJETADO = "Despesa projetada até dez (execução)"


@dataclass(frozen=True)
class ContextoSobra:
    exercicio: int
    execucao_mensal: str  # ex.: "extração 15/10/2026 · sha 63027817"
    liquidacao_competencia: str  # ex.: "Liquidação por Competência.xlsx · modificado em 15/10/2026 11:20"
    emitido_em: str


def _numero(valor: object) -> float | None:
    if valor is None or pd.isna(valor):
        return None
    return float(valor)


def faixa_da_sobra(status: object, projetado: float | None, origem_fator: object, sobra: float | None) -> str:
    """Faixa (ver docstring do módulo) de uma NE; sem sobra, `SEM_SOBRA`."""

    if sobra is None or sobra <= TOLERANCIA:
        return SEM_SOBRA
    encerrado = str(status or "").upper() in _SITUACOES_ENCERRADAS
    if encerrado or (projetado or 0.0) <= TOLERANCIA:
        return FAIXA_1
    return FAIXA_2 if origem_fator == ORIGEM_EXECUCAO else FAIXA_3


def _observacoes(linha: pd.Series, faixa: str, sobra: float | None, sobra_cheio: float | None, referencia: date) -> str:
    notas = []
    vigencia = pd.to_datetime(linha["vigencia_fim"], errors="coerce")
    if pd.notna(vigencia) and vigencia.date() < referencia and str(linha["status_contrato"]).upper() == "ATIVO":
        notas.append(f"vigência encerrada em {vigencia:%d/%m/%Y} com status ATIVO")
    if faixa == FAIXA_1:
        notas.append("conferir faturas pendentes de meses já prestados antes de anular")
    if bool(linha.get("limitada_ao_maior_mes", False)):
        notas.append("projeção limitada ao maior mês liquidado (teto): a sobra some se o fornecedor faturar o valor cheio")
    fator = _numero(linha["fator"])
    if linha["origem_fator"] == ORIGEM_EXECUCAO and fator is not None and fator < 0.5:
        notas.append(f"fator muito baixo ({fator:.2f}): conferir valor mensal do cadastro")
    if sobra is not None and sobra > TOLERANCIA and (sobra_cheio is None or sobra_cheio <= TOLERANCIA):
        notas.append("pelo valor cheio não há sobra")
    if bool(linha.get("ajustada_manualmente", False)):
        notas.append("projeção com ajuste manual do esperado")
    return "; ".join(notas)


def sobra_por_ne(relatorios: dict[str, RelatorioProjecaoExecucao], referencia: date) -> pd.DataFrame:
    """Uma linha por NE de cada base (`relatorios`: nome da base → relatório de projeção), ordenada pela sobra (maior
    primeiro; nula por último). `referencia`: data da extração da Execução Mensal. Não altera os relatórios."""

    partes = []
    for base, relatorio in relatorios.items():
        linhas = relatorio.linhas
        if linhas.empty:
            continue
        for _, linha in linhas.iterrows():
            saldo = _numero(linha["saldo"])
            projetado = _numero(linha["projetado_execucao"])
            cheio = _numero(linha["projetado_valor_cheio"])
            sobra = None if saldo is None or projetado is None else max(0.0, saldo - projetado)
            sobra_cheio = None if saldo is None or cheio is None else max(0.0, saldo - cheio)
            faixa = faixa_da_sobra(linha["status_contrato"], projetado, linha["origem_fator"], sobra)
            vigencia = pd.to_datetime(linha["vigencia_fim"], errors="coerce")
            empenhado = _numero(linha["valor_empenhado"])
            partes.append(
                {
                    "Base": base, "NE": linha["ne_curta"], "Faixa da sobra": faixa,
                    "Fornecedor / programa": linha["fornecedor"], "Contrato / processo": linha["contrato_numero"],
                    "Situação": linha["status_contrato"],
                    "Fim da vigência": None if pd.isna(vigencia) else f"{vigencia:%d/%m/%Y}",
                    "Valor mensal cadastrado": _numero(linha["despesa_mensal"]),
                    "Empenhado": empenhado,
                    "Liquidado (empenhado − saldo)": None if empenhado is None or saldo is None else empenhado - saldo,
                    "Saldo do empenho": saldo,
                    "Origem do fator": linha["origem_fator"], "Fator de execução": _numero(linha["fator"]),
                    "Meses usados": linha["meses_usados"],
                    "Teto do maior mês": "Sim" if bool(linha.get("limitada_ao_maior_mes", False)) else "Não",
                    COL_PROJETADO: projetado, "Despesa projetada até dez (valor cheio)": cheio,
                    "Necessidade pela execução": _numero(linha["necessidade_execucao"]),
                    COL_SOBRA: sobra, "Sobra pelo valor cheio": sobra_cheio,
                    "Observações": _observacoes(linha, faixa, sobra, sobra_cheio, referencia),
                }
            )
    colunas = [
        "Base", "NE", "Faixa da sobra", "Fornecedor / programa", "Contrato / processo", "Situação", "Fim da vigência",
        "Valor mensal cadastrado", "Empenhado", "Liquidado (empenhado − saldo)", "Saldo do empenho", "Origem do fator",
        "Fator de execução", "Meses usados", "Teto do maior mês", COL_PROJETADO, "Despesa projetada até dez (valor cheio)",
        "Necessidade pela execução", COL_SOBRA, "Sobra pelo valor cheio", "Observações",
    ]
    tabela = pd.DataFrame(partes, columns=colunas)
    return tabela.sort_values(COL_SOBRA, ascending=False, na_position="last", kind="stable").reset_index(drop=True)


def sobra_elegivel_por_ne(tabela: pd.DataFrame, faixas: tuple[str, ...] = FAIXAS_NA_ANULACAO) -> dict[str, float]:
    """NE → sobra prevista das NEs cuja faixa está em `faixas` (padrão: `FAIXAS_NA_ANULACAO`), para o Resultado Orçamentário.
    NE sem sobra, ou de outra faixa, fica de fora. Uma NE que apareça nas duas bases soma as sobras."""

    elegiveis = tabela[tabela["Faixa da sobra"].isin(faixas) & (tabela[COL_SOBRA].fillna(0.0) > TOLERANCIA)]
    saida: dict[str, float] = {}
    for ne, sobra in zip(elegiveis["NE"], elegiveis[COL_SOBRA]):
        saida[str(ne)] = saida.get(str(ne), 0.0) + float(sobra)
    return saida


def resumo_da_sobra(tabela: pd.DataFrame) -> pd.DataFrame:
    """Totais por base e faixa (só NEs com sobra) e a linha TOTAL."""

    com_sobra = tabela[tabela[COL_SOBRA].fillna(0.0) > TOLERANCIA]
    if com_sobra.empty:
        return pd.DataFrame([{"Base": "TOTAL", "Faixa da sobra": "", "Nº de NEs": 0, "Sobra prevista (R$)": 0.0, "Sobra pelo valor cheio (R$)": 0.0}])
    grupos = (
        com_sobra.groupby(["Base", "Faixa da sobra"], sort=True)
        .agg(**{"Nº de NEs": ("NE", "count"), "Sobra prevista (R$)": (COL_SOBRA, "sum"), "Sobra pelo valor cheio (R$)": ("Sobra pelo valor cheio", "sum")})
        .reset_index()
    )
    total = pd.DataFrame(
        [{
            "Base": "TOTAL", "Faixa da sobra": "", "Nº de NEs": len(com_sobra),
            "Sobra prevista (R$)": float(com_sobra[COL_SOBRA].sum()),
            "Sobra pelo valor cheio (R$)": float(com_sobra["Sobra pelo valor cheio"].sum()),
        }]
    )
    return pd.concat([grupos, total], ignore_index=True)


def _grade_mensal(relatorios: dict[str, RelatorioProjecaoExecucao], tabela: pd.DataFrame) -> pd.DataFrame:
    sobra_por_ne = {(l["Base"], l["NE"]): l[COL_SOBRA] for _, l in tabela.iterrows()}
    linhas = []
    for base, relatorio in relatorios.items():
        for indice, linha in relatorio.linhas.iterrows():
            registro: dict[str, object] = {"Base": base, "NE": linha["ne_curta"], "Fornecedor / programa": linha["fornecedor"]}
            for mes in range(1, 13):
                tipo = relatorio.mensal.at[indice, f"t{mes}"]
                projetado = tipo in (TIPO_PROJETADO, TIPO_RESTANTE_ABERTO)
                valor = relatorio.mensal.at[indice, f"p{mes}" if projetado else f"r{mes}"]
                registro[MESES[mes - 1]] = None if valor is None or pd.isna(valor) else float(valor)
                registro[f"{MESES[mes - 1]} (tipo)"] = tipo
            registro["Saldo do empenho"] = _numero(linha["saldo"])
            registro["SOBRA PREVISTA"] = sobra_por_ne.get((base, linha["ne_curta"]))
            linhas.append(registro)
    return pd.DataFrame(linhas)


def linhas_metodologia(contexto: ContextoSobra) -> list[tuple[str, str]]:
    return [
        ("Emitido em", contexto.emitido_em),
        ("Exercício", str(contexto.exercicio)),
        ("Execução Mensal", contexto.execucao_mensal),
        ("Liquidação por Competência", contexto.liquidacao_competencia),
        ("Projeção", 'A mesma do Resultado Orçamentário: "Projeção pela execução" (fator de execução, teto para NE sem histórico, '
                     "ajustes manuais vigentes, competência futura pelo lançamento; Bolsas em bolsas inteiras)."),
        ("Sobra prevista", "max(0, saldo do empenho − despesa projetada até dezembro pela execução): o empenho que, pela projeção, "
                           "não será liquidado no exercício. Hoje o Resultado NÃO devolve esse valor: a necessidade da NE para em "
                           "zero e a sobra conta como consumida. Saldo ou projeção desconhecidos: sobra vazia, nunca zero."),
        ("Sobra pelo valor cheio", "A mesma conta com a projeção pelo valor contratado/cadastrado cheio (fator 1, sem teto, sem "
                                   "ajuste): a sobra que existe mesmo se o fornecedor faturar o valor cheio."),
        ("Faixa 1", "Contrato vencido/suspenso/encerrado, ou NE sem nada projetado: sobra mais provável de virar anulação. Conferir "
                    "antes faturas pendentes de meses já prestados (a edição da projeção aceita o valor delas)."),
        ("Faixa 2", "NE com fator medido pela execução real (3 ou mais meses fechados): sobra razoável enquanto o fornecedor "
                    "seguir faturando abaixo do contratado."),
        ("Faixa 3", "NE sem histórico, projetada pelo valor cheio limitado ao maior mês liquidado (teto): sobra frágil."),
        ("Não é sugestão de anulação", "Relatório informativo: não altera cadastro, projeção, Resultado nem o relatório de "
                                       "Anulação de Saldo de Empenho."),
        ("Itens sem NE", "Fora deste relatório (sem empenho, não há sobra)."),
    ]


def gerar_xlsx(relatorios: dict[str, RelatorioProjecaoExecucao], referencia: date, contexto: ContextoSobra) -> bytes:
    """Abas: "Resumo", "Sobra por NE", "Grade mensal" (realizado ou projetado de cada mês) e "Metodologia e fontes"."""

    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    tabela = sobra_por_ne(relatorios, referencia)
    resumo = resumo_da_sobra(tabela)
    grade = _grade_mensal(relatorios, tabela)
    metodologia = pd.DataFrame(linhas_metodologia(contexto), columns=["Item", "Descrição"])
    termos_moeda = ("Valor", "Empenhado", "Liquidado", "Saldo", "Despesa", "Necessidade", "SOBRA", "Sobra", "R$")

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        resumo.to_excel(writer, sheet_name="Resumo", index=False)
        tabela.to_excel(writer, sheet_name="Sobra por NE", index=False)
        grade.to_excel(writer, sheet_name="Grade mensal", index=False)
        metodologia.to_excel(writer, sheet_name="Metodologia e fontes", index=False)
        for nome, planilha in writer.sheets.items():
            planilha.freeze_panes = "A2" if nome == "Metodologia e fontes" else "C2"
            for celula in planilha[1]:
                celula.font = Font(bold=True, color="FFFFFF")
                celula.fill = PatternFill("solid", fgColor="1F4E79")
                celula.alignment = Alignment(wrap_text=True, vertical="center")
            planilha.row_dimensions[1].height = 42
            for posicao, celula in enumerate(planilha[1], start=1):
                letra, titulo = get_column_letter(posicao), str(celula.value or "")
                largura = 14
                if titulo in ("Fornecedor / programa", "Faixa da sobra"):
                    largura = 34
                elif titulo in ("Observações", "Descrição"):
                    largura = 90
                elif titulo == "Item":
                    largura = 28
                planilha.column_dimensions[letra].width = largura
                if "Fator" in titulo:
                    formato = "0.00"
                elif "Nº" not in titulo and (titulo in MESES or any(t in titulo for t in termos_moeda)):
                    formato = "#,##0.00"
                else:
                    formato = None
                for linha in planilha[letra][1:]:
                    if formato:
                        linha.number_format = formato
                    if titulo in ("Observações", "Descrição"):
                        linha.alignment = Alignment(wrap_text=True, vertical="top")
        planilha = writer.sheets["Sobra por NE"]
        coluna = list(tabela.columns).index(COL_SOBRA) + 1
        for numero in range(2, planilha.max_row + 1):
            celula = planilha.cell(numero, coluna)
            if isinstance(celula.value, (int, float)) and celula.value > TOLERANCIA:
                celula.fill = PatternFill("solid", fgColor="FCE4C4")
                celula.font = Font(bold=True)
        for celula in writer.sheets["Resumo"][writer.sheets["Resumo"].max_row]:
            celula.font = Font(bold=True)
    return buffer.getvalue()
