"""Testes das análises em memória de Dotação Anual (BI CPOC - Por Ano)."""

from __future__ import annotations

import unittest

import pandas as pd

from src.dotacao_anual_analysis import (
    KNOWN_ITEM_INDICATORS,
    apply_dotacao_anual_filters,
    build_dotacao_anual_subdivision_analysis,
    build_dotacao_anual_year_analysis,
    build_item_indicators,
    prepare_validated_dotacao_anual_dataset,
)
from src.tesouro_dotacao_anual import transform_dotacao_anual_sheet
from src.tesouro_dotacao_anual_workbook import process_dotacao_anual_workbook
from tests.test_tesouro_dotacao_anual import load_sheet, workbook_bytes, write_recognized_sheet


class DotacaoAnualAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        content = workbook_bytes(write_recognized_sheet)
        worksheet = load_sheet(content)
        self.normalized = transform_dotacao_anual_sheet(
            worksheet, "dotacao_anual.xlsx", "Base"
        ).normalized_data

    def test_filters_by_ano_and_dimension(self) -> None:
        filtered = apply_dotacao_anual_filters(
            self.normalized, {"ano": [2024], "acao_governo": ["ACAO1"]}
        )

        self.assertTrue((filtered["ano_lancamento"] == 2024).all())
        self.assertTrue((filtered["acao_codigo"] == "ACAO1").all())
        self.assertEqual(len(filtered), 6)

    def test_filter_excludes_non_matching_dimension(self) -> None:
        filtered = apply_dotacao_anual_filters(
            self.normalized, {"iduso": ["1"]}
        )

        self.assertTrue((filtered["iduso_codigo"] == "1").all())
        self.assertEqual(len(filtered), 3)

    def test_build_item_indicators_sums_isolated_items(self) -> None:
        indicators = build_item_indicators(self.normalized).set_index(
            "item_informacao_codigo"
        )

        self.assertEqual(
            float(indicators.loc["dotacao_inicial", "valor_movimento_liquido"]), 1000.0
        )
        self.assertEqual(
            float(indicators.loc["dotacao_atualizada", "valor_movimento_liquido"]), 1200.0
        )
        self.assertTrue(
            pd.isna(indicators.loc["dotacao_suplementar", "valor_movimento_liquido"])
        )
        self.assertTrue(
            pd.isna(
                indicators.loc["dotacao_cancelada_remanejada", "valor_movimento_liquido"]
            )
        )
        self.assertEqual(set(KNOWN_ITEM_INDICATORS), set(indicators.index))

    def test_build_year_analysis_aggregates_isolated_items_per_ano(self) -> None:
        year_analysis = build_dotacao_anual_year_analysis(self.normalized)

        self.assertEqual(list(year_analysis["ano_lancamento"]), [2024])
        row = year_analysis.iloc[0]
        self.assertEqual(float(row["dotacao_inicial"]), 1000.0)
        self.assertEqual(float(row["dotacao_atualizada"]), 1200.0)
        self.assertTrue(pd.isna(row["dotacao_suplementar"]))

    def test_build_subdivision_analysis_splits_by_full_dimension_combination(self) -> None:
        subdivisions = build_dotacao_anual_subdivision_analysis(self.normalized)

        self.assertEqual(len(subdivisions), 2)
        self.assertTrue((subdivisions["acao_codigo"] == "ACAO1").all())
        self.assertEqual(set(subdivisions["ptres_codigo"]), {"PTRES1", "PTRES2"})

        row_a = subdivisions[subdivisions["ptres_codigo"] == "PTRES1"].iloc[0]
        self.assertEqual(float(row_a["dotacao_inicial"]), 1000.0)
        self.assertEqual(float(row_a["dotacao_atualizada"]), 1200.0)

        row_b = subdivisions[subdivisions["ptres_codigo"] == "PTRES2"].iloc[0]
        self.assertTrue(pd.isna(row_b["dotacao_inicial"]))
        self.assertEqual(float(row_b["dotacao_atualizada"]), 0.0)

        indicators = build_item_indicators(self.normalized).set_index(
            "item_informacao_codigo"
        )
        self.assertAlmostEqual(
            float(subdivisions["dotacao_atualizada"].sum(min_count=1)),
            float(indicators.loc["dotacao_atualizada", "valor_movimento_liquido"]),
        )

    def test_does_not_mutate_input_dataframe(self) -> None:
        original = self.normalized.copy(deep=True)

        apply_dotacao_anual_filters(self.normalized, {"ano": [2024]})
        build_item_indicators(self.normalized)
        build_dotacao_anual_year_analysis(self.normalized)
        build_dotacao_anual_subdivision_analysis(self.normalized)

        pd.testing.assert_frame_equal(self.normalized, original)

    def test_prepares_only_a_fully_validated_workbook(self) -> None:
        content = workbook_bytes(write_recognized_sheet)
        workbook_result = process_dotacao_anual_workbook(content, "dotacao_anual.xlsx")

        dataset = prepare_validated_dotacao_anual_dataset(workbook_result, content)

        self.assertEqual(dataset.filename, "dotacao_anual.xlsx")
        self.assertEqual(dataset.sheets, ["Base"])
        self.assertEqual(dataset.row_count, 6)
        self.assertEqual(len(dataset.source_sha256), 64)
        self.assertEqual(dataset.validation_status, "Aprovada")

    def test_rejects_a_workbook_without_approved_integrity(self) -> None:
        def corrupted(ws) -> None:
            write_recognized_sheet(ws)
            ws["L4"] = "não é número"

        content = workbook_bytes(corrupted)
        workbook_result = process_dotacao_anual_workbook(content, "dotacao_anual.xlsx")

        self.assertFalse(workbook_result.integrity_approved)
        with self.assertRaises(ValueError):
            prepare_validated_dotacao_anual_dataset(workbook_result, content)


if __name__ == "__main__":
    unittest.main()
