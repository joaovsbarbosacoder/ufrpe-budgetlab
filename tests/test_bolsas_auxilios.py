"""Testes do leitor de Bolsas e Auxílios (src/bolsas_auxilios.py).

Usa uma fixture congelada em `tests/fixtures/` (não a planilha de trabalho em `data/raw/`,
que é substituída a cada atualização) — pulado se o arquivo não existir. O caso de
divergência de saldo (`2026NE000056`) e os casos que batem foram confirmados manualmente
contra a extração de Execução Anual ativa em 13/08/2026, mesma data da fixture; ver histórico
da conversa para o levantamento completo. Valor empenhado (`valor_empenhado_execucao`) não
tem nenhuma divergência nesta fixture — as 17 NEs batem exatamente contra a Execução Anual.

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

from src.bolsas_auxilios import ErroLayoutBase, LINHA_CABECALHO, NOME_ABA, com_saldo_execucao, ler_bolsas_auxilios
from src.execucao_anual import agregar_por_ne, saldo_por_ne
from src.importacao_execucao import carregar_atual
from src.necessidade_empenho import calcular_necessidade_empenho

CAMINHO_BASE = Path("tests/fixtures/bolsas_auxilios_2026-08-13.xlsx")


def _variante_com_coluna_renomeada(caminho: Path, tmp_dir: Path) -> Path:
    """Cópia da planilha real com o cabeçalho "EMPENHO" renomeado — simula uma coluna
    esperada sumindo do layout, sem depender de um arquivo de outra base (que erraria com um
    `ValueError` genérico de aba ausente, não com `ErroLayoutBase`)."""

    wb = openpyxl.load_workbook(caminho)
    aba = wb[NOME_ABA]
    for celula in aba[LINHA_CABECALHO + 1]:
        if celula.value == "EMPENHO":
            celula.value = "EMPENHO RENOMEADO"
    destino = tmp_dir / caminho.name
    wb.save(destino)
    return destino


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestLeituraBolsasAuxilios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = ler_bolsas_auxilios(CAMINHO_BASE)

    def test_le_linhas_e_colunas_esperadas_sem_a_linha_de_totais(self):
        self.assertEqual(len(self.df), 19)
        for coluna in (
            "processo", "programa_bolsa", "ne_curta", "qtd_efetiva", "valor_unitario",
            "valor_mensal", "valor_anual", "valor_empenhado_tg", "saldo_colado_planilha",
            "situacao_tg", "meses_a_empenhar", "valor_a_empenhar",
        ):
            self.assertIn(coluna, self.df.columns)
        # a linha "TOTAIS" da origem não vira linha de dado
        self.assertFalse(self.df["situacao_tg"].astype("string").eq("TOTAIS").any())

    def test_granularidade_e_por_programa_nao_por_bolsista(self):
        # não existe (e não deveria existir) nome/CPF de bolsista individual no esquema —
        # a granularidade é processo x item de despesa (programa), com quantidade agregada.
        for coluna_ausente in ("bolsista", "nome_bolsista", "cpf_bolsista"):
            self.assertNotIn(coluna_ausente, self.df.columns)
        self.assertIn("qtd_efetiva", self.df.columns)

    def test_tem_saldo_vira_booleano(self):
        self.assertEqual(self.df["tem_saldo"].dtype, bool)

    def test_sentinela_de_ne_vira_nulo(self):
        # ao menos um processo desta extração ainda não tem empenho (EMPENHO = "0" na origem).
        self.assertTrue(self.df["ne_curta"].isna().any())
        self.assertFalse(self.df["ne_curta"].astype("string").eq("0").any())

    def test_meses_a_empenhar_reproduz_meses_de_saldo_da_origem(self):
        comparavel = self.df.dropna(subset=["meses_empenhados", "meses_liquidados", "meses_de_saldo"])
        self.assertFalse(comparavel.empty)
        diferenca = (comparavel["meses_a_empenhar"] - comparavel["meses_de_saldo"]).abs()
        self.assertTrue((diferenca <= 1e-6).all())

    def test_valor_a_empenhar_e_valor_mensal_vezes_meses_a_empenhar(self):
        linha = self.df[self.df["ne_curta"] == "2026NE000056"].iloc[0]
        esperado = linha["valor_mensal"] * linha["meses_a_empenhar"]
        self.assertAlmostEqual(linha["valor_a_empenhar"], esperado, places=2)

    def test_layout_diferente_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            variante = _variante_com_coluna_renomeada(CAMINHO_BASE, Path(tmp))
            with self.assertRaises(ErroLayoutBase):
                ler_bolsas_auxilios(variante)


@unittest.skipUnless(
    CAMINHO_BASE.exists() and Path("data/manifestos/execucao_anual_atual.json").exists(),
    "Planilha de Bolsas ou manifesto de Execução Anual ausente",
)
class TestSaldoViaExecucaoAnual(unittest.TestCase):
    """Confere `saldo_execucao`/`diverge_saldo` contra os casos já levantados manualmente.

    Números recalibrados em 26/08/2026 (mesmo motivo de
    `test_contratos_continuos.py::TestSaldoViaExecucaoAnual`): o usuário reimportou a Execução
    Anual só com 2026 atualizado, confirmou que os novos valores são reais, e a planilha de
    Bolsas (fixture congelada de 13/08) ficou desatualizada — a maioria dos NEs passou a
    divergir. NE 2026NE000232 é um dos poucos que ainda batem exatamente nas duas
    comparações; usado como amostra "sem divergência"."""

    @classmethod
    def setUpClass(cls):
        # `carregar_atual` (composta por ano) — mesmo carregador que a página usa de verdade
        # (ver mesmo comentário em test_contratos_continuos.py::TestSaldoViaExecucaoAnual).
        df_execucao = carregar_atual()
        cls.por_ne = saldo_por_ne(agregar_por_ne(df_execucao))
        cls.df = com_saldo_execucao(ler_bolsas_auxilios(CAMINHO_BASE), cls.por_ne)

    def _linha(self, ne_curta: str) -> pd.Series:
        return self.df[self.df["ne_curta"] == ne_curta].iloc[0]

    def test_todos_os_ne_curta_da_planilha_sao_encontrados_na_execucao(self):
        citados = self.df["ne_curta"].dropna().unique()
        self.assertEqual(len(citados), 17)
        encontrados = self.df.dropna(subset=["ne_curta"])["saldo_execucao"].notna()
        self.assertTrue(encontrados.all())

    def test_linhas_sem_empenho_ficam_com_saldo_execucao_nulo(self):
        sem_empenho = self.df[self.df["ne_curta"].isna()]
        self.assertFalse(sem_empenho.empty)
        self.assertTrue(sem_empenho["saldo_execucao"].isna().all())
        self.assertTrue(sem_empenho["diverge_saldo"].isna().all())

    def test_ne_056_diverge_por_liquidacao_nao_capturada_na_planilha(self):
        linha = self._linha("2026NE000056")
        self.assertAlmostEqual(linha["saldo_colado_planilha"], 7246.48, places=2)
        self.assertAlmostEqual(linha["saldo_execucao"], 14883.98, places=2)
        self.assertTrue(bool(linha["diverge_saldo"]))

    def test_ne_232_bate_exatamente(self):
        linha = self._linha("2026NE000232")
        self.assertAlmostEqual(linha["saldo_colado_planilha"], 1400.00, places=2)
        self.assertAlmostEqual(linha["saldo_execucao"], 1400.00, places=2)
        self.assertFalse(bool(linha["diverge_saldo"]))

    def test_quantidade_total_de_divergencias_bate_com_o_levantamento(self):
        comparaveis = self.df.dropna(subset=["ne_curta"])
        self.assertEqual(int(comparaveis["diverge_saldo"].sum()), 12)

    def test_todos_os_ne_curta_tem_valor_empenhado_execucao(self):
        # uma linha por NE nesta base (sem rateio por item, ao contrário de Contratos
        # Contínuos) — todas as 17 NEs citadas encontram valor empenhado na Execução.
        encontrados = self.df.dropna(subset=["ne_curta"])["valor_empenhado_execucao"].notna()
        self.assertTrue(encontrados.all())

    def test_valor_empenhado_diverge_na_maioria_dos_casos(self):
        # até 13/08/2026 nenhuma das 17 NEs divergia em valor empenhado; com a Execução Anual
        # de 26/08 (composição por ano, planilha de Bolsas não reimportada junto), 13 passaram
        # a divergir — NE 232 é uma das 4 que ainda batem.
        linha = self._linha("2026NE000232")
        self.assertAlmostEqual(linha["valor_empenhado_tg"], 11200.0, places=2)
        self.assertAlmostEqual(linha["valor_empenhado_execucao"], 11200.0, places=2)
        self.assertFalse(bool(linha["diverge_valor_empenhado"]))

        comparaveis = self.df.dropna(subset=["ne_curta"])
        self.assertEqual(int(comparaveis["diverge_valor_empenhado"].sum()), 13)

    def test_necessidade_de_empenho_recalculada_para_ne_encontradas_na_execucao(self):
        via_execucao = self.df[self.df["necessidade_via"] == "execucao"]
        self.assertFalse(via_execucao.empty)
        for _, linha in via_execucao.iterrows():
            meses_esperado = linha["meses_empenhados_execucao"] - linha["meses_liquidados_execucao"]
            self.assertAlmostEqual(linha["meses_a_empenhar"], meses_esperado, places=6)
            if pd.notna(linha["valor_mensal"]):
                self.assertAlmostEqual(linha["valor_a_empenhar"], linha["valor_mensal"] * meses_esperado, places=2)


class TestNecessidadeViaExecucaoAnual(unittest.TestCase):
    """`com_saldo_execucao` recalcula `meses_a_empenhar`/`valor_a_empenhar` a partir da
    Execução Anual quando a NE já foi encontrada, em vez das colunas manuais
    `meses_empenhados`/`meses_liquidados` da planilha — dados sintéticos, sem depender de
    fixture (mesmo padrão de `tests/test_contratos_continuos.py::TestNecessidadeViaExecucaoAnual`)."""

    def _por_ne(self, linhas: list[tuple[str, float, float]]) -> pd.DataFrame:
        registros = [
            {"ne_ccor": "00000000000" + curta, "empenhada": empenhada, "liquidada": liquidada, "saldo": empenhada - liquidada}
            for curta, empenhada, liquidada in linhas
        ]
        return pd.DataFrame(registros, columns=["ne_ccor", "empenhada", "liquidada", "saldo"])

    def _df(self, linhas: list[dict]) -> pd.DataFrame:
        base = {
            "ne_curta": pd.NA, "valor_mensal": 0.0, "valor_empenhado_tg": 0.0,
            "saldo_colado_planilha": 0.0, "meses_empenhados": 0.0, "meses_liquidados": 0.0,
        }
        df = pd.DataFrame([{**base, **linha} for linha in linhas])
        df["meses_a_empenhar"], df["valor_a_empenhar"] = calcular_necessidade_empenho(
            df["meses_empenhados"], df["meses_liquidados"], df["valor_mensal"]
        )
        return df

    def test_ne_encontrada_recalcula_a_partir_da_execucao_com_fracao_exata(self):
        df = self._df([{
            "ne_curta": "2026NE000001", "valor_mensal": 1000.0,
            "meses_empenhados": 99.0, "meses_liquidados": 99.0,  # valor da planilha — deve ser ignorado
        }])
        resultado = com_saldo_execucao(df, self._por_ne([("2026NE000001", 5000.0, 2500.0)]))
        self.assertEqual(resultado.loc[0, "necessidade_via"], "execucao")
        self.assertAlmostEqual(resultado.loc[0, "meses_empenhados_execucao"], 5.0)
        self.assertAlmostEqual(resultado.loc[0, "meses_liquidados_execucao"], 2.5)
        self.assertAlmostEqual(resultado.loc[0, "meses_a_empenhar"], 2.5)
        self.assertAlmostEqual(resultado.loc[0, "valor_a_empenhar"], 2500.0)

    def test_sem_ne_mantem_valor_da_planilha(self):
        df = self._df([{"ne_curta": pd.NA, "valor_mensal": 1000.0, "meses_empenhados": 3.0, "meses_liquidados": 1.0}])
        resultado = com_saldo_execucao(df, self._por_ne([]))
        self.assertEqual(resultado.loc[0, "necessidade_via"], "planilha")
        self.assertTrue(pd.isna(resultado.loc[0, "meses_empenhados_execucao"]))
        self.assertAlmostEqual(resultado.loc[0, "valor_a_empenhar"], 2000.0)

    def test_ne_nao_encontrada_na_execucao_mantem_valor_da_planilha(self):
        df = self._df([{
            "ne_curta": "2026NE000099", "valor_mensal": 1000.0,
            "meses_empenhados": 3.0, "meses_liquidados": 1.0,
        }])
        resultado = com_saldo_execucao(df, self._por_ne([("2026NE000001", 5000.0, 2500.0)]))
        self.assertEqual(resultado.loc[0, "necessidade_via"], "planilha")
        self.assertAlmostEqual(resultado.loc[0, "valor_a_empenhar"], 2000.0)

    def test_valor_mensal_zero_mantem_planilha(self):
        df = self._df([{
            "ne_curta": "2026NE000003", "valor_mensal": 0.0,
            "meses_empenhados": 3.0, "meses_liquidados": 1.0,
        }])
        resultado = com_saldo_execucao(df, self._por_ne([("2026NE000003", 5000.0, 2500.0)]))
        self.assertEqual(resultado.loc[0, "necessidade_via"], "planilha")


if __name__ == "__main__":
    unittest.main()
