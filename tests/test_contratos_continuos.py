"""Testes do leitor de Contratos Contínuos (src/contratos_continuos.py).

Usa uma fixture congelada em `tests/fixtures/` (não a planilha de trabalho em `data/raw/`,
que é substituída a cada atualização) — pulado se o arquivo não existir. Os casos de
divergência de saldo (`2026NE000350`, `2026NE000094`) e os casos que batem foram confirmados
manualmente contra a extração de Execução Anual ativa em 13/08/2026, mesma data da fixture;
ver histórico da conversa para o levantamento completo. Valor empenhado
(`valor_empenhado_execucao`, comparado contra a soma por NE — ver docstring de
`com_saldo_execucao`) tem 2 divergências nesta fixture, em NEs diferentes das do saldo
(`2026NE000148`, diferença pequena de arredondamento; `2026NE000178`, planilha zerada mas com
valor real na Execução).

IMPORTANTE: ao atualizar a planilha de trabalho em `data/raw/`, NÃO sobrescreva esta fixture
automaticamente — ver AGENTS.md, seção sobre atualização de dados de Contratos
Contínuos/Bolsas, para o procedimento de substituição deliberada.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import openpyxl
import pandas as pd

from src.contratos_continuos import ErroLayoutBase, NOME_ABA, com_saldo_execucao, ler_contratos_continuos
from src.execucao_anual import agregar_por_ne, ler_execucao_anual, saldo_por_ne
from src.importacao_execucao import Manifesto

CAMINHO_BASE = Path("tests/fixtures/contratos_continuos_2026-08-13.xlsm")


def _variante_com_coluna_renomeada(caminho: Path, tmp_dir: Path) -> Path:
    """Cópia da planilha real com o cabeçalho "EMPENHO" renomeado — simula uma coluna
    esperada sumindo do layout, sem depender de um arquivo de outra base (que erraria com um
    `ValueError` genérico de aba ausente, não com `ErroLayoutBase`)."""

    wb = openpyxl.load_workbook(caminho, keep_vba=True)
    aba = wb[NOME_ABA]
    for celula in aba[1]:
        if celula.value == "EMPENHO":
            celula.value = "EMPENHO RENOMEADO"
    destino = tmp_dir / caminho.name
    wb.save(destino)
    return destino


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestLeituraContratosContinuos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = ler_contratos_continuos(CAMINHO_BASE)

    def test_le_linhas_e_colunas_esperadas(self):
        self.assertEqual(len(self.df), 59)
        for coluna in (
            "ano_contrato", "contrato_numero", "processo_contratacao", "processo_empenho",
            "fornecedor", "tipo_contrato", "status_contrato", "ne_curta", "despesa_mensal",
            "despesa_anual", "valor_empenhado", "saldo_colado_planilha",
            "meses_a_empenhar", "valor_a_empenhar",
        ):
            self.assertIn(coluna, self.df.columns)

    def test_linha_de_total_da_planilha_nao_vira_linha_de_dado(self):
        # a última linha da aba original soma DESPESA MENSAL/ANUAL, VALOR EMPENHADO e SALDO
        # TOTAL TG de todos os contratos, sem FORNECEDOR nem nenhuma outra coluna
        # identificadora — só "STATUS ATUALIZAÇÃO" com um resumo textual ("52 atualizados").
        # Um valor de despesa mensal folgadamente maior que qualquer contrato real (a maior
        # despesa mensal individual da fixture é ~R$ 812 mil; a linha de total somava
        # ~R$ 5,5 milhões) indicaria que essa linha de total vazou para o esquema.
        self.assertFalse(self.df["fornecedor"].isna().any())
        self.assertLess(self.df["despesa_mensal"].max(), 2_000_000)

    def test_nao_traz_as_colunas_manuais_descartadas(self):
        # MESES A EMPENHAR/EMPENHAR (R$) da origem estão sempre vazias nesta planilha (ver
        # docstring do módulo) — a métrica real recalculada é meses_a_empenhar/valor_a_empenhar.
        self.assertNotIn("meses_a_empenhar_original", self.df.columns)
        self.assertNotIn("empenhar_reais", self.df.columns)

    def test_tem_varios_itens_vira_booleano(self):
        self.assertEqual(self.df["tem_varios_itens"].dtype, bool)
        self.assertTrue(self.df["tem_varios_itens"].any())
        self.assertFalse(self.df["tem_varios_itens"].all())

    def test_sentinela_de_ne_vira_nulo(self):
        # ao menos uma linha da extração real usa "-" na coluna EMPENHO (contrato sem
        # empenho no período) — deve virar nulo, não o literal "-".
        self.assertFalse(self.df["ne_curta"].astype("string").eq("-").any())

    def test_meses_a_empenhar_reproduz_meses_de_saldo_da_origem(self):
        # mesma fórmula da coluna MESES DE SALDO da planilha (validada célula a célula
        # contra a origem antes da implementação) — não pode divergir.
        comparavel = self.df.dropna(subset=["meses_empenhados", "meses_liquidados", "meses_de_saldo"])
        self.assertFalse(comparavel.empty)
        diferenca = (comparavel["meses_a_empenhar"] - comparavel["meses_de_saldo"]).abs()
        self.assertTrue((diferenca <= 1e-6).all())

    def test_valor_a_empenhar_e_despesa_mensal_vezes_meses_a_empenhar(self):
        linha = self.df[self.df["ne_curta"] == "2026NE000094"].iloc[0]
        esperado = linha["despesa_mensal"] * linha["meses_a_empenhar"]
        self.assertAlmostEqual(linha["valor_a_empenhar"], esperado, places=2)

    def test_layout_diferente_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            variante = _variante_com_coluna_renomeada(CAMINHO_BASE, Path(tmp))
            with self.assertRaises(ErroLayoutBase):
                ler_contratos_continuos(variante)


@unittest.skipUnless(
    CAMINHO_BASE.exists() and Path("data/manifestos/execucao_anual_atual.json").exists(),
    "Planilha de Contratos Contínuos ou manifesto de Execução Anual ausente",
)
class TestSaldoViaExecucaoAnual(unittest.TestCase):
    """Confere `saldo_execucao`/`diverge_saldo` contra os casos já levantados manualmente:
    2 NEs com divergência real (BASE_TG da planilha desatualizado em relação à Execução
    Anual reimportada) e uma amostra de NEs que batem exatamente."""

    @classmethod
    def setUpClass(cls):
        manifesto = Manifesto.atual()
        df_execucao = ler_execucao_anual(Path("data/raw") / manifesto.arquivo)
        cls.por_ne = saldo_por_ne(agregar_por_ne(df_execucao))
        cls.df = com_saldo_execucao(ler_contratos_continuos(CAMINHO_BASE), cls.por_ne)

    def _linha(self, ne_curta: str) -> pd.Series:
        linhas = self.df[self.df["ne_curta"] == ne_curta]
        return linhas.iloc[0]

    def test_todos_os_ne_curta_da_planilha_sao_encontrados_na_execucao(self):
        citados = self.df["ne_curta"].dropna().unique()
        self.assertEqual(len(citados), 36)
        encontrados = self.df.dropna(subset=["ne_curta"])["saldo_execucao"].notna()
        self.assertTrue(encontrados.all())

    def test_ne_350_diverge_por_liquidacao_nao_capturada_na_planilha(self):
        linha = self._linha("2026NE000350")
        self.assertAlmostEqual(linha["saldo_colado_planilha"], 1516940.26, places=2)
        self.assertAlmostEqual(linha["saldo_execucao"], 1180243.92, places=2)
        self.assertTrue(bool(linha["diverge_saldo"]))

    def test_ne_094_diverge_por_liquidacao_nao_capturada_na_planilha(self):
        linha = self._linha("2026NE000094")
        self.assertAlmostEqual(linha["saldo_colado_planilha"], 39221.85, places=2)
        self.assertAlmostEqual(linha["saldo_execucao"], 20227.20, places=2)
        self.assertTrue(bool(linha["diverge_saldo"]))

    def test_ne_092_bate_exatamente(self):
        linha = self._linha("2026NE000092")
        self.assertAlmostEqual(linha["saldo_colado_planilha"], 17658.16, places=2)
        self.assertAlmostEqual(linha["saldo_execucao"], 17658.16, places=2)
        self.assertFalse(bool(linha["diverge_saldo"]))

    def test_quantidade_total_de_divergencias_bate_com_o_levantamento(self):
        unicos = self.df.dropna(subset=["ne_curta"]).drop_duplicates("ne_curta")
        self.assertEqual(int(unicos["diverge_saldo"].sum()), 2)

    def test_valor_empenhado_e_somado_por_ne_antes_de_comparar(self):
        # NE 116 tem 5 itens (ver investigação da fixture) — valor_empenhado da linha
        # continua sendo o do item, mas o total comparado contra a Execução é a soma da NE.
        linhas = self.df[self.df["ne_curta"] == "2026NE000116"]
        self.assertGreater(len(linhas), 1)
        soma_itens = linhas["valor_empenhado"].sum()
        totais_ne = linhas["valor_empenhado_planilha_total_ne"].unique()
        self.assertEqual(len(totais_ne), 1)
        self.assertAlmostEqual(totais_ne[0], soma_itens, places=2)

    def test_ne_148_diverge_por_arredondamento_do_rateio(self):
        linha = self._linha("2026NE000148")
        self.assertAlmostEqual(linha["valor_empenhado_planilha_total_ne"], 22209.56, places=2)
        self.assertAlmostEqual(linha["valor_empenhado_execucao"], 22214.0, places=2)
        self.assertTrue(bool(linha["diverge_valor_empenhado"]))

    def test_ne_178_diverge_porque_planilha_esta_zerada(self):
        linha = self._linha("2026NE000178")
        self.assertAlmostEqual(linha["valor_empenhado_planilha_total_ne"], 0.0, places=2)
        self.assertAlmostEqual(linha["valor_empenhado_execucao"], 9610.0, places=2)
        self.assertTrue(bool(linha["diverge_valor_empenhado"]))

    def test_ne_092_valor_empenhado_bate_exatamente(self):
        linha = self._linha("2026NE000092")
        self.assertAlmostEqual(linha["valor_empenhado_planilha_total_ne"], 42051.96, places=2)
        self.assertAlmostEqual(linha["valor_empenhado_execucao"], 42051.96, places=2)
        self.assertFalse(bool(linha["diverge_valor_empenhado"]))

    def test_quantidade_total_de_divergencias_de_valor_empenhado_bate_com_o_levantamento(self):
        unicos = self.df.dropna(subset=["ne_curta"]).drop_duplicates("ne_curta")
        self.assertEqual(int(unicos["diverge_valor_empenhado"].sum()), 2)


if __name__ == "__main__":
    unittest.main()
