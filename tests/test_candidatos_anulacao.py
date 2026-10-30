"""Testes de `src/candidatos_anulacao.py` — indicações informativas de candidatos a anulação.

DataFrames sintéticos com valores esperados calculados à mão. Referência: extração de 09/2026;
limites padrão (nunca liquidada ≥ 3 meses, sem liquidação ≥ 3 meses, residual ≤ R$ 1.000 ou ≤ 5%).
"""

from __future__ import annotations

import unittest

import pandas as pd

from src.candidatos_anulacao import (
    COLUNA_INDICACAO_PRINCIPAL,
    COLUNA_INDICACOES,
    COLUNA_MESES_SEM_LIQUIDACAO,
    NUNCA_LIQUIDADA,
    SALDO_NEGATIVO,
    SALDO_RESIDUAL,
    SEM_INDICACAO,
    SEM_LIQUIDACAO_RECENTE,
    com_indicacoes,
    contagem_por_indicacao,
    descrever_parametros,
    meses_sem_liquidacao_por_ne,
    parametros_padrao,
)

ANO, MES = 2026, 9


def _linhas() -> pd.DataFrame:
    """Linhas de item de execução (liquidado por mês) e de empenho (só para conferir que não contam)."""

    return pd.DataFrame(
        [
            # A: liquidou em mar e mai -> último mai -> 9 - 5 = 4 meses
            ("A", 2026, 202603, "item_execucao", 100.0), ("A", 2026, 202605, "item_execucao", 50.0),
            # B: liquidou em ago -> 1 mês
            ("B", 2026, 202608, "item_execucao", 10.0),
            # C: zero em set não conta; último com valor em fev -> 7
            ("C", 2026, 202602, "item_execucao", 30.0), ("C", 2026, 202609, "item_execucao", 0.0),
            # D: exercício anterior -> fora
            ("D", 2025, 202511, "item_execucao", 80.0),
            # E: só linha de empenho (sem item de execução) -> fora
            ("E", 2026, 202609, "empenho", None),
            # F: estorno em jul (negativo, diferente de zero) conta -> 2
            ("F", 2026, 202607, "item_execucao", -20.0),
        ],
        columns=["ne_ccor", "ano", "ano_mes", "tipo_linha", "liquidada"],
    )


class MesesSemLiquidacaoTests(unittest.TestCase):
    def test_calculado_a_mao(self) -> None:
        meses = meses_sem_liquidacao_por_ne(_linhas(), ANO, MES)
        self.assertEqual(meses.to_dict(), {"A": 4, "B": 1, "C": 7, "F": 2})

    def test_base_sem_colunas_devolve_vazio(self) -> None:
        self.assertTrue(meses_sem_liquidacao_por_ne(pd.DataFrame({"ne_ccor": ["A"]}), ANO, MES).empty)


