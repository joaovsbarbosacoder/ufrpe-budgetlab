"""Testes do leitor de Contratos Contínuos (src/contratos_continuos.py).

Usa uma fixture congelada em `tests/fixtures/` (não a planilha de trabalho em `data/raw/`,
que é substituída a cada atualização) — pulado se o arquivo não existir. Os casos de
divergência de saldo (`2026NE000350`, `2026NE000094`) foram originalmente confirmados
manualmente contra a Execução Anual ativa em 13/08/2026, mesma data da fixture (ver histórico
da conversa) — `TestSaldoViaExecucaoMensal` recalibrou em 22/09/2026 contra a Execução
Mensal, a fonte usada pela página real desde então (ver docstring daquela classe). Valor
empenhado (`valor_empenhado_execucao`, comparado contra a soma por NE — ver docstring de
`com_saldo_execucao`) tem casos isolados na mesma fixture (`2026NE000148`, diferença pequena
de arredondamento; `2026NE000178`, planilha zerada mas com valor real na Execução).

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

from src.contratos_continuos import ErroLayoutBase, NOME_ABA, com_meses_pagos, com_saldo_execucao, ler_contratos_continuos
from src.execucao_ne_utils import saldo_por_ne
from src.importacao_execucao_mensal import carregar_atual
from src.necessidade_empenho import calcular_necessidade_empenho
from src.tesouro_execucao_mensal import agregar_por_ne

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
    CAMINHO_BASE.exists() and Path("data/manifestos/execucao_mensal_atual.json").exists(),
    "Planilha de Contratos Contínuos ou manifesto de Execução Mensal ausente",
)
class TestSaldoViaExecucaoMensal(unittest.TestCase):
    """Confere `saldo_execucao`/`diverge_saldo` contra os casos já levantados manualmente.

    Números recalibrados em 22/09/2026: Contratos Contínuos/Bolsas/Contratos Pagamentos
    pararam de depender da Execução Anual (pedido do usuário) — `por_ne_execucao` agora vem
    da Execução Mensal (`src.tesouro_execucao_mensal.agregar_por_ne`), não mais de
    `src.execucao_anual.agregar_por_ne`. Os valores de saldo/empenhado dos NEs já citados
    abaixo (350, 094, 082, 148, 178) bateram EXATAMENTE iguais aos já calibrados contra a
    Execução Anual em 26/08 — só a CONTAGEM total de divergências mudou (31, não mais 32,
    pra saldo; 31, não mais 30, pra valor empenhado), porque outros NEs da fixture (fora do
    conjunto usado como exemplo nomeado) têm movimento mais recente que diverge entre as
    duas fontes. NE 2026NE000082 continua batendo exatamente nas duas comparações."""

    @classmethod
    def setUpClass(cls):
        # `carregar_atual` da Execução MENSAL — mesmo carregador que a página usa de verdade,
        # não a leitura de um único arquivo: assim o teste nunca fica desalinhado do que a
        # Execução Mensal "atual" realmente é depois de uma importação nova.
        df_execucao = carregar_atual()
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
        self.assertAlmostEqual(linha["saldo_execucao"], 2079460.86, places=2)
        self.assertTrue(bool(linha["diverge_saldo"]))

    def test_ne_094_diverge_por_liquidacao_nao_capturada_na_planilha(self):
        linha = self._linha("2026NE000094")
        self.assertAlmostEqual(linha["saldo_colado_planilha"], 39221.85, places=2)
        self.assertAlmostEqual(linha["saldo_execucao"], 60744.90, places=2)
        self.assertTrue(bool(linha["diverge_saldo"]))

    def test_ne_082_bate_exatamente(self):
        linha = self._linha("2026NE000082")
        self.assertAlmostEqual(linha["saldo_colado_planilha"], 140160.23, places=2)
        self.assertAlmostEqual(linha["saldo_execucao"], 140160.23, places=2)
        self.assertFalse(bool(linha["diverge_saldo"]))

    def test_quantidade_total_de_divergencias_bate_com_o_levantamento(self):
        unicos = self.df.dropna(subset=["ne_curta"]).drop_duplicates("ne_curta")
        self.assertEqual(int(unicos["diverge_saldo"].sum()), 31)

    def test_valor_empenhado_e_somado_por_ne_antes_de_comparar(self):
        # NE 116 tem 5 itens (ver investigação da fixture) — valor_empenhado da linha
        # continua sendo o do item, mas o total comparado contra a Execução é a soma da NE.
        linhas = self.df[self.df["ne_curta"] == "2026NE000116"]
        self.assertGreater(len(linhas), 1)
        soma_itens = linhas["valor_empenhado"].sum()
        totais_ne = linhas["valor_empenhado_planilha_total_ne"].unique()
        self.assertEqual(len(totais_ne), 1)
        self.assertAlmostEqual(totais_ne[0], soma_itens, places=2)

    def test_ne_148_diverge_valor_empenhado(self):
        # até 13/08 era só arredondamento do rateio (R$ 4,44 de diferença); a diferença ficou
        # grande o bastante pra não ser mais só arredondamento — mesma causa geral dos outros
        # NEs: planilha desatualizada. Valor idêntico ao já calibrado contra a Execução Anual.
        linha = self._linha("2026NE000148")
        self.assertAlmostEqual(linha["valor_empenhado_planilha_total_ne"], 22209.56, places=2)
        self.assertAlmostEqual(linha["valor_empenhado_execucao"], 28820.0, places=2)
        self.assertTrue(bool(linha["diverge_valor_empenhado"]))

    def test_ne_178_diverge_porque_planilha_esta_zerada(self):
        linha = self._linha("2026NE000178")
        self.assertAlmostEqual(linha["valor_empenhado_planilha_total_ne"], 0.0, places=2)
        self.assertAlmostEqual(linha["valor_empenhado_execucao"], 9610.0, places=2)
        self.assertTrue(bool(linha["diverge_valor_empenhado"]))

    def test_ne_082_valor_empenhado_bate_exatamente(self):
        linha = self._linha("2026NE000082")
        self.assertAlmostEqual(linha["valor_empenhado_planilha_total_ne"], 581056.92, places=2)
        self.assertAlmostEqual(linha["valor_empenhado_execucao"], 581056.92, places=2)
        self.assertFalse(bool(linha["diverge_valor_empenhado"]))

    def test_quantidade_total_de_divergencias_de_valor_empenhado_bate_com_o_levantamento(self):
        unicos = self.df.dropna(subset=["ne_curta"]).drop_duplicates("ne_curta")
        self.assertEqual(int(unicos["diverge_valor_empenhado"].sum()), 31)

    def test_necessidade_de_empenho_recalculada_para_ne_encontradas_na_execucao(self):
        # para toda linha marcada "execucao" (meses_empenhados_execucao/meses_liquidados_execucao
        # em vez das colunas manuais da planilha), meses_a_empenhar/valor_a_empenhar têm que
        # bater com a mesma fórmula de necessidade_empenho.py aplicada aos dois novos campos.
        via_execucao = self.df[self.df["necessidade_via"] == "execucao"]
        self.assertFalse(via_execucao.empty)
        for _, linha in via_execucao.iterrows():
            meses_esperado = linha["meses_empenhados_execucao"] - linha["meses_liquidados_execucao"]
            self.assertAlmostEqual(linha["meses_a_empenhar"], meses_esperado, places=6)
            if pd.notna(linha["despesa_mensal"]):
                self.assertAlmostEqual(linha["valor_a_empenhar"], linha["despesa_mensal"] * meses_esperado, places=2)


class TestNecessidadeViaExecucao(unittest.TestCase):
    """`com_saldo_execucao` recalcula `meses_a_empenhar`/`valor_a_empenhar` a partir da
    Execução (Mensal, desde 22/09/2026 — antes Anual) quando a NE já foi encontrada, em vez
    das colunas manuais `meses_empenhados`/`meses_liquidados` da planilha — dados sintéticos,
    sem depender de fixture nem da base real (`com_saldo_execucao` não sabe nem se importa de
    onde `por_ne_execucao` veio, ver docstring de `src.execucao_ne_utils`); ver
    `TestSaldoViaExecucaoMensal` para a confirmação contra dado real."""

    def _por_ne(self, linhas: list[tuple[str, float, float]]) -> pd.DataFrame:
        registros = [
            {"ne_ccor": "00000000000" + curta, "empenhada": empenhada, "liquidada": liquidada, "saldo": empenhada - liquidada}
            for curta, empenhada, liquidada in linhas
        ]
        return pd.DataFrame(registros, columns=["ne_ccor", "empenhada", "liquidada", "saldo"])

    def _df(self, linhas: list[dict]) -> pd.DataFrame:
        base = {
            "ne_curta": pd.NA, "despesa_mensal": 0.0, "valor_empenhado": 0.0,
            "saldo_colado_planilha": 0.0, "meses_empenhados": 0.0, "meses_liquidados": 0.0,
        }
        df = pd.DataFrame([{**base, **linha} for linha in linhas])
        df["meses_a_empenhar"], df["valor_a_empenhar"] = calcular_necessidade_empenho(
            df["meses_empenhados"], df["meses_liquidados"], df["despesa_mensal"]
        )
        return df

    def test_ne_encontrada_recalcula_a_partir_da_execucao_com_fracao_exata(self):
        # regra confirmada com o usuário: fração exata, sem arredondar meses.
        df = self._df([{
            "ne_curta": "2026NE000001", "despesa_mensal": 1000.0,
            "meses_empenhados": 99.0, "meses_liquidados": 99.0,  # valor da planilha — deve ser ignorado
        }])
        resultado = com_saldo_execucao(df, self._por_ne([("2026NE000001", 5000.0, 2500.0)]))
        self.assertEqual(resultado.loc[0, "necessidade_via"], "execucao")
        self.assertAlmostEqual(resultado.loc[0, "meses_empenhados_execucao"], 5.0)
        self.assertAlmostEqual(resultado.loc[0, "meses_liquidados_execucao"], 2.5)
        self.assertAlmostEqual(resultado.loc[0, "meses_a_empenhar"], 2.5)
        self.assertAlmostEqual(resultado.loc[0, "valor_a_empenhar"], 2500.0)

    def test_sem_ne_mantem_valor_da_planilha(self):
        df = self._df([{"ne_curta": pd.NA, "despesa_mensal": 1000.0, "meses_empenhados": 3.0, "meses_liquidados": 1.0}])
        resultado = com_saldo_execucao(df, self._por_ne([]))
        self.assertEqual(resultado.loc[0, "necessidade_via"], "planilha")
        self.assertTrue(pd.isna(resultado.loc[0, "meses_empenhados_execucao"]))
        self.assertAlmostEqual(resultado.loc[0, "meses_a_empenhar"], 2.0)
        self.assertAlmostEqual(resultado.loc[0, "valor_a_empenhar"], 2000.0)

    def test_ne_nao_encontrada_na_execucao_mantem_valor_da_planilha(self):
        df = self._df([{
            "ne_curta": "2026NE000099", "despesa_mensal": 1000.0,
            "meses_empenhados": 3.0, "meses_liquidados": 1.0,
        }])
        resultado = com_saldo_execucao(df, self._por_ne([("2026NE000001", 5000.0, 2500.0)]))
        self.assertEqual(resultado.loc[0, "necessidade_via"], "planilha")
        self.assertAlmostEqual(resultado.loc[0, "valor_a_empenhar"], 2000.0)

    def test_contrato_com_varios_itens_usa_despesa_mensal_somada_por_ne(self):
        # mesmo critério de rateio de `valor_empenhado_planilha_total_ne`: a razão
        # meses_empenhados_execucao/meses_liquidados_execucao é da NE inteira (repetida em
        # todo item), não recalculada por item — só o valor_a_empenhar final usa a despesa
        # mensal do item.
        df = self._df([
            {"ne_curta": "2026NE000002", "despesa_mensal": 600.0},
            {"ne_curta": "2026NE000002", "despesa_mensal": 400.0},
        ])
        resultado = com_saldo_execucao(df, self._por_ne([("2026NE000002", 3000.0, 1000.0)]))
        self.assertTrue((resultado["meses_empenhados_execucao"] == 3.0).all())
        self.assertTrue((resultado["meses_liquidados_execucao"] == 1.0).all())
        self.assertAlmostEqual(resultado.loc[0, "valor_a_empenhar"], 600.0 * 2)
        self.assertAlmostEqual(resultado.loc[1, "valor_a_empenhar"], 400.0 * 2)

    def test_despesa_mensal_total_ne_zero_mantem_planilha(self):
        # divisão por zero não pode acontecer — fica no fallback da planilha.
        df = self._df([{
            "ne_curta": "2026NE000003", "despesa_mensal": 0.0,
            "meses_empenhados": 3.0, "meses_liquidados": 1.0,
        }])
        resultado = com_saldo_execucao(df, self._por_ne([("2026NE000003", 5000.0, 2500.0)]))
        self.assertEqual(resultado.loc[0, "necessidade_via"], "planilha")
        # despesa_mensal também é 0 nesta linha (é o próprio motivo de despesa_mensal_total_ne
        # dar zero) — o fallback preserva meses_a_empenhar (3 - 1 = 2), mas valor_a_empenhar
        # é 0 × 2, não um valor mensal diferente.
        self.assertAlmostEqual(resultado.loc[0, "meses_a_empenhar"], 2.0)
        self.assertAlmostEqual(resultado.loc[0, "valor_a_empenhar"], 0.0)


class TestLiquidadoViaCompetencia(unittest.TestCase):
    """`com_saldo_execucao(..., indice_liquidado_competencia=...)` — pedido explícito do
    usuário: "Necessidade de Empenho" passa a usar a Liquidação por Competência em vez da
    Execução Mensal (mês de lançamento) para `valor_liquidado_execucao`, quando disponível."""

    def _por_ne(self, linhas: list[tuple[str, float, float]]) -> pd.DataFrame:
        registros = [
            {"ne_ccor": "00000000000" + curta, "empenhada": empenhada, "liquidada": liquidada, "saldo": empenhada - liquidada}
            for curta, empenhada, liquidada in linhas
        ]
        return pd.DataFrame(registros, columns=["ne_ccor", "empenhada", "liquidada", "saldo"])

    def _df(self, linhas: list[dict]) -> pd.DataFrame:
        base = {
            "ne_curta": pd.NA, "despesa_mensal": 0.0, "valor_empenhado": 0.0,
            "saldo_colado_planilha": 0.0, "meses_empenhados": 0.0, "meses_liquidados": 0.0,
        }
        df = pd.DataFrame([{**base, **linha} for linha in linhas])
        df["meses_a_empenhar"], df["valor_a_empenhar"] = calcular_necessidade_empenho(
            df["meses_empenhados"], df["meses_liquidados"], df["despesa_mensal"]
        )
        return df

    def test_sem_indice_competencia_usa_execucao_como_antes(self):
        df = self._df([{
            "ne_curta": "2026NE000001", "despesa_mensal": 1000.0,
            "meses_empenhados": 99.0, "meses_liquidados": 99.0,
        }])
        resultado = com_saldo_execucao(df, self._por_ne([("2026NE000001", 5000.0, 2500.0)]))
        self.assertFalse(bool(resultado.loc[0, "liquidado_via_competencia"]))
        self.assertAlmostEqual(resultado.loc[0, "valor_liquidado_execucao"], 2500.0)
        self.assertAlmostEqual(resultado.loc[0, "meses_liquidados_execucao"], 2.5)

    def test_com_indice_competencia_ne_encontrada_substitui_o_liquidado(self):
        df = self._df([{"ne_curta": "2026NE000001", "despesa_mensal": 1000.0}])
        por_ne = self._por_ne([("2026NE000001", 5000.0, 2500.0)])  # liquidada da Execução: 2500
        indice_competencia = pd.Series({"2026NE000001": 4000.0})  # competência diverge do lançamento
        resultado = com_saldo_execucao(df, por_ne, indice_competencia)
        self.assertTrue(bool(resultado.loc[0, "liquidado_via_competencia"]))
        self.assertAlmostEqual(resultado.loc[0, "valor_liquidado_execucao"], 4000.0)
        self.assertAlmostEqual(resultado.loc[0, "meses_liquidados_execucao"], 4.0)
        self.assertEqual(resultado.loc[0, "necessidade_via"], "execucao")

    def test_com_indice_competencia_ne_ausente_cai_para_planilha(self):
        # NE existe na Execução Mensal (tem saldo/empenhado), mas não tem nenhuma linha de
        # competência apurada — não deve usar o valor de lançamento como substituto
        # silencioso: cai no mesmo fallback de "sem correspondência" de sempre (planilha).
        df = self._df([{
            "ne_curta": "2026NE000002", "despesa_mensal": 1000.0,
            "meses_empenhados": 3.0, "meses_liquidados": 1.0,
        }])
        por_ne = self._por_ne([("2026NE000002", 5000.0, 2500.0)])
        indice_competencia = pd.Series({"2026NE000999": 4000.0}, dtype="float64")  # outra NE, não esta
        resultado = com_saldo_execucao(df, por_ne, indice_competencia)
        self.assertTrue(bool(resultado.loc[0, "liquidado_via_competencia"]))
        self.assertTrue(pd.isna(resultado.loc[0, "valor_liquidado_execucao"]))
        self.assertEqual(resultado.loc[0, "necessidade_via"], "planilha")
        self.assertAlmostEqual(resultado.loc[0, "valor_a_empenhar"], 2000.0)


class TestComMesesPagos(unittest.TestCase):
    """`com_meses_pagos` — indicador independente vindo da planilha de Pagamentos, casado por
    número de contrato normalizado (não pela NE). Dados sintéticos (não depende de fixture de
    Pagamentos): cobre casamento exato, casamento por normalização (zero à esquerda/sufixo de
    unidade), e contrato sem correspondência."""

    def _contratos(self, numeros: list[str]) -> pd.DataFrame:
        return pd.DataFrame({"contrato_numero": numeros})

    def _meses_pagos(self, linhas: list[tuple[str, int, str]]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"contrato_normalizado": normalizado, "meses_pagos": meses, "ultimo_mes_pago": pd.Timestamp(mes)}
                for normalizado, meses, mes in linhas
            ],
            columns=["contrato_normalizado", "meses_pagos", "ultimo_mes_pago"],
        )

    def test_casamento_exato(self):
        df = com_meses_pagos(self._contratos(["23/2025"]), self._meses_pagos([("23/2025", 7, "2026-08-01")]))
        self.assertEqual(df.loc[0, "meses_pagos"], 7)
        self.assertEqual(df.loc[0, "ultimo_mes_pago"], pd.Timestamp("2026-08-01"))

    def test_casamento_por_normalizacao_zero_a_esquerda(self):
        # Contínuos "08/2023" precisa casar com o mesmo contrato já normalizado como "8/2023"
        # na planilha de Pagamentos (ver `normalizar_numero_contrato`).
        df = com_meses_pagos(self._contratos(["08/2023"]), self._meses_pagos([("8/2023", 8, "2026-08-01")]))
        self.assertEqual(df.loc[0, "meses_pagos"], 8)

    def test_contrato_sem_correspondencia_fica_nulo_nao_zero(self):
        df = com_meses_pagos(self._contratos(["99/2099"]), self._meses_pagos([("23/2025", 7, "2026-08-01")]))
        self.assertTrue(pd.isna(df.loc[0, "meses_pagos"]))
        self.assertTrue(pd.isna(df.loc[0, "ultimo_mes_pago"]))

    def test_contrato_sem_numero_reconhecivel_fica_nulo(self):
        df = com_meses_pagos(self._contratos([None]), self._meses_pagos([("23/2025", 7, "2026-08-01")]))
        self.assertTrue(pd.isna(df.loc[0, "meses_pagos"]))

    def test_planilha_de_pagamentos_vazia_nao_quebra(self):
        vazio = pd.DataFrame(columns=["contrato_normalizado", "meses_pagos", "ultimo_mes_pago"])
        df = com_meses_pagos(self._contratos(["23/2025"]), vazio)
        self.assertTrue(pd.isna(df.loc[0, "meses_pagos"]))


if __name__ == "__main__":
    unittest.main()
