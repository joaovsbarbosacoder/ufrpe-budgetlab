"""Testes da página Dotação Orçamentária (leitura pelo manifesto atual).

Espelha `test_execucao_orcamentaria_page.py`: usa a extração real apontada pelo manifesto
atual de Dotação Anual (`data/manifestos/dotacao_anual_atual.json`), sem fixtures sintéticas
— e por isso é pulada se esse manifesto não existir.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.importacao_dotacao import Manifesto

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFESTO_ATUAL = Path("data/manifestos/dotacao_anual_atual.json")


@unittest.skipUnless(MANIFESTO_ATUAL.exists(), f"Manifesto ausente em {MANIFESTO_ATUAL}")
class DotacaoOrcamentariaPageTests(unittest.TestCase):
    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        app.switch_page("app_pages/dotacao_orcamentaria.py")
        app.run(timeout=30)
        return app

    def test_renders_page_from_current_manifest(self) -> None:
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Dotação Orçamentária")
        self.assertTrue(app.metric)

        manifesto = Manifesto.atual()
        anos_texto = ", ".join(str(ano) for ano in manifesto.anos)
        self.assertTrue(any(f"Anos: {anos_texto}" in item.value for item in app.caption))

    def test_shows_procedencia_footer_with_manifest_hash(self) -> None:
        app = self._open_page()
        manifesto = Manifesto.atual()

        self.assertTrue(
            any(f"hash {manifesto.sha256[:8]}" in item.value for item in app.caption)
        )

    def test_marks_ongoing_exercise_when_in_scope(self) -> None:
        # Por padrão nenhum filtro está aplicado — o recorte inclui todos os
        # exercícios da extração, incluindo o exercício em andamento.
        app = self._open_page()

        self.assertTrue(any("O recorte inclui" in item.value for item in app.caption))

    def test_explains_when_no_manifest_available(self) -> None:
        with patch.object(Manifesto, "atual", return_value=None):
            app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(
            any(
                "Nenhuma base de Dotação Anual foi importada" in item.value
                for item in app.info
            )
        )


if __name__ == "__main__":
    unittest.main()
