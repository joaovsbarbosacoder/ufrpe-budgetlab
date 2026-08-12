"""Testes das análises em memória de Dotação Orçamentária."""

import unittest

import pandas as pd

from src.dotacao_analysis import (
    DETAIL_COLUMNS,
    FILTER_COLUMNS,
    INDICATOR_MEMORY_COLUMNS,
    KNOWN_ITEM_INDICATORS,
    MANAGEMENT_DIMENSION_COLUMNS,
    apply_dotacao_filters,
    build_detail_view,
    build_dotacao_dimension_analysis,
    build_indicator_calculation_memory,
    build_item_indicators,
    build_period_analysis,
    build_unknown_item_summary,
    prepare_validated_dataset,
)
from src.tesouro_dotacao import transform_dotacao_sheet
from src.tesouro_dotacao_workbook import process_dotacao_workbook
from tests.test_tesouro_dotacao import make_dotacao_raw, workbook_bytes


class DotacaoAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        raw = make_dotacao_raw()
        self.normalized = transform_dotacao_sheet(
            raw,
            "dotacao.xlsx",
            "2024",
        ).normalized_data
        second_line = self.normalized["linha_origem"] == 5
        self.normalized.loc[second_line, "iduso_codigo"] = "0001"
        self.normalized.loc[second_line, "iduso_descricao"] = "Outro IDUSO"
        self.normalized.loc[second_line, "resultado_primario_codigo"] = "1"
        self.normalized.loc[second_line, "acao_codigo"] = "20XY"
        self.normalized.loc[second_line, "ptres_codigo"] = "R002"
        self.normalized.loc[second_line, "plano_orcamentario_codigo"] = "0001"
        self.normalized.loc[second_line, "grupo_despesa_codigo"] = "4"
        self.normalized.loc[
            second_line,
            "fonte_recursos_detalhada_codigo",
        ] = "0987654321"

    def test_filters_each_dimension(self) -> None:
        filter_values = {
            "exercicio": 2024,
            "iduso": "0001",
            "resultado_primario": "1",
            "acao_governo": "20XY",
            "ptres": "R002",
            "plano_orcamentario": "0001",
            "grupo_despesa": "4",
            "fonte_recursos_detalhada": "0987654321",
            "periodo": "MAR/2024",
            "item_informacao": "creditos_adicionais_excesso_arrecadacao",
        }

        for filter_name, value in filter_values.items():
            with self.subTest(filter_name=filter_name):
                result = apply_dotacao_filters(
                    self.normalized,
                    {filter_name: [value]},
                )
                column = FILTER_COLUMNS[filter_name]
                self.assertFalse(result.empty)
                self.assertTrue(result[column].eq(value).all())

    def test_applies_combined_filters_without_mutating_input(self) -> None:
        original = self.normalized.copy(deep=True)

        result = apply_dotacao_filters(
            self.normalized,
            {
                "iduso": ["0001"],
                "periodo": ["MAR/2024"],
                "item_informacao": [
                    "creditos_adicionais_excesso_arrecadacao"
                ],
            },
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["linha_origem"], 5)
        self.assertEqual(result.iloc[0]["valor_movimento_liquido"], 0.0)
        pd.testing.assert_frame_equal(self.normalized, original)

    def test_filter_can_select_null_dimension_values(self) -> None:
        with_null = self.normalized.copy(deep=True)
        with_null.loc[with_null.index[0], "fonte_recursos_detalhada_codigo"] = pd.NA

        result = apply_dotacao_filters(
            with_null,
            {"fonte_recursos_detalhada": [None]},
        )

        self.assertEqual(len(result), 1)
        self.assertTrue(result["fonte_recursos_detalhada_codigo"].isna().all())

    def test_aggregates_known_items_independently(self) -> None:
        indicators = build_item_indicators(self.normalized).set_index(
            "item_informacao_codigo"
        )

        self.assertEqual(
            set(indicators.index),
            set(KNOWN_ITEM_INDICATORS),
        )
        self.assertEqual(
            indicators.loc["dotacao_inicial", "valor_movimento_liquido"],
            0.0,
        )
        self.assertEqual(
            indicators.loc["dotacao_atualizada", "valor_movimento_liquido"],
            5.0,
        )
        self.assertEqual(
            indicators.loc[
                "creditos_adicionais_excesso_arrecadacao",
                "valor_movimento_liquido",
            ],
            -50.0,
        )
        self.assertEqual(
            indicators.loc[
                "creditos_adicionais_superavit_financeiro",
                "valor_movimento_liquido",
            ],
            24.0,
        )
        self.assertTrue(
            pd.isna(
                indicators.loc[
                    "dotacao_suplementar",
                    "valor_movimento_liquido",
                ]
            )
        )

    def test_indicator_memory_reconciles_with_exact_filtered_lines(self) -> None:
        filtered = apply_dotacao_filters(
            self.normalized,
            {"iduso": ["0001"], "periodo": ["MAR/2024"]},
        )

        memory = build_indicator_calculation_memory(
            filtered,
            "creditos_adicionais_excesso_arrecadacao",
        )

        self.assertTrue(memory.reconciled)
        self.assertEqual(memory.indicador, "Créditos adicionais — excesso de arrecadação")
        self.assertEqual(memory.total_indicador, 0.0)
        self.assertEqual(memory.total_linhas_exibidas, 0.0)
        self.assertEqual(memory.diferenca, 0.0)
        self.assertEqual(memory.quantidade_linhas, 1)
        self.assertEqual(memory.quantidade_zeros, 1)
        self.assertEqual(list(memory.linhas.columns), INDICATOR_MEMORY_COLUMNS)
        self.assertEqual(memory.linhas.iloc[0]["item_informacao_origem"], "Créditos Adicionais - Excesso de Arrecadação")
        self.assertEqual(memory.linhas.iloc[0]["item_informacao_codigo"], "creditos_adicionais_excesso_arrecadacao")
        self.assertEqual(memory.linhas.iloc[0]["arquivo_origem"], "dotacao.xlsx")
        self.assertEqual(memory.linhas.iloc[0]["aba_origem"], "2024")
        self.assertEqual(memory.linhas.iloc[0]["linha_origem"], 5)
        self.assertEqual(memory.linhas.iloc[0]["coluna_origem"], "P")

    def test_indicator_memory_preserves_nulls_and_rejects_unknown_indicator(self) -> None:
        memory = build_indicator_calculation_memory(
            self.normalized,
            "dotacao_inicial",
        )

        self.assertTrue(memory.reconciled)
        self.assertEqual(memory.quantidade_linhas, 2)
        self.assertEqual(memory.quantidade_nulos, 1)
        self.assertEqual(memory.quantidade_zeros, 1)
        self.assertEqual(memory.total_indicador, 0.0)

        with self.assertRaises(ValueError):
            build_indicator_calculation_memory(
                self.normalized,
                "item_nao_mapeado_item_experimental",
            )

    def test_preserves_negative_zero_and_null_states(self) -> None:
        indicators = build_item_indicators(self.normalized).set_index(
            "item_informacao_codigo"
        )

        excess = indicators.loc["creditos_adicionais_excesso_arrecadacao"]
        initial = indicators.loc["dotacao_inicial"]
        absent = indicators.loc["dotacao_suplementar"]

        self.assertEqual(excess["quantidade_negativos"], 1)
        self.assertEqual(excess["quantidade_zeros"], 1)
        self.assertEqual(initial["quantidade_nulos"], 1)
        self.assertEqual(initial["quantidade_zeros"], 1)
        self.assertEqual(absent["quantidade_registros"], 0)
        self.assertTrue(pd.isna(absent["valor_movimento_liquido"]))

    def test_all_null_item_has_null_aggregate_instead_of_zero(self) -> None:
        all_null = self.normalized.copy(deep=True)
        mask = all_null["item_informacao_codigo"] == "dotacao_atualizada"
        all_null.loc[mask, "valor_movimento_liquido"] = pd.NA

        indicator = build_item_indicators(all_null).set_index(
            "item_informacao_codigo"
        ).loc["dotacao_atualizada"]

        self.assertEqual(indicator["quantidade_registros"], 2)
        self.assertEqual(indicator["quantidade_nulos"], 2)
        self.assertTrue(pd.isna(indicator["valor_movimento_liquido"]))

    def test_period_analysis_contains_only_calendar_months(self) -> None:
        period_analysis = build_period_analysis(self.normalized)

        self.assertEqual(set(period_analysis["periodo_tipo"]), {"mes_calendario"})
        self.assertTrue(period_analysis["periodo_ordem"].between(1, 12).all())
        self.assertFalse(
            period_analysis["periodo_rotulo_origem"].str.startswith("013/").any()
        )
        self.assertFalse(
            period_analysis["periodo_rotulo_origem"].str.startswith("014/").any()
        )

    def test_unknown_items_remain_visible(self) -> None:
        unknown = build_unknown_item_summary(self.normalized)
        period_analysis = build_period_analysis(self.normalized)
        detail = build_detail_view(self.normalized)

        self.assertEqual(len(unknown), 1)
        self.assertEqual(
            unknown.iloc[0]["item_informacao_codigo"],
            "item_nao_mapeado_item_experimental",
        )
        self.assertIn(
            "item_nao_mapeado_item_experimental",
            set(period_analysis["item_informacao_codigo"]),
        )
        self.assertIn(
            "item_nao_mapeado_item_experimental",
            set(detail["item_informacao_codigo"]),
        )

    def test_detail_preserves_traceability(self) -> None:
        detail = build_detail_view(self.normalized)

        self.assertEqual(list(detail.columns), DETAIL_COLUMNS)
        self.assertEqual(len(detail), len(self.normalized))
        self.assertFalse(
            detail.duplicated(
                subset=[
                    "arquivo_origem",
                    "aba_origem",
                    "linha_origem",
                    "coluna_origem",
                ]
            ).any()
        )

    def test_period_groups_do_not_double_count_rows_or_values(self) -> None:
        period_analysis = build_period_analysis(self.normalized)
        known_rows = self.normalized[
            self.normalized["item_informacao_codigo"].isin(KNOWN_ITEM_INDICATORS)
        ]
        indicators = build_item_indicators(self.normalized)

        self.assertEqual(
            int(period_analysis["quantidade_registros"].sum()),
            len(self.normalized),
        )
        self.assertAlmostEqual(
            float(period_analysis["valor_movimento_liquido"].sum(skipna=True)),
            float(self.normalized["valor_movimento_liquido"].sum(skipna=True)),
        )
        self.assertAlmostEqual(
            float(indicators["valor_movimento_liquido"].sum(skipna=True)),
            float(known_rows["valor_movimento_liquido"].sum(skipna=True)),
        )

    def test_management_dimension_aggregations_reconcile_with_filtered_base(self) -> None:
        original = self.normalized.copy(deep=True)
        filtered = apply_dotacao_filters(
            self.normalized,
            {"exercicio": [2024]},
        )
        expected_total = filtered["valor_movimento_liquido"].sum(min_count=1)
        expected_indicators = build_item_indicators(filtered).set_index(
            "item_informacao_codigo"
        )

        for dimension, group_columns in MANAGEMENT_DIMENSION_COLUMNS.items():
            with self.subTest(dimension=dimension):
                analysis = build_dotacao_dimension_analysis(filtered, dimension)

                self.assertEqual(
                    list(analysis.columns),
                    [
                        *group_columns,
                        "total_movimentos",
                        *KNOWN_ITEM_INDICATORS,
                    ],
                )
                self.assertAlmostEqual(
                    float(analysis["total_movimentos"].sum(skipna=True)),
                    float(expected_total),
                )
                for item_code in KNOWN_ITEM_INDICATORS:
                    actual = analysis[item_code].sum(min_count=1)
                    expected = expected_indicators.loc[
                        item_code,
                        "valor_movimento_liquido",
                    ]
                    if pd.isna(expected):
                        self.assertTrue(pd.isna(actual))
                    else:
                        self.assertAlmostEqual(float(actual), float(expected))

        pd.testing.assert_frame_equal(self.normalized, original)

    def test_detailed_dimension_keeps_distinct_combinations_separate(self) -> None:
        analysis = build_dotacao_dimension_analysis(self.normalized, "detalhada")

        self.assertGreaterEqual(len(analysis), 2)
        baseline = analysis[
            (analysis["acao_codigo"] == "09HB") & (analysis["ptres_codigo"] == "R001")
        ]
        alternate = analysis[
            (analysis["acao_codigo"] == "20XY") & (analysis["ptres_codigo"] == "R002")
        ]
        self.assertEqual(len(baseline), 1)
        self.assertEqual(len(alternate), 1)
        self.assertEqual(alternate.iloc[0]["iduso_codigo"], "0001")
        self.assertEqual(alternate.iloc[0]["grupo_despesa_codigo"], "4")
        self.assertEqual(
            alternate.iloc[0]["fonte_recursos_detalhada_codigo"],
            "0987654321",
        )

    def test_prepares_only_a_fully_validated_workbook(self) -> None:
        raw = make_dotacao_raw()
        content = workbook_bytes(raw)
        workbook_result = process_dotacao_workbook(content, "dotacao.xlsx")

        dataset = prepare_validated_dataset(workbook_result, content)

        self.assertEqual(dataset.filename, "dotacao.xlsx")
        self.assertEqual(dataset.sheets, ["2024"])
        self.assertEqual(dataset.row_count, 10)
        self.assertEqual(len(dataset.source_sha256), 64)
        self.assertEqual(dataset.validation_status, "Aprovada")

        invalid_raw = raw.copy(deep=True)
        invalid_raw.iat[2, 13] = "Métrica inválida"
        invalid_content = workbook_bytes(invalid_raw)
        invalid_result = process_dotacao_workbook(
            invalid_content,
            "dotacao.xlsx",
        )
        with self.assertRaises(ValueError):
            prepare_validated_dataset(invalid_result, invalid_content)


if __name__ == "__main__":
    unittest.main()
