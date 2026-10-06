"""Testes do cadastro nativo de Contratos Contínuos.

`meses_no_ano` (pedido explícito, mesmo campo/motivo de
`tests/test_bolsas_auxilios_cadastro.py`): total de meses que o contrato é pago no exercício —
corrige o mesmo bug real de Bolsas e Auxílios (`despesa_anual` sempre `× 12`, mesmo para um
contrato que só roda parte do ano). Único módulo deste par (Bolsas/Contratos Contínuos) sem
teste dedicado até agora — os demais campos do cadastro continuam cobertos só indiretamente
por `tests/test_relatorio_reforco_empenho.py`/`tests/test_ui_relatorio_reforco_empenho.py`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import src.contratos_continuos_cadastro as cadastro


class TestMesesNoAno(unittest.TestCase):
    def test_despesa_anual_usa_meses_no_ano(self) -> None:
        registro = cadastro.novo_contrato(despesa_mensal=1000.0, meses_no_ano=6)
        dataframe = cadastro.como_dataframe([registro])
        self.assertAlmostEqual(dataframe.loc[0, "despesa_anual"], 6000.0)

    def test_sem_meses_no_ano_cai_no_padrao_de_12(self) -> None:
        # registro anterior a esta correção (campo nunca preenchido, `novo_contrato` sem o
        # argumento) -- mesmo comportamento de antes, contrato "contínuo" o ano inteiro.
        registro = cadastro.novo_contrato(despesa_mensal=1000.0)
        self.assertIsNone(registro["meses_no_ano"])
        dataframe = cadastro.como_dataframe([registro])
        self.assertAlmostEqual(dataframe.loc[0, "despesa_anual"], 12000.0)

    def test_contrato_de_12_meses_explicito_bate_com_o_padrao_anterior(self) -> None:
        registro = cadastro.novo_contrato(despesa_mensal=2500.0, meses_no_ano=12)
        dataframe = cadastro.como_dataframe([registro])
        self.assertAlmostEqual(dataframe.loc[0, "despesa_anual"], 30000.0)

    def test_meses_no_ano_e_copiado_ao_duplicar_identidade(self) -> None:
        self.assertIn("meses_no_ano", cadastro.CAMPOS_IDENTIDADE)


class TestVigenciaEStatusNoCadastro(unittest.TestCase):
    """`vigencia_fim` (data) e o status SUSPENSO precisam sobreviver à gravação e à leitura: a
    projeção do relatório de Necessidade de Empenho depende dos dois (02/10/2026)."""

    def test_ida_e_volta_preserva_data_e_status(self) -> None:
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(cadastro, "DIRETORIO_PADRAO", Path(pasta)):
            registro = cadastro.novo_contrato(
                contrato_numero="14/2022", status_contrato="SUSPENSO",
                vigencia_fim=pd.Timestamp("2026-11-15"), despesa_mensal=1000.0,
            )
            cadastro.salvar_contrato(2026, registro)
            lido = cadastro.como_dataframe(cadastro.carregar_contratos(2026))
        self.assertEqual(lido.loc[0, "status_contrato"], "SUSPENSO")
        self.assertEqual(lido.loc[0, "vigencia_fim"], pd.Timestamp("2026-11-15"))

    def test_data_removida_grava_nulo_nunca_presumido(self) -> None:
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(cadastro, "DIRETORIO_PADRAO", Path(pasta)):
            registro = cadastro.novo_contrato(contrato_numero="1/2026", vigencia_fim=pd.Timestamp("2026-11-15"))
            cadastro.salvar_contrato(2026, registro)
            registro["vigencia_fim"] = None
            cadastro.atualizar_contrato(2026, registro)
            lido = cadastro.como_dataframe(cadastro.carregar_contratos(2026))
        self.assertTrue(pd.isna(lido.loc[0, "vigencia_fim"]))

    def test_vigencia_e_copiada_ao_duplicar_identidade(self) -> None:
        self.assertIn("vigencia_fim", cadastro.CAMPOS_IDENTIDADE)


class TestInicioDaExecucaoNoCadastro(unittest.TestCase):
    """`inicio_execucao_data` (início por data, 02/10/2026) é dado de execução do exercício."""

    def test_ida_e_volta_preserva_a_data(self) -> None:
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(cadastro, "DIRETORIO_PADRAO", Path(pasta)):
            registro = cadastro.novo_contrato(contrato_numero="9/2026", inicio_execucao_data=pd.Timestamp("2026-07-16"))
            cadastro.salvar_contrato(2026, registro)
            lido = cadastro.como_dataframe(cadastro.carregar_contratos(2026))
        self.assertEqual(lido.loc[0, "inicio_execucao_data"], pd.Timestamp("2026-07-16"))

    def test_sem_data_fica_nulo_nunca_presumido(self) -> None:
        lido = cadastro.como_dataframe([cadastro.novo_contrato(contrato_numero="9/2026")])
        self.assertTrue(pd.isna(lido.loc[0, "inicio_execucao_data"]))

    def test_inicio_e_de_execucao_nao_de_identidade(self) -> None:
        # por exercício: em branco no exercício novo (como `inicio_execucao_mes`), não copiado ao duplicar
        self.assertIn("inicio_execucao_data", cadastro.CAMPOS_EXECUCAO_PADRAO)
        self.assertNotIn("inicio_execucao_data", cadastro.CAMPOS_IDENTIDADE)


if __name__ == "__main__":
    unittest.main()
