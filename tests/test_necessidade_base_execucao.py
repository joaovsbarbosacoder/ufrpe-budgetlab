"""Base da Necessidade de empenho: valor contratual × projeção pela execução (12/10/2026).

`aplicar_projecao_na_necessidade` troca a coluna `necessidade` de `necessidade_por_ne` pela `necessidade_execucao` do
relatório "Projeção pela Execução", sem mexer na entrada e preservando a contratual ao lado. Nulo ≠ zero.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd

from src.relatorio_projecao_execucao import aplicar_projecao_na_necessidade


def _por_ne() -> pd.DataFrame:
    return pd.DataFrame({
        "ne_curta": ["2026NE000001", "2026NE000002", "2026NE000003"],
        "necessidade": [1000.0, 500.0, 0.0],
    })


def _relatorio(valores: dict) -> SimpleNamespace:
    return SimpleNamespace(linhas=pd.DataFrame({
        "ne_curta": list(valores), "necessidade_execucao": list(valores.values()),
    }))


class AplicarProjecaoTests(unittest.TestCase):
    def test_troca_a_necessidade_e_guarda_a_contratual(self) -> None:
        saida = aplicar_projecao_na_necessidade(_por_ne(), _relatorio({
            "2026NE000001": 400.0, "2026NE000002": 0.0, "2026NE000003": 250.0,
        }))
        self.assertEqual(saida["necessidade"].tolist(), [400.0, 0.0, 250.0])
        self.assertEqual(saida["necessidade_contratual"].tolist(), [1000.0, 500.0, 0.0])

    def test_nao_altera_a_entrada(self) -> None:
        entrada = _por_ne()
        aplicar_projecao_na_necessidade(entrada, _relatorio({"2026NE000001": 1.0}))
        self.assertEqual(entrada["necessidade"].tolist(), [1000.0, 500.0, 0.0])
        self.assertNotIn("necessidade_contratual", entrada.columns)

    def test_ne_fora_do_relatorio_ou_com_valor_nulo_fica_nula_e_zero_continua_zero(self) -> None:
        saida = aplicar_projecao_na_necessidade(_por_ne(), _relatorio({"2026NE000001": None, "2026NE000002": 0.0}))
        self.assertTrue(pd.isna(saida.loc[0, "necessidade"]))   # valor mensal desconhecido: nulo
        self.assertEqual(saida.loc[1, "necessidade"], 0.0)      # zero de verdade
        self.assertTrue(pd.isna(saida.loc[2, "necessidade"]))   # NE que o relatório não projetou
        self.assertEqual(saida.loc[2, "necessidade_contratual"], 0.0)

    def test_relatorio_vazio_deixa_tudo_nulo(self) -> None:
        vazio = SimpleNamespace(linhas=pd.DataFrame(columns=["ne_curta", "necessidade_execucao"]))
        saida = aplicar_projecao_na_necessidade(_por_ne(), vazio)
        self.assertTrue(saida["necessidade"].isna().all())


if __name__ == "__main__":
    unittest.main()
