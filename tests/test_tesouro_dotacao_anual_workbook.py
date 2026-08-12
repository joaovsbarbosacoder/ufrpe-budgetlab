"""Testes do processamento multiaba de Dotação Anual (BI CPOC - Por Ano)."""

from __future__ import annotations

from io import BytesIO
import unittest

from openpyxl import Workbook

from src.tesouro_dotacao_anual_workbook import (
    build_sheet_summary,
    process_dotacao_anual_workbook,
)
from tests.test_tesouro_dotacao_anual import write_recognized_sheet


def multi_sheet_workbook_bytes() -> bytes:
    workbook = Workbook()
    recognized_sheet = workbook.active
    recognized_sheet.title = "Base"
    write_recognized_sheet(recognized_sheet)

    unrecognized_sheet = workbook.create_sheet("Notas")
    unrecognized_sheet["A1"] = "Planilha sem relação com Dotação Anual"

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class TesouroDotacaoAnualWorkbookTests(unittest.TestCase):
    def test_processes_recognized_sheet_and_reports_unrecognized(self) -> None:
        content = multi_sheet_workbook_bytes()

        result = process_dotacao_anual_workbook(content, "base.xlsx")

        self.assertEqual(result.recognized_sheets, ["Base"])
        self.assertEqual(result.unrecognized_sheets, ["Notas"])
        self.assertEqual(result.processing_errors, [])
        self.assertTrue(result.integrity_approved)
        self.assertEqual(result.normalized_row_count, 6)
        self.assertAlmostEqual(result.raw_sum, result.normalized_sum)
        self.assertTrue(result.consolidated_inconsistencies.empty)

    def test_does_not_change_uploaded_bytes(self) -> None:
        content = multi_sheet_workbook_bytes()
        original = bytes(content)

        process_dotacao_anual_workbook(content, "base.xlsx")

        self.assertEqual(content, original)

    def test_sheet_summary_reflects_processed_sheets(self) -> None:
        content = multi_sheet_workbook_bytes()
        result = process_dotacao_anual_workbook(content, "base.xlsx")

        summary = build_sheet_summary(result)

        self.assertEqual(set(summary["Aba"]), {"Base", "Notas"})
        base_row = summary[summary["Aba"] == "Base"].iloc[0]
        self.assertEqual(base_row["Status de integridade"], "Aprovada")
        notas_row = summary[summary["Aba"] == "Notas"].iloc[0]
        self.assertEqual(notas_row["Status de integridade"], "Não reconhecida")


if __name__ == "__main__":
    unittest.main()
