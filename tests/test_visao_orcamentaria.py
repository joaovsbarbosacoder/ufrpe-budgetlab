"""Testes da agregação segura entre Dotação e Execução."""

import unittest

import pandas as pd

from src.dotacao_analysis import ValidatedDotacaoDataset
from src.execucao_analysis import ValidatedExecucaoDataset
from src.tesouro_dotacao import transform_dotacao_sheet
from src.tesouro_execucao import transform_execucao_sheet
from src.visao_orcamentaria import (
    apply_common_filters,
    build_common_filter_options,
    build_memorias_por_origem,
    build_visao_orcamentaria,
)
from tests.test_tesouro_dotacao import make_dotacao_raw
from tests.test_tesouro_execucao import make_execucao_raw


COMMON_VALUES = {
    "iduso_codigo": "0",
    "resultado_primario_codigo": "1",
    "acao_codigo": "0181",
    "plano_orcamentario_codigo": "0000",
    "grupo_despesa_codigo": "1",
    "fonte_recursos_detalhada_codigo": "1000000000",
    "ptres_codigo": "169886",
}


class VisaoOrcamentariaTests(unittest.TestCase):
    def setUp(self) -> None:
        dotacao = transform_dotacao_sheet(make_dotacao_raw(), "dotacao.xlsx", "2024").normalized_data.copy(deep=True)
        execucao = transform_execucao_sheet(make_execucao_raw(), "execucao.xlsx", "Execução").normalized_data.copy(deep=True)
        for column, value in COMMON_VALUES.items():
            dotacao[column] = value
            execucao[column] = value
        self.dotacao = ValidatedDotacaoDataset("dotacao.xlsx", "dotacao", ["2024"], dotacao, "Aprovada")
        self.execucao = ValidatedExecucaoDataset("execucao.xlsx", "execucao", ["Execução"], execucao, "Aprovada")

    def test_aggregates_indicators_directly_without_double_counting(self) -> None:
        result = build_visao_orcamentaria(self.dotacao, self.execucao)
        indicators = result.indicadores.set_index("indicador_codigo")
        expected_dotacao = self.dotacao.normalized_data.loc[
            self.dotacao.normalized_data["item_informacao_codigo"] == "dotacao_atualizada",
            "valor_movimento_liquido",
        ].sum(min_count=1)
        self.assertEqual(indicators.loc["dotacao_atualizada", "valor_movimento_liquido"], expected_dotacao)
        for metric in ["despesa_empenhada", "despesa_liquidada", "despesa_paga"]:
            expected = self.execucao.normalized_data.loc[
                self.execucao.normalized_data["metrica_execucao_codigo"] == metric,
                "valor_movimento_liquido",
            ].sum(min_count=1)
            self.assertEqual(indicators.loc[metric, "valor_movimento_liquido"], expected)
        self.assertEqual(len(result.dotacao_filtrada), len(self.dotacao.normalized_data))
        self.assertEqual(len(result.execucao_filtrada), len(self.execucao.normalized_data))

    def test_common_filters_are_applied_separately_to_both_sources(self) -> None:
        self.dotacao.normalized_data.loc[0, "acao_codigo"] = "9999"
        self.execucao.normalized_data.loc[0, "acao_codigo"] = "9999"
        dotacao, execucao = apply_common_filters(
            self.dotacao.normalized_data,
            self.execucao.normalized_data,
            {"acao_governo": ["9999"]},
        )
        self.assertEqual(len(dotacao), 1)
        self.assertEqual(len(execucao), 1)
        self.assertEqual(dotacao.iloc[0]["acao_codigo"], "9999")
        self.assertEqual(execucao.iloc[0]["acao_codigo"], "9999")

    def test_classification_existing_only_in_one_base_does_not_create_rows_in_other(self) -> None:
        self.dotacao.normalized_data.loc[0, "ptres_codigo"] = "SOMENTE_DOTACAO"
        options = build_common_filter_options(self.dotacao.normalized_data, self.execucao.normalized_data)
        self.assertIn("SOMENTE_DOTACAO", options["ptres"])
        result = build_visao_orcamentaria(self.dotacao, self.execucao, {"ptres": ["SOMENTE_DOTACAO"]})
        self.assertEqual(len(result.dotacao_filtrada), 1)
        self.assertTrue(result.execucao_filtrada.empty)
        self.assertTrue(result.indicadores[result.indicadores["origem"] == "execucao"]["quantidade_registros"].eq(0).all())

    def test_memories_preserve_traceability_by_source(self) -> None:
        memories = build_memorias_por_origem(build_visao_orcamentaria(self.dotacao, self.execucao))
        self.assertEqual(set(memories), {"dotacao", "execucao"})
        self.assertEqual(set(memories["dotacao"]["arquivo_origem"]), {"dotacao.xlsx"})
        self.assertEqual(set(memories["execucao"]["arquivo_origem"]), {"execucao.xlsx"})
        self.assertFalse(memories["dotacao"].empty)
        self.assertFalse(memories["execucao"].empty)

    def test_inputs_are_not_mutated(self) -> None:
        original_dotacao = self.dotacao.normalized_data.copy(deep=True)
        original_execucao = self.execucao.normalized_data.copy(deep=True)
        build_visao_orcamentaria(self.dotacao, self.execucao, {"iduso": ["0"]})
        pd.testing.assert_frame_equal(self.dotacao.normalized_data, original_dotacao)
        pd.testing.assert_frame_equal(self.execucao.normalized_data, original_execucao)


if __name__ == "__main__":
    unittest.main()