class IndicacoesTests(unittest.TestCase):
    def setUp(self) -> None:
        # ne, empenhada, liquidada, saldo, idade
        linhas = [
            ("A", 10_000.0, 150.0, 9_850.0, 6),     # liquidou, última há 4 meses -> sem liquidação recente
            ("B", 10_000.0, 9_600.0, 400.0, 6),     # liquidou há 1 mês, saldo 400 -> residual (R$)
            ("G", 100_000.0, 96_000.0, 4_000.0, 6),  # sem linhas de liquidação aqui; 4% -> residual (%)
            ("H", 5_000.0, None, 5_000.0, 4),       # nada liquidado, 4 meses -> nunca liquidada
            ("I", 5_000.0, 0.0, 5_000.0, 2),        # nada liquidado, mas só 2 meses -> nada
            ("J", 5_000.0, None, 5_000.0, None),    # exercício anterior (idade nula) -> nada
            ("K", 300.0, 350.0, -50.0, 6),          # saldo negativo
            ("L", 365.0, 365.0, -1.5e-14, 6),       # resíduo de ponto flutuante: saldo zero, nada
            ("M", 2_000.0, 1_000.0, 1_000.0, 6),    # residual no limite (≤ R$ 1.000)
            ("N", None, None, None, None),          # tudo nulo -> nada
        ]
        self.visivel = pd.DataFrame(linhas, columns=["ne_ccor", "empenhada", "liquidada", "saldo", "idade_meses"])
        empenhado = self.visivel["empenhada"].where(self.visivel["empenhada"].fillna(0) != 0)
        self.visivel["percentual_saldo"] = self.visivel["saldo"] / empenhado * 100
        self.visivel["idade_meses"] = self.visivel["idade_meses"].astype("Int64")
        self.resultado = com_indicacoes(self.visivel, _linhas(), ANO, MES, parametros_padrao()).set_index("ne_ccor")

    def _indicacoes(self, ne: str) -> object:
        valor = self.resultado.loc[ne, COLUNA_INDICACOES]
        return None if pd.isna(valor) else valor

    def test_cada_regra_calculada_a_mao(self) -> None:
        self.assertEqual(self._indicacoes("A"), SEM_LIQUIDACAO_RECENTE)
        self.assertEqual(self._indicacoes("B"), SALDO_RESIDUAL)
        self.assertEqual(self._indicacoes("G"), SALDO_RESIDUAL)
        self.assertEqual(self._indicacoes("H"), NUNCA_LIQUIDADA)
        self.assertEqual(self._indicacoes("K"), SALDO_NEGATIVO)
        self.assertEqual(self._indicacoes("M"), SALDO_RESIDUAL)

    def test_nulo_e_residuo_de_ponto_flutuante_nao_disparam(self) -> None:
        for ne in ("I", "J", "L", "N"):
            self.assertIsNone(self._indicacoes(ne), ne)
            self.assertEqual(self.resultado.loc[ne, COLUNA_INDICACAO_PRINCIPAL], SEM_INDICACAO)

    def test_varias_indicacoes_e_principal_pela_prioridade(self) -> None:
        # A com saldo residual também: limite em R$ 10 mil -> as duas, principal "sem liquidação"
        parametros = {**parametros_padrao(), "anul_residual_rs": 10_000.0}
        resultado = com_indicacoes(self.visivel, _linhas(), ANO, MES, parametros).set_index("ne_ccor")
        self.assertEqual(resultado.loc["A", COLUNA_INDICACOES], f"{SEM_LIQUIDACAO_RECENTE}; {SALDO_RESIDUAL}")
        self.assertEqual(resultado.loc["A", COLUNA_INDICACAO_PRINCIPAL], SEM_LIQUIDACAO_RECENTE)

    def test_limites_ajustaveis(self) -> None:
        parametros = {**parametros_padrao(), "anul_nunca_meses": 2, "anul_sem_liq_meses": 5}
        resultado = com_indicacoes(self.visivel, _linhas(), ANO, MES, parametros).set_index("ne_ccor")
        self.assertEqual(resultado.loc["I", COLUNA_INDICACOES], NUNCA_LIQUIDADA)  # agora 2 meses bastam
        self.assertTrue(pd.isna(resultado.loc["A", COLUNA_INDICACOES]))  # 4 meses < 5

    def test_nao_altera_nem_descarta_linhas(self) -> None:
        original = self.visivel.copy()
        resultado = com_indicacoes(self.visivel, _linhas(), ANO, MES, parametros_padrao())
        pd.testing.assert_frame_equal(self.visivel, original)
        self.assertEqual(len(resultado), len(original))
        pd.testing.assert_series_equal(resultado["saldo"], original["saldo"])
        self.assertEqual(self.resultado.loc["A", COLUNA_MESES_SEM_LIQUIDACAO], 4)
        self.assertTrue(pd.isna(self.resultado.loc["H", COLUNA_MESES_SEM_LIQUIDACAO]))

    def test_contagem_por_indicacao(self) -> None:
        contagem = {c["nome"]: (c["n"], c["saldo"]) for c in contagem_por_indicacao(self.resultado.reset_index())}
        self.assertEqual(contagem[SALDO_RESIDUAL], (3, 400.0 + 4_000.0 + 1_000.0))
        self.assertEqual(contagem[NUNCA_LIQUIDADA], (1, 5_000.0))
        self.assertEqual(contagem[SALDO_NEGATIVO], (1, -50.0))

    def test_descricao_dos_parametros(self) -> None:
        regras = dict(descrever_parametros(parametros_padrao()))
        self.assertIn("R$ 1.000,00", regras[SALDO_RESIDUAL])
        self.assertIn("5%", regras[SALDO_RESIDUAL])
        self.assertIn("3 meses", regras[NUNCA_LIQUIDADA])


if __name__ == "__main__":
    unittest.main()
