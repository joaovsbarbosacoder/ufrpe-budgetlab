"""Testes da validação de integridade da normalização de Dotação."""

import unittest

import pandas as pd

from src.tesouro_dotacao import transform_dotacao_sheet
from src.tesouro_dotacao_validation import validate_dotacao_normalization
from tests.test_tesouro_dotacao import make_dotacao_raw


class TesouroDotacaoValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_dataframe = make_dotacao_raw()
        self.normalized_dataframe = transform_dotacao_sheet(
            self.raw_dataframe,
            "dotacao.xlsx",
            "2024",
        ).normalized_data

    def validate(self):
        return validate_dotacao_normalization(
            self.raw_dataframe,
            self.normalized_dataframe,
            "2024",
        )

    def test_total_sum_is_equal(self) -> None:
        validation = self.validate()

        self.assertTrue(validation.approved)
        self.assertAlmostEqual(validation.raw_sum, validation.normalized_sum)
        self.assertAlmostEqual(validation.difference, 0.0)

    def test_sum_is_equal_by_period(self) -> None:
        validation = self.validate()

        self.assertTrue(validation.period_comparison["consistente"].all())
        self.assertTrue(
            validation.period_comparison["diferenca"].fillna(0).eq(0).all()
        )

    def test_sum_is_equal_by_item(self) -> None:
        validation = self.validate()

        self.assertTrue(validation.item_comparison["consistente"].all())
        self.assertTrue(validation.item_comparison["diferenca"].fillna(0).eq(0).all())

    def test_sum_is_equal_by_period_and_item(self) -> None:
        validation = self.validate()

        self.assertTrue(validation.period_item_comparison["consistente"].all())
        self.assertTrue(
            validation.period_item_comparison["diferenca"].fillna(0).eq(0).all()
        )

    def test_normalized_row_count_matches_monetary_cells(self) -> None:
        validation = self.validate()

        self.assertEqual(validation.raw_data_row_count, 2)
        self.assertEqual(validation.monetary_column_count, 5)
        self.assertEqual(validation.monetary_cell_count, 10)
        self.assertEqual(validation.normalized_row_count, 10)

    def test_null_values_are_preserved(self) -> None:
        validation = self.validate()

        self.assertEqual(validation.raw_null_count, 3)
        self.assertEqual(validation.normalized_null_count, 3)

    def test_zero_values_are_preserved(self) -> None:
        validation = self.validate()

        self.assertEqual(validation.raw_zero_count, 2)
        self.assertEqual(validation.normalized_zero_count, 2)

    def test_negative_values_are_preserved(self) -> None:
        validation = self.validate()

        self.assertEqual(validation.raw_negative_count, 2)
        self.assertEqual(validation.normalized_negative_count, 2)

    def test_detects_an_intentional_divergence(self) -> None:
        divergent_dataframe = self.normalized_dataframe.copy(deep=True)
        divergent_dataframe.loc[0, "valor_movimento_liquido"] = 0.5

        validation = validate_dotacao_normalization(
            self.raw_dataframe,
            divergent_dataframe,
            "2024",
        )
        inconsistency_types = set(validation.inconsistencies["tipo"])

        self.assertFalse(validation.approved)
        self.assertAlmostEqual(validation.difference, 0.5)
        self.assertIn("soma_total", inconsistency_types)
        self.assertIn("valor_por_coordenada", inconsistency_types)
        self.assertIn("soma_por_periodo", inconsistency_types)
        self.assertIn("soma_por_item", inconsistency_types)
        self.assertIn("soma_por_periodo_item", inconsistency_types)

    def test_reconciles_only_months_and_reports_ignored_periods(self) -> None:
        raw = make_dotacao_raw(
            periods=["JAN/2024", "013/2024", "014/2024"],
            items=["Dotação Inicial", "Dotação Atualizada", "Item Experimental"],
        )
        original_raw = raw.copy(deep=True)
        normalized = transform_dotacao_sheet(raw, "dotacao.xlsx", "2024").normalized_data
        validation = validate_dotacao_normalization(raw, normalized, "2024")

        self.assertTrue(validation.approved)
        self.assertEqual(validation.periods_found, ["JAN/2024", "013/2024", "014/2024"])
        self.assertEqual(validation.periods_in_scope, ["JAN/2024"])
        self.assertEqual(validation.periods_ignored, ["013/2024", "014/2024"])
        self.assertEqual(validation.ignored_column_count, 2)
        self.assertEqual(validation.ignored_monetary_cell_count, 4)
        self.assertEqual(validation.ignored_value_sum, -45.0)
        self.assertEqual(validation.monetary_cell_count, 2)
        self.assertEqual(validation.normalized_row_count, 2)
        self.assertEqual(validation.raw_sum, 0.0)
        self.assertEqual(validation.normalized_sum, 0.0)
        self.assertEqual(validation.difference, 0.0)
        pd.testing.assert_frame_equal(raw, original_raw)

    def test_does_not_mutate_raw_or_normalized_dataframes(self) -> None:
        original_raw = self.raw_dataframe.copy(deep=True)
        original_normalized = self.normalized_dataframe.copy(deep=True)

        self.validate()

        pd.testing.assert_frame_equal(self.raw_dataframe, original_raw)
        pd.testing.assert_frame_equal(
            self.normalized_dataframe,
            original_normalized,
        )


if __name__ == "__main__":
    unittest.main()
