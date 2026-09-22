"""Testes de `src/execucao_ne_utils.py` — ligação por Nota de Empenho, compartilhada entre
Execução Anual e Execução Mensal.

Movidos de `tests/test_execucao_anual.py` em 22/09/2026 (junto com as funções que testam —
ver docstring de `src.execucao_ne_utils`): `TestIndiceValorPagoPorNeCurta` continua usando a
Execução Anual como fonte de dados real só para exercitar o índice contra uma base
volumosa/realista — a função em si (`indice_valor_pago_por_ne_curta`) não tem preferência de
base, funcionaria igual com a Mensal.
"""

import unittest
from pathlib import Path

import pandas as pd

from src.execucao_anual import agregar_por_ne, ler_execucao_anual
from src.execucao_ne_utils import indice_valor_pago_por_ne_curta, ne_curta

CAMINHO_BASE = Path("data/raw/BI CPOC - EXEC. DESPESAS - Por Ano - com processo.xlsx")


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Base ausente em {CAMINHO_BASE}")
class TestIndiceValorPagoPorNeCurta(unittest.TestCase):
    """`indice_valor_pago_por_ne_curta` — base da reconciliação em
    `app_pages/contratos_pagamentos.py` contra o valor oficial pago por NE."""

    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_anual(CAMINHO_BASE)
        cls.por_ne = agregar_por_ne(cls.df)
        cls.indice = indice_valor_pago_por_ne_curta(cls.por_ne)

    def test_mesma_quantidade_de_nes_que_agregar_por_ne(self):
        self.assertEqual(len(self.indice), len(self.por_ne))

    def test_indexado_pela_ne_curta_nao_pelo_ne_ccor_completo(self):
        amostra = self.por_ne.iloc[0]
        esperado = ne_curta(amostra["ne_ccor"])
        self.assertIn(esperado, self.indice.index)

    def test_valor_bate_com_a_coluna_paga_da_linha_correspondente(self):
        amostra = self.por_ne.iloc[0]
        chave = ne_curta(amostra["ne_ccor"])
        valor_esperado = amostra["paga"]
        if pd.isna(valor_esperado):
            self.assertTrue(pd.isna(self.indice[chave]))
        else:
            self.assertAlmostEqual(float(self.indice[chave]), float(valor_esperado), places=2)


class TestNeCurta(unittest.TestCase):
    """`ne_curta` usa o ano embutido no próprio `ne_ccor` (posições 11-14), não o Ano
    Lançamento — os dois podem divergir em NE de resto a pagar (ver alerta em
    `src.execucao_anual.validar`)."""

    def test_forma_curta_a_partir_do_ne_ccor_completo(self):
        self.assertEqual(ne_curta("153165152392025NE000709"), "2025NE000709")

    def test_resto_a_pagar_usa_o_ano_do_proprio_ne_ccor(self):
        # NE do exercício de 2024, ainda em execução (Ano Lançamento) em 2026: o ano do
        # ne_ccor (2024) é o que importa para achar o marcador "NE", não o Ano Lançamento.
        self.assertEqual(ne_curta("153165152392024NE000500"), "2024NE000500")


if __name__ == "__main__":
    unittest.main()
