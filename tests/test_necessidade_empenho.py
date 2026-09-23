"""Testes de src/necessidade_empenho.py."""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.necessidade_empenho import calcular_necessidade_empenho, necessidade_ate_mes_vigente


class TestCalcularNecessidadeEmpenho(unittest.TestCase):
    def test_meses_a_empenhar_e_empenhado_menos_liquidado(self):
        meses, valor = calcular_necessidade_empenho(pd.Series([8.0]), pd.Series([5.0]), pd.Series([1000.0]))
        self.assertAlmostEqual(meses.iloc[0], 3.0)
        self.assertAlmostEqual(valor.iloc[0], 3000.0)


class TestNecessidadeAteMesVigente(unittest.TestCase):
    def test_exemplo_do_pedido_despesa_120_mil_empenhado_70_mil_outubro(self):
        # despesa anual 120 mil -> mensal 10 mil; já empenhado 70 mil; início em janeiro (mês
        # 1); "hoje" outubro (mês 10) -> deveria estar empenhado 10 mil x 10 = 100 mil ->
        # sugestão 100 mil - 70 mil = 30 mil (exemplo exato do pedido).
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([70_000.0]), pd.Series([1]), 2026, hoje=date(2026, 10, 15),
        )
        self.assertAlmostEqual(valor.iloc[0], 30_000.0)
        self.assertAlmostEqual(meses.iloc[0], 3.0)

    def test_ja_empenhado_acima_do_alvo_nao_fica_negativo(self):
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([150_000.0]), pd.Series([1]), 2026, hoje=date(2026, 10, 15),
        )
        self.assertEqual(valor.iloc[0], 0.0)
        self.assertEqual(meses.iloc[0], 0.0)

    def test_inicio_no_mes_vigente_conta_como_1_mes(self):
        # início em outubro, hoje também outubro -> só 1 mês decorrido (contagem inclusiva).
        meses, _ = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([0.0]), pd.Series([10]), 2026, hoje=date(2026, 10, 15),
        )
        self.assertAlmostEqual(meses.iloc[0], 1.0)

    def test_inicio_desconhecido_gera_nan(self):
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([70_000.0]), pd.Series([pd.NA], dtype="Int64"), 2026,
            hoje=date(2026, 10, 15),
        )
        self.assertTrue(pd.isna(meses.iloc[0]))
        self.assertTrue(pd.isna(valor.iloc[0]))

    # ---------------------------------------------------------------- virada de exercício
    # Reproduz o bug real: um cadastro de 2026 ainda não duplicado para 2027 (duplicação é
    # manual, ver src/cadastro_por_exercicio.py) continua sendo exibido em janeiro/2027. Sem
    # `ano_referencia`, `hoje.month (1) - inicio_execucao_mes (10) + 1 = -8`, sempre limitado a
    # zero — subestimava a sugestão silenciosamente. Com `ano_referencia`, o exercício 2026 já
    # encerrado usa dezembro como mês vigente, não o mês real de hoje (que é de outro ano).

    def test_exercicio_encerrado_usa_dezembro_como_mes_vigente(self):
        # início em outubro/2026, "hoje" já é janeiro/2027, mas ano_referencia continua 2026
        # (cadastro do ano anterior, ainda não duplicado) -> meses decorridos = out+nov+dez = 3,
        # igual a se "hoje" ainda fosse dezembro/2026 (mesmo resultado do teste de dezembro
        # abaixo) -- nunca o -8/0 que o cálculo ingênuo (só por número de mês) daria.
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([0.0]), pd.Series([10]), 2026, hoje=date(2027, 1, 15),
        )
        self.assertAlmostEqual(meses.iloc[0], 3.0)
        self.assertAlmostEqual(valor.iloc[0], 30_000.0)

    def test_exercicio_encerrado_bate_com_dezembro_do_proprio_exercicio(self):
        # mesmo resultado do teste acima, calculado direto com "hoje" = dezembro/2026 (o "mês
        # vigente" de um exercício encerrado tem que ser equivalente a olhar pra ele em
        # dezembro do próprio ano, não pra um mês de outro exercício).
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([0.0]), pd.Series([10]), 2026, hoje=date(2026, 12, 20),
        )
        self.assertAlmostEqual(meses.iloc[0], 3.0)
        self.assertAlmostEqual(valor.iloc[0], 30_000.0)

    def test_exercicio_ainda_nao_comecou_nao_sugere_nada(self):
        # caso defensivo (não deve acontecer na prática): olhar um exercício futuro a partir de
        # hoje não pode sugerir nada, nunca um número negativo.
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([0.0]), pd.Series([1]), 2027, hoje=date(2026, 6, 1),
        )
        self.assertEqual(meses.iloc[0], 0.0)
        self.assertEqual(valor.iloc[0], 0.0)

    def test_exercicio_corrente_nao_muda_comportamento_de_antes(self):
        # quando ano_referencia == hoje.year, o comportamento é idêntico ao de antes da
        # correção (mesmo cenário do exemplo do pedido, reafirmado explicitamente aqui).
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([70_000.0]), pd.Series([1]), 2026, hoje=date(2026, 10, 15),
        )
        self.assertAlmostEqual(meses.iloc[0], 3.0)
        self.assertAlmostEqual(valor.iloc[0], 30_000.0)


if __name__ == "__main__":
    unittest.main()
