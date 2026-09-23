"""Testes estruturais da visão geral de TEDs."""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TedsVisaoGeralPageTests(unittest.TestCase):
    def test_preserva_cabecalho_mesmo_sem_dados_importados(self) -> None:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run(timeout=20)
        app.switch_page("app_pages/teds_visao_geral.py")
        app.run(timeout=20)

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Visão geral")
        self.assertTrue(
            any("descentralização de crédito" in item.value for item in app.markdown)
        )


if __name__ == "__main__":
    unittest.main()
