"""Testes da validação de integridade da normalização de Dotação Anual."""

from __future__ import annotations

import unittest

import pandas as pd

from src.tesouro_dotacao_anual import transform_dotacao_anual_sheet
from src.tesouro_dotacao_anual_validation import validate_dotacao_anual_normalization
from tests.test_tesouro_dotacao_anual import load_sheet, workbook_bytes, write_recognized_sheet


class TesouroDotacaoAnualValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        content = workbook_bytes(write_recognized_sheet)
        self.worksheet = load_sheet(content)
        self.normalized_dataframe = transform_dotacao_anual_sheet(
            self.worksheet, "base.xlsx", "Base"
        ).normalized_data

    def validate(self):
        return validate_dotacao_anual_normalization(
            self.worksheet, self.normalized_dataframe, "Base"
        )

    def test_total_sum_is_equal(self) -> None:
        validation = self.validate()

        self.assertTrue(validation.approved)
        self.assertAlmostEqual(validation.raw_sum, validation.normalized_sum)
        self.assertAlmostEqual(validation.difference, 0.0)

    def test_null_zero_and_negative_counts_are_preserved(self) -> None:
        validation = self.validate()

        self.assertEqual(validation.raw_null_count, validation.normalized_null_count)
        self.assertEqual(validation.raw_zero_count, validation.normalized_zero_count)
        self.assertEqual(validation.raw_negative_count, validation.normalized_negative_count)
        self.assertGreaterEqual(validation.normalized_null_count, 1)
        self.assertGreaterEqual(validation.normalized_zero_count, 1)
        self.assertGreaterEqual(validation.normalized_negative_count, 1)

    def test_sum_is_equal_by_item_and_by_ano(self) -> None:
        validation = self.validate()

        self.assertTrue(validation.item_comparison["consistente"].all())
        self.assertTrue(validation.ano_comparison["consistente"].all())
        self.assertTrue(validation.ano_item_comparison["consistente"].all())

    def test_normalized_row_count_matches_monetary_cells(self) -> None:
        validation = self.validate()

        self.assertEqual(
            validation.monetary_cell_count,
            validation.raw_data_row_count * validation.monetary_column_count,
        )
        self.assertEqual(validation.normalized_row_count, validation.monetary_cell_count)

    def test_detects_a_value_divergence_at_a_coordinate(self) -> None:
        tampered = self.normalized_dataframe.copy(deep=True)
        target = (tampered["linha_origem"] == 4) & (tampered["coluna_origem"] == "L")
        tampered.loc[target, "valor_movimento_liquido"] = 999999.0

        validation = validate_dotacao_anual_normalization(self.worksheet, tampered, "Base")

        self.assertFalse(validation.approved)
        self.assertIn(
            "valor_por_coordenada",
            validation.inconsistencies["tipo"].tolist(),
        )

    def test_does_not_mutate_worksheet_or_normalized_dataframe(self) -> None:
        original_normalized = self.normalized_dataframe.copy(deep=True)

        self.validate()

        self.assertEqual(self.worksheet["L4"].value, 1000)
        pd.testing.assert_frame_equal(self.normalized_dataframe, original_normalized)


if __name__ == "__main__":
    unittest.main()
