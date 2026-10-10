"""Testes do leitor de Contratos Contínuos (src/contratos_continuos.py).

Usa uma fixture congelada em `tests/fixtures/` (não a planilha de trabalho em `data/raw/`,
que é substituída a cada atualização) — pulado se o arquivo não existir. Os casos de
divergência de saldo (`2026NE000350`, `2026NE000094`) foram originalmente confirmados
manualmente contra a Execução Anual ativa em 13/08/2026, mesma data da fixture (ver histórico
da conversa) — `TestSaldoViaExecucaoMensal` confere contra a Execução Mensal (a fonte usada
pela página real), lida de uma fixture congelada (`CAMINHO_EXECUCAO_MENSAL`), não da
importação atual em `data/manifestos/` (ver docstring daquela classe). Valor
empenhado (`valor_empenhado_execucao`, comparado contra a soma por NE — ver docstring de
`com_saldo_execucao`) tem casos isolados na mesma fixture (`2026NE000148`, diferença pequena
de arredondamento; `2026NE000178`, planilha zerada mas com valor real na Execução).

IMPORTANTE: ao atualizar a planilha de trabalho em `data/raw/`, NÃO sobrescreva esta fixture
automaticamente — ver AGENTS.md, seção sobre atualização de dados de Contratos
Contínuos/Bolsas, para o procedimento de substituição deliberada.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import openpyxl
import pandas as pd

from src.contratos_cadastro import montar_contratos, montar_empenhos, montar_termos
from src.contratos_continuos import (
    DESPESA_CONTRATUAL,
    DESPESA_EMPENHADO_SUSPENSO,
    ErroLayoutBase,
    NOME_ABA,
    SITUACOES_CONCILIACAO,
    aditivo_sugerido,
    aditivos_pendentes,
    candidatos_novos,
    com_contratosgov,
    com_efeitos_da_suspensao,
    com_meses_pagos,
    com_saldo_execucao,
    filtrar_candidatos,
    ler_contratos_continuos,
    numero_no_formato_continuos,
    registro_novo_do_gov,
    tipo_aditivo_por_qualificacao,
)
from src.contratos_aditivos import Aditivo, aditivos_do_registro
from src.contratos_continuos_cadastro import como_dataframe, novo_contrato
from src.execucao_ne_utils import saldo_por_ne
from src.necessidade_empenho import calcular_necessidade_empenho
from src.tesouro_execucao_mensal import agregar_por_ne, ler_execucao_mensal

CAMINHO_BASE = Path("tests/fixtures/contratos_continuos_2026-08-13.xlsm")
#: Execução Mensal congelada (a mesma de tests/test_bolsas_auxilios.py e
#: tests/test_consulta_empenhos_page.py) — valores esperados de `TestSaldoViaExecucaoMensal`
#: conferidos à mão contra ela.
CAMINHO_EXECUCAO_MENSAL = Path("tests/fixtures/execucao_mensal_2026-09-22.xlsx")


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
    CAMINHO_BASE.exists() and CAMINHO_EXECUCAO_MENSAL.exists(),
    "Fixture de Contratos Contínuos ou de Execução Mensal ausente",
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
    duas fontes. NE 2026NE000082 continua batendo exatamente nas duas comparações.

    DESACOPLADO DA IMPORTAÇÃO ATUAL (30/09/2026, mesma correção de test_bolsas_auxilios.py):
    a Execução Mensal era lida ao vivo (`carregar_atual()`), e qualquer importação nova que
    mexesse nestas NEs quebraria o teste sem regressão real. Agora vem da fixture congelada
    `CAMINHO_EXECUCAO_MENSAL` (extração de 22/09). Todos os valores abaixo continuaram
    idênticos contra ela; conferidos à mão: NE 350 empenhado 3.112.763,78 − liquidado
    1.033.302,92 = 2.079.460,86; NE 094 162.070,80 − 101.325,90 = 60.744,90."""

    @classmethod
    def setUpClass(cls):
        # mesmo leitor/agregação que a página usa (`agregar_por_ne` da Execução MENSAL), só que
        # sobre a fixture congelada em vez da importação atual.
        df_execucao = ler_execucao_mensal(CAMINHO_EXECUCAO_MENSAL)
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


