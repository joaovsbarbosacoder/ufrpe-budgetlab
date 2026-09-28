"""Testes estruturais do painel inicial."""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests._apptest import TEMPO_LIMITE_APPTEST


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class HomePageTests(unittest.TestCase):
    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=TEMPO_LIMITE_APPTEST)
        app.run()
        app.switch_page("app_pages/home.py")
        app.run()
        return app

    def test_renders_real_status_metrics_and_quick_accesses(self) -> None:
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Visão geral")
        self.assertEqual(len(app.metric), 4)
        self.assertTrue(any("Bases disponíveis" in metric.label for metric in app.metric))
        self.assertTrue(any(str(metric.value).endswith("de 8") for metric in app.metric))

        links = [link.label for link in app.get("page_link")]
        self.assertIn("Consulta de empenhos", links)
        self.assertIn("Gerenciamento de prazos", links)
        self.assertIn("Atualizar planilhas", links)

    def test_explains_that_financial_values_are_not_combined(self) -> None:
        app = self._open_page()

        self.assertTrue(
            any(
                "não combinam valores financeiros" in caption.value
                for caption in app.caption
            )
        )


if __name__ == "__main__":
    unittest.main()
