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
    TIPOS, SITUACOES
    Aditivo (dataclass)
    aditivos_do_registro(bruto) -> list[Aditivo]
    aditivo_para_registro(aditivo) -> dict
    validar_aditivos(aditivos) -> list[str]
    valor_vigente_em(despesa_mensal, aditivos, dia) -> (valor | None, Aditivo | None)
    rateio_vigente_em(itens_base, aditivos, dia) -> list[dict]
    vigencia_efetiva(vigencia_fim, aditivos) -> (Timestamp, Aditivo | None)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

TIPOS = ("REAJUSTE", "REPACTUACAO", "PRORROGACAO", "ACRESCIMO_SUPRESSAO", "OUTRO")
SITUACOES = ("PREVISTO", "ASSINADO")

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
