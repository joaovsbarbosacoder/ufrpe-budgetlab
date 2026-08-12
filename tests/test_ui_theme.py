"""Testes unitários de formatação visual sem regras de negócio."""

import unittest

import pandas as pd

from src.ui_theme import format_brl_compact, format_brl_full


class UiThemeTests(unittest.TestCase):
    def test_formats_compact_currency_with_brazilian_suffixes(self) -> None:
        self.assertEqual(format_brl_compact(83_600_000), "R$ 83,6 mi")
        self.assertEqual(format_brl_compact(2_450_000_000), "R$ 2,45 bi")
        self.assertEqual(format_brl_compact(352_400), "R$ 352,4 mil")

    def test_formats_complete_currency_and_null(self) -> None:
        self.assertEqual(format_brl_full(83_612_345.67), "R$ 83.612.345,67")
        self.assertEqual(format_brl_compact(-1_000), "R$ -1 mil")
        self.assertEqual(format_brl_full(pd.NA), "Valor nulo")


if __name__ == "__main__":
    unittest.main()
