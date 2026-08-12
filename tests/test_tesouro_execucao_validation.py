"""Testes de reconciliação independente da Execução da Despesa."""

import unittest

import pandas as pd

from src.tesouro_execucao import transform_execucao_sheet
from src.tesouro_execucao_validation import validate_execucao_normalization
from tests.test_tesouro_execucao import make_execucao_raw


class TesouroExecucaoValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = make_execucao_raw()
        self.normalized = transform_execucao_sheet(self.raw, "execucao.xlsx", "Execução").normalized_data

    def test_reconciles_by_measure_year_and_measure_year(self) -> None:
        validation = validate_execucao_normalization(self.raw, self.normalized, "Execução")
        self.assertTrue(validation.approved)
        self.assertEqual(validation.raw_data_row_count, 3)
        self.assertEqual(validation.monetary_cell_count, 9)
        self.assertEqual(validation.normalized_row_count, 9)
        self.assertTrue(validation.metric_comparison["consistente"].all())
        self.assertTrue(validation.year_comparison["consistente"].all())
        self.assertTrue(validation.metric_year_comparison["consistente"].all())

    def test_detects_divergence_and_preserves_input_dataframes(self) -> None:
        original_raw = self.raw.copy(deep=True)
        original_normalized = self.normalized.copy(deep=True)
        divergent = self.normalized.copy(deep=True)
        divergent.loc[0, "valor_movimento_liquido"] = 1.0
        validation = validate_execucao_normalization(self.raw, divergent, "Execução")
        self.assertFalse(validation.approved)
        self.assertIn("soma_por_medida", set(validation.inconsistencies["tipo"]))
        self.assertIn("soma_por_ano", set(validation.inconsistencies["tipo"]))
        self.assertIn("soma_por_medida_ano", set(validation.inconsistencies["tipo"]))
        self.assertIn("valor_por_coordenada", set(validation.inconsistencies["tipo"]))
        pd.testing.assert_frame_equal(self.raw, original_raw)
        pd.testing.assert_frame_equal(self.normalized, original_normalized)

    def test_detects_duplicate_source_coordinates(self) -> None:
        duplicated = pd.concat([self.normalized, self.normalized.iloc[[0]]], ignore_index=True)
        validation = validate_execucao_normalization(self.raw, duplicated, "Execução")
        self.assertFalse(validation.approved)
        self.assertIn("coordenadas_duplicadas", set(validation.inconsistencies["tipo"]))


if __name__ == "__main__":
    unittest.main()
