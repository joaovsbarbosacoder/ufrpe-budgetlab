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
        html = "".join(h.proto.body for h in app.get("html"))
        # indicadores em cartões (28/10/2026): bases, prazos pendentes, atrasados e vencendo
        self.assertEqual(html.count('class="hm-kpi"'), 4)
        for rotulo in ("Bases disponíveis", "Prazos pendentes", "Atrasados", "Vencendo"):
            self.assertIn(rotulo, html)
        self.assertIn("de 7</small>", html)
        # painéis de prazos e de bases (uma linha por base cadastrada)
        self.assertIn("Prazos que pedem atenção", html)
        self.assertIn("Bases de dados", html)
        self.assertGreaterEqual(html.count('class="hm-linha"'), 7)

        links = [link.label for link in app.get("page_link")]
        self.assertIn("Consulta de empenhos", links)
        self.assertIn("Gerenciamento de prazos", links)
        self.assertIn("Atualizar planilhas", links)
        self.assertIn("Despesas de pessoal", links)

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
