"""Regressão da página de importação com colunas sem cabeçalho."""

from io import BytesIO
from pathlib import Path
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def unnamed_columns_workbook_bytes() -> bytes:
    """Cria uma aba genérica com colunas que o Pandas identifica como Unnamed."""

    dataframe = pd.DataFrame(
        {
            "PTRES": ["R001"],
            "Unnamed: 1": ["Descrição"],
            "Unnamed: 3": [None],
        }
    )
    buffer = BytesIO()
    dataframe.to_excel(buffer, sheet_name="Dados", index=False)
    return buffer.getvalue()


class ImportacaoBasesPageTests(unittest.TestCase):
    def test_renders_page_with_unnamed_columns_without_exception(self) -> None:
        app = AppTest.from_file(PROJECT_ROOT / "app.py")
        app.run()
        app.switch_page("app_pages/importacao_bases.py")
        app.run(timeout=10)
        app.file_uploader[0].set_value(
            (
                "colunas_unnamed.xlsx",
                unnamed_columns_workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        )
        app.run(timeout=15)

        self.assertEqual(len(app.exception), 0)
        self.assertIn(
            "Nenhuma informação corresponde à estrutura confirmada de Dotação Anual.",
            [item.value for item in app.info],
        )


if __name__ == "__main__":
    unittest.main()
