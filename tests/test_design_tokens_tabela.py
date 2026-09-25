"""Coerência das constantes da tabela de subdivisões (Painel por Ação)."""

import re
import unittest

from src import design_tokens as dt


def _minimos(colunas: str) -> list[int]:
    """Largura mínima em px de cada coluna de um `grid-template-columns`."""
    resultado = []
    for token in re.findall(r"minmax\(\s*(\d+)px[^)]*\)|(\d+)px", colunas):
        resultado.append(int(token[0] or token[1]))
    return resultado


def _px(valor: str) -> int:
    return int(valor.removesuffix("px"))


class TestTabelaSubdivisoes(unittest.TestCase):
    def test_compacta_mantem_todas_as_colunas(self):
        self.assertEqual(
            len(_minimos(dt.SUBDIV_COLUMNS_COMPACT)), len(_minimos(dt.SUBDIV_COLUMNS))
        )
        self.assertEqual(len(_minimos(dt.SUBDIV_COLUMNS)), 11)

    def test_min_width_e_soma_dos_minimos_mais_gaps(self):
        for colunas, largura in (
            (dt.SUBDIV_COLUMNS, dt.TABLE_MIN_WIDTH),
            (dt.SUBDIV_COLUMNS_COMPACT, dt.TABLE_MIN_WIDTH_COMPACT),
        ):
            minimos = _minimos(colunas)
            gaps = (len(minimos) - 1) * _px(dt.SUBDIV_GAP)
            self.assertEqual(sum(minimos) + gaps, _px(largura))

    def test_compacta_e_mais_estreita(self):
        self.assertLess(_px(dt.TABLE_MIN_WIDTH_COMPACT), _px(dt.TABLE_MIN_WIDTH))


if __name__ == "__main__":
    unittest.main()