class TestEfeitosDaSuspensao(unittest.TestCase):
    """Contrato SUSPENSO só produz efeito pelo já empenhado/liquidado (pedido explícito, 06/10/2026):
    Despesa anual (e Cobertura por PTRES) = empenhado; "Saldo a liquidar (execução)" = 0. Valores à mão."""

    @staticmethod
    def _df() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "ne_curta": ["2026NE000001", "2026NE000002", "2026NE000003", None],
                "status_contrato": ["ATIVO", "suspenso", "SUSPENSO", "SUSPENSO"],
                "despesa_anual": [12_000.0, 24_000.0, 6_000.0, 3_600.0],
                "valor_empenhado": [5_000.0, 9_000.0, 1_500.0, float("nan")],
                "valor_empenhado_execucao": [7_000.0, 10_000.0, float("nan"), float("nan")],
                "meses_a_empenhar": [2.0, 3.0, 1.0, 1.0],
                "valor_a_empenhar": [2_000.0, 6_000.0, 500.0, 300.0],
                "saldo_execucao": [1_000.0, 4_000.0, float("nan"), float("nan")],
            }
        )

    def test_ativo_nao_muda(self):
        resultado = com_efeitos_da_suspensao(self._df())
        self.assertEqual(resultado.loc[0, "despesa_anual"], 12_000.0)
        self.assertEqual(resultado.loc[0, "valor_a_empenhar"], 2_000.0)
        self.assertEqual(resultado.loc[0, "despesa_anual_base"], DESPESA_CONTRATUAL)

    def test_suspenso_usa_o_empenhado_da_execucao_e_zera_o_a_empenhar(self):
        resultado = com_efeitos_da_suspensao(self._df())
        self.assertEqual(resultado.loc[1, "despesa_anual"], 10_000.0)  # Execução, não os 24.000 do contrato
        self.assertEqual(resultado.loc[1, "despesa_anual_contratual"], 24_000.0)  # original preservado
        self.assertEqual(resultado.loc[1, "despesa_anual_base"], DESPESA_EMPENHADO_SUSPENSO)
        self.assertEqual((resultado.loc[1, "meses_a_empenhar"], resultado.loc[1, "valor_a_empenhar"]), (0.0, 0.0))
        self.assertEqual(resultado.loc[1, "saldo_execucao"], 4_000.0)  # saldo não muda

    def test_sem_execucao_usa_o_empenhado_do_cadastro_e_nulo_continua_nulo(self):
        resultado = com_efeitos_da_suspensao(self._df())
        self.assertEqual(resultado.loc[2, "despesa_anual"], 1_500.0)
        self.assertTrue(pd.isna(resultado.loc[3, "despesa_anual"]))  # sem empenho conhecido: nulo, não zero

    def test_ne_compartilhada_nao_repete_o_empenho_da_ne_inteira(self):
        df = self._df()
        df.loc[2, "ne_curta"] = "2026NE000002"  # duas linhas na mesma NE (empenho da NE = 10.000)
        df.loc[2, "valor_empenhado_execucao"] = 10_000.0
        resultado = com_efeitos_da_suspensao(df)
        self.assertEqual((resultado.loc[1, "despesa_anual"], resultado.loc[2, "despesa_anual"]), (9_000.0, 1_500.0))

    def test_nao_altera_a_entrada(self):
        df = self._df()
        com_efeitos_da_suspensao(df)
        self.assertEqual(df.loc[1, "despesa_anual"], 24_000.0)
        self.assertNotIn("despesa_anual_base", df.columns)


# --- integração com o Contratos.gov.br (10/2026) -------------------------------------------------

FIXTURE_CONTRATOSGOV = Path("tests/fixtures/contratosgov_2026-10-08.json")
REF_GOV = date(2026, 10, 8)


