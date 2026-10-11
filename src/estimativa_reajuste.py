"""
Estimativa de reajuste de Contratos Contínuos, por competência — regras v2 (11/10/2026).

Camada: regra de negócio pura (pandas/datetime; sem Streamlit, sem leitura de arquivo, sem rede). Specs:
`docs/superpowers/specs/2026-10-11-estimativa-reajuste-contratos-design.md` (base) e
`docs/superpowers/specs/2026-10-11-estimativa-reajuste-regras-v2.md` (ciclos com estado — esta versão).

CENÁRIO SEPARADO: nada aqui altera Necessidade de Empenho, Projeção pela Execução, Registro ou aditivos
cadastrados — o módulo só LÊ o contrato e devolve a estimativa. Essas projeções usam só o valor REGISTRADO;
registrar o aditivo de Reajuste com valor transforma o ciclo em "registrado" e ele sai daqui (sem dupla contagem).

Ciclos de reajuste (ver `ciclos_do_contrato`):
  * registrado — aditivo de Reajuste ASSINADO com valor no cadastro: já está no valor mensal; só ancora.
  * formalizado — reajuste no Contratos.gov (termo aditivo com REAJUSTE, ou APOSTILAMENTO com novo valor — o
    reajuste por índice costuma ser formalizado por apostila) ou aditivo assinado sem valor, sem valor no cadastro:
    ESTIMADO pelo índice. ANUALIDADE: evento a menos de ~1 ano (`ANUALIDADE_DIAS`) do reajuste anterior (ou do
    início do contrato) não abre ciclo novo. Um apostilamento IMPLANTA o ciclo se foi assinado depois da data-base
    e o novo valor vale até ~1 ano depois dela. Entra se a data-base cai no exercício; antes dele, se a implantação
    foi assinada no exercício ou um apostilamento retroativo assinado no exercício a cobre; senão presume-se
    incorporado ao valor do cadastro (só ancora).
  * projetado — aniversários de 12 em 12 meses a partir do último reajuste registrado/formalizado (senão do início
    do contrato; a data manual manda), dentro da vigência efetiva e a partir de janeiro do exercício.
Percentual do ciclo: manual > índice oficial acumulado nos 12 meses anteriores à data-base > ausente (nulo, nunca
0%). Acréscimo por competência = base × (fator − 1), separado em formalizado e projetado; competências de anos
anteriores (alcançadas por ciclo formalizado) ficam marcadas `exercicio_anterior`.
Base da competência: liquidado por competência; competência apurada sem lançamento = vazio; futura = contratado
(teto). O LIQUIDADO de competência iniciada depois da implantação do reajuste (data do novo valor do primeiro
apostilamento após a data-base) já vem reajustado: aquele ciclo não incide de novo sobre ele. Aditivo PREVISTO de
reajuste (a estimativa promovida) é ignorado no contratado.

Contrato público:
    ParametrosReajuste, Retroativo, Apostilamento, Ciclo, EstimativaContrato
    termos_do_gov(termos) -> {contrato_id: {"reajustes": [date], "retroativos": [...], "apostilamentos": [...]}}
    nes_do_gov(empenhos, contrato_id, planos_internos) -> set[str]
    implantacao_do_ciclo(data_base, apostilamentos) -> date | None
    ciclos_do_contrato(*, inicio_contrato, fim_efetivo, aditivos, reajustes_gov, retroativos, apostilamentos,
                       data_base_manual, inicio_exercicio) -> ([(data_base, estado, desde)], motivo)
    percentual_do_ciclo(data_base, desde, parametros, variacoes) -> (percentual | None, origem)
    estimar_contrato(...) -> EstimativaContrato
    aditivo_previsto_do_ciclo(estimativa, aditivos, despesa_mensal) -> Aditivo | None
    nes_em_conflito, liquidado_do_contrato, ultimo_mes_coberto
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from src.contratos_aditivos import Aditivo, custo_mensal, valor_vigente_em, vigencia_efetiva
from src.indices_economicos import INDICES, acumulado_periodo

COLUNAS_MATRIZ = [
    "contrato", "ano", "mes", "competencia", "exercicio_anterior", "base_valor", "base_origem", "ciclo", "data_base",
    "estado_ciclo", "percentual", "percentual_origem", "fator", "acrescimo_formalizado", "acrescimo_projetado",
    "acrescimo", "prorrogacao_prevista", "estorno_liquido",
]

#: reajuste do gov a até tantos dias de um aditivo registrado é o mesmo ciclo (dúvida registrada na spec v2)
TOLERANCIA_DIAS = 45
#: anualidade do reajuste (interregno mínimo de um ano), com folga para datas de assinatura/aniversário
ANUALIDADE_DIAS = 330

_NAN = float("nan")


@dataclass(frozen=True)
class ParametrosReajuste:
    """O que o usuário configura por contrato: índice oficial (opcional), percentual manual (opcional; zero é um
    valor válido) e data-base manual (a próxima data-base projetada, opcional)."""

    indice: str | None = None
    percentual_manual: float | None = None
    data_base_manual: date | None = None


@dataclass(frozen=True)
class Retroativo:
    """Apostilamento retroativo do Contratos.gov: período em meses inteiros e valor (do contrato INTEIRO —
    referência, não comparável à parcela da 20RK)."""

    assinatura: date
    inicio: date
    fim: date
    valor: float | None


@dataclass(frozen=True)
class Apostilamento:
    """Apostilamento do Contratos.gov: quando foi assinado e a partir de quando vale o novo valor."""

    assinatura: date
    novo_valor: date


@dataclass(frozen=True)
class Ciclo:
    data_base: date
    estado: str  # formalizado | projetado
    desde: date  # início da janela do índice (12 meses antes da data-base)
    percentual: float | None
    origem: str  # manual | oficial | oficial_ultimo | sem_indice
    #: data do novo valor do primeiro apostilamento após a data-base: o liquidado daí em diante já vem reajustado
    implementado_em: date | None = None


@dataclass(frozen=True)
class EstimativaContrato:
    matriz: pd.DataFrame
    #: estimado | sem_indice | sem_data_base | sem_vigencia_fim | sem_reajuste_na_vigencia
    situacao: str
    ciclos: list[Ciclo] = field(default_factory=list)
    #: apostilamentos retroativos do gov assinados no exercício (referência)
    retroativos_exercicio: list[Retroativo] = field(default_factory=list)

    @property
    def datas_base(self) -> list[date]:
        return [c.data_base for c in self.ciclos]


def _vazio(valor: object) -> bool:
    return valor is None or (not isinstance(valor, (list, dict)) and bool(pd.isna(valor)))


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


def _sem_acento(texto: object) -> str:
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii").upper()


def _periodo(texto: object) -> tuple[date, date] | None:
    """"MM/AAAA–MM/AAAA" → (1º dia do mês inicial, último dia do mês final); `None` se não houver duas datas."""

    achados = re.findall(r"(\d{2})/(\d{4})", str(texto or ""))
    if len(achados) < 2:
        return None
    (m1, a1), (m2, a2) = achados[0], achados[-1]
    fim_ano, fim_mes = int(a2), int(m2)
    return date(int(a1), int(m1), 1), date(fim_ano, fim_mes, calendar.monthrange(fim_ano, fim_mes)[1])


def termos_do_gov(termos: pd.DataFrame) -> dict[str, dict[str, list]]:
    """Por `contrato_id` do Contratos.gov: `reajustes` (Termos Aditivos com REAJUSTE na qualificação: a data de
    início do novo valor, ou o início do termo), `retroativos` (Apostilamentos retroativos com período legível) e
    `apostilamentos` (todos: assinatura e data do novo valor)."""

    resultado: dict[str, dict[str, list]] = {}
    if termos is None or termos.empty:
        return resultado
    for _, termo in termos.iterrows():
        item = resultado.setdefault(
            str(termo["contrato_id"]), {"reajustes": [], "retroativos": [], "apostilamentos": []}
        )
        if termo["tipo"] == "Termo de Apostilamento":
            assinatura = _como_data(termo.get("data_assinatura"))
            if assinatura is not None:
                item["apostilamentos"].append(
                    Apostilamento(assinatura, _como_data(termo.get("data_inicio_novo_valor")) or assinatura)
                )
        if termo["tipo"] == "Termo Aditivo" and "REAJUSTE" in _sem_acento(termo.get("qualificacao_termo")):
            data = _como_data(termo.get("data_inicio_novo_valor")) or _como_data(termo.get("vigencia_inicio"))
            if data is not None:
                item["reajustes"].append(data)
        elif termo["tipo"] == "Termo de Apostilamento" and termo.get("retroativo") is True:
            periodo = _periodo(termo.get("retroativo_periodo"))
            assinatura = _como_data(termo.get("data_assinatura"))
            if periodo is not None and assinatura is not None:
                valor = termo.get("retroativo_valor")
                item["retroativos"].append(
                    Retroativo(assinatura, periodo[0], periodo[1], None if _vazio(valor) else float(valor))
                )
    for item in resultado.values():
        item["apostilamentos"].sort(key=lambda a: (a.assinatura, a.novo_valor))
    return resultado


def nes_do_gov(empenhos: pd.DataFrame | None, contrato_id: object, planos_internos: set[str]) -> set[str]:
    """NEs (forma curta) dos empenhos do contrato no Contratos.gov cujo plano interno está em `planos_internos` (os
    do cadastro de Contínuos). O gov traz o contrato INTEIRO (outras ações/PIs); Contínuos guarda só a parcela da
    20RK — sem PI no cadastro, nenhuma NE é acrescentada (nada é presumido)."""

    if empenhos is None or empenhos.empty or not planos_internos or _vazio(contrato_id):
        return set()
    recorte = empenhos[empenhos["contrato_id"].astype(str) == str(contrato_id)]
    codigos = recorte["plano_interno"].astype(str).str.split(" - ").str[0].str.strip()
    return {str(ne) for ne, pi in zip(recorte["ne"], codigos) if pi in planos_internos and not _vazio(ne)}


def implantacao_do_ciclo(data_base: date, apostilamentos: list[Apostilamento] | None) -> date | None:
    """Quando o reajuste da `data_base` passou a ser pago: o primeiro apostilamento assinado a partir da data-base
    cujo novo valor vale até ~1 ano depois dela — a data é a maior entre assinatura e novo valor (o
    novo valor retroativo só é pago depois de assinado). `None` se nenhum o implanta."""

    for apostilamento in sorted(apostilamentos or [], key=lambda a: (a.assinatura, a.novo_valor)):
        # assinado ANTES da data-base, só se for o próprio apostilamento que a define (reajuste por apostila):
        # um apostilamento anterior implanta o reajuste anterior, não este
        if apostilamento.assinatura < data_base and apostilamento.novo_valor != data_base:
            continue
        if data_base - timedelta(days=TOLERANCIA_DIAS) <= apostilamento.novo_valor <= data_base + timedelta(days=365):
            return max(apostilamento.assinatura, apostilamento.novo_valor)
    return None


def ciclos_do_contrato(
    *, inicio_contrato: object, fim_efetivo: object, aditivos: list[Aditivo], reajustes_gov: list | None,
    retroativos: list[Retroativo] | None, data_base_manual: object, inicio_exercicio: date,
    apostilamentos: list[Apostilamento] | None = None,
) -> tuple[list[tuple[date, str, date]], str]:
    """Ciclos a estimar — (data-base, estado, desde) — e o motivo (`ok`, `sem_data_base`, `sem_vigencia_fim`,
    `sem_reajuste_na_vigencia`). Regras na docstring do módulo e na spec v2."""

    fim = _como_data(fim_efetivo)
    if fim is None:
        return [], "sem_vigencia_fim"
    inicio = _como_data(inicio_contrato)
    retroativos = retroativos or []

    reajustes_assinados = [a for a in aditivos if a.tipo == "REAJUSTE" and a.situacao == "ASSINADO" and a.data_inicio]
    registrados = sorted({a.data_inicio for a in reajustes_assinados if a.valor_mensal is not None})
    apostilamentos = sorted(apostilamentos or [], key=lambda a: (a.assinatura, a.novo_valor))
    por_termo = sorted({
        *(d for d in (_como_data(x) for x in reajustes_gov or []) if d is not None),
        *(a.data_inicio for a in reajustes_assinados if a.valor_mensal is None),
    })
    # reajuste por apostila: só o apostilamento sem termo de reajuste a menos de um ano dele (perto de um termo, o
    # apostilamento é a implantação daquele reajuste — ver `implantacao_do_ciclo` —, não um ciclo próprio)
    por_apostila = {
        a.novo_valor for a in apostilamentos
        if not any(abs((a.novo_valor - t).days) < ANUALIDADE_DIAS for t in [*por_termo, *registrados])
    }
    candidatos = sorted({*por_termo, *por_apostila})
    formalizados: list[date] = []
    referencia = inicio  # anualidade: conta do reajuste anterior (registrado ou formalizado) ou do início
    for dia, registrado in sorted([*((d, True) for d in registrados), *((d, False) for d in candidatos)]):
        if registrado:
            referencia = dia
            continue
        if any(abs((dia - r).days) <= TOLERANCIA_DIAS for r in registrados):
            continue  # o registrado manda: é o mesmo ciclo
        if referencia is not None and (dia - referencia).days < ANUALIDADE_DIAS:
            continue  # menos de um ano do anterior: não é reajuste novo
        formalizados.append(dia)
        referencia = dia

    def pendente(dia: date) -> bool:
        if dia >= inicio_exercicio:
            return True
        if any(r.assinatura >= inicio_exercicio and r.inicio <= dia <= r.fim for r in retroativos):
            return True
        implantacao = implantacao_do_ciclo(dia, apostilamentos)
        return implantacao is not None and implantacao >= inicio_exercicio

    eventos = sorted({*registrados, *formalizados})
    incluidos = [(dia, "formalizado") for dia in formalizados if pendente(dia)]

    manual = _como_data(data_base_manual)
    ancora = eventos[-1] if eventos else inicio
    primeira = manual or (None if ancora is None else _somar_meses(ancora, 12))
    if primeira is None and not incluidos:
        return [], "sem_data_base"
    if primeira is not None:
        atual, passo = primeira, 0
        while atual <= fim:
            if atual >= inicio_exercicio:
                incluidos.append((atual, "projetado"))
            passo += 1
            atual = _somar_meses(primeira, 12 * passo)

    incluidos.sort()
    ciclos = [(dia, estado, _somar_meses(dia, -12)) for dia, estado in incluidos]
    return ciclos, ("ok" if ciclos else "sem_reajuste_na_vigencia")


def percentual_do_ciclo(
    data_base: date, desde: date, parametros: ParametrosReajuste, variacoes: dict | None
) -> tuple[float | None, str]:
    """Percentual do ciclo e sua origem: `manual`, `oficial`, `oficial_ultimo` (estimado) ou `sem_indice` (nulo —
    nunca 0%). O oficial acumula os meses de `desde` (12 meses antes) até o mês anterior à data-base."""

    if parametros.percentual_manual is not None and not pd.isna(parametros.percentual_manual):
        return float(parametros.percentual_manual), "manual"
    if (parametros.indice or "").upper() in INDICES and variacoes:
        percentual, origem = acumulado_periodo(
            variacoes, (desde.year, desde.month), (data_base.year, data_base.month)
        )
        if percentual is not None:
            return percentual, origem
    return None, "sem_indice"


def _meses_entre(inicio: tuple[int, int], fim: tuple[int, int]) -> list[tuple[int, int]]:
    meses, (ano, mes) = [], inicio
    while (ano, mes) <= fim:
        meses.append((ano, mes))
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return meses


def _fatores(
    ciclos: list[Ciclo], primeiro_dia: date, ultimo_dia: date, base_liquidada: bool = False
) -> tuple[float | None, float | None, list[Ciclo]]:
    """(fator dos formalizados, fator de todos, ciclos aplicáveis). Fator `None` quando um ciclo aplicável não tem
    percentual (os seguintes dependem dele). O mês da data-base é proporcional aos dias a partir dela. Com base
    LIQUIDADA, o ciclo já implantado antes do início do mês não incide (o liquidado já vem reajustado)."""

    aplicaveis = [c for c in ciclos if c.data_base <= ultimo_dia]
    formal: float | None = 1.0
    total: float | None = 1.0
    for ciclo in aplicaveis:
        if base_liquidada and ciclo.implementado_em is not None and primeiro_dia >= ciclo.implementado_em:
            continue
        if ciclo.percentual is None:
            total = None
            if ciclo.estado == "formalizado":
                formal = None
            break
        peso = 1.0 if ciclo.data_base <= primeiro_dia else (ultimo_dia.day - ciclo.data_base.day + 1) / ultimo_dia.day
        multiplicador = 1.0 + peso * ciclo.percentual / 100.0
        total *= multiplicador
        if ciclo.estado == "formalizado":
            formal *= multiplicador
    return formal, total, aplicaveis


def estimar_contrato(
    *, contrato: str, despesa_mensal: object, aditivos: list[Aditivo], vigencia_inicio: object,
    vigencia_fim: object, parametros: ParametrosReajuste, exercicio_inicial: int,
    variacoes: dict | None = None, liquidado: dict[tuple[int, int], float] | None = None,
    ultimo_mes_coberto: tuple[int, int] | None = None, reajustes_gov: list | None = None,
    retroativos: list[Retroativo] | None = None, apostilamentos: list[Apostilamento] | None = None,
) -> EstimativaContrato:
    """Matriz por competência (mês/ano) do contrato: de janeiro do exercício (ou do início da vigência, se
    posterior; ou do primeiro ciclo formalizado pendente, se anterior) ao fim da vigência efetiva. `liquidado` é o
    liquidado por competência do contrato (NEs de todos os exercícios, estornos com sinal)."""

    inicio_exercicio = date(exercicio_inicial, 1, 1)
    retroativos_exercicio = [r for r in retroativos or [] if r.assinatura >= inicio_exercicio]
    efetiva, _ = vigencia_efetiva(vigencia_fim, aditivos)
    fim_efetivo = None if pd.isna(efetiva) else efetiva.date()
    inicio = _como_data(vigencia_inicio)
    brutos, motivo = ciclos_do_contrato(
        inicio_contrato=inicio, fim_efetivo=fim_efetivo, aditivos=aditivos, reajustes_gov=reajustes_gov,
        retroativos=retroativos, data_base_manual=parametros.data_base_manual, inicio_exercicio=inicio_exercicio,
        apostilamentos=apostilamentos,
    )
    if fim_efetivo is None:
        return EstimativaContrato(pd.DataFrame(columns=COLUNAS_MATRIZ), "sem_vigencia_fim", [], retroativos_exercicio)

    ciclos = []
    for data_base, estado, desde in brutos:
        percentual, origem = percentual_do_ciclo(data_base, desde, parametros, variacoes)
        implantacao = implantacao_do_ciclo(data_base, apostilamentos) if estado == "formalizado" else None
        ciclos.append(Ciclo(data_base, estado, desde, percentual, origem, implantacao))

    garantido, _ = vigencia_efetiva(vigencia_fim, [a for a in aditivos if not a.previsto])
    garantido_data = None if pd.isna(garantido) else garantido.date()
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

    primeiro_mes = (exercicio_inicial, 1)
    pendentes_anteriores = [c.data_base for c in ciclos if c.data_base < inicio_exercicio]
    if pendentes_anteriores:
        primeiro = min(pendentes_anteriores)
        primeiro_mes = (primeiro.year, primeiro.month)
    if inicio is not None:
        primeiro_mes = max(primeiro_mes, (inicio.year, inicio.month))

    linhas = []
    for ano, mes in _meses_entre(primeiro_mes, (fim_efetivo.year, fim_efetivo.month)):
        primeiro_dia = date(ano, mes, 1)
        ultimo_dia = date(ano, mes, calendar.monthrange(ano, mes)[1])
        if liquidado is not None and (ano, mes) in liquidado:
            base, origem_base = float(liquidado[(ano, mes)]), "liquidado"
        elif ultimo_mes_coberto is not None and (ano, mes) <= ultimo_mes_coberto:
            base, origem_base = None, "sem_liquidado"
        else:
            base, origem_base = contratado(ano, mes), "contratado"

        formal, total, aplicaveis = _fatores(ciclos, primeiro_dia, ultimo_dia, origem_base == "liquidado")
        ultimo = aplicaveis[-1] if aplicaveis else None
        if motivo == "sem_data_base":
            formal = total = None  # data-base desconhecida: acréscimo desconhecido, não zero
        if not aplicaveis and motivo != "sem_data_base":
            acr_formal = acr_projetado = 0.0  # antes da primeira data-base nada incide
        else:
            acr_formal = _NAN if base is None or formal is None else base * (formal - 1.0)
            acr_projetado = _NAN if base is None or formal is None or total is None else base * (total - formal)
        linhas.append({
            "contrato": contrato, "ano": ano, "mes": mes, "competencia": f"{mes:02d}/{ano}",
            "exercicio_anterior": ano < exercicio_inicial,
            "base_valor": _NAN if base is None else base, "base_origem": origem_base,
            "ciclo": len(aplicaveis), "data_base": None if ultimo is None else ultimo.data_base,
            "estado_ciclo": None if ultimo is None else ultimo.estado,
            "percentual": _NAN if ultimo is None or ultimo.percentual is None else ultimo.percentual,
            "percentual_origem": None if ultimo is None else ultimo.origem,
            "fator": _NAN if total is None else total,
            "acrescimo_formalizado": acr_formal, "acrescimo_projetado": acr_projetado,
            "acrescimo": acr_formal + acr_projetado,
            "prorrogacao_prevista": bool(garantido_data is not None and ultimo_dia > garantido_data),
            "estorno_liquido": bool(origem_base == "liquidado" and base is not None and base < 0),
        })

    matriz = pd.DataFrame(linhas, columns=COLUNAS_MATRIZ)
    if motivo != "ok":
        situacao = motivo
    elif any(c.percentual is None for c in ciclos):
        situacao = "sem_indice"
    else:
        situacao = "estimado"
    return EstimativaContrato(matriz, situacao, ciclos, retroativos_exercicio)


def aditivo_previsto_do_ciclo(
    estimativa: EstimativaContrato, aditivos: list[Aditivo], despesa_mensal: object
) -> Aditivo | None:
    """Aditivo REAJUSTE/PREVISTO do próximo ciclo PROJETADO ainda sem aditivo, com percentual conhecido:
    `data_inicio` = data-base e `valor_mensal` = valor mensal em vigor × (1 + percentual). Ciclo formalizado não se
    promove (registre o aditivo assinado com o valor real). `None` quando não há ciclo promovível. Não grava nada."""

    ocupadas = {a.data_inicio for a in aditivos if a.data_inicio is not None}
    for ciclo in estimativa.ciclos:
        if ciclo.estado != "projetado" or ciclo.data_base in ocupadas:
            continue
        if ciclo.percentual is None:
            return None
        vigente, _ = valor_vigente_em(despesa_mensal, aditivos, ciclo.data_base)
        if vigente is None:
            return None
        return Aditivo(
            numero=f"Reajuste previsto {ciclo.data_base:%m/%Y}", tipo="REAJUSTE", situacao="PREVISTO",
            data_inicio=ciclo.data_base, valor_mensal=round(vigente * (1.0 + ciclo.percentual / 100.0), 2),
        )
    return None


def nes_em_conflito(registros: list[dict]) -> dict[str, set[str]]:
    """NEs ligadas a mais de um `contrato_numero` (entre os registros de todos os exercícios). Uma NE
    pertence a um único contrato: a repetição é inconsistência de cadastro — sinalizada, e o liquidado dessa
    NE fica fora da base até a correção (nunca se escolhe um contrato por conta própria)."""

    por_ne: dict[str, set[str]] = {}
    for registro in registros:
        ne, contrato = registro.get("ne_curta"), registro.get("contrato_numero")
        if _vazio(ne) or _vazio(contrato) or not str(ne).strip() or not str(contrato).strip():
            continue
        por_ne.setdefault(str(ne).strip(), set()).add(str(contrato).strip())
    return {ne: contratos for ne, contratos in por_ne.items() if len(contratos) > 1}


def liquidado_do_contrato(nes: set[str], liquidacao_por_mes: pd.DataFrame | None) -> dict[tuple[int, int], float]:
    """Liquidado por competência (ano, mês) das `nes` do contrato, estornos com sinal. `liquidacao_por_mes`
    é o `liquidado_por_ne_e_mes` com `ne_curta` (colunas `ne_curta`, `ano_mes` AAAAMM e `valor`). Só
    aparece o mês com lançamento — ausência é ausência de dado."""

    if liquidacao_por_mes is None or liquidacao_por_mes.empty or not nes:
        return {}
    recorte = liquidacao_por_mes[liquidacao_por_mes["ne_curta"].isin(nes)]
    resultado: dict[tuple[int, int], float] = {}
    for ano_mes, valor in recorte.groupby("ano_mes")["valor"].sum().items():
        resultado[(int(ano_mes) // 100, int(ano_mes) % 100)] = float(valor)
    return resultado


def ultimo_mes_coberto(liquidacao_por_mes: pd.DataFrame | None, hoje: date | None = None) -> tuple[int, int] | None:
    """Último mês (ano, mês) que se considera APURADO na base de Liquidação por Competência: o mês anterior ao
    de `hoje`, nunca além do maior mês presente na base. Não é o maior mês da base: ela traz competências
    futuras esparsas (documentos hábeis com referência adiante) que não indicam cobertura. `None` sem base.
    Dúvida registrada: o último mês cheio ainda pode receber liquidação tardia."""

    if liquidacao_por_mes is None or liquidacao_por_mes.empty:
        return None
    hoje = hoje or date.today()
    maior = int(liquidacao_por_mes["ano_mes"].max())
    anterior = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
    return min((maior // 100, maior % 100), anterior)
