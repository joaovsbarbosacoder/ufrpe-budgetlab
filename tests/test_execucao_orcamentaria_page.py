"""Testes da página Execução Orçamentária (filtros + cards + série histórica)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.importacao_execucao import Manifesto


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFESTO_ATUAL = Path("data/manifestos/execucao_anual_atual.json")


@unittest.skipUnless(MANIFESTO_ATUAL.exists(), f"Manifesto ausente em {MANIFESTO_ATUAL}")
class ExecucaoOrcamentariaPageTests(unittest.TestCase):
    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        app.switch_page("app_pages/execucao_orcamentaria.py")
        app.run(timeout=30)
        return app

    def test_renders_cards_from_current_manifest(self) -> None:
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Execução Orçamentária")
        labels = [metric.label for metric in app.metric]
        self.assertEqual(
            labels,
            ["Empenhado", "Liquidado", "Pago", "% Liquidado/Empenhado", "% Pago/Liquidado"],
        )
        empenhado = next(metric for metric in app.metric if metric.label == "Empenhado")
        self.assertEqual(empenhado.value, "R$ 3,23 bi")

    def test_shows_procedencia_footer_with_manifest_hash(self) -> None:
        app = self._open_page()

        self.assertTrue(any("hash 7d09c278" in item.value for item in app.caption))

    def test_marks_ongoing_exercise_when_in_scope(self) -> None:
        # A legenda fixa da série histórica sempre explica a convenção ("O
        # exercício em andamento aparece com textura listrada..."), então o
        # marcador de verdade — que só aparece quando o recorte realmente
        # inclui o ano em andamento — é o aviso dos cards ("O recorte inclui").
        app = self._open_page()

        self.assertTrue(
            any("O recorte inclui" in item.value for item in app.caption)
        )

    def test_filtering_by_exercise_narrows_totals_and_hides_marker(self) -> None:
        app = self._open_page()
        exercicio_filter = next(m for m in app.multiselect if m.label == "Exercício")
        exercicio_filter.set_value(["2023"])
        app.run(timeout=30)

        self.assertEqual(len(app.exception), 0)
        empenhado = next(metric for metric in app.metric if metric.label == "Empenhado")
        self.assertEqual(empenhado.value, "R$ 762,5 mi")
        self.assertFalse(
            any("O recorte inclui" in item.value for item in app.caption)
        )

    def test_serie_historica_marks_only_the_ongoing_exercise(self) -> None:
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(item.value == "Série histórica" for item in app.subheader))

        charts = app.get("plotly_chart")
        self.assertEqual(len(charts), 2)
        spec = json.loads(charts[0].proto.spec)

        anos = spec["layout"]["xaxis"]["ticktext"]
        self.assertEqual(anos, ["2023", "2024", "2025", "2026 ⏳"])

        for trace in spec["data"]:
            self.assertIn(trace["name"], ("Empenhado", "Liquidado", "Pago"))
            shapes = trace["marker"]["pattern"]["shape"]
            # só a última posição (2026, em andamento) tem textura listrada
            self.assertEqual(shapes, ["", "", "", "/"])

    def test_composicao_selectbox_lists_all_dimensions(self) -> None:
        app = self._open_page()

        self.assertTrue(any(item.value == "Composição" for item in app.subheader))
        dimensao_select = next(sb for sb in app.selectbox if sb.label == "Dimensão")
        self.assertEqual(
            list(dimensao_select.options),
            [
                "GND",
                "Fonte de Recursos",
                "Ação de Governo",
                "Natureza de Despesa Detalhada",
                "Resultado Primário",
                "UG Responsável",
                "UGR",
                "PI",
                "PTRES",
                "Plano Orçamentário",
                "Favorecido",
            ],
        )

    def test_composicao_low_cardinality_dimension_shows_all_categories_untruncated(self) -> None:
        app = self._open_page()
        dimensao_select = next(sb for sb in app.selectbox if sb.label == "Dimensão")
        dimensao_select.set_value("GND")
        app.run(timeout=30)

        self.assertEqual(len(app.exception), 0)
        tables = app.get("dataframe")
        self.assertEqual(len(tables), 1)
        self.assertEqual(len(tables[0].value), 3)
        self.assertFalse(any("ficaram fora do ranking" in item.value for item in app.caption))

    def test_composicao_high_cardinality_dimension_is_ranked_and_truncated(self) -> None:
        app = self._open_page()
        dimensao_select = next(sb for sb in app.selectbox if sb.label == "Dimensão")
        dimensao_select.set_value("Favorecido")
        app.run(timeout=30)

        self.assertEqual(len(app.exception), 0)
        tables = app.get("dataframe")
        self.assertEqual(len(tables), 1)
        tabela = tables[0].value
        self.assertEqual(len(tabela), 15)
        self.assertTrue(
            (tabela["Empenhado"].reset_index(drop=True) == tabela["Empenhado"].sort_values(ascending=False).reset_index(drop=True)).all()
        )
        self.assertTrue(
            any("Mostrando as 15 categorias" in item.value and "ficaram fora do ranking" in item.value for item in app.caption)
        )

    def test_composicao_plano_orcamentario_dimension_is_also_ranked(self) -> None:
        # "Plano Orçamentário" (102 categorias na base atual) não consta na lista de
        # alta cardinalidade documentada, mas precisa do mesmo corte dinâmico.
        app = self._open_page()
        dimensao_select = next(sb for sb in app.selectbox if sb.label == "Dimensão")
        dimensao_select.set_value("Plano Orçamentário")
        app.run(timeout=30)

        self.assertEqual(len(app.exception), 0)
        tables = app.get("dataframe")
        self.assertEqual(len(tables[0].value), 15)
        self.assertTrue(
            any("ficaram fora do ranking" in item.value for item in app.caption)
        )

    def test_rastreabilidade_prompts_for_selection_by_default(self) -> None:
        app = self._open_page()

        self.assertTrue(any(item.value == "Rastreabilidade" for item in app.subheader))
        ne_select = next(sb for sb in app.selectbox if sb.label == "Nota de Empenho (NE)")
        self.assertIsNone(ne_select.value)
        self.assertTrue(
            any("Selecione uma NE" in item.value for item in app.caption)
        )

    def test_rastreabilidade_shows_source_rows_with_linha_origem_for_selected_ne(self) -> None:
        # NE com uma linha de empenho e uma linha de item de execução (anulação) —
        # confirma que ambas aparecem, com linha_origem visível.
        ne_ccor_esperado = "153165152392023NE000001"
        app = self._open_page()
        ne_select = next(sb for sb in app.selectbox if sb.label == "Nota de Empenho (NE)")
        rotulo = next(label for label in ne_select.options if label.startswith(ne_ccor_esperado))
        ne_select.set_value(rotulo)
        app.run(timeout=30)

        self.assertEqual(len(app.exception), 0)
        tables = app.get("dataframe")
        tabela_rastreabilidade = tables[-1].value
        self.assertIn("linha_origem", tabela_rastreabilidade.columns)
        self.assertEqual(sorted(tabela_rastreabilidade["linha_origem"].tolist()), [596, 598])
        self.assertTrue(
            any(
                f"linha(s) de origem na planilha para a NE {ne_ccor_esperado}" in item.value
                for item in app.caption
            )
        )

    def test_explains_when_no_manifest_available(self) -> None:
        with patch.object(Manifesto, "atual", return_value=None):
            app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(
            any(
                "Nenhuma base de Execução Anual foi importada" in item.value
                for item in app.info
            )
        )


if __name__ == "__main__":
    unittest.main()
