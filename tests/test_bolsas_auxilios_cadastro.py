"""Testes do cadastro nativo e da migração de Bolsas e Auxílios."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import src.bolsas_auxilios_cadastro as cadastro


class TestValorMensalExcepcional(unittest.TestCase):
    def test_sem_excecao_calcula_quantidade_vezes_valor_unitario(self) -> None:
        registro = cadastro.novo_programa(
            qtd_efetiva=3, valor_unitario=500.0, meses_no_ano=12,
        )

        dataframe = cadastro.como_dataframe([registro])

        self.assertTrue(pd.isna(dataframe.loc[0, "valor_mensal_excepcional"]))
        self.assertAlmostEqual(dataframe.loc[0, "valor_mensal"], 1500.0)
        self.assertAlmostEqual(dataframe.loc[0, "valor_anual"], 18000.0)

    def test_excecao_preserva_valor_sem_mudar_quantidade_zero(self) -> None:
        registro = cadastro.novo_programa(
            qtd_efetiva=0,
            valor_unitario=6136.0,
            valor_mensal_excepcional=6136.0,
            meses_no_ano=1,
        )

        dataframe = cadastro.como_dataframe([registro])

        self.assertEqual(dataframe.loc[0, "qtd_efetiva"], 0)
        self.assertAlmostEqual(dataframe.loc[0, "valor_mensal"], 6136.0)
        self.assertAlmostEqual(dataframe.loc[0, "valor_anual"], 6136.0)

    def test_migracao_grava_excecao_somente_quando_origem_diverge(self) -> None:
        origem = pd.DataFrame(
            [
                {
                    "processo": "001",
                    "programa_bolsa": "REGULAR",
                    "qtd_efetiva": 2,
                    "valor_unitario": 500.0,
                    "valor_mensal": 1000.0,
                    "meses_no_ano": 12,
                },
                {
                    "processo": "002",
                    "programa_bolsa": "COMPLEMENTO",
                    "qtd_efetiva": 0,
                    "valor_unitario": 6136.0,
                    "valor_mensal": 6136.0,
                    "meses_no_ano": 1,
                },
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(cadastro, "DIRETORIO_PADRAO", Path(tmp)),
                patch.object(cadastro, "ler_bolsas_auxilios", return_value=origem),
            ):
                cadastro.migrar_de_planilha("origem.xlsx", 2026)
                registros = cadastro.carregar_programas(2026)

        por_programa = {registro["programa_bolsa"]: registro for registro in registros}
        self.assertIsNone(por_programa["REGULAR"]["valor_mensal_excepcional"])
        self.assertAlmostEqual(
            por_programa["COMPLEMENTO"]["valor_mensal_excepcional"], 6136.0
        )


if __name__ == "__main__":
    unittest.main()
