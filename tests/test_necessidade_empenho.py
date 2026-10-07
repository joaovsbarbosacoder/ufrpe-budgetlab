"""Testes de src/necessidade_empenho.py."""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.necessidade_empenho import (
    calcular_necessidade_empenho,
    janela_de_execucao,
    meses_vigentes_no_exercicio,
    necessidade_ate_dezembro,
    necessidade_ate_mes_vigente,
)


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

    # ---------------------------------------------------------------- teto de meses_no_ano
    # Reproduz o bug real reportado: bolsa "parcela única" (AUXÍLIO BEXT) tem `meses_no_ano=1`
    # — só é paga uma vez no ano. Sem o teto, o cálculo assumia pagamento em TODO mês desde o
    # início da execução, sugerindo reforço mesmo já com a única parcela paga.

    def test_meses_no_ano_limita_parcela_unica_ja_paga_por_completo(self):
        # início em março, "hoje" setembro -> 7 meses decorridos sem o teto; com
        # meses_no_ano=1, nunca passa de 1 -- e como já foi empenhado o equivalente a 1 mês
        # (70.000 / 70.000), a sugestão fica em zero (caso real da BEXT).
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([70_000.0]), pd.Series([70_000.0]), pd.Series([3]), 2026,
            hoje=date(2026, 9, 23), meses_no_ano=pd.Series([1]),
        )
        self.assertEqual(meses.iloc[0], 0.0)
        self.assertEqual(valor.iloc[0], 0.0)

    def test_meses_no_ano_limita_mesmo_sem_nenhum_pagamento_ainda(self):
        # mesma bolsa parcela única, mas AINDA não empenhada -- teto limita a sugestão a 1 mês
        # (a própria parcela única), nunca aos 7 meses que o calendário sozinho sugeriria.
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([70_000.0]), pd.Series([0.0]), pd.Series([3]), 2026,
            hoje=date(2026, 9, 23), meses_no_ano=pd.Series([1]),
        )
        self.assertEqual(meses.iloc[0], 1.0)
        self.assertEqual(valor.iloc[0], 70_000.0)

    def test_meses_no_ano_nao_afeta_bolsa_dentro_do_teto(self):
        # meses_no_ano=12 (padrão) nunca é o fator limitante -- mesmo resultado do teste do
        # exemplo do pedido (120 mil/ano, 70 mil empenhado, início janeiro, hoje outubro).
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([70_000.0]), pd.Series([1]), 2026,
            hoje=date(2026, 10, 15), meses_no_ano=pd.Series([12]),
        )
        self.assertAlmostEqual(meses.iloc[0], 3.0)
        self.assertAlmostEqual(valor.iloc[0], 30_000.0)

    def test_meses_no_ano_ausente_mantem_comportamento_de_antes(self):
        # None (default, usado por Contratos Contínuos -- sem esse conceito) não muda nada.
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([70_000.0]), pd.Series([70_000.0]), pd.Series([3]), 2026, hoje=date(2026, 9, 23),
        )
        self.assertAlmostEqual(meses.iloc[0], 6.0)
        self.assertAlmostEqual(valor.iloc[0], 420_000.0)


class TestFracaoDoPrimeiroMes(unittest.TestCase):
    """Início da execução por data (02/10/2026): o mês de início deixa de contar inteiro. `hoje` =
    15/10 (mês vigente 10), exercício 2026."""

    HOJE = date(2026, 10, 15)

    def _meses(self, inicio: int, fracao: float | None, empenhado: float = 0.0, meses_no_ano: float | None = None):
        meses, _ = necessidade_ate_mes_vigente(
            pd.Series([1000.0]), pd.Series([empenhado]), pd.Series([inicio]), 2026, hoje=self.HOJE,
            meses_no_ano=None if meses_no_ano is None else pd.Series([meses_no_ano]),
            fracao_primeiro_mes=None if fracao is None else pd.Series([fracao]),
        )
        return meses.iloc[0]

    def test_sem_fracao_o_mes_de_inicio_conta_cheio(self):
        self.assertAlmostEqual(self._meses(7, None), 4.0)  # jul, ago, set, out
        self.assertAlmostEqual(self._meses(7, 1.0), 4.0)  # fração 1 = igual

    def test_fracao_desconta_a_parte_nao_executada_do_primeiro_mes(self):
        # começa 16/07 (16 de 31 dias): 4 − (1 − 16/31) = 3 + 16/31
        self.assertAlmostEqual(self._meses(7, 16 / 31), 3 + 16 / 31)

    def test_inicio_depois_do_mes_vigente_nao_vira_negativo(self):
        self.assertEqual(self._meses(11, 0.5), 0.0)  # início em novembro, hoje outubro

    def test_teto_de_meses_no_ano_vale_depois_da_fracao(self):
        # janeiro pela metade: 10 − 0,5 = 9,5 meses decorridos, mas o contrato só paga 6 no ano
        self.assertAlmostEqual(self._meses(1, 0.5, meses_no_ano=6), 6.0)

    def test_desconta_o_empenhado_depois_da_fracao(self):
        self.assertAlmostEqual(self._meses(7, 16 / 31, empenhado=2000.0), 1 + 16 / 31)  # 3,516 − 2 meses empenhados



