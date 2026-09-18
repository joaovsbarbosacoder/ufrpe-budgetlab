"""Testes de `src/teds_calculos.py` com os números de 2026 citados no briefing."""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.teds_calculos import (
    ResumoFinanceiroTed,
    diferenca_nc_pf,
    nc_liquida,
    percentual_financeiro,
    pf_liquida,
    saldo_a_liquidar,
    saldo_a_pagar,
    saldo_empenho,
)


class CalculosPrincipaisTests(unittest.TestCase):
    def test_totais_2026_ug_153165(self):
        nc_liq = nc_liquida(Decimal("5076636.25"), Decimal("0.00"))
        pf_liq = pf_liquida(Decimal("2748263.99"), Decimal("0.00"))
        self.assertEqual(nc_liq, Decimal("5076636.25"))
        self.assertEqual(pf_liq, Decimal("2748263.99"))
        self.assertEqual(diferenca_nc_pf(nc_liq, pf_liq), Decimal("2328372.26"))

    def test_percentual_indisponivel_quando_denominador_zero(self):
        self.assertIsNone(percentual_financeiro(Decimal("0"), Decimal("0")))
        self.assertIsNone(percentual_financeiro(Decimal("100"), Decimal("0")))

    def test_percentual_calculado(self):
        percentual = percentual_financeiro(Decimal("50"), Decimal("200"))
        self.assertEqual(percentual, Decimal("0.25"))

    def test_saldos(self):
        self.assertEqual(saldo_empenho(Decimal("388300.00"), Decimal("388300.00")), Decimal("0.00"))
        self.assertEqual(saldo_a_liquidar(Decimal("388300.00"), Decimal("100000.00")), Decimal("288300.00"))
        self.assertEqual(saldo_a_pagar(Decimal("100000.00"), Decimal("60000.00")), Decimal("40000.00"))


class ResumoFinanceiroTedTests(unittest.TestCase):
    def test_ted_17352_bate_exatamente(self):
        resumo = ResumoFinanceiroTed(
            chave_ted="17352|1ABDKU",
            nc_liquida=Decimal("388300.00"),
            pf_liquida=Decimal("388300.00"),
            empenhado_liquido=Decimal("388300.00"),
            liquidado=Decimal("0.00"),
            pago=Decimal("0.00"),
        )
        self.assertEqual(resumo.diferenca_nc_pf, Decimal("0.00"))
        self.assertEqual(resumo.percentual_financeiro, Decimal("1.00"))
        self.assertEqual(resumo.saldo_empenho, Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
