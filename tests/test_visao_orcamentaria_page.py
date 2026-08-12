"""Fluxo de sessão da página integrada de Visão Orçamentária."""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.test_tesouro_dotacao import make_dotacao_raw, workbook_bytes as dotacao_workbook_bytes
from tests.test_tesouro_execucao_workbook import workbook_bytes as execucao_workbook_bytes


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class VisaoOrcamentariaPageTests(unittest.TestCase):
    def test_displays_indicators_after_loading_both_validated_bases(self) -> None:
        app = AppTest.from_file(PROJECT_ROOT / "app.py")
        app.run()
        app.switch_page("app_pages/importacao_bases.py")
        app.run(timeout=15)
        app.file_uploader[0].set_value(("dotacao.xlsx", dotacao_workbook_bytes(make_dotacao_raw()), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        app.run(timeout=20)
        app.file_uploader[0].set_value(("execucao.xlsx", execucao_workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        app.run(timeout=20)
        app.switch_page("app_pages/visao_orcamentaria.py")
        app.run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Visão Orçamentária")
        metric_labels = [item.label for item in app.metric]
        self.assertTrue(all(label in metric_labels for label in ["Dotação Atualizada", "Empenhado", "Liquidado", "Pago"]))


if __name__ == "__main__":
    unittest.main()