class TestNecessidadeAteDezembro(unittest.TestCase):
    """Necessidade até Dezembro de Bolsas e Auxílios (05/10/2026): o que falta empenhar para cobrir o
    exercício — `valor_mensal × meses restantes`, SEM subtrair o saldo, que já está no empenhado."""

    def test_valores_a_mao(self):
        mensal = pd.Series([1000.0, 1000.0, 1000.0, 70_000.0, 0.0])
        empenhado = pd.Series([8000.0, 12_000.0, 15_000.0, 70_000.0, 500.0])
        meses_no_ano = pd.Series([12.0, 12.0, 12.0, 1.0, 12.0])
        restantes, necessidade = necessidade_ate_dezembro(mensal, empenhado, meses_no_ano)
        # 8 meses empenhados => 4 restantes => 4000; 12 empenhados => 0; empenhou além do ano => 0 (nunca
        # negativo); parcela única já empenhada (meses_no_ano=1) => 0; despesa mensal 0 => 0
        self.assertEqual(restantes.tolist(), [4.0, 0.0, 0.0, 0.0, 12.0])
        self.assertEqual(necessidade.tolist(), [4000.0, 0.0, 0.0, 0.0, 0.0])

    def test_saldo_nao_entra_na_conta_caso_da_ne_88(self):
        # despesa 927.298,47, empenhado 7.418.387,76 (8 meses), 12 meses no ano: faltam 4 meses =
        # 3.709.193,88. A regra anterior ainda subtraía o saldo (887.964,05), dando 2.821.229,83.
        restantes, necessidade = necessidade_ate_dezembro(
            pd.Series([927_298.47]), pd.Series([7_418_387.76]), pd.Series([12.0])
        )
        self.assertAlmostEqual(restantes.iloc[0], 4.0, places=6)
        self.assertAlmostEqual(necessidade.iloc[0], 3_709_193.88, places=2)

    def test_meses_no_ano_ausente_vira_12(self):
        restantes, necessidade = necessidade_ate_dezembro(
            pd.Series([100.0]), pd.Series([600.0]), pd.Series([float("nan")])
        )
        self.assertEqual((restantes.iloc[0], necessidade.iloc[0]), (6.0, 600.0))

    def test_empenhado_nulo_conta_como_nada_empenhado(self):
        restantes, necessidade = necessidade_ate_dezembro(
            pd.Series([100.0]), pd.Series([float("nan")]), pd.Series([12.0])
        )
        self.assertEqual((restantes.iloc[0], necessidade.iloc[0]), (12.0, 1200.0))

    def test_nao_altera_as_entradas(self):
        mensal, empenhado, meses = pd.Series([100.0, 0.0]), pd.Series([300.0, 5.0]), pd.Series([12.0, float("nan")])
        copias = [serie.copy(deep=True) for serie in (mensal, empenhado, meses)]
        necessidade_ate_dezembro(mensal, empenhado, meses)
        for original, copia in zip((mensal, empenhado, meses), copias):
            pd.testing.assert_series_equal(original, copia)


