"""Testes de `src/liquidacao_consumo.py` (13/10/2026): NE com competência em exercício posterior passa a ser
medida pelo mês do lançamento. Dados sintéticos; valores calculados à mão."""

from __future__ import annotations

import unittest

import pandas as pd

from src.liquidacao_consumo import competencia_pelo_consumo
from src.relatorio_necessidade_empenho import necessidade_por_ne
from src.relatorio_projecao_execucao import montar_relatorio

NE_ANTECIPADA = "2026NE000551"
NE_NORMAL = "2026NE000001"


def _competencia() -> pd.DataFrame:
    # NE antecipada: 12 parcelas de 100 de out/2026 a set/2027 (1.200); NE normal: jan–jul/2026 a 900
    meses = [202610, 202611, 202612] + [202701 + i for i in range(9)]
    return pd.DataFrame({
        "ne_curta": [NE_ANTECIPADA] * 12 + [NE_NORMAL] * 7,
        "ano_mes": meses + [202601 + i for i in range(7)],
        "valor": [100.0] * 12 + [900.0] * 7,
    })


def _lancamento(liquidada_antecipada: float = 1200.0) -> pd.DataFrame:
    return pd.DataFrame({
        "ne_curta": [NE_ANTECIPADA, NE_ANTECIPADA, NE_NORMAL],
        "ano_mes": [202609, 202610, 202601],
        "liquidada": [0.0, liquidada_antecipada, 900.0],
    })


class TestCompetenciaPeloConsumo(unittest.TestCase):
    def test_ne_com_competencia_futura_vai_para_o_mes_do_lancamento(self):
        resultado = competencia_pelo_consumo(_competencia(), _lancamento(), 2026)
        antecipada = resultado.dados[resultado.dados["ne_curta"] == NE_ANTECIPADA]
        self.assertEqual(antecipada["ano_mes"].tolist(), [202610])
        self.assertEqual(antecipada["valor"].tolist(), [1200.0])
        self.assertEqual(resultado.nes_trocadas, [NE_ANTECIPADA])
        self.assertEqual(resultado.divergencias, {})

    def test_ne_normal_e_demais_colunas_ficam_como_estao(self):
        entrada = _competencia()
        resultado = competencia_pelo_consumo(entrada, _lancamento(), 2026)
        normal = resultado.dados[resultado.dados["ne_curta"] == NE_NORMAL]
        pd.testing.assert_frame_equal(
            normal.reset_index(drop=True), entrada[entrada["ne_curta"] == NE_NORMAL].reset_index(drop=True)
        )
        self.assertEqual(len(entrada), 19)  # entrada não é alterada

    def test_mes_com_zero_no_lancamento_nao_vira_linha(self):
        resultado = competencia_pelo_consumo(_competencia(), _lancamento(), 2026)
        self.assertNotIn(202609, resultado.dados.loc[resultado.dados["ne_curta"] == NE_ANTECIPADA, "ano_mes"].tolist())

    def test_sem_liquidacao_no_lancamento_mantem_competencia_e_sinaliza(self):
        sem_lancamento = _lancamento().iloc[2:]  # só a NE normal
        resultado = competencia_pelo_consumo(_competencia(), sem_lancamento, 2026)
        self.assertEqual(resultado.nes_trocadas, [])
        self.assertEqual(resultado.nes_sem_lancamento, [NE_ANTECIPADA])
        self.assertEqual(len(resultado.dados), 19)
        self.assertTrue(any(NE_ANTECIPADA in aviso for aviso in resultado.avisos()))

    def test_total_divergente_mantem_competencia_e_avisa(self):
        # lançado 1.000 ≠ competência 1.200: a Execução Mensal não cobre tudo → nada é trocado nem descartado
        resultado = competencia_pelo_consumo(_competencia(), _lancamento(1000.0), 2026)
        self.assertEqual(resultado.nes_trocadas, [])
        self.assertEqual(resultado.divergencias, {NE_ANTECIPADA: (1200.0, 1000.0)})
        self.assertEqual(len(resultado.dados), 19)
        self.assertEqual(resultado.dados.loc[resultado.dados["ne_curta"] == NE_ANTECIPADA, "valor"].sum(), 1200.0)
        self.assertTrue(any(NE_ANTECIPADA in aviso for aviso in resultado.avisos()))

    def test_sem_competencia_futura_nada_muda(self):
        resultado = competencia_pelo_consumo(_competencia(), _lancamento(), 2027)
        self.assertEqual(resultado.nes_trocadas, [])
        self.assertEqual(len(resultado.dados), 19)

    def test_bases_indisponiveis(self):
        self.assertIsNone(competencia_pelo_consumo(None, _lancamento(), 2026))
        vazio = competencia_pelo_consumo(_competencia().iloc[0:0], _lancamento(), 2026)
        self.assertTrue(vazio.dados.empty)
        sem_tempo = competencia_pelo_consumo(_competencia(), None, 2026)
        self.assertEqual(sem_tempo.nes_sem_lancamento, [NE_ANTECIPADA])


class TestEfeitoNaProjecaoPelaExecucao(unittest.TestCase):
    """Cenário da 2026NE000551: contrato cadastrado como UM mês (despesa_mensal = valor anual), empenho
    liquidado todo em outubro, competência espalhada em 12 parcelas. Mês de referência = 10."""

    def _relatorio(self, competencia: pd.DataFrame):
        filtrado = pd.DataFrame([{
            "ne_curta": NE_ANTECIPADA, "fornecedor": "F", "contrato_numero": "19/2025",
            "despesa_mensal": 1200.0, "meses_no_ano": 1.0, "inicio_execucao_mes": 10.0,
            "inicio_execucao_efetivo": 10.0, "inicio_execucao_data": pd.NaT,
            "valor_empenhado": 1200.0, "valor_empenhado_execucao": 1200.0,
            "valor_empenhado_planilha_total_ne": 1200.0, "valor_liquidado_execucao": 1200.0,
            "liquidado_via_competencia": True, "saldo_execucao": 0.0, "saldo_colado_planilha": 0.0,
            "status_contrato": "ATIVO", "vigencia_fim": pd.NaT,
        }])
        por_ne, sem_ne = necessidade_por_ne(filtrado, None, 2026)
        return montar_relatorio(por_ne, sem_ne, competencia, 2026, 10).linhas.iloc[0]

    def test_pela_competencia_inventa_necessidade(self):
        competencia = _competencia()
        competencia = competencia[competencia["ne_curta"] == NE_ANTECIPADA]
        self.assertAlmostEqual(self._relatorio(competencia)["necessidade_execucao"], 1100.0)  # 1.200 − 100

    def test_pelo_consumo_nao_ha_necessidade(self):
        competencia = _competencia()
        competencia = competencia[competencia["ne_curta"] == NE_ANTECIPADA]
        ajustada = competencia_pelo_consumo(competencia, _lancamento(), 2026).dados
        linha = self._relatorio(ajustada)
        self.assertAlmostEqual(linha["projetado_execucao"], 0.0)
        self.assertAlmostEqual(linha["necessidade_execucao"], 0.0)


if __name__ == "__main__":
    unittest.main()
