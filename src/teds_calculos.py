"""
Cálculos financeiros do acompanhamento de TEDs — ver "Cálculos principais" no briefing.

Tudo em `Decimal` (nunca `float`); percentuais ficam `None` quando o denominador é zero
("indisponível", não "0%" — regra explícita do briefing).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def nc_liquida(total_nc_descentralizacao: Decimal, total_nc_devolucao: Decimal) -> Decimal:
    return total_nc_descentralizacao - total_nc_devolucao


def pf_liquida(total_pf_repasse: Decimal, total_pf_devolucao: Decimal) -> Decimal:
    return total_pf_repasse - total_pf_devolucao


def diferenca_nc_pf(nc_liq: Decimal, pf_liq: Decimal) -> Decimal:
    return nc_liq - pf_liq


def percentual_financeiro(pf_liq: Decimal, nc_liq: Decimal) -> Decimal | None:
    if nc_liq == 0:
        return None
    return pf_liq / nc_liq


def saldo_empenho(nc_liq: Decimal, empenhado_liquido: Decimal) -> Decimal:
    return nc_liq - empenhado_liquido


def saldo_a_liquidar(empenhado_liquido: Decimal, liquidado: Decimal) -> Decimal:
    return empenhado_liquido - liquidado


def saldo_a_pagar(liquidado: Decimal, pago: Decimal) -> Decimal:
    return liquidado - pago


@dataclass(frozen=True)
class ResumoFinanceiroTed:
    """Agregado de indicadores de um único TED, num único exercício de emissão."""

    chave_ted: str
    nc_liquida: Decimal
    pf_liquida: Decimal
    empenhado_liquido: Decimal
    liquidado: Decimal
    pago: Decimal

    @property
    def diferenca_nc_pf(self) -> Decimal:
        return diferenca_nc_pf(self.nc_liquida, self.pf_liquida)

    @property
    def percentual_financeiro(self) -> Decimal | None:
        return percentual_financeiro(self.pf_liquida, self.nc_liquida)

    @property
    def saldo_empenho(self) -> Decimal:
        return saldo_empenho(self.nc_liquida, self.empenhado_liquido)

    @property
    def saldo_a_liquidar(self) -> Decimal:
        return saldo_a_liquidar(self.empenhado_liquido, self.liquidado)

    @property
    def saldo_a_pagar(self) -> Decimal:
        return saldo_a_pagar(self.liquidado, self.pago)
