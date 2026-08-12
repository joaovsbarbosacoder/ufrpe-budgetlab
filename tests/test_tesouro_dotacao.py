"""Testes do tratamento específico de Dotação do Tesouro Gerencial."""

from io import BytesIO
import unittest

import pandas as pd

from src.excel_importer import list_excel_sheets, read_excel_sheet
from src.tesouro_dotacao import (
    read_dotacao_sheet,
    recognize_dotacao_base,
    transform_dotacao_sheet,
)


METRIC = "Movim. Líquido - R$ (Item Informação)"


def make_dotacao_raw(
    periods: list[object] | None = None,
    items: list[str] | None = None,
    l1_label: str = "Mês Lançamento",
) -> pd.DataFrame:
    periods = periods or [
        "JAN/2024",
        None,
        "MAR/2024",
        "ABR/2024",
        "MAI/2024",
    ]
    items = items or [
        "Dotação Inicial",
        "Dotação Atualizada",
        "Créditos Adicionais - Excesso de Arrecadação",
        "Créditos Adicionais - Superávit Financeiro",
        "Item Experimental",
    ]
    if len(periods) != len(items):
        raise ValueError("Períodos e itens devem ter o mesmo tamanho.")

    first_header = [
        "IDUSO",
        None,
        "Resultado Primário Lei",
        None,
        "Ação Governo",
        None,
        "PTRES",
        "Plano Orçamentário",
        None,
        "Grupo Despesa",
        None,
        l1_label,
        None,
        *periods,
    ]
    second_header = [None] * 11 + ["Item Informação", None, *items]
    third_header = [None] * 11 + ["Fonte Recursos Detalhada", None]
    third_header.extend([METRIC] * len(items))

    first_values = ([0.0, None, -50.0, 25.0, 10.0] + [0.0] * len(items))[
        : len(items)
    ]
    second_values = ([None, 5.0, 0.0, -1.0, None] + [None] * len(items))[
        : len(items)
    ]
    first_data_row = [
        "0000",
        "IDUSO sem contrapartida",
        "-9.0",
        "Resultado primário",
        "09HB",
        "Ação de governo",
        "R001",
        "0000",
        "Plano orçamentário",
        "3.0",
        "Outras despesas correntes",
        1234567890.0,
        "Fonte detalhada",
        *first_values,
    ]
    second_data_row = [
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        *second_values,
    ]

    return pd.DataFrame(
        [first_header, second_header, third_header, first_data_row, second_data_row]
    )