def _gov():
    """(contratos, termos, empenhos) da fotografia congelada do Contratos.gov.br (6 contratos,
    UG 153165), com a data de referência dos valores conferidos à mão (08/10/2026)."""

    fotografia = json.loads(FIXTURE_CONTRATOSGOV.read_text(encoding="utf-8"))
    return montar_contratos(fotografia, REF_GOV), montar_termos(fotografia), montar_empenhos(fotografia)


def _cadastro(*registros: dict) -> pd.DataFrame:
    return como_dataframe([novo_contrato(**r) for r in registros], 2026, hoje=REF_GOV)


@unittest.skipUnless(FIXTURE_CONTRATOSGOV.exists(), f"Fixture ausente em {FIXTURE_CONTRATOSGOV}")
class TestComContratosGov(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contratos, cls.termos, cls.empenhos = _gov()

    def _ligar(self, *registros: dict, contratos=None, empenhos=None) -> pd.DataFrame:
        return com_contratosgov(
            _cadastro(*registros),
            self.contratos if contratos is None else contratos,
            self.termos,
            self.empenhos if empenhos is None else empenhos,
        )

    def test_liga_por_ne(self):
        linha = self._ligar(
            {"contrato_numero": "13/2026", "ne_curta": "2026NE000522", "vigencia_fim": pd.Timestamp("2027-09-10")}
        ).iloc[0]
        self.assertEqual(linha["contratosgov_id"], "1004328")
        self.assertEqual(linha["ligacao_por"], "ne")
        self.assertEqual(linha["situacao_conciliacao"], "conciliado")
        self.assertFalse(linha["diverge_vigencia"])
        self.assertEqual(linha["qtd_termos"], 1)
        self.assertEqual(linha["qtd_aditivos_gov"], 0)
        self.assertEqual(linha["situacao_vigencia_gov"], "vigente")
        self.assertEqual(linha["vigencia_fim_contratosgov"], date(2027, 9, 10))

    def test_ne_com_espacos_e_minusculas_liga(self):
        linha = self._ligar({"contrato_numero": "13/2026", "ne_curta": " 2026ne000522 "}).iloc[0]
        self.assertEqual(linha["contratosgov_id"], "1004328")

    def test_liga_por_numero_e_cnpj_sem_ne(self):
        linha = self._ligar(
            {"contrato_numero": "29/2021", "fornecedor_cnpj_cpf": "07.674.744/0001-30",
             "vigencia_fim": pd.Timestamp("2026-10-17")}
        ).iloc[0]
        self.assertEqual(linha["ligacao_por"], "numero")
        self.assertEqual(linha["contratosgov_id"], "118872")
        self.assertEqual(linha["qtd_termos"], 5)
        self.assertEqual(linha["qtd_aditivos_gov"], 4)
        self.assertEqual(linha["situacao_conciliacao"], "conciliado")

    def test_cnpj_sem_zero_a_esquerda_liga_por_numero(self):
        # o cadastro real tem CNPJs que perderam o zero inicial ("3508097000136"); a comparação ignora os
        # zeros à esquerda dos DOIS lados, sem alterar o que está gravado
        registro = {"contrato_numero": "13/2026", "fornecedor_cnpj_cpf": "5340639000130"}  # gov: 05340639000130
        linha = self._ligar(registro).iloc[0]
        self.assertEqual((linha["ligacao_por"], linha["contratosgov_id"]), ("numero", "1004328"))
        pf = self._ligar({"contrato_numero": "21/2023", "fornecedor_cnpj_cpf": "191"}).iloc[0]  # gov: 00000000191
        self.assertEqual(pf["contratosgov_id"], "220038")

    def test_cnpj_so_de_zeros_nao_liga(self):
        linha = self._ligar({"contrato_numero": "13/2026", "fornecedor_cnpj_cpf": "000"}).iloc[0]
        self.assertEqual(linha["situacao_conciliacao"], "sem_par_no_contratosgov")

    def test_numero_sem_cnpj_nao_liga(self):
        linha = self._ligar({"contrato_numero": "29/2021"}).iloc[0]
        self.assertEqual(linha["situacao_conciliacao"], "sem_par_no_contratosgov")
        self.assertTrue(pd.isna(linha["contratosgov_id"]))

    def test_divergente_e_aditivo_nativo_concilia(self):
        base = {"contrato_numero": "29/2021", "ne_curta": "2025NE000046", "vigencia_fim": pd.Timestamp("2025-10-17")}
        divergente = self._ligar(base).iloc[0]
        self.assertEqual(divergente["situacao_conciliacao"], "divergente")
        self.assertTrue(divergente["diverge_vigencia"])
        self.assertEqual(divergente["vigencia_fim_contratosgov"], date(2026, 10, 17))

        aditivo = {"numero": "4", "tipo": "PRORROGACAO", "situacao": "ASSINADO",
                   "data_inicio": "2025-10-18", "vigencia_fim": "2026-10-17"}
        conciliado = self._ligar({**base, "aditivos": [aditivo]}).iloc[0]
        self.assertEqual(conciliado["situacao_conciliacao"], "conciliado")
        self.assertFalse(conciliado["diverge_vigencia"])

    def test_conflito_ne_e_numero(self):
        linha = self._ligar(
            {"contrato_numero": "13/2026", "fornecedor_cnpj_cpf": "05340639000130", "ne_curta": "2025NE000046"}
        ).iloc[0]
        self.assertEqual(linha["situacao_conciliacao"], "conflito")
        self.assertTrue(pd.isna(linha["contratosgov_id"]))
        self.assertTrue(pd.isna(linha["vigencia_fim_contratosgov"]))
        self.assertTrue(pd.isna(linha["diverge_vigencia"]))

    def test_ne_em_dois_contratos_e_conflito(self):
        duplicada = pd.concat(
            [self.empenhos, self.empenhos[self.empenhos["ne"] == "2026NE000522"].assign(contrato_id="118872")],
            ignore_index=True,
        )
        linha = self._ligar({"contrato_numero": "13/2026", "ne_curta": "2026NE000522"}, empenhos=duplicada).iloc[0]
        self.assertEqual(linha["situacao_conciliacao"], "conflito")

    def test_varios_registros_do_mesmo_contrato(self):
        df = self._ligar(
            {"contrato_numero": "13/2026", "ne_curta": "2026NE000522"},
            {"contrato_numero": "13/2026", "ne_curta": "2026NE000523"},
        )
        self.assertEqual(list(df["contratosgov_id"]), ["1004328", "1004328"])

    def test_sem_par_e_ne_nula_nao_casam_entre_si(self):
        df = self._ligar({"contrato_numero": "99/2026", "ne_curta": "2026NE999999"}, {"contrato_numero": "98/2026"})
        self.assertEqual(set(df["situacao_conciliacao"]), {"sem_par_no_contratosgov"})
        self.assertTrue(df["diverge_vigencia"].isna().all())
        self.assertTrue(df["contratosgov_id"].isna().all())

    def test_vigencia_nula_nao_e_divergencia(self):
        linha = self._ligar({"contrato_numero": "13/2026", "ne_curta": "2026NE000522"}).iloc[0]
        self.assertEqual(linha["situacao_conciliacao"], "sem_data_para_comparar")
        self.assertTrue(pd.isna(linha["diverge_vigencia"]))
        self.assertEqual(linha["contratosgov_id"], "1004328")

    def test_contrato_encerrado_no_gov(self):
        linha = self._ligar({"contrato_numero": "18/2014", "ne_curta": "2021NE000072"}).iloc[0]
        self.assertEqual(linha["situacao_vigencia_gov"], "encerrado")

    def test_situacoes_conhecidas(self):
        df = self._ligar(
            {"contrato_numero": "13/2026", "ne_curta": "2026NE000522", "vigencia_fim": pd.Timestamp("2027-09-10")},
            {"contrato_numero": "99/2026"},
        )
        self.assertTrue(set(df["situacao_conciliacao"]) <= set(SITUACOES_CONCILIACAO))

    def test_nao_altera_linhas_nem_valores(self):
        original = _cadastro(
            {"contrato_numero": "13/2026", "ne_curta": "2026NE000522", "despesa_mensal": 1000.0},
            {"contrato_numero": "99/2026"},
        )
        resultado = com_contratosgov(original, self.contratos, self.termos, self.empenhos)
        self.assertEqual(len(resultado), len(original))
        pd.testing.assert_frame_equal(resultado[list(original.columns)], original)

    def test_df_vazio_devolve_colunas_novas(self):
        resultado = com_contratosgov(_cadastro(), self.contratos, self.termos, self.empenhos)
        self.assertEqual(len(resultado), 0)
        for coluna in ("contratosgov_id", "ligacao_por", "situacao_conciliacao", "situacao_vigencia_gov",
                       "vigencia_fim_contratosgov", "diverge_vigencia", "qtd_termos", "qtd_aditivos_gov",
                       "valor_parcela_contratosgov"):
            self.assertIn(coluna, resultado.columns)


class TestTipoDoAditivoPorQualificacao(unittest.TestCase):
    def test_tipo_por_qualificacao(self):
        casos = {
            "VIGÊNCIA; REAJUSTE": "REAJUSTE",
            "VIGÊNCIA": "PRORROGACAO",
            "ACRÉSCIMO / SUPRESSÃO": "ACRESCIMO_SUPRESSAO",
            "INFORMATIVO; ACRÉSCIMO / SUPRESSÃO; VIGÊNCIA": "PRORROGACAO",
            "INFORMATIVO": "OUTRO",
            "": "OUTRO",
            None: "OUTRO",
            pd.NA: "OUTRO",
        }
        for qualificacao, esperado in casos.items():
            with self.subTest(qualificacao=qualificacao):
                self.assertEqual(tipo_aditivo_por_qualificacao(qualificacao), esperado)


@unittest.skipUnless(FIXTURE_CONTRATOSGOV.exists(), f"Fixture ausente em {FIXTURE_CONTRATOSGOV}")
class TestAditivosDoGov(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contratos, cls.termos, cls.empenhos = _gov()

    def _termos(self, contrato_id: str) -> pd.DataFrame:
        return self.termos[self.termos["contrato_id"] == contrato_id]

    def _numeros_pendentes(self, contrato_id: str, aditivos: list[Aditivo]) -> list[str]:
        return list(aditivos_pendentes(aditivos, self._termos(contrato_id))["numero"])

    def test_pendentes_do_118872_sem_aditivos_nativos(self):
        self.assertEqual(
            self._numeros_pendentes("118872", []), ["00001/2022", "00002/2023", "00003/2024", "00004/2025"]
        )

    def test_registrado_por_numero_normalizado(self):
        nativos = aditivos_do_registro([{"numero": "1/2022", "tipo": "REAJUSTE", "situacao": "ASSINADO", "data_inicio": "2022-10-17"}])
        self.assertEqual(self._numeros_pendentes("118872", nativos), ["00002/2023", "00003/2024", "00004/2025"])

    def test_registrado_por_data_de_assinatura(self):
        nativos = aditivos_do_registro(
            [{"numero": "TA", "tipo": "PRORROGACAO", "situacao": "ASSINADO", "data_inicio": "2023-10-18",
              "data_assinatura": "2023-10-17"}]
        )
        self.assertEqual(self._numeros_pendentes("118872", nativos), ["00001/2022", "00003/2024", "00004/2025"])

    def test_apostilamento_e_contrato_nao_sao_aditivos(self):
        self.assertEqual(
            self._numeros_pendentes("18940", []), ["00001/2019", "00002/2021", "00003/2022", "00004/2024"]
        )

    def test_aditivo_sugerido_reajuste(self):
        termo = self._termos("118872").set_index("numero").loc["00004/2025"].rename("00004/2025")
        termo["numero"] = "00004/2025"
        self.assertEqual(
            aditivo_sugerido(termo),
            Aditivo(
                numero="00004/2025", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2025, 10, 18),
                data_assinatura=date(2025, 9, 16), valor_mensal=None, vigencia_fim=date(2026, 10, 17), itens=None,
            ),
        )

    def test_aditivo_sugerido_sem_data_inicio_usa_assinatura(self):
        termo = self._termos("18940").query("numero == '00001/2019'").iloc[0]
        sugerido = aditivo_sugerido(termo)
        self.assertEqual(sugerido.tipo, "PRORROGACAO")
        self.assertEqual(sugerido.data_inicio, date(2019, 11, 28))
        self.assertIsNone(sugerido.valor_mensal)

    def test_termo_sem_numero_usa_o_id_do_termo_e_nao_duplica(self):
        termo = pd.Series(
            {"termo_id": "999", "tipo": "Termo Aditivo", "numero": None, "qualificacao_termo": "VIGÊNCIA",
             "data_assinatura": None, "data_inicio_novo_valor": None, "vigencia_fim": None}
        )
        sugerido = aditivo_sugerido(termo)
        self.assertEqual(sugerido.numero, "TERMO 999")  # nunca o texto "None"
        termos = pd.DataFrame([termo])
        self.assertEqual(len(aditivos_pendentes([], termos)), 1)
        self.assertEqual(len(aditivos_pendentes([sugerido], termos)), 0)  # depois de registrado, não é mais pendente
        vazio = aditivos_do_registro([{"numero": "", "tipo": "OUTRO", "situacao": "ASSINADO", "data_inicio": "2026-01-01"}])
        self.assertEqual(len(aditivos_pendentes(vazio, termos)), 1)  # cartão em branco não "registra" o termo

    def test_aditivo_sugerido_sem_nenhuma_data_deixa_inicio_nulo(self):
        termo = pd.Series(
            {"numero": "00009/2026", "qualificacao_termo": "VIGÊNCIA", "data_assinatura": None,
             "data_inicio_novo_valor": None, "vigencia_fim": None}
        )
        sugerido = aditivo_sugerido(termo)
        self.assertIsNone(sugerido.data_inicio)
        self.assertIsNone(sugerido.vigencia_fim)

    def test_com_contratosgov_conta_pendentes(self):
        df = com_contratosgov(
            _cadastro({"contrato_numero": "29/2021", "ne_curta": "2025NE000046"}, {"contrato_numero": "99/2026"}),
            self.contratos, self.termos, self.empenhos,
        )
        self.assertEqual(df.loc[0, "qtd_aditivos_pendentes"], 4)
        self.assertTrue(pd.isna(df.loc[1, "qtd_aditivos_pendentes"]))


class TestNumeroNoFormatoContinuos(unittest.TestCase):
    def test_formatos(self):
        casos = {
            "00013/2026": "13/2026", "00002/2026": "02/2026", "00018/2014": "18/2014",
            "SN/2026": "SN/2026", "ABC": "ABC", None: None,
        }
        for numero_gov, esperado in casos.items():
            with self.subTest(numero_gov=numero_gov):
                self.assertEqual(numero_no_formato_continuos(numero_gov), esperado)


@unittest.skipUnless(FIXTURE_CONTRATOSGOV.exists(), f"Fixture ausente em {FIXTURE_CONTRATOSGOV}")
class TestCandidatosNovos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contratos, cls.termos, cls.empenhos = _gov()

    def _candidatos(self, *registros: dict, contratos=None):
        return candidatos_novos(
            _cadastro(*registros), self.contratos if contratos is None else contratos, self.empenhos
        )

    def test_com_um_registro_ligado(self):
        candidatos, em_duvida = self._candidatos({"contrato_numero": "13/2026", "ne_curta": "2026NE000522"})
        self.assertEqual(list(candidatos["contrato_id"]), ["118872", "18940", "220038"])  # por vigência crescente
        self.assertEqual(len(em_duvida), 0)
        self.assertTrue(candidatos["motivo"].str.len().gt(0).all())

    def test_cadastro_vazio_lista_os_quatro_vigentes(self):
        candidatos, _ = self._candidatos()
        self.assertEqual(set(candidatos["contrato_id"]), {"1004328", "118872", "18940", "220038"})
        self.assertNotIn("71912", set(candidatos["contrato_id"]))  # inativo
        self.assertNotIn("7925", set(candidatos["contrato_id"]))  # encerrado

    def test_conflito_vai_para_duvida(self):
        candidatos, em_duvida = self._candidatos(
            {"contrato_numero": "13/2026", "fornecedor_cnpj_cpf": "05340639000130", "ne_curta": "2025NE000046"}
        )
        self.assertEqual(set(em_duvida["contrato_id"]), {"1004328", "118872"})
        self.assertTrue(em_duvida["motivo"].str.contains("conflito").all())
        self.assertEqual(set(candidatos["contrato_id"]), {"18940", "220038"})

    def test_sem_vigencia_vai_para_duvida(self):
        contratos = self.contratos.copy()
        contratos.loc[contratos["contrato_id"] == "220038", ["situacao_vigencia", "vigencia_fim"]] = ["sem_vigencia", None]
        candidatos, em_duvida = self._candidatos(contratos=contratos)
        self.assertEqual(list(em_duvida["contrato_id"]), ["220038"])
        self.assertIn("sem vigência", em_duvida.iloc[0]["motivo"])
        self.assertNotIn("220038", set(candidatos["contrato_id"]))

    def test_varios_registros_do_mesmo_contrato_nao_duplicam(self):
        candidatos, _ = self._candidatos(
            {"contrato_numero": "13/2026", "ne_curta": "2026NE000522"},
            {"contrato_numero": "13/2026", "ne_curta": "2026NE000523"},
        )
        ids = list(candidatos["contrato_id"])
        self.assertNotIn("1004328", ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_documento_preserva_zeros(self):
        candidatos, _ = self._candidatos()
        documento = candidatos.set_index("contrato_id").loc["220038", "fornecedor_documento"]
        self.assertEqual(documento, "00000000191")

    def _candidato(self, contrato_id: str) -> pd.Series:
        candidatos, _ = self._candidatos()
        return candidatos[candidatos["contrato_id"] == contrato_id].iloc[0]

    def test_cnpj_sem_zero_nao_gera_candidato_duplicado(self):
        candidatos, _ = self._candidatos({"contrato_numero": "13/2026", "fornecedor_cnpj_cpf": "5340639000130"})
        self.assertNotIn("1004328", set(candidatos["contrato_id"]))

    def test_motivo_de_conflito_nao_afirma_a_causa(self):
        _, em_duvida = self._candidatos(
            {"contrato_numero": "13/2026", "fornecedor_cnpj_cpf": "05340639000130", "ne_curta": "2025NE000046"}
        )
        motivo = em_duvida.iloc[0]["motivo"]
        self.assertIn("conflito", motivo)
        self.assertIn("mais de um contrato", motivo)  # a NE pode estar em dois contratos, não só "contratos diferentes"

    def test_registro_novo_do_gov_com_ne(self):
        registro = registro_novo_do_gov(self._candidato("1004328"), "2026NE000522")
        self.assertEqual(registro["contrato_numero"], "13/2026")
        self.assertEqual(registro["ano_contrato"], 2026)
        self.assertEqual(registro["fornecedor_cnpj_cpf"], "05340639000130")
        self.assertEqual(registro["vigencia_fim"], pd.Timestamp("2027-09-10"))
        self.assertEqual(registro["status_contrato"], "ATIVO")
        self.assertEqual(registro["ne_curta"], "2026NE000522")
        self.assertEqual(registro["natureza_despesa_cod"], "339039")
        self.assertEqual(registro["pi_cod"], "M20RKG01SCN")
        self.assertEqual(registro["fonte_cod"], "1000000000")
        for ausente in ("acao_cod", "ptres", "ugr_cod", "despesa_mensal", "meses_empenhados", "meses_liquidados"):
            self.assertNotIn(ausente, registro)

    def test_registro_novo_do_gov_sem_ne_e_contrato_sem_empenhos(self):
        for contrato_id in ("1004328", "220038"):
            with self.subTest(contrato_id=contrato_id):
                registro = registro_novo_do_gov(self._candidato(contrato_id))
                for campo in ("ne_curta", "natureza_despesa_cod", "pi_cod", "fonte_cod"):
                    self.assertIsNone(registro[campo])

    def test_ne_de_outro_contrato_levanta(self):
        with self.assertRaises(ValueError):
            registro_novo_do_gov(self._candidato("1004328"), "2025NE000046")

    def test_registro_aceito_por_novo_contrato(self):
        novo_contrato(**registro_novo_do_gov(self._candidato("1004328"), "2026NE000522"))


@unittest.skipUnless(FIXTURE_CONTRATOSGOV.exists(), f"Fixture ausente em {FIXTURE_CONTRATOSGOV}")
class TestFiltrarCandidatos(unittest.TestCase):
    """`filtrar_candidatos` (busca + ocultar parcela zero) só reduz o que é MOSTRADO: não altera a entrada nem
    muda quem é candidato. Parcela nula (sem dado) nunca é tratada como zero."""

    @classmethod
    def setUpClass(cls):
        contratos, _termos, empenhos = _gov()
        cls.candidatos, _ = candidatos_novos(_cadastro(), contratos, empenhos)  # os 4 vigentes

    def _ids(self, **filtros) -> list[str]:
        return list(filtrar_candidatos(self.candidatos, **filtros)["contrato_id"])

    def test_sem_filtro_devolve_todos_na_mesma_ordem(self):
        todos = list(self.candidatos["contrato_id"])
        self.assertEqual(self._ids(), todos)
        self.assertEqual(self._ids(busca="   "), todos)
        self.assertEqual(len(todos), 4)

    def test_busca_por_numero_do_gov_ou_do_cadastro(self):
        self.assertEqual(self._ids(busca="21/2017"), ["18940"])
        self.assertEqual(self._ids(busca="00021/2017"), ["18940"])

    def test_busca_por_fornecedor_sem_diferenciar_caixa(self):
        self.assertEqual(self._ids(busca="tekis"), ["118872"])
        self.assertEqual(self._ids(busca="  RIO AVE "), ["18940"])

    def test_busca_por_documento(self):
        self.assertEqual(self._ids(busca="05340639"), ["1004328"])

    def test_busca_sem_resultado_devolve_vazio_com_as_mesmas_colunas(self):
        resultado = filtrar_candidatos(self.candidatos, busca="nao existe")
        self.assertEqual(len(resultado), 0)
        self.assertEqual(list(resultado.columns), list(self.candidatos.columns))

    def test_ocultar_parcela_zero(self):
        self.assertNotIn("220038", self._ids(ocultar_parcela_zero=True))  # parcela 0,00 no gov
        self.assertEqual(len(self._ids(ocultar_parcela_zero=True)), 3)
        self.assertIn("220038", self._ids(ocultar_parcela_zero=False))

    def test_parcela_nula_nao_e_zero(self):
        candidatos = self.candidatos.copy()
        candidatos["valor_parcela"] = candidatos["valor_parcela"].astype(object)
        candidatos.loc[candidatos["contrato_id"] == "220038", "valor_parcela"] = None
        ids = list(filtrar_candidatos(candidatos, ocultar_parcela_zero=True)["contrato_id"])
        self.assertIn("220038", ids)

    def test_busca_e_parcela_zero_combinadas(self):
        self.assertEqual(self._ids(busca="21/2023", ocultar_parcela_zero=True), [])
        self.assertEqual(self._ids(busca="21/2023"), ["220038"])

    def test_nao_altera_a_entrada(self):
        antes = self.candidatos.copy(deep=True)
        filtrar_candidatos(self.candidatos, busca="rio", ocultar_parcela_zero=True)
        pd.testing.assert_frame_equal(self.candidatos, antes)


if __name__ == "__main__":
    unittest.main()
