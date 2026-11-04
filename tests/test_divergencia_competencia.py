"""Liquidação por Competência × Execução Mensal (SIAFI) por NE — `src/divergencia_competencia.py` e
`liquidacao_competencia.documentos_repetidos` (03/11/2026).

Caso de origem: 2026NE000551 (Minha Biblioteca), empenhado e liquidado no SIAFI R$ 389.563,20; o relatório de competência
de 03/11 trouxe o NP001010 em dois NS (NS010241 e NS011049) com as mesmas 12 parcelas, e o executado passou do empenho
sem aviso. Aqui os valores são sintéticos, na mesma forma: só aviso, nenhum valor muda.
"""

from __future__ import annotations

import unittest

import pandas as pd

from src.divergencia_competencia import (
    COLUNAS,
    COLUNAS_DESCONSIDERADOS,
    avisos_desconsiderados,
    avisos_divergencia,
    divergencias_por_ne,
    sem_documentos_repetidos,
)
from src.liquidacao_competencia import documentos_repetidos, liquidado_por_ne

PREFIXO = "15316515239"


def _ccor(curta: str) -> str:
    return PREFIXO + curta


def _competencia(linhas: list[tuple[str, str, str, int, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [(_ccor(ne), _ccor(dh), _ccor(doc), mes, valor) for ne, dh, doc, mes, valor in linhas],
        columns=["ne_ccor", "documento_habil", "doc_contabil", "ano_mes_referencia", "valor"],
    )


def _execucao(linhas: list[tuple[str, float | None, float | None]]) -> pd.DataFrame:
    df = pd.DataFrame(
        [(_ccor(ne), emp, liq) for ne, emp, liq in linhas], columns=["ne_ccor", "empenhada", "liquidada"]
    ).astype({"empenhada": "float64", "liquidada": "float64"})
    df["saldo"] = df["empenhada"] - df["liquidada"].fillna(0.0)
    return df


#: NE 551: dois NS do mesmo NP com a mesma série (3 meses × 100) — liquidado por competência 600 sobre empenho 300
DUPLICADA = [
    ("2026NE000551", "2026NP001010", "2026NS010241", 202610, 100.0),
    ("2026NE000551", "2026NP001010", "2026NS010241", 202611, 100.0),
    ("2026NE000551", "2026NP001010", "2026NS010241", 202612, 100.0),
    ("2026NE000551", "2026NP001010", "2026NS011049", 202610, 100.0),
    ("2026NE000551", "2026NP001010", "2026NS011049", 202611, 100.0),
    ("2026NE000551", "2026NP001010", "2026NS011049", 202612, 100.0),
]


class TestDocumentosRepetidos(unittest.TestCase):
    def test_mesma_serie_em_dois_ns_do_mesmo_np(self):
        r = documentos_repetidos(_competencia(DUPLICADA))
        self.assertEqual(len(r), 1)
        linha = r.iloc[0]
        self.assertEqual(linha["ne_ccor"], _ccor("2026NE000551"))
        self.assertEqual(linha["documento_habil"], _ccor("2026NP001010"))
        self.assertEqual(linha["docs_contabeis"], f"{_ccor('2026NS010241')}, {_ccor('2026NS011049')}")
        self.assertEqual(linha["meses"], 3)
        self.assertAlmostEqual(linha["valor_por_documento"], 300.0)

    def test_series_diferentes_nao_sao_repeticao(self):
        # um mês com valor diferente (ex.: complemento) — não é a mesma apropriação
        linhas = [l if l[2:4] != ("2026NS011049", 202612) else (*l[:4], 50.0) for l in DUPLICADA]
        self.assertTrue(documentos_repetidos(_competencia(linhas)).empty)

    def test_estorno_nao_e_repeticao(self):
        linhas = DUPLICADA[:3] + [(ne, dh, "2026NS011049", mes, -v) for ne, dh, _, mes, v in DUPLICADA[:3]]
        self.assertTrue(documentos_repetidos(_competencia(linhas)).empty)

    def test_mesmo_ns_em_np_diferentes_nao_e_repeticao(self):
        linhas = DUPLICADA[:3] + [(ne, "2026NP001011", "2026NS011049", mes, v) for ne, _, _, mes, v in DUPLICADA[:3]]
        self.assertTrue(documentos_repetidos(_competencia(linhas)).empty)

    def test_base_vazia(self):
        r = documentos_repetidos(_competencia([]))
        self.assertTrue(r.empty)
        self.assertEqual(list(r.columns), ["ne_ccor", "documento_habil", "docs_contabeis", "meses", "valor_por_documento"])

    def test_nao_altera_a_entrada(self):
        base = _competencia(DUPLICADA)
        copia = base.copy()
        documentos_repetidos(base)
        pd.testing.assert_frame_equal(base, copia)


class TestDivergenciasPorNe(unittest.TestCase):
    def setUp(self):
        self.indice = pd.Series({
            "2026NE000551": 600.0,   # acima do empenhado (300) e do SIAFI (300)
            "2026NE000183": 5150.0,  # acima do SIAFI (5000), abaixo do empenhado (7500)
            "2026NE000099": 900.0,   # abaixo do SIAFI (1000): atraso comum, fora do aviso
            "2026NE000057": 200.005,  # dentro da tolerância de R$ 0,01
            "2026NE000700": 80.0,    # SIAFI sem liquidação (nulo) e competência abaixo do empenho
            "2026NE000800": 500.0,   # SIAFI sem liquidação (nulo) e competência acima do empenho
        })
        self.execucao = _execucao([
            ("2026NE000551", 300.0, 300.0),
            ("2026NE000183", 7500.0, 5000.0),
            ("2026NE000099", 2000.0, 1000.0),
            ("2026NE000057", 300.0, 200.0),
            ("2026NE000700", 100.0, None),
            ("2026NE000800", 100.0, None),
            ("2026NE000900", 100.0, 50.0),  # sem competência: não comparada
        ])

    def _div(self, nes, repetidos=None):
        return divergencias_por_ne(nes, self.indice, self.execucao, repetidos).set_index("ne_curta")

    def test_classifica_acima_do_empenho_e_acima_do_siafi(self):
        d = self._div(list(self.indice.index) + ["2026NE000900"])
        self.assertEqual(sorted(d.index), ["2026NE000183", "2026NE000551", "2026NE000800"])
        self.assertTrue(d.loc["2026NE000551", "acima_do_empenho"])
        self.assertAlmostEqual(d.loc["2026NE000551", "diferenca_siafi"], 300.0)
        self.assertFalse(d.loc["2026NE000183", "acima_do_empenho"])
        self.assertAlmostEqual(d.loc["2026NE000183", "diferenca_siafi"], 150.0)

    def test_siafi_nulo_nao_vira_zero(self):
        d = self._div(["2026NE000700", "2026NE000800"])
        # 700: abaixo do empenho e sem liquidado no SIAFI para comparar — nada a avisar
        self.assertNotIn("2026NE000700", d.index)
        # 800: acima do empenho; a diferença sobre o SIAFI fica nula, não 500
        self.assertTrue(d.loc["2026NE000800", "acima_do_empenho"])
        self.assertTrue(pd.isna(d.loc["2026NE000800", "liquidado_siafi"]))
        self.assertTrue(pd.isna(d.loc["2026NE000800", "diferenca_siafi"]))

    def test_so_nes_pedidas_e_sem_nulos_nem_repetidas(self):
        d = self._div(pd.Series(["2026NE000183", None, "2026NE000183", pd.NA]))
        self.assertEqual(list(d.index), ["2026NE000183"])

    def test_competencia_indisponivel(self):
        d = divergencias_por_ne(["2026NE000551"], None, self.execucao)
        self.assertTrue(d.empty)
        self.assertEqual(list(d.columns), COLUNAS)

    def test_documentos_repetidos_da_ne(self):
        repetidos = documentos_repetidos(_competencia(DUPLICADA))
        d = self._div(["2026NE000551", "2026NE000183"], repetidos)
        self.assertEqual(
            d.loc["2026NE000551", "documentos_repetidos"],
            "2026NP001010 com 2026NS010241 e 2026NS011049 repetindo 3 mês(es) (R$ 300,00 cada)",
        )
        self.assertTrue(pd.isna(d.loc["2026NE000183", "documentos_repetidos"]))

    def test_nao_altera_as_entradas(self):
        indice, execucao = self.indice.copy(), self.execucao.copy()
        divergencias_por_ne(list(self.indice.index), self.indice, self.execucao)
        pd.testing.assert_series_equal(self.indice, indice)
        pd.testing.assert_frame_equal(self.execucao, execucao)


class TestAvisos(unittest.TestCase):
    def test_dois_avisos_com_os_valores_das_duas_bases(self):
        indice = pd.Series({"2026NE000551": 779126.40, "2026NE000183": 5150769.14})
        execucao = _execucao([("2026NE000551", 389563.20, 389563.20), ("2026NE000183", 7500000.0, 5145111.24)])
        repetidos = documentos_repetidos(_competencia(DUPLICADA))
        avisos = avisos_divergencia(
            divergencias_por_ne(["2026NE000551", "2026NE000183"], indice, execucao, repetidos), "Contratos Contínuos"
        )
        self.assertEqual(len(avisos), 2)
        acima, so_siafi = avisos
        self.assertTrue(acima.startswith("Contratos Contínuos: liquidação por competência acima do empenhado"))
        self.assertIn("nenhum valor foi alterado", acima)
        self.assertIn(
            "2026NE000551 — empenhado R$ 389.563,20, liquidado no SIAFI R$ 389.563,20, por competência "
            "R$ 779.126,40 (+R$ 389.563,20 sobre o SIAFI)", acima,
        )
        self.assertIn("documento 2026NP001010 com 2026NS010241 e 2026NS011049", acima)
        self.assertNotIn("2026NE000183", acima)
        self.assertIn("acima do liquidado no SIAFI", so_siafi)
        self.assertIn(
            "2026NE000183 — liquidado no SIAFI R$ 5.145.111,24, por competência R$ 5.150.769,14 (+R$ 5.657,90 sobre o SIAFI)",
            so_siafi,
        )
        self.assertNotIn("acima do empenhado", so_siafi)

    def test_sem_divergencia_sem_aviso(self):
        self.assertEqual(avisos_divergencia(pd.DataFrame(columns=COLUNAS), "Bolsas e Auxílios"), [])


class TestSemDocumentosRepetidos(unittest.TestCase):
    """Regra de 04/11/2026 ("ignorar NS repetido"): a cópia sai da conta só com a duplicidade comprovada pela Execução
    Mensal — competência acima do empenhado e, sem a cópia, não abaixo do liquidado no SIAFI."""

    OUTRA_NE = [("2026NE000183", "2026NP000500", "2026NS000600", 202610, 50.0)]

    def _rodar(self, execucao, linhas=None):
        return sem_documentos_repetidos(_competencia(linhas or DUPLICADA + self.OUTRA_NE), _execucao(execucao))

    def test_duplicidade_comprovada_sai_da_conta(self):
        base, fora = self._rodar([("2026NE000551", 300.0, 300.0), ("2026NE000183", 100.0, 50.0)])
        totais = liquidado_por_ne(base)
        self.assertAlmostEqual(totais[_ccor("2026NE000551")], 300.0)
        self.assertAlmostEqual(totais[_ccor("2026NE000183")], 50.0)  # outra NE intacta
        self.assertEqual(set(base["doc_contabil"]), {_ccor("2026NS010241"), _ccor("2026NS000600")})  # mantém o menor
        self.assertEqual(len(base), 4)
        self.assertEqual(list(fora.columns), COLUNAS_DESCONSIDERADOS)
        l = fora.iloc[0]
        self.assertEqual((l["ne_curta"], l["doc_mantido"], l["docs_desconsiderados"]),
                         ("2026NE000551", _ccor("2026NS010241"), _ccor("2026NS011049")))
        self.assertAlmostEqual(l["valor_desconsiderado"], 300.0)
        self.assertAlmostEqual(l["competencia_antes"], 600.0)
        self.assertAlmostEqual(l["competencia_depois"], 300.0)

    def test_dentro_do_empenhado_nada_sai(self):
        # empenho 700 cobre os 600: pode ser pagamento real com a mesma série
        base, fora = self._rodar([("2026NE000551", 700.0, 600.0)])
        self.assertEqual(len(base), 7)
        self.assertTrue(fora.empty)

    def test_sem_empenhado_na_execucao_nada_sai(self):
        base, fora = self._rodar([("2026NE000183", 100.0, 50.0)])
        self.assertEqual(len(base), 7)
        self.assertTrue(fora.empty)

    def test_sem_a_copia_ficaria_abaixo_do_siafi_nada_sai(self):
        # empenhado 500 < 600, mas o SIAFI já liquidou 450: tirar 300 deixaria a competência em 300 < 450
        base, fora = self._rodar([("2026NE000551", 500.0, 450.0)])
        self.assertEqual(len(base), 7)
        self.assertTrue(fora.empty)

    def test_siafi_nulo_nao_impede(self):
        base, fora = self._rodar([("2026NE000551", 300.0, None)])
        self.assertAlmostEqual(liquidado_por_ne(base)[_ccor("2026NE000551")], 300.0)
        self.assertEqual(len(fora), 1)

    def test_sem_repeticao_devolve_a_base(self):
        base = _competencia(DUPLICADA[:3])
        saida, fora = sem_documentos_repetidos(base, _execucao([("2026NE000551", 100.0, 100.0)]))
        self.assertIs(saida, base)
        self.assertTrue(fora.empty)

    def test_nao_altera_as_entradas(self):
        base, execucao = _competencia(DUPLICADA), _execucao([("2026NE000551", 300.0, 300.0)])
        copia_base, copia_execucao = base.copy(), execucao.copy()
        sem_documentos_repetidos(base, execucao)
        pd.testing.assert_frame_equal(base, copia_base)
        pd.testing.assert_frame_equal(execucao, copia_execucao)

    def test_aviso_lista_o_que_saiu(self):
        _, fora = self._rodar([("2026NE000551", 300.0, 300.0)])
        avisos = avisos_desconsiderados(fora, "Contratos Contínuos", ["2026NE000551"])
        self.assertEqual(len(avisos), 1)
        self.assertTrue(avisos[0].startswith("Contratos Contínuos: documento repetido na Liquidação por Competência "
                                             "desconsiderado na conta"))
        self.assertIn(
            "2026NE000551 — 2026NP001010: contado 2026NS010241, desconsiderado 2026NS011049 (−R$ 300,00 em 3 mês(es)); "
            "competência R$ 600,00 → R$ 300,00, empenhado R$ 300,00, liquidado no SIAFI R$ 300,00", avisos[0],
        )
        self.assertEqual(avisos_desconsiderados(fora, "Bolsas e Auxílios", ["2026NE000057"]), [])
        self.assertEqual(avisos_desconsiderados(pd.DataFrame(columns=COLUNAS_DESCONSIDERADOS), "X"), [])


if __name__ == "__main__":
    unittest.main()
