"""
Estimativa de reajuste de Contratos Contínuos, por competência (11/10/2026).

Camada: regra de negócio pura (pandas/datetime; sem Streamlit, sem leitura de arquivo, sem rede). Spec:
`docs/superpowers/specs/2026-10-11-estimativa-reajuste-contratos-design.md`.

CENÁRIO SEPARADO: nada aqui altera Necessidade de Empenho, Projeção pela Execução, Registro ou aditivos
cadastrados — o módulo só LÊ o contrato e devolve a estimativa. A promoção a aditivo PREVISTO
(`aditivo_previsto_do_ciclo`) devolve o aditivo; quem grava é a tela, por clique.

Regras (resumo; detalhes e dúvidas registradas na spec):
  * Data-base: a manual; senão 12 meses após o último aditivo de Reajuste ASSINADO; senão 12 meses após o
    início da vigência. As seguintes, a cada 12 meses, só enquanto a data-base cabe na vigência EFETIVA
    (inclusive prorrogação PREVISTA).
  * Percentual do ciclo: manual > oficial (acumulado de 12 meses) > ausente. Ausente = nulo, nunca 0%.
  * Reajustes compostos entre ciclos; o mês da data-base é proporcional aos dias.
  * Base da competência: liquidado por competência (vazio quando a competência já foi apurada e o contrato
    não tem lançamento; nunca zero presumido); competência posterior à cobertura da base de liquidação usa o
    valor contratado em vigor, rotulado como teto. Aditivo PREVISTO de reajuste (a própria estimativa
    promovida) é ignorado no valor contratado — sem dupla contagem.

Contrato público:
    ParametrosReajuste(indice, percentual_manual, data_base_manual)
    EstimativaContrato(matriz, situacao, datas_base, ciclos)
    datas_base(*, vigencia_inicio, vigencia_fim_efetiva, aditivos, data_base_manual) -> (list[date], motivo)
    percentual_do_ciclo(data_base, parametros, variacoes) -> (percentual | None, origem)
    estimar_contrato(*, contrato, despesa_mensal, aditivos, vigencia_inicio, vigencia_fim, parametros,
                     exercicio_inicial, variacoes=None, liquidado=None, ultimo_mes_coberto=None) -> EstimativaContrato
    aditivo_previsto_do_ciclo(estimativa, aditivos, despesa_mensal) -> Aditivo | None
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from src.contratos_aditivos import Aditivo, custo_mensal, valor_vigente_em, vigencia_efetiva
from src.indices_economicos import INDICES, acumulado_12m

COLUNAS_MATRIZ = [
    "contrato", "ano", "mes", "competencia", "base_valor", "base_origem", "ciclo", "data_base", "percentual",
    "percentual_origem", "fator", "acrescimo", "prorrogacao_prevista", "estorno_liquido",
]

_NAN = float("nan")


@dataclass(frozen=True)
class ParametrosReajuste:
    """O que o usuário configura por contrato: índice oficial (opcional), percentual manual (opcional;
    zero é um valor válido) e data-base manual (a próxima data-base, opcional)."""

    indice: str | None = None
    percentual_manual: float | None = None
    data_base_manual: date | None = None


@dataclass(frozen=True)
class EstimativaContrato:
    matriz: pd.DataFrame
    #: estimado | sem_indice | sem_data_base | sem_vigencia_fim | sem_reajuste_na_vigencia
    situacao: str
    datas_base: list[date] = field(default_factory=list)
    #: um dict por ciclo: data_base, percentual (ou None), origem
    ciclos: list[dict] = field(default_factory=list)


def _vazio(valor: object) -> bool:
    return valor is None or bool(pd.isna(valor))


def _como_data(valor: object) -> date | None:
    if _vazio(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def _somar_meses(dia: date, meses: int) -> date:
    indice = dia.year * 12 + (dia.month - 1) + meses
    ano, mes = divmod(indice, 12)
    mes += 1
    return date(ano, mes, min(dia.day, calendar.monthrange(ano, mes)[1]))


def datas_base(
    *, vigencia_inicio: object, vigencia_fim_efetiva: object, aditivos: list[Aditivo], data_base_manual: object
) -> tuple[list[date], str]:
    """Datas-base dos ciclos e o motivo (`ok`, `sem_data_base`, `sem_vigencia_fim` ou
    `sem_reajuste_na_vigencia`). Só aditivos de Reajuste ASSINADOS deslocam a data-base: os PREVISTOS são a
    própria estimativa."""

    fim = _como_data(vigencia_fim_efetiva)
    if fim is None:
        return [], "sem_vigencia_fim"
    primeira = _como_data(data_base_manual)
    if primeira is None:
        assinados = [a for a in aditivos if a.tipo == "REAJUSTE" and a.situacao == "ASSINADO" and a.data_inicio is not None]
        if assinados:
            primeira = _somar_meses(max(a.data_inicio for a in assinados), 12)
        else:
            inicio = _como_data(vigencia_inicio)
            if inicio is None:
                return [], "sem_data_base"
            primeira = _somar_meses(inicio, 12)
    datas = []
    atual, passo = primeira, 0
    while atual <= fim:
        datas.append(atual)
        passo += 1
        atual = _somar_meses(primeira, 12 * passo)
    return datas, ("ok" if datas else "sem_reajuste_na_vigencia")


def percentual_do_ciclo(
    data_base: date, parametros: ParametrosReajuste, variacoes: dict | None
) -> tuple[float | None, str]:
    """Percentual do ciclo e sua origem: `manual`, `oficial`, `oficial_ultimo` (estimado) ou `sem_indice`
    (nulo — nunca 0%)."""

    if parametros.percentual_manual is not None and not pd.isna(parametros.percentual_manual):
        return float(parametros.percentual_manual), "manual"
    indice = (parametros.indice or "").upper()
    if indice in INDICES and variacoes:
        percentual, origem = acumulado_12m(variacoes, data_base.year, data_base.month)
        if percentual is not None:
            return percentual, origem
    return None, "sem_indice"


def _meses_entre(inicio: tuple[int, int], fim: tuple[int, int]) -> list[tuple[int, int]]:
    meses, (ano, mes) = [], inicio
    while (ano, mes) <= fim:
        meses.append((ano, mes))
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return meses


def _fator_do_mes(ciclos: list[dict], primeiro_dia: date, ultimo_dia: date) -> tuple[float | None, int, dict | None]:
    """(fator acumulado, nº de ciclos aplicáveis, último ciclo aplicável). Fator `None` quando algum ciclo
    aplicável não tem percentual."""

    aplicaveis = [c for c in ciclos if c["data_base"] <= ultimo_dia]
    fator: float | None = 1.0
    for ciclo in aplicaveis:
        if ciclo["percentual"] is None:
            fator = None
            break
        dias_mes = ultimo_dia.day
        peso = 1.0 if ciclo["data_base"] <= primeiro_dia else (dias_mes - ciclo["data_base"].day + 1) / dias_mes
        fator *= 1.0 + peso * ciclo["percentual"] / 100.0
    return fator, len(aplicaveis), (aplicaveis[-1] if aplicaveis else None)


def estimar_contrato(
    *, contrato: str, despesa_mensal: object, aditivos: list[Aditivo], vigencia_inicio: object,
    vigencia_fim: object, parametros: ParametrosReajuste, exercicio_inicial: int,
    variacoes: dict | None = None, liquidado: dict[tuple[int, int], float] | None = None,
    ultimo_mes_coberto: tuple[int, int] | None = None,
) -> EstimativaContrato:
    """Matriz por competência (mês/ano) do contrato, do início da vigência (ou de janeiro de
    `exercicio_inicial`, sem o início) ao fim da vigência efetiva. `liquidado` é o liquidado por competência
    do contrato (NEs de todos os exercícios, estornos com sinal) e `ultimo_mes_coberto` o último mês coberto
    pela base de Liquidação por Competência."""

    efetiva, _ = vigencia_efetiva(vigencia_fim, aditivos)
    fim_efetivo = None if pd.isna(efetiva) else efetiva.date()
    inicio = _como_data(vigencia_inicio)
    datas, motivo = datas_base(
        vigencia_inicio=inicio, vigencia_fim_efetiva=fim_efetivo, aditivos=aditivos,
        data_base_manual=parametros.data_base_manual,
    )
    if fim_efetivo is None:
        return EstimativaContrato(pd.DataFrame(columns=COLUNAS_MATRIZ), "sem_vigencia_fim")

    ciclos = []
    for data_base in datas:
        percentual, origem = percentual_do_ciclo(data_base, parametros, variacoes)
        ciclos.append({"data_base": data_base, "percentual": percentual, "origem": origem})

    garantido, _ = vigencia_efetiva(vigencia_fim, [a for a in aditivos if not a.previsto])
    garantido_data = None if pd.isna(garantido) else garantido.date()
    # o valor contratado ignora o aditivo PREVISTO de reajuste: ele É a estimativa (promovida), não base
    aditivos_base = [a for a in aditivos if not (a.previsto and a.tipo == "REAJUSTE" and a.valor_mensal is not None)]
    inicio_execucao = None if inicio is None else pd.Timestamp(inicio)

    custos: dict[int, list[float]] = {}

    def contratado(ano: int, mes: int) -> float | None:
        if ano not in custos:
            custos[ano] = custo_mensal(
                despesa_mensal, aditivos_base, ano, status="ATIVO", vigencia_fim=vigencia_fim, inicio=inicio_execucao
            )
        valor = custos[ano][mes - 1]
        return None if pd.isna(valor) else float(valor)

    primeiro_mes = (inicio.year, inicio.month) if inicio is not None else (exercicio_inicial, 1)
    linhas = []
    for ano, mes in _meses_entre(primeiro_mes, (fim_efetivo.year, fim_efetivo.month)):
        primeiro_dia = date(ano, mes, 1)
        ultimo_dia = date(ano, mes, calendar.monthrange(ano, mes)[1])
        if ultimo_mes_coberto is not None and (ano, mes) <= ultimo_mes_coberto:
            if liquidado is not None and (ano, mes) in liquidado:
                base, origem_base = float(liquidado[(ano, mes)]), "liquidado"
            else:
                base, origem_base = None, "sem_liquidado"
        else:
            base, origem_base = contratado(ano, mes), "contratado"

        fator, n_ciclo, ciclo = _fator_do_mes(ciclos, primeiro_dia, ultimo_dia)
        if motivo == "sem_data_base":
            fator = None  # data-base desconhecida: o acréscimo é desconhecido, não zero
        acrescimo = _NAN if base is None or fator is None else base * (fator - 1.0)
        linhas.append({
            "contrato": contrato, "ano": ano, "mes": mes, "competencia": f"{mes:02d}/{ano}",
            "base_valor": _NAN if base is None else base, "base_origem": origem_base,
            "ciclo": n_ciclo, "data_base": None if ciclo is None else ciclo["data_base"],
            "percentual": _NAN if ciclo is None or ciclo["percentual"] is None else ciclo["percentual"],
            "percentual_origem": None if ciclo is None else ciclo["origem"],
            "fator": _NAN if fator is None else fator, "acrescimo": acrescimo,
            "prorrogacao_prevista": bool(garantido_data is not None and ultimo_dia > garantido_data and primeiro_dia <= fim_efetivo),
            "estorno_liquido": bool(origem_base == "liquidado" and base is not None and base < 0),
        })

    matriz = pd.DataFrame(linhas, columns=COLUNAS_MATRIZ)
    if motivo != "ok":
        situacao = motivo
    elif any(c["percentual"] is None for c in ciclos):
        situacao = "sem_indice"
    else:
        situacao = "estimado"
    return EstimativaContrato(matriz, situacao, datas, ciclos)


def aditivo_previsto_do_ciclo(
    estimativa: EstimativaContrato, aditivos: list[Aditivo], despesa_mensal: object
) -> Aditivo | None:
    """Aditivo REAJUSTE/PREVISTO do próximo ciclo ainda sem aditivo, com percentual conhecido: `data_inicio`
    = data-base e `valor_mensal` = valor mensal em vigor na data-base × (1 + percentual). `None` quando não
    há ciclo promovível. Não grava nada."""

    ocupadas = {a.data_inicio for a in aditivos if a.data_inicio is not None}
    for ciclo in estimativa.ciclos:
        if ciclo["data_base"] in ocupadas:
            continue
        if ciclo["percentual"] is None:
            return None  # os ciclos seguintes dependem deste valor
        vigente, _ = valor_vigente_em(despesa_mensal, aditivos, ciclo["data_base"])
        if vigente is None:
            return None
        return Aditivo(
            numero=f"Reajuste previsto {ciclo['data_base']:%m/%Y}", tipo="REAJUSTE", situacao="PREVISTO",
            data_inicio=ciclo["data_base"], valor_mensal=round(vigente * (1.0 + ciclo["percentual"] / 100.0), 2),
        )
    return None
