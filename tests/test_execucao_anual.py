"""
Testes da base ANUAL de Execução da Despesa.

Dois níveis, propositalmente separados para sobreviver a reimportações:

  * INVARIANTES — valem para qualquer extração desta base. Se um deles quebrar, a extração
    mudou de natureza e a análise precisa ser repensada. Nunca afrouxar.
  * REFERÊNCIA — totais absolutos de UMA extração específica, identificada por hash.
    Só são conferidos quando o arquivo em disco é exatamente aquela extração; com outro
    arquivo, o teste é pulado em vez de falhar. É isso que permite trocar a base sem
    mexer na suíte.

Ajuste CAMINHO_BASE e os imports ao pacote do projeto.
"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.execucao_anual import (
    COLUNAS,
    MEDIDAS,
    ErroLayoutBase,
    agregar,
    ler_execucao_anual,
    reconciliar,
    validar,
)
from src.importacao_execucao import (
    Manifesto,
    comparar,
    gerar_manifesto,
    historico,
    historico_como_tabela,
    importar,
)

CAMINHO_BASE = Path("data/raw/BI PROPLAD - EXEC. DESPESAS - Por Ano (9).xlsx")

# Extração de referência recebida em 11/08/2026. Ao substituir a base por uma extração mais
# recente, NÃO edite estes números: registre a nova referência acrescentando outra entrada
# (o hash é que decide qual se aplica).
REFERENCIAS = {
    "7d09c278": {
        "descricao": "Extração recebida em 11/08/2026, exercícios 2023-2026",
        "linhas": 7779,
        "linhas_empenho": 4092,
        "linhas_item_execucao": 3687,
        "notas_empenho_distintas": 3700,
        "anos": [2023, 2024, 2025, 2026],
        "totais": {
            "empenhada": 3232327499.34,
            "liquidada": 2864970004.16,
            "paga": 2616012762.14,
        },
        "totais_por_ano": {
            2023: {"empenhada": 762455916.88, "liquidada": 723987833.09, "paga": 651361558.65},
            2024: {"empenhada": 784086352.51, "liquidada": 759877180.18, "paga": 687779472.58},
            2025: {"empenhada": 931345340.39, "liquidada": 882774236.76, "paga": 790633667.10},
            2026: {"empenhada": 754439889.56, "liquidada": 498330754.13, "paga": 486238063.81},
        },
    },
}


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Base ausente em {CAMINHO_BASE}")
class TestInvariantesDaBase(unittest.TestCase):
    """Verdades estruturais que qualquer extração desta base precisa respeitar."""

    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_anual(CAMINHO_BASE)

    def test_colunas_e_tipos(self):
        for col in COLUNAS:
            self.assertIn(col, self.df.columns)
        self.assertEqual(str(self.df["ano"].dtype), "int16")
        for m in MEDIDAS:
            self.assertTrue(pd.api.types.is_float_dtype(self.df[m]))

    def test_codigos_permanecem_texto_com_zeros_a_esquerda(self):
        self.assertTrue(self.df["fonte_cod"].str.len().eq(3).all())
        self.assertTrue((self.df["acao_cod"].str.len() >= 4).all())

    def test_liquidado_e_pago_so_em_linhas_de_item(self):
        empenho = self.df[self.df["tipo_linha"] == "empenho"]
        self.assertEqual(int(empenho["liquidada"].notna().sum()), 0)
        self.assertEqual(int(empenho["paga"].notna().sum()), 0)

    def test_empenhado_nas_linhas_de_item_se_anula(self):
        itens = self.df[self.df["tipo_linha"] == "item_execucao"]
        self.assertAlmostEqual(float(itens["empenhada"].sum()), 0.0, places=2)

    def test_ano_lancamento_igual_ao_ano_da_ne(self):
        self.assertTrue(self.df["ne_ano"].eq(self.df["ano"].astype(str)).all())

    def test_coerencia_financeira_por_ano(self):
        por_ano = self.df.groupby("ano")[MEDIDAS].sum()
        for ano, linha in por_ano.iterrows():
            self.assertLessEqual(linha["liquidada"], linha["empenhada"] + 0.01, f"{ano}")
            self.assertLessEqual(linha["paga"], linha["liquidada"] + 0.01, f"{ano}")

    def test_sem_duplicatas_na_chave_dimensional(self):
        chave = [c for c in COLUNAS if c not in MEDIDAS]
        self.assertEqual(int(self.df.duplicated(subset=chave).sum()), 0)

    def test_agregacao_preserva_total(self):
        por_gnd = agregar(self.df, por=["gnd_cod", "gnd_desc"])
        for m in MEDIDAS:
            self.assertAlmostEqual(float(por_gnd[m].sum()), float(self.df[m].sum()), places=2, msg=m)

    def test_rastreabilidade_ate_a_linha_de_origem(self):
        self.assertEqual(int(self.df["linha_origem"].min()), 3)
        self.assertEqual(int(self.df["linha_origem"].nunique()), len(self.df))

    def test_validacao_sem_erros(self):
        rel = validar(self.df)
        self.assertTrue(rel.ok, rel.erros)
        self.assertEqual(rel.alertas, [])


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Base ausente em {CAMINHO_BASE}")
class TestReferenciaDaExtracao(unittest.TestCase):
    """Totais absolutos — só se aplicam à extração cujo hash está em REFERENCIAS."""

    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_anual(CAMINHO_BASE)
        cls.manifesto = gerar_manifesto(cls.df, CAMINHO_BASE)
        cls.ref = REFERENCIAS.get(cls.manifesto.sha256[:8])

    def setUp(self):
        if self.ref is None:
            self.skipTest(
                f"Extração {self.manifesto.sha256[:8]} não catalogada em REFERENCIAS — "
                "acrescente uma entrada ao trocar a base."
            )

    def test_contagens(self):
        r = reconciliar(self.df)
        for campo in ("linhas", "linhas_empenho", "linhas_item_execucao", "notas_empenho_distintas"):
            self.assertEqual(r[campo], self.ref[campo], campo)
        self.assertEqual(r["anos"], self.ref["anos"])

    def test_reconciliacao_total(self):
        r = reconciliar(self.df)
        for medida, valor in self.ref["totais"].items():
            self.assertAlmostEqual(r["totais"][medida], valor, places=2, msg=medida)

    def test_reconciliacao_por_ano(self):
        r = reconciliar(self.df)
        for ano, medidas in self.ref["totais_por_ano"].items():
            for medida, valor in medidas.items():
                self.assertAlmostEqual(
                    r["totais_por_ano"][ano][medida], valor, places=2, msg=f"{ano}/{medida}"
                )


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Base ausente em {CAMINHO_BASE}")
class TestImportacaoVersionada(unittest.TestCase):
    def test_primeira_importacao_registra_manifesto(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = importar(CAMINHO_BASE, tmp)
            self.assertTrue(res.ok, res.validacao.erros)
            self.assertFalse(res.delta.houve_anterior)
            self.assertIsNotNone(res.caminho_manifesto)
            self.assertEqual(len(historico(tmp)), 1)
            self.assertEqual(Manifesto.atual(tmp).sha256, res.manifesto.sha256)

    def test_reimportar_o_mesmo_arquivo_e_idempotente(self):
        with tempfile.TemporaryDirectory() as tmp:
            importar(CAMINHO_BASE, tmp)
            segunda = importar(CAMINHO_BASE, tmp)
            self.assertTrue(segunda.delta.mesma_extracao)
            self.assertIsNone(segunda.caminho_manifesto)
            self.assertEqual(len(historico(tmp)), 1)

    def test_manifesto_carrega_igual_ao_que_foi_salvo(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = importar(CAMINHO_BASE, tmp)
            recarregado = Manifesto.carregar(res.caminho_manifesto)
            self.assertEqual(recarregado.sha256, res.manifesto.sha256)
            self.assertEqual(recarregado.totais, res.manifesto.totais)
            self.assertEqual(recarregado.data_extracao, res.manifesto.data_extracao)

    def test_historico_como_tabela(self):
        with tempfile.TemporaryDirectory() as tmp:
            importar(CAMINHO_BASE, tmp)
            tabela = historico_como_tabela(tmp)
            self.assertEqual(len(tabela), 1)
            for coluna in ("data_extracao", "arquivo", "sha256_curto", "linhas", *MEDIDAS):
                self.assertIn(coluna, tabela.columns)


class TestDelta(unittest.TestCase):
    """Comparação entre extrações — não depende do arquivo real."""

    def _manifesto(self, sha: str, anos_totais: dict) -> Manifesto:
        totais = {m: round(sum(v[m] for v in anos_totais.values()), 2) for m in MEDIDAS}
        return Manifesto(
            base="execucao_anual",
            arquivo="x.xlsx",
            sha256=sha,
            data_extracao="2026-08-11T10:00:00",
            importado_em="2026-08-11T10:00:00",
            linhas=10,
            linhas_empenho=6,
            linhas_item_execucao=4,
            notas_empenho_distintas=6,
            anos=sorted(int(a) for a in anos_totais),
            totais=totais,
            totais_por_ano={str(a): v for a, v in anos_totais.items()},
        )

    def test_primeira_importacao(self):
        d = comparar(None, self._manifesto("a" * 64, {2025: dict(empenhada=1.0, liquidada=1.0, paga=1.0)}))
        self.assertFalse(d.houve_anterior)

    def test_hash_igual_significa_mesma_extracao(self):
        m = self._manifesto("b" * 64, {2025: dict(empenhada=1.0, liquidada=1.0, paga=1.0)})
        d = comparar(m, m)
        self.assertTrue(d.mesma_extracao)
        self.assertEqual(d.anos_alterados, {})

    def test_exercicio_em_andamento_avancou(self):
        antes = self._manifesto("c" * 64, {
            2025: dict(empenhada=100.0, liquidada=90.0, paga=80.0),
            2026: dict(empenhada=50.0, liquidada=30.0, paga=20.0),
        })
        depois = self._manifesto("d" * 64, {
            2025: dict(empenhada=100.0, liquidada=90.0, paga=80.0),
            2026: dict(empenhada=70.0, liquidada=45.0, paga=35.0),
        })
        d = comparar(antes, depois)
        self.assertEqual(list(d.anos_alterados), [2026])
        self.assertAlmostEqual(d.anos_alterados[2026]["empenhada"]["diferenca"], 20.0)
        self.assertEqual(d.alertas, [])  # avanço do exercício corrente não é alerta

    def test_mudanca_retroativa_gera_alerta(self):
        antes = self._manifesto("e" * 64, {
            2024: dict(empenhada=100.0, liquidada=90.0, paga=80.0),
            2025: dict(empenhada=100.0, liquidada=90.0, paga=80.0),
        })
        depois = self._manifesto("f" * 64, {
            2024: dict(empenhada=95.0, liquidada=90.0, paga=80.0),
            2025: dict(empenhada=100.0, liquidada=90.0, paga=80.0),
        })
        d = comparar(antes, depois)
        self.assertIn(2024, d.anos_alterados)
        self.assertTrue(any("retroativ" in a for a in d.alertas))

    def test_exercicio_que_some_gera_alerta(self):
        antes = self._manifesto("1" * 64, {
            2023: dict(empenhada=10.0, liquidada=9.0, paga=8.0),
            2024: dict(empenhada=10.0, liquidada=9.0, paga=8.0),
        })
        depois = self._manifesto("2" * 64, {2024: dict(empenhada=10.0, liquidada=9.0, paga=8.0)})
        d = comparar(antes, depois)
        self.assertEqual(d.anos_removidos, [2023])
        self.assertTrue(any("2023" in a for a in d.alertas))

    def test_ano_novo_e_detectado(self):
        antes = self._manifesto("3" * 64, {2025: dict(empenhada=10.0, liquidada=9.0, paga=8.0)})
        depois = self._manifesto("4" * 64, {
            2025: dict(empenhada=10.0, liquidada=9.0, paga=8.0),
            2026: dict(empenhada=5.0, liquidada=1.0, paga=1.0),
        })
        d = comparar(antes, depois)
        self.assertEqual(d.anos_novos, [2026])


class TestContratoDeLayout(unittest.TestCase):
    def test_arquivo_inexistente(self):
        with self.assertRaises(FileNotFoundError):
            ler_execucao_anual(Path("nao_existe.xlsx"))

    @unittest.skipUnless(CAMINHO_BASE.exists(), f"Base ausente em {CAMINHO_BASE}")
    def test_layout_diferente_e_rejeitado(self):
        df = pd.read_excel(CAMINHO_BASE, header=None, nrows=5, dtype=str).drop(columns=[0])
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            df.to_excel(tmp.name, header=False, index=False)
            with self.assertRaises(ErroLayoutBase):
                ler_execucao_anual(tmp.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
