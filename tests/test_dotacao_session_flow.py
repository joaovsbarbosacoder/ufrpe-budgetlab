"""Testes do compartilhamento em sessão da base validada de Dotação Anual."""

import unittest
import ast
import importlib
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.dotacao_anual_analysis import DOTACAO_ANUAL_ANALYSIS_SESSION_KEY
from tests.test_tesouro_dotacao_anual import (
    merge_cells,
    workbook_bytes,
    write_recognized_sheet,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
METRIC = "Movim. Líquido - R$ (Item Informação)"


def write_recognized_sheet_2025(ws) -> None:
    """Variante da base válida, com ano e valores diferentes do fixture padrão."""

    ws["A1"] = "Iduso"
    merge_cells(ws, 1, 1, 3, 2)
    ws["C1"] = "Resultado Primário Lei"
    merge_cells(ws, 1, 3, 3, 4)
    ws["E1"] = "Ação Governo"
    merge_cells(ws, 1, 5, 3, 6)
    ws["G1"] = "PTRES"
    merge_cells(ws, 1, 7, 3, 7)
    ws["H1"] = "Fonte Recursos Detalhada"
    merge_cells(ws, 1, 8, 3, 9)
    ws["J1"] = "Item Informação"
    merge_cells(ws, 1, 10, 1, 11)
    ws["J2"] = "Ano Lançamento"
    merge_cells(ws, 2, 10, 2, 11)
    ws["J3"] = "Plano Orçamentário"
    merge_cells(ws, 3, 10, 3, 11)

    ws["L1"] = "DOTACAO ATUALIZADA"
    ws["L2"] = 2025
    ws["L3"] = METRIC

    ws["A4"] = 1
    ws["B4"] = "Iduso A"
    ws["C4"] = 10
    ws["D4"] = "RP A"
    ws["E4"] = "ACAO9"
    ws["F4"] = "Acao desc Z"
    ws["G4"] = "PTRES9"
    ws["H4"] = "FONTE9"
    ws["I4"] = "Fonte Z"
    ws["J4"] = "PO9"
    ws["K4"] = "PO Z"
    ws["L4"] = 5000


def write_invalid_sheet(ws) -> None:
    """Estrutura reconhecida, mas com valor monetário não numérico."""

    write_recognized_sheet(ws)
    ws["L4"] = "não é número"


class DotacaoSessionFlowTests(unittest.TestCase):
    """Garante que a navegação não perde uma base validada na mesma sessão."""

    def _open_import_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        app.switch_page("app_pages/importacao_bases.py")
        app.run(timeout=10)
        self.assertEqual(len(app.exception), 0)
        return app

    def _upload(self, app: AppTest, filename: str, content: bytes) -> None:
        app.file_uploader[0].set_value(
            (
                filename,
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        )
        app.run(timeout=15)
        self.assertEqual(len(app.exception), 0)

    def _open_analysis_page(self, app: AppTest) -> AppTest:
        app.switch_page("app_pages/dotacao_orcamentaria.py")
        app.run(timeout=15)
        self.assertEqual(len(app.exception), 0)
        return app

    def test_analysis_page_analytic_import_contract_is_available(self) -> None:
        page_path = PROJECT_ROOT / "app_pages" / "dotacao_orcamentaria.py"
        page_tree = ast.parse(page_path.read_text(encoding="utf-8"))
        imported_names = {
            alias.name
            for node in ast.walk(page_tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "src.dotacao_anual_analysis"
            for alias in node.names
        }
        analysis_module = importlib.import_module("src.dotacao_anual_analysis")

        self.assertTrue(imported_names)
        self.assertFalse(
            [name for name in imported_names if not hasattr(analysis_module, name)]
        )

        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        self._open_analysis_page(app)

    def test_transfers_validated_base_to_session_and_analysis_page(self) -> None:
        app = self._open_import_page()
        self._upload(app, "dotacao_anual.xlsx", workbook_bytes(write_recognized_sheet))

        dataset = app.session_state[DOTACAO_ANUAL_ANALYSIS_SESSION_KEY]
        self.assertEqual(dataset.filename, "dotacao_anual.xlsx")
        self.assertEqual(dataset.sheets, ["Base"])
        self.assertEqual(dataset.row_count, 6)
        self.assertEqual(dataset.validation_status, "Aprovada")

        analysis = self._open_analysis_page(app)
        self.assertEqual(analysis.title[0].value, "Dotação Orçamentária")
        self.assertTrue(any("Anos: 2024" in item.value for item in analysis.caption))
        self.assertTrue(analysis.metric)

    def test_analysis_page_explains_when_no_validated_base_is_loaded(self) -> None:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()

        analysis = self._open_analysis_page(app)

        self.assertTrue(
            any(
                "Nenhuma base de Dotação Anual validada está carregada." in item.value
                for item in analysis.info
            )
        )

    def test_does_not_make_invalid_validation_available_to_analysis(self) -> None:
        app = self._open_import_page()
        self._upload(app, "dotacao_anual_invalida.xlsx", workbook_bytes(write_invalid_sheet))

        self.assertNotIn(DOTACAO_ANUAL_ANALYSIS_SESSION_KEY, app.session_state)
        analysis = self._open_analysis_page(app)
        self.assertTrue(
            any(
                "Nenhuma base de Dotação Anual validada está carregada." in item.value
                for item in analysis.info
            )
        )

    def test_replaces_session_dataset_when_a_new_validated_base_is_uploaded(self) -> None:
        app = self._open_import_page()
        self._upload(app, "dotacao_anual_2024.xlsx", workbook_bytes(write_recognized_sheet))
        first_dataset = app.session_state[DOTACAO_ANUAL_ANALYSIS_SESSION_KEY]

        self._upload(
            app,
            "dotacao_anual_2025.xlsx",
            workbook_bytes(write_recognized_sheet_2025),
        )
        replacement_dataset = app.session_state[DOTACAO_ANUAL_ANALYSIS_SESSION_KEY]

        self.assertEqual(first_dataset.filename, "dotacao_anual_2024.xlsx")
        self.assertEqual(replacement_dataset.filename, "dotacao_anual_2025.xlsx")
        self.assertNotEqual(
            first_dataset.source_sha256,
            replacement_dataset.source_sha256,
        )
        self.assertEqual(replacement_dataset.row_count, 1)

        analysis = self._open_analysis_page(app)
        self.assertTrue(analysis.metric)


if __name__ == "__main__":
    unittest.main()
