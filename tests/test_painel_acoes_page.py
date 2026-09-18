"""Testes da página Painel por Ação de Governo.

Migrou de `st.session_state` para o manifesto versionado de Dotação Anual
(`src/importacao_dotacao.py`). As planilhas sintéticas são lidas em diretório temporário e o
manifesto/DataFrame são injetados: os testes não tocam em `data/raw/` ou `data/manifestos/`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.importacao_dotacao import gerar_manifesto, ler_dotacao_anual
from tests.test_tesouro_dotacao_anual import (
    workbook_bytes,
    write_recognized_sheet,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
def write_sheet_with_empty_subdivision(ws) -> None:
    """Base válida com uma ação extra sem nenhum valor monetário informado.

    Reproduz o caso real: a combinação de dimensões existe na planilha (a
    linha está lá, com código de ação, fonte etc.), mas as quatro colunas
    de indicador conhecido estão vazias para o ano da base. Essa ação não
    deve aparecer no painel.
    """

    write_recognized_sheet(ws)

    ws["A6"] = 9
    ws["B6"] = "Iduso C"
    ws["C6"] = 10
    ws["D6"] = "RP A"
    ws["E6"] = "ACAO_VAZIA"
    ws["F6"] = "Ação sem dado no ano"
    ws["G6"] = "PTRES9"
    ws["H6"] = "FONTE9"
    ws["I6"] = "Fonte C"
    ws["J6"] = "PO9"
    ws["K6"] = "PO C"
    ws["L6"] = None
    ws["M6"] = None
    ws["N6"] = None


def write_sheet_with_two_acoes(ws) -> None:
    """Base válida com duas ações distintas, ambas com dado real no ano."""

    write_recognized_sheet(ws)

    ws["A6"] = 9
    ws["B6"] = "Iduso C"
    ws["C6"] = 10
    ws["D6"] = "RP A"
    ws["E6"] = "ACAO2"
    ws["F6"] = "Segunda ação"
    ws["G6"] = "PTRES9"
    ws["H6"] = "FONTE9"
    ws["I6"] = "Fonte C"
    ws["J6"] = "PO9"
    ws["K6"] = "PO C"
    ws["L6"] = 500
    ws["M6"] = 600
    ws["N6"] = 10


def write_sheet_with_phantom_fonte(ws) -> None:
    """Base válida com uma Fonte extra, na mesma Ação, sem nenhum valor real.

    Reproduz o relato: ao filtrar por uma Ação, uma Fonte sem dotação
    correspondente (existe só porque a linha está na planilha, mas as
    quatro colunas de indicador conhecido estão vazias) não deve aparecer
    como opção selecionável no filtro de Fonte.
    """

    write_recognized_sheet(ws)

    ws["A6"] = 9
    ws["B6"] = "Iduso C"
    ws["C6"] = 10
    ws["D6"] = "RP A"
    ws["E6"] = "ACAO1"
    ws["F6"] = "Acao desc A"
    ws["G6"] = "PTRES9"
    ws["H6"] = "FONTE_FANTASMA"
    ws["I6"] = "Fonte sem dado"
    ws["J6"] = "PO9"
    ws["K6"] = "PO C"
    ws["L6"] = None
    ws["M6"] = None
    ws["N6"] = None


class PainelAcoesPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporario = tempfile.TemporaryDirectory()
        self._patch_manifesto = patch(
            "src.importacao_dotacao.Manifesto.atual", return_value=None
        )
        self._patch_carregar = patch(
            "src.importacao_dotacao.carregar_atual", return_value=None
        )
        self.mock_manifesto = self._patch_manifesto.start()
        self.mock_carregar = self._patch_carregar.start()

    def tearDown(self) -> None:
        self._patch_carregar.stop()
        self._patch_manifesto.stop()
        self._temporario.cleanup()

    def _importar_fixture(self, nome: str, builder) -> Path:
        caminho = Path(self._temporario.name) / nome
        caminho.write_bytes(workbook_bytes(builder))
        leitura = ler_dotacao_anual(caminho)
        manifesto = gerar_manifesto(leitura, caminho)
        self.mock_manifesto.return_value = manifesto
        self.mock_carregar.return_value = leitura.workbook.consolidated_data
        return caminho

    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        app.switch_page("app_pages/painel_acoes.py")
        app.run(timeout=20)
        if app.selectbox:
            app.selectbox[0].select(2024)
            app.run(timeout=20)
        return app

    def test_renders_cards_after_loading_validated_base(self) -> None:
        self._importar_fixture("dotacao_anual.xlsx", write_recognized_sheet)
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Painel por Ação de Governo")
        self.assertTrue(app.metric)
        self.assertTrue(any("1 ações" in item.value for item in app.caption))

    def test_hides_action_without_any_known_indicator_value(self) -> None:
        self._importar_fixture("dotacao_anual.xlsx", write_sheet_with_empty_subdivision)
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        cards_html = " ".join(item.value for item in app.markdown)
        self.assertIn("ACAO1", cards_html)
        self.assertNotIn("ACAO_VAZIA", cards_html)
        self.assertTrue(any("1 ações" in item.value for item in app.caption))

    def test_multiselect_filter_narrows_to_chosen_action_codes(self) -> None:
        self._importar_fixture("dotacao_anual.xlsx", write_sheet_with_two_acoes)
        app = self._open_page()
        self.assertEqual(len(app.exception), 0)

        cards_html = " ".join(item.value for item in app.markdown)
        self.assertIn("ACAO1", cards_html)
        self.assertIn("ACAO2", cards_html)

        acao_filter = next(m for m in app.multiselect if m.label == "Ação Governo")
        self.assertEqual(acao_filter.value, [])
        acao_filter.set_value(["ACAO2 — Segunda ação"])
        app.run(timeout=20)

        self.assertEqual(len(app.exception), 0)
        cards_html_after = " ".join(item.value for item in app.markdown)
        self.assertIn("ACAO2", cards_html_after)
        self.assertNotIn("ACAO1", cards_html_after)

    def test_filter_options_exclude_values_without_any_real_data(self) -> None:
        self._importar_fixture("dotacao_anual.xlsx", write_sheet_with_phantom_fonte)
        app = self._open_page()
        self.assertEqual(len(app.exception), 0)

        acao_filter = next(m for m in app.multiselect if m.label == "Ação Governo")
        acao_filter.set_value(["ACAO1 — Acao desc A"])
        app.run(timeout=20)
        self.assertEqual(len(app.exception), 0)

        fonte_filter = next(m for m in app.multiselect if m.label == "Fonte Detalhada")
        fonte_options = fonte_filter.options
        self.assertTrue(any(option.startswith("FONTE1") for option in fonte_options))
        self.assertTrue(any(option.startswith("FONTE2") for option in fonte_options))
        self.assertFalse(any("FONTE_FANTASMA" in option for option in fonte_options))

    def test_explains_when_no_base_was_imported(self) -> None:
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(
            any(
                "Nenhuma base de Dotação Anual foi importada ainda." in item.value
                for item in app.info
            )
        )


if __name__ == "__main__":
    unittest.main()
