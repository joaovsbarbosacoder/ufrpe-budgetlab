"""Contratos estruturais da normalização de Execução da Despesa."""

import unittest

import pandas as pd

from src.tesouro_execucao import (
    EXECUCAO_OUTPUT_COLUMNS,
    recognize_execucao_base,
    transform_execucao_sheet,
)


HEADERS = [
    "Iduso", None, "Resultado Primário Lei", None,
    "Categoria Econômica Despesa", None, "Ação Governo", None,
    "Elemento Despesa", None, "Fonte Recursos Detalhada", None,
    "Grupo Despesa", None, "Natureza Despesa", None,
    "Natureza Despesa Detalhada", None, "Subitem", None, "PI", None,
    "Plano Orçamentário", None, None, "PTRES", "UG Executora", None,
    "UG Responsável", None, "UGR - Gestão", None, "NE CCor",
    "NE CCor - Favorecido", "Item Informação",
    "DESPESAS EMPENHADAS (CONTROLE EMPENHO)",
    "DESPESAS LIQUIDADAS (CONTROLE EMPENHO)",
    "DESPESAS PAGAS (CONTROLE EMPENHO)",
]


def make_execucao_raw(row_count: int = 3) -> pd.DataFrame:
    """Fixture tabular equivalente à assinatura real, sem regras contábeis."""

    rows = [HEADERS, [None] * 34 + ["Ano Lançamento"] + ["Movim. Líquido - R$ (Item Informação)"] * 3]
    for index in range(row_count):
        empenhada = 0.0 if index == 0 else float(index * 100)
        liquidada = pd.NA if index == 0 else (-10.0 if index == 1 else float(index * 80))
        paga = pd.NA if index == 0 else (0.0 if index == 1 else float(index * 70))
        rows.append([
            0, "RECURSOS", 1, "PRIMÁRIO", 3, "CORRENTE",
            "0181", "AÇÃO", "01", "ELEMENTO", "1000000000", "FONTE",
            1, "GRUPO", "319001", "NATUREZA", "31900101", "NATUREZA DETALHADA",
            1, "SUBITEM", "A1B2", "PI", "0181", "0000", "PLANO",
            "169886", "153165", "UG EXECUTORA", "150748", "UG RESPONSÁVEL",
            "00123", "UGR", f"15316515239{2023 + index % 2}NE0000{index:02d}", "FAVORECIDO",
            2023 + index % 2, empenhada, liquidada, paga,
        ])
    return pd.DataFrame(rows)


class TesouroExecucaoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = make_execucao_raw()

    def test_recognizes_positive_and_negative_structures(self) -> None:
        self.assertTrue(recognize_execucao_base(self.raw).matched)
        invalid = self.raw.copy(deep=True)
        invalid.iat[0, 35] = "MEDIDA DESCONHECIDA"
        self.assertFalse(recognize_execucao_base(invalid).matched)

    def test_creates_12345_long_rows_for_equivalent_fixture(self) -> None:
        result = transform_execucao_sheet(make_execucao_raw(4115), "execucao.xlsx", "Execução")
        self.assertTrue(result.recognized)
        self.assertEqual(result.normalized_row_count, 12_345)
        self.assertEqual(len(result.normalized_data), 12_345)

    def test_preserves_null_zero_and_negative_values(self) -> None:
        result = transform_execucao_sheet(self.raw, "execucao.xlsx", "Execução")
        values = result.normalized_data["valor_movimento_liquido"]
        self.assertEqual(int(values.isna().sum()), 2)
        self.assertEqual(int(values.eq(0).fillna(False).sum()), 2)
        self.assertEqual(int(values.lt(0).fillna(False).sum()), 1)
        self.assertEqual(str(values.dtype), "Float64")

    def test_preserves_codes_with_leading_zeroes_and_alphanumeric_codes(self) -> None:
        result = transform_execucao_sheet(self.raw, "execucao.xlsx", "Execução")
        first = result.normalized_data.iloc[0]
        self.assertEqual(first["acao_codigo"], "0181")
        self.assertEqual(first["elemento_despesa_codigo"], "01")
        self.assertEqual(first["ugr_gestao_codigo"], "00123")
        self.assertEqual(first["pi_codigo"], "A1B2")

    def test_preserves_w_without_semantic_reinterpretation(self) -> None:
        result = transform_execucao_sheet(self.raw, "execucao.xlsx", "Execução")
        self.assertIn("plano_orcamentario_nivel1_origem", EXECUCAO_OUTPUT_COLUMNS)
        self.assertEqual(result.normalized_data.iloc[0]["plano_orcamentario_nivel1_origem"], "0181")

    def test_coordinates_are_unique_and_raw_is_immutable(self) -> None:
        original = self.raw.copy(deep=True)
        result = transform_execucao_sheet(self.raw, "execucao.xlsx", "Execução")
        self.assertFalse(result.normalized_data.duplicated(subset=["arquivo_origem", "aba_origem", "linha_origem", "coluna_origem"]).any())
        pd.testing.assert_frame_equal(self.raw, original)

    def test_non_numeric_value_is_reported_without_silent_conversion(self) -> None:
        raw = self.raw.copy(deep=True)
        raw.iat[2, 35] = "inválido"
        result = transform_execucao_sheet(raw, "execucao.xlsx", "Execução")
        self.assertTrue(result.validation_failures)
        self.assertTrue(pd.isna(result.normalized_data.iloc[0]["valor_movimento_liquido"]))


if __name__ == "__main__":
    unittest.main()
