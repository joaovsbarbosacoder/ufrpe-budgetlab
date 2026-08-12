"""Testes da leitura e do diagnóstico estrutural de arquivos Excel."""

from io import BytesIO
import unittest

import pandas as pd

from src.excel_importer import (
    diagnose_dataframe,
    list_excel_sheets,
    read_excel_sheet,
)


class ExcelImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_dataframe = pd.DataFrame(
            {
                "codigo": [1, 2, 3],
                "valor": [10.0, None, 30.0],
                "vazia": [None, None, None],
            }
        )
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            self.source_dataframe.to_excel(writer, sheet_name="Dados", index=False)
            pd.DataFrame({"resumo": ["ok"]}).to_excel(
                writer,
                sheet_name="Resumo",
                index=False,
            )
        self.file_content = buffer.getvalue()

    def test_reads_excel_sheet(self) -> None:
        dataframe = read_excel_sheet(
            self.file_content,
            "base.xlsx",
            "Dados",
        )

        self.assertEqual(dataframe["codigo"].tolist(), [1, 2, 3])

    def test_identifies_sheet_names(self) -> None:
        sheet_names = list_excel_sheets(self.file_content, "base.xlsx")

        self.assertEqual(sheet_names, ["Dados", "Resumo"])

    def test_counts_rows_and_columns(self) -> None:
        dataframe = read_excel_sheet(
            self.file_content,
            "base.xlsx",
            "Dados",
        )

        self.assertEqual(dataframe.shape, (3, 3))

    def test_diagnoses_fully_empty_columns(self) -> None:
        dataframe = read_excel_sheet(
            self.file_content,
            "base.xlsx",
            "Dados",
        )

        diagnostics = diagnose_dataframe(dataframe)

        self.assertEqual(diagnostics.fully_empty_columns, ["vazia"])
        self.assertEqual(diagnostics.empty_cells_by_column["vazia"], 3)
        self.assertEqual(diagnostics.empty_cells_by_column["valor"], 1)

    def test_identifies_unnamed_columns_without_mutating_dataframe(self) -> None:
        dataframe = pd.DataFrame(
            {
                "PTRES": [123456.0, None],
                "Unnamed: 1": [None, "Detalhamento"],
                "Unnamed: 3": [None, None],
            }
        )
        original_dataframe = dataframe.copy(deep=True)

        diagnostics = diagnose_dataframe(dataframe)

        self.assertEqual(
            diagnostics.unnamed_columns,
            ["Unnamed: 1", "Unnamed: 3"],
        )
        pd.testing.assert_frame_equal(dataframe, original_dataframe)


if __name__ == "__main__":
    unittest.main()
