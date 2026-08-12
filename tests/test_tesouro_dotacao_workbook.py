"""Testes do processamento multiaba de Dotação do Tesouro Gerencial."""

from io import BytesIO
import unittest

import pandas as pd

from src.tesouro_dotacao_workbook import (
    build_sheet_summary,
    process_dotacao_workbook,
)
from tests.test_tesouro_dotacao import make_dotacao_raw


def multi_sheet_workbook_bytes() -> bytes:
    raw_2023 = make_dotacao_raw()
    raw_2023.iat[3, 13] = 100.0
    raw_2024 = make_dotacao_raw(
        periods=["JAN/2024", "013/2024"],
        items=["Dotação Inicial", "Dotação Atualizada"],
    )
    notes = pd.DataFrame({"Observação": ["Aba auxiliar"]})

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        raw_2023.to_excel(writer, sheet_name="2023", header=False, index=False)
        notes.to_excel(writer, sheet_name="Notas", index=False)
        raw_2024.to_excel(writer, sheet_name="2024", header=False, index=False)
    return buffer.getvalue()


def real_structure_workbook_bytes() -> bytes:
    """Create the representative real structure for all annual sheets."""

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for year in range(2019, 2027):
            make_dotacao_raw().to_excel(
                writer,
                sheet_name=str(year),
                header=False,
                index=False,
            )
    return buffer.getvalue()


class TesouroDotacaoWorkbookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.file_content = multi_sheet_workbook_bytes()
        self.result = process_dotacao_workbook(
            self.file_content,
            "dotacao_multiaba.xlsx",
        )

    def test_processes_every_recognized_sheet_and_reports_unrecognized(self) -> None:
        self.assertEqual(self.result.recognized_sheets, ["2023", "2024"])
        self.assertEqual(self.result.unrecognized_sheets, ["Notas"])
        self.assertEqual(self.result.processing_errors, [])
        self.assertTrue(self.result.integrity_approved)

        ignored = next(
            item for item in self.result.sheet_results if item.sheet_name == "Notas"
        )
        self.assertTrue(ignored.structural_failures)

    def test_recognizes_real_structure_in_all_annual_sheets_from_2019_to_2026(
        self,
    ) -> None:
        result = process_dotacao_workbook(
            real_structure_workbook_bytes(),
            "dotacao_real.xlsx",
        )

        self.assertEqual(
            result.recognized_sheets,
            [str(year) for year in range(2019, 2027)],
        )
        self.assertEqual(result.unrecognized_sheets, [])
        self.assertTrue(result.integrity_approved)

    def test_consolidates_with_complete_traceability_and_no_duplicates(self) -> None:
        consolidated = self.result.consolidated_data

        self.assertEqual(len(consolidated), 12)
        self.assertEqual(set(consolidated["aba_origem"]), {"2023", "2024"})
        self.assertEqual(set(consolidated["arquivo_origem"]), {"dotacao_multiaba.xlsx"})
        self.assertFalse(
            consolidated.duplicated(
                subset=[
                    "arquivo_origem",
                    "aba_origem",
                    "linha_origem",
                    "coluna_origem",
                ]
            ).any()
        )
        self.assertEqual(self.result.consolidated_duplicate_count, 0)

    def test_preserves_counts_and_sums_in_consolidation(self) -> None:
        self.assertEqual(self.result.monetary_cell_count, 12)
        self.assertEqual(self.result.normalized_row_count, 12)
        self.assertEqual(self.result.null_count, 4)
        self.assertEqual(self.result.zero_count, 2)
        self.assertEqual(self.result.negative_count, 2)
        self.assertEqual(self.result.ignored_column_count, 1)
        self.assertEqual(self.result.ignored_monetary_cell_count, 2)
        self.assertEqual(self.result.ignored_value_sum, 5.0)
        self.assertAlmostEqual(self.result.raw_sum, self.result.normalized_sum)
        self.assertAlmostEqual(self.result.difference, 0.0)
        self.assertTrue(self.result.consolidated_inconsistencies.empty)

    def test_exposes_status_and_validation_messages_by_sheet(self) -> None:
        summary = build_sheet_summary(self.result).set_index("Aba")

        self.assertEqual(summary.loc["2023", "Status de integridade"], "Aprovada")
        self.assertEqual(summary.loc["2024", "Status de integridade"], "Aprovada")
        self.assertEqual(summary.loc["Notas", "Status de integridade"], "Não reconhecida")

        raw_with_invalid_metric = make_dotacao_raw()
        raw_with_invalid_metric.iat[2, 13] = "Métrica não reconhecida"
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            raw_with_invalid_metric.to_excel(
                writer, sheet_name="2024", header=False, index=False
            )
        invalid_result = process_dotacao_workbook(
            buffer.getvalue(),
            "dotacao.xlsx",
        )
        sheet = invalid_result.sheet_results[0]

        self.assertTrue(sheet.recognized)
        self.assertTrue(sheet.validation_failures)
        self.assertEqual(sheet.status_label, "Com inconsistências")
        self.assertFalse(invalid_result.integrity_approved)

    def test_does_not_change_uploaded_bytes(self) -> None:
        original_content = bytes(self.file_content)

        process_dotacao_workbook(self.file_content, "dotacao_multiaba.xlsx")

        self.assertEqual(self.file_content, original_content)

    def test_returns_empty_consolidation_when_no_sheet_is_recognized(self) -> None:
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            pd.DataFrame({"A": [1]}).to_excel(writer, sheet_name="Resumo", index=False)

        result = process_dotacao_workbook(buffer.getvalue(), "resumo.xlsx")

        self.assertEqual(result.recognized_sheets, [])
        self.assertEqual(result.unrecognized_sheets, ["Resumo"])
        self.assertTrue(result.consolidated_data.empty)
        self.assertFalse(result.integrity_approved)


if __name__ == "__main__":
    unittest.main()
