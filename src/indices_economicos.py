"""
Índices econômicos oficiais (BCB/SGS) para a estimativa de reajuste de contratos (11/10/2026).

Camada: acesso a dado externo + regra pura de acumulação. Não importa Streamlit. Spec:
`docs/superpowers/specs/2026-10-11-estimativa-reajuste-contratos-design.md`.

Nada é gravado: a consulta é de sessão (a página a coloca em cache). Falha de rede, resposta inválida ou
índice desconhecido levantam `ErroIndiceEconomico` — quem consome mostra a falha e segue só com o percentual
manual; um índice ausente nunca vira 0%.

Contrato público:
    SERIES_BCB, INDICES
    ErroIndiceEconomico
    variacoes_bcb(indice, inicio, fim, *, buscar=None) -> dict[(ano, mes), float]   # variação mensal, em %
    acumulado_12m(variacoes, ano, mes) -> (percentual | None, origem)
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date
from typing import Callable

#: série mensal de variação (%) no SGS/BCB: IPCA, INPC e IGP-M.
SERIES_BCB = {"IPCA": 433, "INPC": 188, "IGPM": 189}
INDICES = tuple(SERIES_BCB)

_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados?formato=json&dataInicial={inicio}&dataFinal={fim}"
_TIMEOUT_SEGUNDOS = 20.0


class ErroIndiceEconomico(RuntimeError):
    """Índice indisponível: desconhecido, rede fora do ar ou resposta fora do formato esperado."""


def _buscar_http(url: str) -> list[dict]:
    requisicao = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ufrpe-budgetlab"})
    with urllib.request.urlopen(requisicao, timeout=_TIMEOUT_SEGUNDOS) as resposta:  # noqa: S310 (URL fixa https)
        return json.loads(resposta.read().decode("utf-8"))


def variacoes_bcb(
    indice: str, inicio: date, fim: date, *, buscar: Callable[[str], list[dict]] | None = None
) -> dict[tuple[int, int], float]:
    """Variação mensal (%) do `indice` entre `inicio` e `fim`, por (ano, mês). `buscar` (URL → JSON) é
    injetável para testes; o padrão consulta a API pública do BCB."""

    serie = SERIES_BCB.get(str(indice).upper())
    if serie is None:
        raise ErroIndiceEconomico(f"Índice desconhecido: {indice!r}. Disponíveis: {', '.join(INDICES)}.")
    url = _URL.format(serie=serie, inicio=inicio.strftime("%d/%m/%Y"), fim=fim.strftime("%d/%m/%Y"))
    try:
        dados = (buscar or _buscar_http)(url)
    except (OSError, ValueError) as erro:
        raise ErroIndiceEconomico(f"Não foi possível consultar o {indice} no Banco Central ({erro}).") from erro
    if not isinstance(dados, list):
        raise ErroIndiceEconomico(f"Resposta inesperada do Banco Central para o {indice}.")
    resultado: dict[tuple[int, int], float] = {}
    for item in dados:
        try:
            dia, mes, ano = str(item["data"]).split("/")
            resultado[(int(ano), int(mes))] = float(str(item["valor"]).replace(",", "."))
        except (KeyError, ValueError, TypeError) as erro:
            raise ErroIndiceEconomico(f"Registro inválido do Banco Central para o {indice}: {item!r}.") from erro
    return resultado


def _mes_anterior(ano: int, mes: int) -> tuple[int, int]:
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)


def _janela(ano: int, mes: int) -> list[tuple[int, int]]:
    """12 meses terminando em (ano, mes), em ordem cronológica."""

    meses = []
    for _ in range(12):
        meses.append((ano, mes))
        ano, mes = _mes_anterior(ano, mes)
    return meses[::-1]


def acumulado_12m(
    variacoes: dict[tuple[int, int], float], ano: int, mes: int
) -> tuple[float | None, str]:
    """Acumulado (%) dos 12 meses anteriores ao mês (`ano`, `mes`) da data-base. Origem: `oficial` (os 12
    meses esperados existem), `oficial_ultimo` (a série ainda não chegou lá: usa os 12 meses terminando no
    último mês disponível anterior à data-base — estimativa) ou `ausente` (menos de 12 meses disponíveis:
    nulo, nunca 0%)."""

    fim_esperado = _mes_anterior(ano, mes)
    disponiveis = [chave for chave in variacoes if chave <= fim_esperado]
    if not disponiveis:
        return None, "ausente"
    ultimo = max(disponiveis)
    janela = _janela(*ultimo)
    if any(chave not in variacoes for chave in janela):
        return None, "ausente"
    fator = 1.0
    for chave in janela:
        fator *= 1.0 + variacoes[chave] / 100.0
    origem = "oficial" if ultimo == fim_esperado else "oficial_ultimo"
    return (fator - 1.0) * 100.0, origem