class TestJanelaDeExecucao(unittest.TestCase):
    """Primeiro e último dia (inclusive) em que o contrato está em execução no exercício —
    base única da série mensal dos aditivos (06/10/2026). `None` = nenhum dia."""

    def test_janela(self):
        T = pd.Timestamp
        casos = [
            (("ATIVO", pd.NaT, 2026, None, None), (T("2026-01-01"), T("2026-12-31"))),
            (("ATIVO", T("2026-11-15"), 2026, T("2026-07-16"), None), (T("2026-07-16"), T("2026-11-15"))),
            (("SUSPENSO", pd.NaT, 2026, None, T("2026-10-01")), (T("2026-01-01"), T("2026-09-30"))),
            (("SUSPENSO", T("2026-06-30"), 2026, None, T("2026-10-01")), (T("2026-01-01"), T("2026-06-30"))),
            (("SUSPENSO", pd.NaT, 2026, None, None), None),
            (("SUSPENSO", pd.NaT, 2026, None, T("2026-01-01")), None),
            (("VENCIDO", pd.NaT, 2026, None, None), None),
            (("VENCIDO", T("2027-03-01"), 2026, None, None), (T("2026-01-01"), T("2026-12-31"))),
            (("ATIVO", T("2025-12-31"), 2026, None, None), None),
            (("ATIVO", pd.NaT, 2026, T("2027-01-01"), None), None),
            (("ATIVO", pd.NaT, 2026, T("2025-06-01"), None), (T("2026-01-01"), T("2026-12-31"))),
            (("ATIVO", T("2026-06-30"), 2026, T("2026-08-01"), None), None),
        ]
        for argumentos, esperado in casos:
            self.assertEqual(janela_de_execucao(*argumentos), esperado, msg=str(argumentos))

    def test_meses_vigentes_mantem_a_semantica_do_none(self):
        T = pd.Timestamp
        # fim em 31/12 do próprio exercício é um limite declarado: 12,0 (não None)
        self.assertEqual(meses_vigentes_no_exercicio("ATIVO", T("2026-12-31"), 2026), 12.0)
        self.assertIsNone(meses_vigentes_no_exercicio("ATIVO", T("2027-03-01"), 2026))
        self.assertIsNone(meses_vigentes_no_exercicio("ATIVO", pd.NaT, 2026, T("2026-01-01")))
        self.assertAlmostEqual(meses_vigentes_no_exercicio("ATIVO", T("2026-11-15"), 2026, T("2026-07-16")), 3 + 15 / 30 + 16 / 31)


class TestNecessidadeAteMesVigenteComPesos(unittest.TestCase):
    def test_pesos_mensais_substituem_os_meses_decorridos(self):
        # valor vigente 3.300; série 3.000 (jan–jun) e 3.300 (jul–dez) → pesos 3.000/3.300 e 1;
        # jan–out = 6 × 3.000/3.300 + 4 = 9,4545… meses; empenhado 18.000 = 5,4545… meses → 4,0
        pesos = [3_000 / 3_300] * 6 + [1.0] * 6
        meses, valor = necessidade_ate_mes_vigente(
            pd.Series([3_300.0]), pd.Series([18_000.0]), pd.Series([1]), 2026, hoje=date(2026, 10, 6),
            pesos_mensais=pd.Series([pesos], dtype=object),
        )
        self.assertAlmostEqual(meses.iloc[0], 4.0)
        self.assertAlmostEqual(valor.iloc[0], 13_200.0)

    def test_pesos_nulos_mantem_a_conta_antiga(self):
        meses, _ = necessidade_ate_mes_vigente(
            pd.Series([10_000.0]), pd.Series([70_000.0]), pd.Series([1]), 2026, hoje=date(2026, 10, 15),
            pesos_mensais=pd.Series([None], dtype=object),
        )
        self.assertAlmostEqual(meses.iloc[0], 3.0)

    def test_primeiro_mes_proporcional_aplica_a_fracao_ao_peso_do_mes(self):
        # início em julho com metade do mês: jul 0,5 + ago + set + out = 3,5 meses (pesos 1)
        meses, _ = necessidade_ate_mes_vigente(
            pd.Series([1_000.0]), pd.Series([0.0]), pd.Series([7]), 2026, hoje=date(2026, 10, 6),
            fracao_primeiro_mes=pd.Series([0.5]), pesos_mensais=pd.Series([[1.0] * 12], dtype=object),
        )
        self.assertAlmostEqual(meses.iloc[0], 3.5)

    def test_peso_nulo_no_intervalo_gera_nulo(self):
        pesos = [float("nan")] * 12
        meses, _ = necessidade_ate_mes_vigente(
            pd.Series([0.0]), pd.Series([100.0]), pd.Series([1]), 2026, hoje=date(2026, 10, 6),
            pesos_mensais=pd.Series([pesos], dtype=object),
        )
        self.assertTrue(pd.isna(meses.iloc[0]))


if __name__ == "__main__":
    unittest.main()
