"""Testes do cadastro nativo de Contratos Contínuos.

`meses_no_ano` (pedido explícito, mesmo campo/motivo de
`tests/test_bolsas_auxilios_cadastro.py`): total de meses que o contrato é pago no exercício —
corrige o mesmo bug real de Bolsas e Auxílios (`despesa_anual` sempre `× 12`, mesmo para um
contrato que só roda parte do ano). Único módulo deste par (Bolsas/Contratos Contínuos) sem
teste dedicado até agora — os demais campos do cadastro continuam cobertos só indiretamente
por `tests/test_relatorio_reforco_empenho.py`/`tests/test_ui_relatorio_reforco_empenho.py`.
"""

from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
