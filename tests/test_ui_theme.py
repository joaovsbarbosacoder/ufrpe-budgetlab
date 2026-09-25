"""Testes unitários de formatação visual sem regras de negócio."""

import unittest
from pathlib import Path

import pandas as pd

from src import design_tokens
from src.ui_theme import _metric_visual, _theme_css, format_brl_compact, format_brl_full


class UiThemeTests(unittest.TestCase):
    def test_formats_compact_currency_with_brazilian_suffixes(self) -> None:
        self.assertEqual(format_brl_compact(83_600_000), "R$ 83,6 mi")
        self.assertEqual(format_brl_compact(2_450_000_000), "R$ 2,45 bi")
        self.assertEqual(format_brl_compact(352_400), "R$ 352,4 mil")

    def test_formats_complete_currency_and_null(self) -> None:
        self.assertEqual(format_brl_full(83_612_345.67), "R$ 83.612.345,67")
        self.assertEqual(format_brl_compact(-1_000), "R$ -1 mil")
        self.assertEqual(format_brl_full(pd.NA), "Valor nulo")

    def test_default_visual_shell_matches_light_administrative_layout(self) -> None:
        css = _theme_css()
        self.assertIn("min-width: 15.5rem", css)
        self.assertIn(design_tokens.SIDEBAR_ACTIVE, css)
        self.assertIn(design_tokens.BG, css)
        self.assertIn("ufrpe-page-context", css)
        self.assertIn("stDataFrame", css)
        self.assertIn(f"border-radius: {design_tokens.RADIUS}", css)
        self.assertIn(f"border-radius: {design_tokens.RADIUS_SM}", css)

    def test_sidebar_nav_labels_wrap_instead_of_truncating(self) -> None:
        css = _theme_css()
        self.assertIn("text-overflow: clip !important", css)
        self.assertIn("white-space: normal !important", css)
        self.assertIn("max-width: 1400px", css)

    def test_rounded_shape_tokens_match_streamlit_theme(self) -> None:
        config = (Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml").read_text(encoding="utf-8")

        self.assertEqual(design_tokens.RADIUS, "14px")
        self.assertEqual(design_tokens.RADIUS_SM, "10px")
        self.assertIn('baseRadius = "large"', config)
        self.assertIn('buttonRadius = "medium"', config)

    def test_dark_mode_is_not_available(self) -> None:
        css = _theme_css()
        config = (Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml").read_text(encoding="utf-8")

        self.assertIn("color-scheme: light", css)
        self.assertIn('base = "light"', config)
        self.assertNotIn("[theme.dark]", config)
        self.assertFalse(hasattr(design_tokens, "alternar_tema"))
        self.assertFalse(hasattr(design_tokens, "tema_atual"))

    def test_metric_visual_uses_semantic_status_colors(self) -> None:
        self.assertEqual(_metric_visual({"label": "Alertas críticos"}), ("!", design_tokens.NEGATIVE))
        self.assertEqual(_metric_visual({"label": "Registros aceitos"}), ("✓", design_tokens.POSITIVE))


if __name__ == "__main__":
    unittest.main()