def workbook_bytes(raw_dataframe: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        raw_dataframe.to_excel(
            writer,
            sheet_name="2024",
            header=False,
            index=False,
        )
    return buffer.getvalue()


class TesouroDotacaoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_dataframe = make_dotacao_raw()

    def test_recognizes_positive_and_negative_structures(self) -> None:
        positive = recognize_dotacao_base(self.raw_dataframe)
        negative_dataframe = self.raw_dataframe.copy(deep=True)
        negative_dataframe.iat[0, 0] = "Outra dimensão"
        negative = recognize_dotacao_base(negative_dataframe)

        self.assertTrue(positive.matched)
        self.assertFalse(negative.matched)
        self.assertTrue(any("A1" in failure for failure in negative.validation_failures))

    def test_recognizes_real_l1_month_launch_label(self) -> None:
        recognition = recognize_dotacao_base(self.raw_dataframe)

        self.assertTrue(recognition.matched)
        self.assertEqual(recognition.validation_failures, [])

    def test_recognizes_documented_legacy_l1_alias_only(self) -> None:
        legacy = recognize_dotacao_base(make_dotacao_raw(l1_label="Período"))
        unexpected = recognize_dotacao_base(make_dotacao_raw(l1_label="Mês"))

        self.assertTrue(legacy.matched)
        self.assertFalse(unexpected.matched)
        self.assertTrue(
            any("L1" in failure for failure in unexpected.validation_failures)
        )

    def test_preserves_description_columns_previously_named_unnamed(self) -> None:
        file_content = workbook_bytes(self.raw_dataframe)
        generic_dataframe = read_excel_sheet(file_content, "dotacao.xlsx", "2024")
        raw_dataframe = read_dotacao_sheet(file_content, "dotacao.xlsx", "2024")
        result = transform_dotacao_sheet(raw_dataframe, "dotacao.xlsx", "2024")
        first = result.normalized_data.iloc[0]

        self.assertIn("Unnamed: 1", generic_dataframe.columns)
        self.assertEqual(first["iduso_descricao"], "IDUSO sem contrapartida")
        self.assertEqual(
            first["resultado_primario_descricao"],
            "Resultado primário",
        )
        self.assertEqual(first["acao_descricao"], "Ação de governo")
        self.assertEqual(
            first["plano_orcamentario_descricao"],
            "Plano orçamentário",
        )
        self.assertEqual(
            first["grupo_despesa_descricao"],
            "Outras despesas correntes",
        )
        self.assertEqual(
            first["fonte_recursos_detalhada_descricao"],
            "Fonte detalhada",
        )

    def test_fills_a_to_k_and_does_not_fill_l_or_m(self) -> None:
        result = transform_dotacao_sheet(
            self.raw_dataframe,
            "dotacao.xlsx",
            "2024",
        )
        first = result.normalized_data.query(
            "linha_origem == 4 and coluna_origem == 'N'"
        ).iloc[0]
        second = result.normalized_data.query(
            "linha_origem == 5 and coluna_origem == 'N'"
        ).iloc[0]

        hierarchy_fields = [
            "iduso_codigo",
            "iduso_descricao",
            "resultado_primario_codigo",
            "resultado_primario_descricao",
            "acao_codigo",
            "acao_descricao",
            "ptres_codigo",
            "plano_orcamentario_codigo",
            "plano_orcamentario_descricao",
            "grupo_despesa_codigo",
            "grupo_despesa_descricao",
        ]
        for field in hierarchy_fields:
            self.assertEqual(second[field], first[field], field)

        self.assertEqual(first["resultado_primario_codigo"], "-9")
        self.assertEqual(first["acao_codigo"], "09HB")
        self.assertEqual(first["ptres_codigo"], "R001")
        self.assertEqual(first["plano_orcamentario_codigo"], "0000")
        self.assertEqual(first["grupo_despesa_codigo"], "3")
        self.assertEqual(
            first["fonte_recursos_detalhada_codigo"],
            "1234567890",
        )
        self.assertTrue(pd.isna(second["fonte_recursos_detalhada_codigo"]))
        self.assertTrue(pd.isna(second["fonte_recursos_detalhada_descricao"]))

    def test_preserves_null_zero_and_negative_values(self) -> None:
        result = transform_dotacao_sheet(
            self.raw_dataframe,
            "dotacao.xlsx",
            "2024",
        )
        normalized = result.normalized_data.set_index(
            ["linha_origem", "coluna_origem"]
        )

        self.assertEqual(normalized.loc[(4, "N"), "valor_movimento_liquido"], 0.0)
        self.assertTrue(
            pd.isna(normalized.loc[(4, "O"), "valor_movimento_liquido"])
        )
        self.assertEqual(
            normalized.loc[(4, "P"), "valor_movimento_liquido"],
            -50.0,
        )
        self.assertEqual(str(result.normalized_data["valor_movimento_liquido"].dtype), "Float64")

    def test_recognizes_month_year_labels_and_horizontal_period_fill(self) -> None:
        result = transform_dotacao_sheet(
            self.raw_dataframe,
            "dotacao.xlsx",
            "2024",
        )
        normalized = result.normalized_data
        january_columns = normalized[normalized["coluna_origem"].isin(["N", "O"])]
        march = normalized[normalized["coluna_origem"] == "P"].iloc[0]
        april = normalized[normalized["coluna_origem"] == "Q"].iloc[0]

        self.assertEqual(set(january_columns["periodo_ordem"]), {1})
        self.assertEqual(set(january_columns["periodo_rotulo_origem"]), {"JAN/2024"})
        self.assertEqual(march["periodo_ordem"], 3)
        self.assertEqual(march["periodo_tipo"], "mes_calendario")
        self.assertEqual(march["mes_numero"], 3)
        self.assertEqual(april["periodo_ordem"], 4)

    def test_does_not_create_missing_periods_in_partial_year(self) -> None:
        partial_raw = make_dotacao_raw(
            periods=["JAN/2025", "013/2025"],
            items=["Dotação Inicial", "Dotação Atualizada"],
        )
        result = transform_dotacao_sheet(partial_raw, "parcial.xlsx", "2025")

        self.assertEqual(result.periods_found, ["JAN/2025", "013/2025"])
        self.assertEqual(result.periods_in_scope, ["JAN/2025"])
        self.assertEqual(result.periods_ignored, ["013/2025"])
        self.assertEqual(result.ignored_column_count, 1)
        self.assertEqual(result.ignored_monetary_cell_count, 2)
        self.assertEqual(result.ignored_value_sum, 5.0)
        self.assertEqual(set(result.normalized_data["periodo_ordem"]), {1})
        self.assertEqual(result.normalized_row_count, 2)

    def test_recognizes_partial_2026_without_creating_missing_months(self) -> None:
        month_labels = [
            f"{month}/2026"
            for month in ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO"]
        ]
        raw = make_dotacao_raw(
            periods=month_labels,
            items=["Dotação Inicial"] * len(month_labels),
        )
        result = transform_dotacao_sheet(raw, "dotacao.xlsx", "2026")

        self.assertEqual(result.periods_in_scope, month_labels)
        self.assertEqual(set(result.normalized_data["periodo_ordem"]), set(range(1, 9)))
        self.assertEqual(result.normalized_row_count, 16)

    def test_recognizes_all_months_from_january_to_december_2019(self) -> None:
        month_labels = [
            f"{month}/2019"
            for month in [
                "JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
                "JUL", "AGO", "SET", "OUT", "NOV", "DEZ",
            ]
        ]
        raw = make_dotacao_raw(
            periods=month_labels,
            items=["Dotação Inicial"] * len(month_labels),
        )
        result = transform_dotacao_sheet(raw, "dotacao.xlsx", "2019")

        self.assertEqual(result.periods_found, month_labels)
        self.assertEqual(result.periods_in_scope, month_labels)
        self.assertEqual(result.periods_ignored, [])
        self.assertEqual(
            set(result.normalized_data["periodo_ordem"]),
            set(range(1, 13)),
        )
        self.assertTrue(
            result.normalized_data["periodo_tipo"].eq("mes_calendario").all()
        )

    def test_ignores_013_and_014_without_changing_the_raw_dataframe(self) -> None:
        raw = make_dotacao_raw(
            periods=["JAN/2024", "013/2024", "014/2024"],
            items=["Dotação Inicial", "Dotação Atualizada", "Item Experimental"],
        )
        original = raw.copy(deep=True)
        result = transform_dotacao_sheet(raw, "dotacao.xlsx", "2024")

        self.assertEqual(result.periods_ignored, ["013/2024", "014/2024"])
        self.assertEqual(result.ignored_column_count, 2)
        self.assertEqual(result.ignored_monetary_cell_count, 4)
        self.assertEqual(result.ignored_value_sum, -45.0)
        self.assertEqual(set(result.normalized_data["periodo_rotulo_origem"]), {"JAN/2024"})
        self.assertNotIn("013/2024", set(result.normalized_data["periodo_rotulo_origem"]))
        self.assertNotIn("014/2024", set(result.normalized_data["periodo_rotulo_origem"]))
        pd.testing.assert_frame_equal(raw, original)

    def test_normalizes_excess_revenue_and_financial_surplus_items(self) -> None:
        result = transform_dotacao_sheet(
            self.raw_dataframe,
            "dotacao.xlsx",
            "2024",
        )
        item_codes = set(result.normalized_data["item_informacao_codigo"])

        self.assertIn(
            "creditos_adicionais_excesso_arrecadacao",
            item_codes,
        )
        self.assertIn(
            "creditos_adicionais_superavit_financeiro",
            item_codes,
        )

    def test_normalizes_all_known_items(self) -> None:
        known_items = [
            "Projeto Inicial da LOA - Fixação da Despesa",
            "Dotação Inicial",
            "Dotação Suplementar",
            "Dotação Atualizada",
            "Dotação Cancelada/Remanejada",
            "Créditos Adicionais - Excesso de Arrecadação",
            "Créditos Adicionais - Superávit Financeiro",
        ]
        raw_dataframe = make_dotacao_raw(
            periods=["JAN/2024", None, None, None, None, None, None],
            items=known_items,
        )
        result = transform_dotacao_sheet(
            raw_dataframe,
            "dotacao.xlsx",
            "2024",
        )

        self.assertEqual(
            set(result.normalized_data["item_informacao_codigo"]),
            {
                "projeto_inicial_loa_fixacao_despesa",
                "dotacao_inicial",
                "dotacao_suplementar",
                "dotacao_atualizada",
                "dotacao_cancelada_remanejada",
                "creditos_adicionais_excesso_arrecadacao",
                "creditos_adicionais_superavit_financeiro",
            },
        )
        self.assertEqual(result.warnings, [])

    def test_warns_about_unknown_items_without_discarding_them(self) -> None:
        result = transform_dotacao_sheet(
            self.raw_dataframe,
            "dotacao.xlsx",
            "2024",
        )
        experimental = result.normalized_data[
            result.normalized_data["item_informacao_origem"] == "Item Experimental"
        ]

        self.assertFalse(experimental.empty)
        self.assertEqual(
            set(experimental["item_informacao_codigo"]),
            {"item_nao_mapeado_item_experimental"},
        )
        self.assertTrue(any("Item Experimental" in warning for warning in result.warnings))

    def test_has_no_duplicate_source_coordinates_and_does_not_mutate_raw(self) -> None:
        original_dataframe = self.raw_dataframe.copy(deep=True)
        result = transform_dotacao_sheet(
            self.raw_dataframe,
            "dotacao.xlsx",
            "2024",
        )

        duplicates = result.normalized_data.duplicated(
            subset=["arquivo_origem", "aba_origem", "linha_origem", "coluna_origem"]
        )
        self.assertFalse(duplicates.any())
        pd.testing.assert_frame_equal(self.raw_dataframe, original_dataframe)

    def test_keeps_generic_importer_working(self) -> None:
        file_content = workbook_bytes(self.raw_dataframe)

        self.assertEqual(list_excel_sheets(file_content, "dotacao.xlsx"), ["2024"])
        generic_dataframe = read_excel_sheet(
            file_content,
            "dotacao.xlsx",
            "2024",
        )
        raw_dataframe = read_dotacao_sheet(
            file_content,
            "dotacao.xlsx",
            "2024",
        )

        self.assertFalse(generic_dataframe.empty)
        self.assertEqual(raw_dataframe.iat[0, 0], "IDUSO")
        self.assertEqual(raw_dataframe.shape, self.raw_dataframe.shape)


if __name__ == "__main__":
    unittest.main()
