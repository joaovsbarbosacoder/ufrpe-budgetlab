"""Testes da orquestração em memória de Execução da Despesa."""

from io import BytesIO
import unittest

import pandas as pd

from src.tesouro_execucao_workbook import process_execucao_workbook
from tests.test_tesouro_execucao import make_execucao_raw


def workbook_bytes() -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        make_execucao_raw().to_excel(writer, sheet_name="Execução", header=False, index=False)
        pd.DataFrame({"Observação": ["Aba auxiliar"]}).to_excel(writer, sheet_name="Notas", index=False)
    return buffer.getvalue()


class TesouroExecucaoWorkbookTests(unittest.TestCase):
    def test_processes_recognized_sheet_and_preserves_uploaded_bytes(self) -> None:
        content = workbook_bytes()
        original = bytes(content)
        result = process_execucao_workbook(content, "execucao.xlsx")
        self.assertEqual(result.recognized_sheets, ["Execução"])
        self.assertTrue(result.integrity_approved)
        self.assertEqual(len(result.consolidated_data), 9)
        self.assertTrue(result.consolidated_inconsistencies.empty)
        self.assertEqual(content, original)


if __name__ == "__main__":
    unittest.main()
