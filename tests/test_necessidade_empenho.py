"""Testes de src/necessidade_empenho.py."""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.necessidade_empenho import calcular_necessidade_empenho, necessidade_ate_mes_vigente


class TestCalcularNecessidadeEmpenho(unittest.TestCase):
    def test_meses_a_empenhar_e_empenhado_menos_liquidado(self):
        meses, valor = calcular_necessidade_empenho(pd.Series([8.0]), pd.Series([5.0]), pd.Series([1000.0]))
        self.assertAlmostEqual(meses.iloc[0], 3.0)
        self.assertAlmostEqual(valor.iloc[0], 3000.0)


class TestNecessidadeAteMesVigente(unittest.TestCase):
    def test_exemplo_do_pedido_despesa_120_mil_empenhado_70_mil_outubro(self):
        # despesa anual 120 mil -> mensal 10 mil; já empenhado 70 mil; início em janeiro (mês
        # 1); "hoje" outubro (mês 10) -> deveria estar empenhado 10 mil x 10 = 100 mil ->
        # sugestão 100 mil - 70 mil = 30 mil (exemplo exato do pedido).
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([70_000.0]), pd.Series([1]), hoje=date(2026, 10, 15),
        )
        self.assertAlmostEqual(valor.iloc[0], 30_000.0)
        self.assertAlmostEqual(meses.iloc[0], 3.0)

    def test_ja_empenhado_acima_do_alvo_nao_fica_negativo(self):
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([150_000.0]), pd.Series([1]), hoje=date(2026, 10, 15),
        )
        self.assertEqual(valor.iloc[0], 0.0)
        self.assertEqual(meses.iloc[0], 0.0)

    def test_inicio_no_mes_vigente_conta_como_1_mes(self):
        # início em outubro, hoje também outubro -> só 1 mês decorrido (contagem inclusiva).
        meses, _ = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([0.0]), pd.Series([10]), hoje=date(2026, 10, 15),
        )
        self.assertAlmostEqual(meses.iloc[0], 1.0)

    def test_inicio_desconhecido_gera_nan(self):
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([70_000.0]), pd.Series([pd.NA], dtype="Int64"), hoje=date(2026, 10, 15),
        )
        self.assertTrue(pd.isna(meses.iloc[0]))
        self.assertTrue(pd.isna(valor.iloc[0]))


if __name__ == "__main__":
    unittest.main()
