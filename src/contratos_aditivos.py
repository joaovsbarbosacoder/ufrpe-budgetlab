"""
Aditivos de Contratos Contínuos — modelo, validação e valores vigentes (06/10/2026).

Camada: regra de negócio pura (só pandas/datetime; sem Streamlit, sem leitura de arquivo). Spec:
`docs/superpowers/specs/2026-10-06-aditivos-contratos-design.md`.

Quando um contrato é prorrogado, o valor mensal normalmente é reajustado; um único `despesa_mensal`
por contrato fazia o valor novo valer para o exercício inteiro e distorcia a projeção. O contrato
passa a guardar uma lista de aditivos (`aditivos`, mesmo padrão de `itens`): cada um diz o que muda
(valor mensal, vigência, rateio dos itens) e a partir de quando. `despesa_mensal` e `vigencia_fim` do
contrato são sempre os ORIGINAIS (antes do 1º aditivo) e nunca são sobrescritos; o valor, a vigência
e o rateio em vigor numa data são derivados aqui, na hora.

Campo vazio de um aditivo = "mantém o anterior" (nulo, nunca zero). `numero` é identificador (texto,
nunca convertido em número). Datas são gravadas como texto "AAAA-MM-DD" (o `st.date_input` devolve
`date`, que o motor de persistência não serializa dentro de estruturas aninhadas).

Contrato público:
    TIPOS, SITUACOES, ROTULO_TIPO, ROTULO_SITUACAO
    Aditivo (dataclass)
    aditivos_do_registro(bruto) -> list[Aditivo]
    aditivo_para_registro(aditivo) -> dict
    validar_aditivos(aditivos) -> list[str]
    valor_vigente_em(despesa_mensal, aditivos, dia) -> (valor | None, Aditivo | None)
    rateio_vigente_em(itens_base, aditivos, dia) -> list[dict]
    vigencia_efetiva(vigencia_fim, aditivos) -> (Timestamp, Aditivo | None)
    serie_valor_mensal(despesa_mensal, aditivos, exercicio, numero_item=None, itens_base=None) -> list[float]
    custo_mensal(despesa_mensal, aditivos, exercicio, *, status, vigencia_fim, ...) -> list[float]
    retroativo_por_aditivo(despesa_mensal, aditivos, exercicio, meses_realizados) -> list[(Aditivo, float)]
    meses_com_previsto(aditivos, exercicio) -> set[int]
    dia_de_referencia(exercicio, hoje=None) -> date
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from src.necessidade_empenho import janela_de_execucao

TIPOS = ("REAJUSTE", "REPACTUACAO", "PRORROGACAO", "ACRESCIMO_SUPRESSAO", "OUTRO")
SITUACOES = ("PREVISTO", "ASSINADO")

#: rótulos para tela e relatórios
ROTULO_TIPO = {
    "REAJUSTE": "Reajuste", "REPACTUACAO": "Repactuação", "PRORROGACAO": "Prorrogação",
    "ACRESCIMO_SUPRESSAO": "Acréscimo/supressão", "OUTRO": "Outro",
}
ROTULO_SITUACAO = {"ASSINADO": "Assinado", "PREVISTO": "Previsto"}

#: tolerância (pontos percentuais) na soma do rateio, a mesma da janela de itens de licitação.
_TOLERANCIA_RATEIO = 0.5
_ITEM_UNICO = [{"numero": 1, "percentual": 100.0}]


@dataclass(frozen=True)
class Aditivo:
    """Um aditivo do contrato. `data_inicio` é obrigatória (pode ser passada: retroativo) — fica
    `None` só enquanto o formulário está incompleto, e `validar_aditivos` recusa. Campo opcional
    nulo = mantém o anterior."""

    numero: str
    tipo: str
    situacao: str
    data_inicio: date | None
    data_assinatura: date | None = None
    valor_mensal: float | None = None
    vigencia_fim: date | None = None
    itens: list[dict] | None = None

    @property
    def previsto(self) -> bool:
        return self.situacao == "PREVISTO"


def _vazio(valor: object) -> bool:
    return valor is None or (not isinstance(valor, (list, dict)) and bool(pd.isna(valor)))


def _para_data(valor: object, campo: str) -> date | None:
    if _vazio(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.date()
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError as erro:
        raise ValueError(f"Aditivo com {campo} inválida ({valor!r}); esperado AAAA-MM-DD.") from erro


def _dia(dia: object) -> date:
    return _para_data(dia, "data")  # type: ignore[return-value]


def _numero(valor: object) -> float | None:
    return None if _vazio(valor) else float(valor)


def _itens(valor: object) -> list[dict] | None:
    if _vazio(valor) or not isinstance(valor, list):
        return None
    return [{"numero": int(item["numero"]), "percentual": float(item["percentual"])} for item in valor]


def _chave_ordem(aditivo: Aditivo) -> tuple:
    return (aditivo.data_inicio is None, aditivo.data_inicio or date.min)


def aditivos_do_registro(bruto: object) -> list[Aditivo]:
    """Aditivos do registro do contrato (lista de dicts gravada no JSON) em ordem de `data_inicio`.
    Ausente, nulo ou vazio → lista vazia (registro anterior aos aditivos). Data ilegível levanta
    `ValueError` — dado financeiro nunca é descartado em silêncio."""

    if not isinstance(bruto, list):
        return []
    aditivos = []
    for item in bruto:
        if isinstance(item, Aditivo):
            aditivos.append(item)
            continue
        aditivos.append(
            Aditivo(
                numero=str(item.get("numero") or ""),
                tipo=str(item.get("tipo") or "").upper(),
                situacao=str(item.get("situacao") or "").upper(),
                data_inicio=_para_data(item.get("data_inicio"), "data de início"),
                data_assinatura=_para_data(item.get("data_assinatura"), "data de assinatura"),
                valor_mensal=_numero(item.get("valor_mensal")),
                vigencia_fim=_para_data(item.get("vigencia_fim"), "vigência"),
                itens=_itens(item.get("itens")),
            )
        )
    return sorted(aditivos, key=_chave_ordem)


def aditivo_para_registro(aditivo: Aditivo) -> dict:
    """Aditivo no formato gravado no JSON do contrato (datas ISO, `numero` como texto)."""

    def iso(dia: date | None) -> str | None:
        return None if dia is None else dia.isoformat()

    return {
        "numero": str(aditivo.numero),
        "tipo": aditivo.tipo,
        "situacao": aditivo.situacao,
        "data_inicio": iso(aditivo.data_inicio),
        "data_assinatura": iso(aditivo.data_assinatura),
        "valor_mensal": aditivo.valor_mensal,
        "vigencia_fim": iso(aditivo.vigencia_fim),
        "itens": None if aditivo.itens is None else [dict(item) for item in aditivo.itens],
    }


def _rotulo(aditivo: Aditivo) -> str:
    return aditivo.numero.strip() or "Aditivo sem nº"


def validar_aditivos(aditivos: list[Aditivo]) -> list[str]:
    """Mensagens de erro (lista vazia = válido), cada uma prefixada pelo nº do termo. Valor mensal
    negativo é aceito (a base real já teve um caso)."""

    erros = []
    for aditivo in aditivos:
        rotulo = _rotulo(aditivo)
        if not aditivo.numero.strip():
            erros.append("Aditivo sem nº: informe o número do termo.")
        if aditivo.tipo not in TIPOS:
            erros.append(f"{rotulo}: tipo inválido.")
        if aditivo.situacao not in SITUACOES:
            erros.append(f"{rotulo}: situação inválida.")
        if aditivo.data_inicio is None:
            erros.append(f"{rotulo}: informe a data de início.")
        if aditivo.valor_mensal is None and aditivo.vigencia_fim is None and aditivo.itens is None:
            erros.append(f"{rotulo}: informe ao menos novo valor, nova vigência ou novo rateio.")
        if aditivo.itens is not None:
            soma = sum(item["percentual"] for item in aditivo.itens)
            if abs(soma - 100) > _TOLERANCIA_RATEIO:
                erros.append(f"{rotulo}: o rateio dos itens precisa fechar em 100% (está em {soma:.1f}%).")

    por_data: dict[date, list[Aditivo]] = {}
    for aditivo in aditivos:
        if aditivo.data_inicio is not None:
            por_data.setdefault(aditivo.data_inicio, []).append(aditivo)
    for data, grupo in sorted(por_data.items()):
        if len(grupo) > 1:
            nomes = " e ".join(_rotulo(a) for a in grupo)
            erros.append(f"{nomes}: a mesma data de início ({data:%d/%m/%Y}) deixa a ordem ambígua.")
    return erros


def _em_vigor(aditivos: list[Aditivo], dia: object) -> list[Aditivo]:
    limite = _dia(dia)
    return [a for a in sorted(aditivos, key=_chave_ordem) if a.data_inicio is not None and a.data_inicio <= limite]


def valor_vigente_em(
    despesa_mensal: object, aditivos: list[Aditivo], dia: object
) -> tuple[float | None, Aditivo | None]:
    """Valor mensal em vigor em `dia` e o aditivo que o definiu: o `valor_mensal` do último aditivo
    iniciado até `dia` que tem valor; senão a `despesa_mensal` original (nula continua nula)."""

    vigente = next((a for a in reversed(_em_vigor(aditivos, dia)) if a.valor_mensal is not None), None)
    if vigente is not None:
        return vigente.valor_mensal, vigente
    return _numero(despesa_mensal), None


def rateio_vigente_em(itens_base: list[dict] | None, aditivos: list[Aditivo], dia: object) -> list[dict]:
    """Rateio dos itens de licitação em vigor em `dia`: o do último aditivo iniciado até lá que o
    informa; senão `itens_base` (item único a 100% quando vazio)."""

    vigente = next((a for a in reversed(_em_vigor(aditivos, dia)) if a.itens is not None), None)
    if vigente is not None:
        return [dict(item) for item in vigente.itens]
    if isinstance(itens_base, list) and itens_base:
        return [dict(item) for item in itens_base]
    return [dict(item) for item in _ITEM_UNICO]


def vigencia_efetiva(vigencia_fim: object, aditivos: list[Aditivo]) -> tuple[pd.Timestamp, Aditivo | None]:
    """Vigência (fim) efetiva: a do último aditivo (por data de início) que a informa; senão a do
    contrato. O aditivo que a definiu vem junto (ou `None`); `NaT` quando não há nenhuma."""

    com_vigencia = [a for a in sorted(aditivos, key=_chave_ordem) if a.vigencia_fim is not None]
    if com_vigencia:
        ultimo = com_vigencia[-1]
        return pd.Timestamp(ultimo.vigencia_fim), ultimo
    if _vazio(vigencia_fim):
        return pd.NaT, None
    return pd.Timestamp(vigencia_fim), None


# ---------------------------------------------------------------------------------------------
# Série mensal, custo do mês, retroativo e previstos (spec §4)
# ---------------------------------------------------------------------------------------------


def _dias_do_exercicio(exercicio: int) -> list[date]:
    dia, ultimo = date(exercicio, 1, 1), date(exercicio, 12, 31)
    dias = []
    while dia <= ultimo:
        dias.append(dia)
        dia += timedelta(days=1)
    return dias


def _dias_no_mes(dia: date) -> int:
    return calendar.monthrange(dia.year, dia.month)[1]


def _valores_diarios(
    despesa_mensal: object, aditivos: list[Aditivo], exercicio: int,
    numero_item: int | None = None, itens_base: list[dict] | None = None,
) -> list[tuple[date, float | None]]:
    """(dia, valor mensal em vigor no dia) para cada dia do exercício. Com `numero_item`, o valor do
    item: valor do contrato × percentual do item no rateio vigente ÷ 100 (0 se o item não está no
    rateio). Valor ainda desconhecido (despesa original nula antes do 1º valor de aditivo) = `None`."""

    ordenados = [a for a in sorted(aditivos, key=_chave_ordem) if a.data_inicio is not None]
    valor = _numero(despesa_mensal)
    rateio = itens_base if isinstance(itens_base, list) and itens_base else _ITEM_UNICO
    proximo = 0
    resultado = []
    for dia in _dias_do_exercicio(exercicio):
        while proximo < len(ordenados) and ordenados[proximo].data_inicio <= dia:
            aditivo = ordenados[proximo]
            if aditivo.valor_mensal is not None:
                valor = aditivo.valor_mensal
            if aditivo.itens is not None:
                rateio = aditivo.itens
            proximo += 1
        if numero_item is None or valor is None:
            resultado.append((dia, valor))
        else:
            percentual = next((float(i["percentual"]) for i in rateio if int(i["numero"]) == numero_item), 0.0)
            resultado.append((dia, valor * percentual / 100))
    return resultado


def _agregar_por_mes(contribuicoes: list[tuple[date, float | None]]) -> list[float]:
    """Por mês (12 valores): a soma dos valores diários ÷ dias do mês — dividir só no fim (e não somar
    `valor ÷ dias` dia a dia) mantém exatos os valores que são múltiplos inteiros, como `1.000 × 31 ÷ 31`.
    Mês sem nenhuma contribuição = 0,0; mês com alguma contribuição de valor desconhecido (`None`) = NaN
    — nunca vira zero."""

    soma = [0.0] * 12
    dias = [0] * 12
    desconhecido = [False] * 12
    for dia, valor in contribuicoes:
        dias[dia.month - 1] = _dias_no_mes(dia)
        if valor is None:
            desconhecido[dia.month - 1] = True
        else:
            soma[dia.month - 1] += valor
    return [float("nan") if desconhecido[i] else (soma[i] / dias[i] if dias[i] else 0.0) for i in range(12)]


def serie_valor_mensal(
    despesa_mensal: object, aditivos: list[Aditivo], exercicio: int,
    numero_item: int | None = None, itens_base: list[dict] | None = None,
) -> list[float]:
    """12 valores mensais do `exercicio`: a média, por dia, do valor mensal em vigor (um reajuste no
    meio do mês dá o valor proporcional aos dias dos dois lados). Sem corte de vigência, início ou
    suspensão (ver `custo_mensal`). NaN no mês em que o valor é desconhecido."""

    diarios = _valores_diarios(despesa_mensal, aditivos, exercicio, numero_item, itens_base)
    return _agregar_por_mes(diarios)


def custo_mensal(
    despesa_mensal: object, aditivos: list[Aditivo], exercicio: int, *,
    status: object, vigencia_fim: object, inicio: object = None, data_suspensao: object = None,
    meses_no_ano: object = None, numero_item: int | None = None, itens_base: list[dict] | None = None,
) -> list[float]:
    """Custo de cada mês do `exercicio`: a soma, nos dias em que o contrato está em execução, do valor
    em vigor ÷ dias do mês. A janela de execução é a de `janela_de_execucao` com a vigência
    EFETIVA (`vigencia_efetiva`, a do último aditivo que a altera) — SUSPENSO, VENCIDO sem data e
    início/fim fora do exercício seguem as regras de sempre. `meses_no_ano` (teto de referência; vazio
    = sem teto) para de contar quando a soma das frações mensais dos dias em execução o atinge.
    Mês fora da janela = 0,0; valor desconhecido em dia contado = NaN; sem nenhum valor conhecido no
    exercício, os 12 meses são NaN (despesa nula continua nula). Sem aditivo e com valor constante, a
    soma é `despesa_mensal × meses em execução` — a conta de antes dos aditivos."""

    diarios = _valores_diarios(despesa_mensal, aditivos, exercicio, numero_item, itens_base)
    if all(valor is None for _, valor in diarios):
        return [float("nan")] * 12
    efetiva, _ = vigencia_efetiva(vigencia_fim, aditivos)
    janela = janela_de_execucao(status, efetiva, exercicio, inicio, data_suspensao)
    if janela is None:
        return [0.0] * 12
    primeiro, ultimo = janela[0].date(), janela[1].date()
    teto = None if _vazio(meses_no_ano) else float(meses_no_ano)

    contribuicoes = []
    acumulado = 0.0
    for dia, valor in diarios:
        if dia < primeiro or dia > ultimo:
            continue
        fracao = 1.0 / _dias_no_mes(dia)
        peso = 1.0  # fração do dia que conta (o último dia pode contar parcialmente, por causa do teto)
        if teto is not None:
            restante = teto - acumulado
            if restante <= 1e-9:
                break
            peso = min(1.0, restante / fracao)
            if peso > 1.0 - 1e-9:  # erro de ponto flutuante do acumulado: o dia conta inteiro
                peso = 1.0
        acumulado += fracao * peso
        contribuicoes.append((dia, None if valor is None else valor * peso))
    return _agregar_por_mes(contribuicoes)


def retroativo_por_aditivo(
    despesa_mensal: object, aditivos: list[Aditivo], exercicio: int, meses_realizados: set[int],
) -> list[tuple[Aditivo, float]]:
    """Retroativo de cada aditivo ASSINADO com valor novo e `data_assinatura` posterior à
    `data_inicio`: a soma, nos dias de [data_inicio, data_assinatura) do `exercicio` que caem em meses
    já realizados (`meses_realizados`, 1-12), de (valor em vigor − valor sem esse aditivo) ÷ dias do
    mês. Aditivo previsto, sem assinatura, sem valor ou assinado no próprio dia do início não tem
    retroativo (não entra no resultado)."""

    resultado = []
    for aditivo in aditivos:
        if (
            aditivo.situacao != "ASSINADO" or aditivo.valor_mensal is None
            or aditivo.data_assinatura is None or aditivo.data_inicio is None
            or aditivo.data_assinatura <= aditivo.data_inicio
        ):
            continue
        sem_este = [a for a in aditivos if a is not aditivo]
        com = dict(_valores_diarios(despesa_mensal, aditivos, exercicio))
        sem = dict(_valores_diarios(despesa_mensal, sem_este, exercicio))
        total = 0.0
        for dia, valor in com.items():
            if not (aditivo.data_inicio <= dia < aditivo.data_assinatura) or dia.month not in meses_realizados:
                continue
            anterior = sem[dia]
            if valor is None or anterior is None:
                continue
            total += (valor - anterior) / _dias_no_mes(dia)
        resultado.append((aditivo, total))
    return resultado


def meses_com_previsto(aditivos: list[Aditivo], exercicio: int) -> set[int]:
    """Meses (1-12) do `exercicio` cujo valor mensal ou cuja vigência vem de um aditivo PREVISTO —
    valores estimados, a marcar em tela e relatórios. Vigência: os meses entre o fim da vigência
    garantida (sem os previstos) e a vigência efetiva."""

    meses = set()
    for dia in _dias_do_exercicio(exercicio):
        _, definidor = valor_vigente_em(None, aditivos, dia)
        if definidor is not None and definidor.previsto:
            meses.add(dia.month)

    _, definidor_vigencia = vigencia_efetiva(None, aditivos)
    if definidor_vigencia is not None and definidor_vigencia.previsto:
        garantida, _ = vigencia_efetiva(None, [a for a in aditivos if not a.previsto])
        efetiva, _ = vigencia_efetiva(None, aditivos)
        if not pd.isna(garantida):
            for dia in _dias_do_exercicio(exercicio):
                if pd.Timestamp(dia) > garantida and pd.Timestamp(dia) <= efetiva:
                    meses.add(dia.month)
    return meses


def dia_de_referencia(exercicio: int | None, hoje: date | None = None) -> date:
    """"Hoje" limitado ao exercício: hoje se está nele, 31/12 se o exercício já passou, 01/01 se ainda
    não começou. Sem exercício, hoje. Usado para o "valor mensal vigente" exibido."""

    hoje = hoje or date.today()
    if exercicio is None:
        return hoje
    if hoje.year > exercicio:
        return date(exercicio, 12, 31)
    if hoje.year < exercicio:
        return date(exercicio, 1, 1)
    return hoje
