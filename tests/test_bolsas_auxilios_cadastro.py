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


class TestProcessos(unittest.TestCase):
    """`processo` (processo de empenho) e `processo_contratacao` (campo novo, 06/10/2026)."""

    def test_ida_e_volta_preserva_os_dois_processos_como_texto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(cadastro, "DIRETORIO_PADRAO", Path(tmp)):
            registro = cadastro.novo_programa(
                processo="001167/2026-78", processo_contratacao="000123/2025-01", programa_bolsa="PIBIC",
            )
            cadastro.salvar_programa(2026, registro)
            lido = cadastro.como_dataframe(cadastro.carregar_programas(2026))
        self.assertEqual(lido.loc[0, "processo"], "001167/2026-78")
        self.assertEqual(lido.loc[0, "processo_contratacao"], "000123/2025-01")

    def test_registro_anterior_sem_o_campo_fica_nulo_e_nao_copia_o_de_empenho(self) -> None:
        # registros já gravados (migrados da planilha, que não tem essa coluna) não têm a chave
        legado = cadastro.novo_programa(processo="001167/2026-78", programa_bolsa="PIBIC")
        legado.pop("processo_contratacao")
        lido = cadastro.como_dataframe([legado])
        self.assertTrue(pd.isna(lido.loc[0, "processo_contratacao"]))
        self.assertEqual(lido.loc[0, "processo"], "001167/2026-78")

    def test_migracao_deixa_processo_da_contratacao_nulo(self) -> None:
        origem = pd.DataFrame([{"processo": "001", "programa_bolsa": "X", "qtd_efetiva": 1, "valor_unitario": 1.0}])
        with tempfile.TemporaryDirectory() as tmp, patch.object(cadastro, "ler_bolsas_auxilios", return_value=origem):
            criados = cadastro.migrar_de_planilha("origem.xlsx", 2026, diretorio_base=tmp)
        self.assertIsNone(criados[0]["processo_contratacao"])
        self.assertEqual(criados[0]["processo"], "001")

    def test_processo_da_contratacao_e_copiado_ao_duplicar_identidade(self) -> None:
        self.assertIn("processo_contratacao", cadastro.CAMPOS_IDENTIDADE)


if __name__ == "__main__":
    unittest.main()
