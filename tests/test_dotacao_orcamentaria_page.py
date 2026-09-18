"""Testes da página Dotação Orçamentária com base controlada em memória.

O manifesto e o DataFrame são injetados na camada de importação. Nenhum teste depende de
`data/raw/` nem altera os manifestos de trabalho do ambiente local.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.importacao_dotacao import gerar_manifesto, ler_dotacao_anual
from tests.test_tesouro_dotacao_anual import workbook_bytes, write_recognized_sheet

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DotacaoOrcamentariaPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporario = tempfile.TemporaryDirectory()
        cls.caminho_fixture = Path(cls._temporario.name) / "dotacao_anual.xlsx"
        cls.caminho_fixture.write_bytes(workbook_bytes(write_recognized_sheet))
        referencia = datetime(2024, 12, 31, 12).timestamp()
        os.utime(cls.caminho_fixture, (referencia, referencia))
        leitura = ler_dotacao_anual(cls.caminho_fixture)
        cls.dataframe = leitura.workbook.consolidated_data
        cls.manifesto = gerar_manifesto(leitura, cls.caminho_fixture)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporario.cleanup()

    def setUp(self) -> None:
        self._patch_manifesto = patch(
            "src.importacao_dotacao.Manifesto.atual", return_value=self.manifesto
        )
        self._patch_carregar = patch(
            "src.importacao_dotacao.carregar_atual", return_value=self.dataframe.copy()
        )
        self._patch_manifesto_execucao = patch(
            "src.importacao_execucao.Manifesto.atual", return_value=None
        )
        self.mock_manifesto = self._patch_manifesto.start()
        self._patch_carregar.start()
        self._patch_manifesto_execucao.start()

    def tearDown(self) -> None:
        self._patch_manifesto_execucao.stop()
        self._patch_carregar.stop()
        self._patch_manifesto.stop()

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

        anos_texto = ", ".join(str(ano) for ano in self.manifesto.anos)
        self.assertTrue(any(f"Anos: {anos_texto}" in item.value for item in app.caption))

    def test_shows_procedencia_footer_with_manifest_hash(self) -> None:
        app = self._open_page()
        self.assertTrue(
            any(f"hash {self.manifesto.sha256[:8]}" in item.value for item in app.caption)
        )

    def test_marks_ongoing_exercise_when_in_scope(self) -> None:
        # Por padrão nenhum filtro está aplicado — o recorte inclui todos os
        # exercícios da extração, incluindo o exercício em andamento.
        app = self._open_page()

        self.assertTrue(any("O recorte inclui" in item.value for item in app.caption))

    def test_explains_when_no_manifest_available(self) -> None:
        self.mock_manifesto.return_value = None
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
