"""Smoke test da página Gerenciamento de Prazos — bloco Google Agenda por situação de
conexão. A situação é simulada com `mock.patch` (nunca lê `data/google_agenda/` real)."""

import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PainelPrazosGoogleAgendaTests(unittest.TestCase):
    def _abrir(self, situacao: str) -> AppTest:
        with mock.patch("src.google_agenda.situacao_conexao", return_value=situacao):
            app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
            app.run(timeout=60)
            app.switch_page("app_pages/painel_prazos.py")
            app.run(timeout=60)
        return app

    def test_sem_credenciais_mostra_instrucao(self):
        app = self._abrir("sem_credenciais")
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("docs/google_agenda.md" in m.value for m in app.markdown))

    def test_desconectado_mostra_botao_conectar(self):
        app = self._abrir("desconectado")
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Conectar ao Google Agenda", [b.label for b in app.button])


if __name__ == "__main__":
    unittest.main()
