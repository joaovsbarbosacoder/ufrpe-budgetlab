"""Testes do relatório (PDF/Excel) de Necessidade de Empenho até o fim do exercício —
`src/relatorio_necessidade_empenho.py`. Dados sintéticos no formato de saída de
`contratos_continuos.com_saldo_execucao`; valores esperados calculados à mão (ver cada caso)."""

from __future__ import annotations

import unittest
import math
from datetime import date
from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from src.relatorio_necessidade_empenho import (
    BASE_COMPETENCIA,
    BASE_LANCAMENTO,
    BASE_PLANILHA,
    BASE_SEM_NE,
    BASE_SEM_SALDO,
    ContextoRelatorioNecessidade,
    gerar_pdf,
    _avisos,
    gerar_xlsx,
    limite_de_projecao,
    mes_referencia_do_exercicio,
    meses_vigentes_no_exercicio,
    montar_relatorio,
    necessidade_por_ne,
    projetar_necessidade_mensal,
)

NE_A = "2026NE000010"  # competência
NE_B = "2026NE000020"  # lançamento, já tudo empenhado
NE_C = "2026NE000030"  # só saldo colado na planilha
NE_D = "2026NE000040"  # nenhuma fonte de saldo


def _linha(**campos: object) -> dict:
    base = {
        "ne_curta": None, "fornecedor": "F", "contrato_numero": "1/2026", "despesa_mensal": 0.0,
        "meses_no_ano": 12.0, "valor_empenhado": 0.0, "valor_empenhado_execucao": None,
        "valor_empenhado_planilha_total_ne": None, "valor_liquidado_execucao": None,
        "liquidado_via_competencia": False, "saldo_execucao": None, "saldo_colado_planilha": None,
        "status_contrato": "ATIVO", "vigencia_fim": pd.NaT,
    }
    base.update(campos)
    return base


def _filtrado() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # NE A — dois itens somam despesa mensal 1000. Empenhado 8000 (Execução), liquidado por
            # competência 5000 => saldo 3000; meses já empenhados 8; restantes 4;
            # necessidade = 1000*4 − 3000 = 1000.
            _linha(ne_curta=NE_A, fornecedor="ALFA", contrato_numero="10/2026", despesa_mensal=600.0,
                   valor_empenhado_execucao=8000.0, valor_empenhado_planilha_total_ne=8000.0,
                   valor_liquidado_execucao=5000.0, liquidado_via_competencia=True,
                   saldo_execucao=2500.0, saldo_colado_planilha=2500.0),
            _linha(ne_curta=NE_A, fornecedor="ALFA", contrato_numero="10/2026", despesa_mensal=400.0,
                   valor_empenhado_execucao=8000.0, valor_empenhado_planilha_total_ne=8000.0,
                   valor_liquidado_execucao=5000.0, liquidado_via_competencia=True,
                   saldo_execucao=2500.0, saldo_colado_planilha=2500.0),
            # NE B — lançamento: saldo 500; empenhado 12000 (planilha) ÷ 1000 = 12 meses; restantes
            # 0; necessidade = max(1000*0 − 500, 0) = 0 (nunca negativa).
            _linha(ne_curta=NE_B, fornecedor="BETA", contrato_numero="20/2026", despesa_mensal=1000.0,
                   valor_empenhado_planilha_total_ne=12000.0, valor_liquidado_execucao=11500.0,
                   saldo_execucao=500.0),
            # NE C — sem saldo na Execução; usa o saldo colado 100. Despesa 100, 12 meses, empenhado
            # 600 => 6 meses já empenhados, 6 restantes; necessidade = 100*6 − 100 = 500.
            _linha(ne_curta=NE_C, fornecedor="GAMA", contrato_numero="30/2026", despesa_mensal=100.0,
                   valor_empenhado_planilha_total_ne=600.0, saldo_colado_planilha=100.0),
            # NE D — nenhuma fonte de saldo (assume 0). Despesa 50, meses_no_ano 6, empenhado 100 =>
            # 2 meses já empenhados, 4 restantes; necessidade = 50*4 − 0 = 200.
            _linha(ne_curta=NE_D, fornecedor="DELTA", contrato_numero="40/2026", despesa_mensal=50.0,
                   meses_no_ano=6.0, valor_empenhado_planilha_total_ne=100.0),
            # sem NE — despesa 200, meses_no_ano 6, empenhado 400 => 2 meses, 4 restantes;
            # necessidade = 200*4 = 800, sem saldo a abater.
            _linha(ne_curta=None, fornecedor="OMEGA", contrato_numero="SN/2026", despesa_mensal=200.0,
                   meses_no_ano=6.0, valor_empenhado=400.0),
        ]
    )


def _meses_liquidados() -> pd.DataFrame:
    return pd.DataFrame(
        {"ne_curta": [NE_A], "meses_liquidados": [5], "ultimo_mes_liquidado": [pd.Timestamp("2026-05-01")]}
    )


def _contexto(origem_competencia: str | None = "Liquidação por Competência.xlsx · modificado em 01/10/2026 10:00") -> ContextoRelatorioNecessidade:
    return ContextoRelatorioNecessidade(
        exercicio=2026, data_extracao="30/09/2026", hash_manifesto="abcd1234",
        data_emissao="01/10/2026 12:00", origem_competencia=origem_competencia, busca="",
    )


def _liquidacao_mensal() -> pd.DataFrame:
    # NE A: jan e mar de 2026 (realizado) e set/2025 (outro exercício — fora). As demais NEs não
    # têm competência; "2026NE999999" não está no relatório.
    return pd.DataFrame(
        {
            "ne_curta": [NE_A, NE_A, NE_A, "2026NE999999"],
            "ano_mes": [202601, 202603, 202509, 202601],
            "valor": [500.0, 700.0, 11.0, 5.0],
        }
    )


MES_REF = 9  # extração em setembro/2026


def _relatorio(liquidacao: pd.DataFrame | None = None, mes_ref: int = MES_REF, filtrado: pd.DataFrame | None = None):
    por_ne, sem_ne = necessidade_por_ne(_filtrado() if filtrado is None else filtrado, _meses_liquidados(), 2026)
    return montar_relatorio(por_ne, sem_ne, liquidacao, 2026, mes_ref)


class TestNecessidadePorNe(unittest.TestCase):
    def setUp(self) -> None:
        self.entrada = _filtrado()
        self.copia = self.entrada.copy(deep=True)
        self.por_ne, self.sem_ne = necessidade_por_ne(self.entrada, _meses_liquidados())
        self.por_ne = self.por_ne.set_index("ne_curta")

    def test_ne_por_competencia(self):
        a = self.por_ne.loc[NE_A]
        self.assertEqual(a["despesa_mensal"], 1000.0)  # itens da mesma NE somados
        self.assertEqual(a["saldo_para_necessidade"], 3000.0)
        self.assertEqual(a["meses_ja_empenhados"], 8.0)
        self.assertEqual(a["meses_restantes"], 4.0)
        # 1000 × 4 meses restantes = 4000: o saldo (3000) já está dentro do empenhado e NÃO é
        # subtraído de novo (correção de 02/10/2026; a regra anterior dava 4000 − 3000 = 1000)
        self.assertEqual(a["necessidade"], 4000.0)
        self.assertEqual(a["base_saldo"], BASE_COMPETENCIA)
        self.assertEqual(a["meses_liquidados"], 5)

    def test_necessidade_nunca_negativa(self):
        b = self.por_ne.loc[NE_B]
        self.assertEqual(b["meses_restantes"], 0.0)
        self.assertEqual(b["necessidade"], 0.0)
        self.assertEqual(b["base_saldo"], BASE_LANCAMENTO)

    def test_fallback_de_saldo_pela_planilha_e_sem_saldo(self):
        c = self.por_ne.loc[NE_C]
        self.assertEqual((c["saldo_para_necessidade"], c["necessidade"], c["base_saldo"]), (100.0, 600.0, BASE_PLANILHA))
        d = self.por_ne.loc[NE_D]
        self.assertEqual((d["saldo_para_necessidade"], d["necessidade"], d["base_saldo"]), (0.0, 200.0, BASE_SEM_SALDO))

    def test_item_sem_ne_nao_abate_saldo(self):
        self.assertEqual(len(self.sem_ne), 1)
        linha = self.sem_ne.iloc[0]
        self.assertEqual(linha["meses_restantes"], 4.0)
        self.assertEqual(linha["necessidade"], 800.0)
        self.assertEqual(linha["base_saldo"], BASE_SEM_NE)

    def test_nao_altera_entrada(self):
        pd.testing.assert_frame_equal(self.entrada, self.copia)

    def test_sem_base_de_meses_liquidados(self):
        por_ne, _ = necessidade_por_ne(_filtrado(), None)
        self.assertTrue(por_ne["meses_liquidados"].isna().all())


class TestMontarRelatorio(unittest.TestCase):
    def setUp(self) -> None:
        self.relatorio = _relatorio(_liquidacao_mensal())

    def test_ordem_da_tela_nes_por_necessidade_e_depois_sem_ne(self):
        # NEs: A 4000, C 600, D 200, B 0; depois o item sem NE (800), mesmo maior que D/B.
        nes = self.relatorio.linhas["ne_curta"]
        self.assertEqual(nes.iloc[:4].tolist(), [NE_A, NE_C, NE_D, NE_B])
        self.assertTrue(pd.isna(nes.iloc[4]))

    def test_totais(self):
        self.assertEqual(self.relatorio.total_necessidade, 4000.0 + 600.0 + 200.0 + 0.0 + 800.0)
        self.assertEqual(self.relatorio.qtd_ne, 4)
        self.assertEqual(self.relatorio.qtd_sem_ne, 1)
        # saldo total só das NEs (item sem NE tem saldo nulo, não zero): 3000 + 100 + 0 + 500
        self.assertEqual(self.relatorio.total_saldo, 3600.0)

    def test_item_sem_ne_tem_liquidado_e_saldo_nulos(self):
        linha = self.relatorio.linhas.iloc[-1]
        self.assertTrue(pd.isna(linha["saldo"]))
        self.assertTrue(pd.isna(linha["valor_liquidado"]))

    def test_meses_no_ano_sem_cadastro_vira_12(self):
        filtrado = _filtrado()
        filtrado["meses_no_ano"] = None
        relatorio = montar_relatorio(*necessidade_por_ne(filtrado, None), None, 2026, MES_REF)
        self.assertTrue((relatorio.linhas["meses_no_ano"] == 12.0).all())


class TestProjecaoMensal(unittest.TestCase):
    def test_mes_referencia_do_exercicio(self):
        self.assertEqual(mes_referencia_do_exercicio(date(2026, 9, 30), 2026), 9)
        self.assertEqual(mes_referencia_do_exercicio(date(2025, 12, 31), 2026), 0)
        self.assertEqual(mes_referencia_do_exercicio(date(2027, 1, 5), 2026), 12)  # encerrado

    def test_primeiro_mes_projeta_despesa_mensal_menos_saldo(self):
        # caso real da NE 2026NE000088: despesa 927.298,47, saldo 887.964,05, de agosto a dezembro.
        meses = projetar_necessidade_mensal(927298.47, 887964.05, 8, 5)
        self.assertTrue(all(math.isnan(v) for v in meses[:7]))
        self.assertAlmostEqual(meses[7], 39334.42, places=2)  # ago = despesa − saldo
        for mes in meses[8:]:
            self.assertAlmostEqual(mes, 927298.47, places=2)  # set–dez: despesa cheia

    def test_saldo_maior_que_a_despesa_e_abatido_nos_meses_seguintes(self):
        # mensal 100, saldo 250: acumulado 100/200/300/400 => excesso 0/0/50/150 => 0, 0, 50, 100.
        self.assertEqual(projetar_necessidade_mensal(100.0, 250.0, 1, 4)[:4], [0.0, 0.0, 50.0, 100.0])

    def test_saldo_negativo_cai_todo_no_primeiro_mes(self):
        # mensal 100, saldo −50: nov: 100 − (−50) = 150; dez: 100.
        self.assertEqual(projetar_necessidade_mensal(100.0, -50.0, 11, 2)[10:], [150.0, 100.0])

    def test_sem_meses_a_projetar_ou_entrada_nula_nao_vira_zero(self):
        for meses in (
            projetar_necessidade_mensal(100.0, 0.0, 5, 0),
            projetar_necessidade_mensal(100.0, 0.0, 13, 3),
            projetar_necessidade_mensal(float("nan"), 0.0, 5, 3),
            projetar_necessidade_mensal(100.0, float("nan"), 5, 3),
        ):
            self.assertTrue(all(math.isnan(v) for v in meses))

    def test_nao_passa_de_dezembro(self):
        meses = projetar_necessidade_mensal(100.0, 0.0, 11, 9)
        self.assertEqual(meses[10:], [100.0, 100.0])


class TestGradeMensal(unittest.TestCase):
    def setUp(self) -> None:
        self.relatorio = _relatorio(_liquidacao_mensal())
        self.mensal = self.relatorio.mensal.copy()
        self.mensal.index = [
            ne if isinstance(ne, str) else "SEM_NE" for ne in self.relatorio.linhas["ne_curta"].tolist()
        ]

    def _projetado(self, ne: str, meses: range = range(1, 13)) -> list[float]:
        return [self.mensal.loc[ne, f"p{m}"] for m in meses]

    def test_realizado_e_primeiro_mes_sem_liquidacao(self):
        # NE A tem competência em jan e mar/2026 (set/2025 é outro exercício e fica de fora).
        a = self.mensal.loc[NE_A]
        self.assertEqual((a["r1"], a["r3"]), (500.0, 700.0))
        self.assertTrue(pd.isna(a["r2"]))  # fev sem registro: nulo, não zero
        self.assertEqual(a["primeiro_mes_projecao"], 4)  # mês seguinte ao último com liquidação
        self.assertEqual(a["meses_projetados"], 9)  # abr–dez; vida do contrato: 12 − 2 meses realizados = 10
        self.assertEqual(self.relatorio.total_mensal_realizado[0], 500.0)
        self.assertIsNone(self.relatorio.total_mensal_realizado[1])

    def test_ne_com_realizado_projeta_do_mes_seguinte_ao_ultimo_liquidado(self):
        # A: mensal 1000, saldo 3000, abr–dez: acumulado 1000…9000 => 0, 0, 0, 1000 × 6 (jul–dez).
        self.assertEqual(self._projetado(NE_A, range(4, 13)), [0.0, 0.0, 0.0] + [1000.0] * 6)
        self.assertTrue(all(math.isnan(v) for v in self._projetado(NE_A, range(1, 4))))

    def test_ne_sem_competencia_projeta_do_mes_seguinte_a_extracao(self):
        # B (saldo 500, mensal 1000): out 500, nov 1000, dez 1000. C (saldo 100, mensal 100): 0, 100, 100.
        self.assertEqual(self._projetado(NE_B, range(10, 13)), [500.0, 1000.0, 1000.0])
        self.assertEqual(self._projetado(NE_C, range(10, 13)), [0.0, 100.0, 100.0])
        self.assertEqual(self.mensal.loc[NE_B, "primeiro_mes_projecao"], 10)
        self.assertEqual(self.relatorio.nes_sem_realizado, [NE_C, NE_D, NE_B])

    def test_item_sem_ne_nao_abate_saldo_e_respeita_meses_no_ano(self):
        # despesa 200, meses_no_ano 6: out–dez, 200 cada (3 ≤ 6). D: despesa 50 => 50 cada.
        self.assertEqual(self._projetado("SEM_NE", range(10, 13)), [200.0, 200.0, 200.0])
        self.assertEqual(self._projetado(NE_D, range(10, 13)), [50.0, 50.0, 50.0])

    def test_valor_do_mes_realizado_projetado_ou_sem_dado(self):
        indice_a = self.relatorio.linhas.index[self.relatorio.linhas["ne_curta"] == NE_A][0]
        self.assertEqual(self.relatorio.valor_do_mes(indice_a, 1), (500.0, False))
        self.assertEqual(self.relatorio.valor_do_mes(indice_a, 2), (None, False))
        self.assertEqual(self.relatorio.valor_do_mes(indice_a, 4), (0.0, True))
        self.assertEqual(self.relatorio.valor_do_mes(indice_a, 7), (1000.0, True))

    def test_totais_da_grade(self):
        # A 6000 + B 2500 + C 200 + D 150 + sem NE 600
        self.assertEqual(self.relatorio.total_projetado, 9450.0)
        self.assertEqual(self.relatorio.total_necessidade, 5600.0)  # a do Resumo Consolidado (sem abater saldo)
        self.assertEqual(self.relatorio.total_mensal_projetado[3:], [0.0, 0.0, 0.0, 1000.0, 1000.0, 1000.0, 1750.0, 2350.0, 2350.0])

    def test_registro_depois_do_mes_de_referencia_nao_e_descartado(self):
        liquidacao = pd.concat(
            [_liquidacao_mensal(), pd.DataFrame({"ne_curta": [NE_A], "ano_mes": [202610], "valor": [999.0]})],
            ignore_index=True,
        )
        a = _relatorio(liquidacao).mensal
        linha = a.iloc[0]
        self.assertEqual(linha["r10"], 999.0)  # realizado em outubro
        self.assertEqual(linha["primeiro_mes_projecao"], 11)  # projeta a partir de novembro

    def test_vida_do_contrato_limita_a_projecao(self):
        # D (meses_no_ano 6) liquidou jan–mai: 6 − 5 = 1 mês restante => só junho é projetado.
        liquidacao = pd.concat(
            [
                _liquidacao_mensal(),
                pd.DataFrame({"ne_curta": [NE_D] * 5, "ano_mes": [202601, 202602, 202603, 202604, 202605], "valor": [50.0] * 5}),
            ],
            ignore_index=True,
        )
        d = _relatorio(liquidacao).mensal
        d = d.loc[_relatorio(liquidacao).linhas["ne_curta"] == NE_D].iloc[0]
        self.assertEqual(d["meses_projetados"], 1)
        self.assertEqual(d["primeiro_mes_projecao"], 6)
        self.assertEqual(d["p6"], 50.0)
        self.assertTrue(pd.isna(d["p7"]))

    def test_sem_base_de_competencia_projeta_todas_do_mes_seguinte_a_extracao(self):
        relatorio = _relatorio(None)
        self.assertTrue(relatorio.mensal[[f"r{m}" for m in range(1, 13)]].isna().all().all())
        self.assertEqual(len(relatorio.nes_sem_realizado), 4)
        self.assertTrue((relatorio.mensal["primeiro_mes_projecao"] == 10).all())

    def test_exercicio_encerrado_nao_projeta(self):
        relatorio = _relatorio(_liquidacao_mensal(), mes_ref=12)
        self.assertTrue(relatorio.mensal[[f"p{m}" for m in range(1, 13)]].isna().all().all())
        self.assertEqual(relatorio.total_projetado, 0.0)

    def test_exercicio_futuro_projeta_o_ano_todo(self):
        relatorio = _relatorio(None, mes_ref=0)
        indice_d = relatorio.linhas.index[relatorio.linhas["ne_curta"] == NE_D][0]
        self.assertEqual(relatorio.mensal.at[indice_d, "meses_projetados"], 6)  # vida: meses_no_ano = 6


class TestXlsx(unittest.TestCase):
    def setUp(self) -> None:
        relatorio = _relatorio(_liquidacao_mensal())
        self.livro = load_workbook(BytesIO(gerar_xlsx(relatorio, _contexto())))

    def _linha(self, aba, numero):
        cabecalho = [c.value for c in aba[1]]
        return dict(zip(cabecalho, [c.value for c in aba[numero]]))

    def test_abas(self):
        self.assertEqual(
            self.livro.sheetnames,
            ["Projeção mensal", "Detalhe mensal", "Total mensal", "Resumo por NE", "Parâmetros"],
        )

    def test_projecao_mensal_uma_linha_por_ne_com_todos_os_meses_e_saldo_atual(self):
        aba = self.livro["Projeção mensal"]
        self.assertEqual(aba.max_row, 6)  # cabeçalho + 4 NEs + 1 item sem NE
        a = self._linha(aba, 2)
        self.assertEqual(a["NE"], NE_A)
        self.assertEqual(a["Saldo atual do empenho"], 3000.0)
        self.assertEqual((a["Jan"], a["Mar"]), (500.0, 700.0))
        self.assertIsNone(a["Fev"])  # nulo, não zero
        self.assertEqual((a["Abr"], a["Jul"], a["Dez"]), (0.0, 1000.0, 1000.0))  # projetado
        self.assertEqual((a["Total realizado"], a["Total projetado"], a["Primeiro mês projetado"]), (1200.0, 6000.0, "Abr"))
        sem_ne = self._linha(aba, 6)
        self.assertIsNone(sem_ne["NE"])
        self.assertIsNone(sem_ne["Saldo atual do empenho"])  # nulo, não zero
        self.assertEqual((sem_ne["Out"], sem_ne["Nov"], sem_ne["Dez"]), (200.0, 200.0, 200.0))
        self.assertIsNone(sem_ne["Jan"])

    def test_valor_projetado_evidenciado_por_estilo(self):
        aba = self.livro["Projeção mensal"]
        cabecalho = [c.value for c in aba[1]]
        projetado = aba.cell(row=2, column=cabecalho.index("Jul") + 1)
        realizado = aba.cell(row=2, column=cabecalho.index("Mar") + 1)
        self.assertTrue(projetado.font.italic)
        self.assertEqual(projetado.fill.fgColor.rgb[-6:], "FFF2CC")
        self.assertFalse(realizado.font.italic)
        self.assertNotEqual(realizado.fill.fgColor.rgb[-6:], "FFF2CC")

    def test_detalhe_mensal_identifica_o_tipo_de_cada_mes(self):
        aba = self.livro["Detalhe mensal"]
        linhas = [dict(zip([c.value for c in aba[1]], [c.value for c in aba[n]])) for n in range(2, aba.max_row + 1)]
        da_a = [l for l in linhas if l["NE"] == NE_A]
        self.assertEqual(len(da_a), 11)  # jan, mar realizados + abr–dez projetados
        self.assertEqual({l["Tipo"] for l in da_a if l["Nº do mês"] in (1, 3)}, {"Realizado"})
        self.assertEqual({l["Tipo"] for l in da_a if l["Nº do mês"] >= 4}, {"Projetado"})
        self.assertFalse(any(l["Nº do mês"] == 2 for l in da_a))  # fev sem dado não vira linha

    def test_total_mensal(self):
        aba = self.livro["Total mensal"]
        projetado = self._linha(aba, 3)
        self.assertEqual((projetado["Out"], projetado["Nov"], projetado["Dez"]), (1750.0, 2350.0, 2350.0))
        self.assertEqual(projetado["Total"], 9450.0)

    def test_resumo_por_ne_traz_as_duas_necessidades(self):
        aba = self.livro["Resumo por NE"]
        self.assertEqual(aba.max_row, 6)
        a = self._linha(aba, 2)
        self.assertEqual(a["NE"], NE_A)
        self.assertEqual(a["Necessidade até dezembro (Resumo)"], 4000.0)
        self.assertEqual(a["Necessidade projetada (grade)"], 6000.0)
        self.assertEqual(a["Saldo atual do empenho"], 3000.0)
        ultima = self._linha(aba, 6)
        self.assertIsNone(ultima["Saldo atual do empenho"])
        self.assertIsNone(ultima["Liquidado"])
        self.assertEqual(ultima["Base do saldo"], BASE_SEM_NE)

    def test_parametros_trazem_totais_regra_projecao_e_avisos(self):
        textos = {l[0].value: l[1].value for l in self.livro["Parâmetros"].iter_rows(min_row=2)}
        self.assertEqual(textos["Necessidade projetada na grade (R$)"], "9.450,00")
        self.assertEqual(textos["Necessidade até Dezembro — Resumo Consolidado (R$)"], "5.600,00")
        self.assertIn("primeiro mês sem liquidação", textos["Projeção"])
        self.assertIn("meses restantes", textos["Regra do Resumo Consolidado"])
        self.assertEqual(textos["Exercício"], "2026")

    def test_aviso_de_diferenca_para_o_resumo_consolidado(self):
        avisos = [l[1].value for l in self.livro["Parâmetros"].iter_rows(min_row=2) if l[0].value == "Avisos"]
        self.assertTrue(any("difere da Necessidade até Dezembro do Resumo Consolidado" in a for a in avisos))

    def test_aviso_quando_competencia_indisponivel(self):
        relatorio = _relatorio(None)
        livro = load_workbook(BytesIO(gerar_xlsx(relatorio, _contexto(origem_competencia=None))))
        avisos = [l[1].value for l in livro["Parâmetros"].iter_rows(min_row=2) if l[0].value == "Avisos"]
        self.assertTrue(any("Liquidação por Competência não está disponível" in a for a in avisos))


class TestPdf(unittest.TestCase):
    def test_gera_pdf_valido(self):
        pdf = gerar_pdf(_relatorio(_liquidacao_mensal()), _contexto())
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1500)

    def test_pdf_com_caracteres_especiais_e_sem_competencia(self):
        filtrado = _filtrado()
        filtrado.loc[0, "fornecedor"] = "ALFA <&> LTDA"
        relatorio = montar_relatorio(*necessidade_por_ne(filtrado, None), None, 2026, MES_REF)
        self.assertTrue(gerar_pdf(relatorio, _contexto(origem_competencia=None)).startswith(b"%PDF"))

    def test_pdf_e_excel_nos_extremos_do_calendario(self):
        for mes_ref in (0, 12):
            relatorio = _relatorio(_liquidacao_mensal(), mes_ref=mes_ref)
            self.assertTrue(gerar_pdf(relatorio, _contexto()).startswith(b"%PDF"), mes_ref)
            self.assertTrue(gerar_xlsx(relatorio, _contexto()).startswith(b"PK"), mes_ref)


class TestLimiteDeProjecao(unittest.TestCase):
    def test_suspenso_nao_projeta_nem_com_vigencia_futura(self):
        limite = limite_de_projecao("SUSPENSO", pd.Timestamp("2027-06-30"), 2026)
        self.assertEqual((limite.ultimo_mes, limite.aviso), (0, "suspenso"))

    def test_status_e_case_insensitive(self):
        self.assertEqual(limite_de_projecao("suspenso", pd.NaT, 2026).ultimo_mes, 0)

    def test_data_manda_ate_o_mes_do_fim_com_mes_proporcional(self):
        limite = limite_de_projecao("ATIVO", pd.Timestamp("2026-11-15"), 2026)
        self.assertEqual((limite.ultimo_mes, limite.mes_do_fim, limite.fracao_ultimo_mes), (11, 11, 0.5))
        self.assertIn("mês final proporcional: 15/30", limite.motivo)

    def test_fim_no_ultimo_dia_do_mes_e_mes_cheio(self):
        limite = limite_de_projecao("ATIVO", pd.Timestamp("2026-02-28"), 2026)  # fevereiro tem 28 dias em 2026
        self.assertEqual((limite.ultimo_mes, limite.fracao_ultimo_mes), (2, 1.0))
        self.assertNotIn("proporcional", limite.motivo)
        self.assertEqual(limite_de_projecao("ATIVO", pd.Timestamp("2026-02-14"), 2026).fracao_ultimo_mes, 0.5)

    def test_sem_data_decide_o_status(self):
        self.assertEqual(limite_de_projecao("VENCIDO", pd.NaT, 2026).ultimo_mes, 0)
        self.assertEqual(limite_de_projecao("VENCIDO", pd.NaT, 2026).aviso, "vencido_sem_data")
        self.assertEqual(limite_de_projecao("ATIVO", pd.NaT, 2026).ultimo_mes, 12)
        self.assertEqual(limite_de_projecao("ATIVO", None, 2026).aviso, "sem_data")
        self.assertEqual(limite_de_projecao(None, pd.NaT, 2026).ultimo_mes, 12)  # status ausente: não presume vencido

    def test_vigencia_de_outro_ano(self):
        encerrada = limite_de_projecao("ATIVO", pd.Timestamp("2025-12-31"), 2026)
        self.assertEqual((encerrada.ultimo_mes, encerrada.aviso), (0, "ativo_com_vigencia_encerrada"))
        self.assertIsNone(limite_de_projecao("VENCIDO", pd.Timestamp("2025-12-31"), 2026).aviso)
        futura = limite_de_projecao("ATIVO", pd.Timestamp("2027-03-01"), 2026)
        self.assertEqual((futura.ultimo_mes, futura.aviso), (12, None))
        self.assertEqual(limite_de_projecao("VENCIDO", pd.Timestamp("2027-03-01"), 2026).aviso, "vencido_com_vigencia")


class TestVigenciaNaProjecao(unittest.TestCase):
    """NE_B: despesa mensal 1000, saldo 500, sem competência => projeta a partir de outubro
    (referência = setembro). Sem restrição: out 500, nov 1000, dez 1000."""

    @staticmethod
    def _projecao_de_b(status: str | None = "ATIVO", fim: str | None = None):
        filtrado = _filtrado()
        indice = filtrado.index[filtrado["ne_curta"] == NE_B][0]
        filtrado.loc[indice, "status_contrato"] = status
        filtrado.loc[indice, "vigencia_fim"] = pd.Timestamp(fim) if fim else pd.NaT
        relatorio = _relatorio(_liquidacao_mensal(), filtrado=filtrado)
        linha = relatorio.mensal.loc[relatorio.linhas["ne_curta"] == NE_B].iloc[0]
        return relatorio, linha, [linha[f"p{m}"] for m in (10, 11, 12)]

    def test_sem_restricao_projeta_ate_dezembro(self):
        _, linha, meses = self._projecao_de_b("ATIVO", "2027-03-01")
        self.assertEqual(meses, [500.0, 1000.0, 1000.0])
        self.assertIsNone(linha["aviso_vigencia"])

    def test_suspenso_nao_projeta_mesmo_vigente(self):
        relatorio, linha, meses = self._projecao_de_b("SUSPENSO", "2027-03-01")
        self.assertTrue(all(math.isnan(v) for v in meses))
        self.assertEqual(linha["observacao_projecao"], "Suspenso — sem projeção")
        self.assertEqual(linha["aviso_vigencia"], "suspenso")
        self.assertTrue(pd.isna(linha["primeiro_mes_projecao"]))

    def test_mes_final_proporcional(self):
        # fim 15/11: out cheio (acumulado 1000 − saldo 500 = 500); nov 15/30 de 1000 (acumulado 1500
        # − 500 = 1000 → +500); dezembro não projeta.
        _, linha, meses = self._projecao_de_b("ATIVO", "2026-11-15")
        self.assertEqual(meses[:2], [500.0, 500.0])
        self.assertTrue(math.isnan(meses[2]))
        self.assertEqual(linha["meses_projetados"], 2)

    def test_fim_no_ultimo_dia_do_mes_projeta_o_mes_cheio(self):
        _, linha, meses = self._projecao_de_b("ATIVO", "2026-10-31")
        self.assertEqual(meses[0], 500.0)
        self.assertTrue(math.isnan(meses[1]))
        self.assertEqual(linha["meses_projetados"], 1)
        self.assertNotIn("proporcional", linha["observacao_projecao"])

    def test_vigencia_encerrada_antes_do_primeiro_mes_a_projetar(self):
        relatorio, linha, meses = self._projecao_de_b("ATIVO", "2026-09-30")
        self.assertTrue(all(math.isnan(v) for v in meses))
        self.assertEqual(linha["observacao_projecao"], "Vigência encerrada em 30/09/2026 — sem projeção")
        self.assertEqual(linha["aviso_vigencia"], "ativo_com_vigencia_encerrada")  # data manda sobre ATIVO

    def test_vencido_com_data_encerrada_nao_gera_aviso_de_inconsistencia(self):
        _, linha, meses = self._projecao_de_b("VENCIDO", "2026-09-30")
        self.assertTrue(all(math.isnan(v) for v in meses))
        self.assertIsNone(linha["aviso_vigencia"])

    def test_vencido_com_vigencia_futura_segue_a_data_e_avisa(self):
        _, linha, meses = self._projecao_de_b("VENCIDO", "2027-03-01")
        self.assertEqual(meses, [500.0, 1000.0, 1000.0])
        self.assertEqual(linha["aviso_vigencia"], "vencido_com_vigencia")

    def test_vencido_sem_data_nao_projeta(self):
        _, linha, meses = self._projecao_de_b("VENCIDO", None)
        self.assertTrue(all(math.isnan(v) for v in meses))
        self.assertEqual(linha["aviso_vigencia"], "vencido_sem_data")

    def test_realizado_continua_aparecendo_em_contrato_sem_projecao(self):
        filtrado = _filtrado()
        indice = filtrado.index[filtrado["ne_curta"] == NE_A][0]
        filtrado.loc[filtrado["ne_curta"] == NE_A, "status_contrato"] = "SUSPENSO"
        relatorio = _relatorio(_liquidacao_mensal(), filtrado=filtrado)
        linha = relatorio.mensal.loc[relatorio.linhas["ne_curta"] == NE_A].iloc[0]
        self.assertEqual((linha["r1"], linha["r3"]), (500.0, 700.0))  # dado financeiro nunca descartado
        self.assertTrue(linha[[f"p{m}" for m in range(1, 13)]].isna().all())

    def test_projecao_total_so_conta_o_que_pode_ser_projetado(self):
        relatorio, _, _ = self._projecao_de_b("SUSPENSO", None)
        # B (2500) sai do total da grade de 9450
        self.assertEqual(relatorio.total_projetado, 9450.0 - 2500.0)

    def test_avisos_listam_suspensos_e_contratos_sem_data(self):
        relatorio, _, _ = self._projecao_de_b("SUSPENSO", None)
        avisos = _avisos(relatorio, _contexto())
        self.assertTrue(any(a.startswith("Contratos SUSPENSOS") and NE_B in a for a in avisos))
        self.assertTrue(any(a.startswith("Contratos sem data de vigência") for a in avisos))

    def test_excel_traz_status_vigencia_e_observacao(self):
        relatorio, _, _ = self._projecao_de_b("SUSPENSO", "2027-03-01")
        livro = load_workbook(BytesIO(gerar_xlsx(relatorio, _contexto())))
        aba = livro["Projeção mensal"]
        cabecalho = [c.value for c in aba[1]]
        linhas = [dict(zip(cabecalho, [c.value for c in aba[n]])) for n in range(2, aba.max_row + 1)]
        b = next(l for l in linhas if l["NE"] == NE_B)
        self.assertEqual(b["Status"], "SUSPENSO")
        self.assertEqual(b["Vigência (fim)"].date().isoformat(), "2027-03-01")
        self.assertEqual(b["Observação da projeção"], "Suspenso — sem projeção")
        self.assertIsNone(b["Out"])  # sem realizado e sem projeção: vazio, não zero
        a = next(l for l in linhas if l["NE"] == NE_A)
        self.assertIsNone(a["Vigência (fim)"])  # sem data no cadastro: vazio

    def test_pdf_gera_com_status_e_vigencia(self):
        relatorio, _, _ = self._projecao_de_b("SUSPENSO", "2027-03-01")
        self.assertTrue(gerar_pdf(relatorio, _contexto()).startswith(b"%PDF"))


class TestVigenciaNoCard(unittest.TestCase):
    """A Necessidade até Dezembro do card (`necessidade_por_ne`) respeita vigência e status quando o
    exercício é informado (02/10/2026). Valores à mão a partir do fixture `_filtrado`."""

    def test_meses_vigentes_no_exercicio(self):
        casos = [
            (("SUSPENSO", pd.Timestamp("2027-06-30")), 0.0),
            (("suspenso", pd.NaT), 0.0),
            (("VENCIDO", pd.NaT), 0.0),
            (("ATIVO", pd.NaT), None),
            ((None, pd.NaT), None),  # status ausente: não presume vencido
            (("ATIVO", pd.Timestamp("2025-12-31")), 0.0),
            (("ATIVO", pd.Timestamp("2027-01-01")), None),
            (("ATIVO", pd.Timestamp("2026-06-15")), 5.5),  # jan–mai + 15/30 de junho
            (("ATIVO", pd.Timestamp("2026-01-31")), 1.0),  # fim no último dia do mês: mês cheio
            (("VENCIDO", pd.Timestamp("2026-12-31")), 12.0),  # a data manda sobre o status
        ]
        for (status, fim), esperado in casos:
            obtido = meses_vigentes_no_exercicio(status, fim, 2026)
            if esperado is None:
                self.assertIsNone(obtido, (status, fim))
            else:
                self.assertAlmostEqual(obtido, esperado, msg=str((status, fim)))
        self.assertAlmostEqual(meses_vigentes_no_exercicio("ATIVO", pd.Timestamp("2026-03-15"), 2026), 2 + 15 / 31)

    def _por_ne(self, ajustes: dict | None = None, exercicio: int | None = 2026):
        filtrado = _filtrado()
        for ne, campos in (ajustes or {}).items():
            mascara = filtrado["ne_curta"].isna() if ne is None else filtrado["ne_curta"] == ne
            for campo, valor in campos.items():
                filtrado.loc[mascara, campo] = valor
        por_ne, sem_ne = necessidade_por_ne(filtrado, _meses_liquidados(), exercicio)
        return por_ne.set_index("ne_curta"), sem_ne

    def test_sem_vigencia_e_ativo_nada_muda(self):
        por_ne, sem_ne = self._por_ne()
        self.assertEqual(
            [por_ne.loc[ne, "necessidade"] for ne in (NE_A, NE_B, NE_C, NE_D)], [4000.0, 0.0, 600.0, 200.0]
        )
        self.assertEqual(sem_ne.iloc[0]["necessidade"], 800.0)
        self.assertTrue(por_ne["meses_vigentes"].isna().all())

    def test_suspenso_zera_a_necessidade(self):
        por_ne, _ = self._por_ne({NE_A: {"status_contrato": "SUSPENSO"}})
        self.assertEqual(por_ne.loc[NE_A, "meses_vigentes"], 0.0)
        self.assertEqual(por_ne.loc[NE_A, "meses_restantes"], 0.0)
        self.assertEqual(por_ne.loc[NE_A, "necessidade"], 0.0)  # era 4000

    def test_vencido_sem_data_zera_mas_vencido_com_vigencia_futura_segue_a_data(self):
        por_ne, _ = self._por_ne({NE_C: {"status_contrato": "VENCIDO"}})
        self.assertEqual(por_ne.loc[NE_C, "necessidade"], 0.0)  # era 600
        por_ne, _ = self._por_ne({NE_C: {"status_contrato": "VENCIDO", "vigencia_fim": pd.Timestamp("2027-03-01")}})
        self.assertEqual(por_ne.loc[NE_C, "necessidade"], 600.0)  # a data manda: inalterado

    def test_vigencia_limita_os_meses_com_mes_final_proporcional(self):
        # D: despesa 50, meses_no_ano 6, empenhado 100 (2 meses). Fim 15/03: vigente 2 + 15/31 meses
        # => restantes = 15/31; necessidade = 50 × 15/31 (sem saldo a abater).
        por_ne, _ = self._por_ne({NE_D: {"vigencia_fim": pd.Timestamp("2026-03-15")}})
        self.assertAlmostEqual(por_ne.loc[NE_D, "meses_restantes"], 15 / 31)
        self.assertAlmostEqual(por_ne.loc[NE_D, "necessidade"], 50 * 15 / 31)

    def test_vigencia_ja_coberta_pelo_empenho_nao_gera_necessidade(self):
        # C empenhou 6 meses e a vigência acaba em 30/06 (6 meses vigentes): nada a empenhar.
        por_ne, _ = self._por_ne({NE_C: {"vigencia_fim": pd.Timestamp("2026-06-30")}})
        self.assertEqual(por_ne.loc[NE_C, "meses_restantes"], 0.0)
        self.assertEqual(por_ne.loc[NE_C, "necessidade"], 0.0)

    def test_item_sem_ne_tambem_respeita_a_vigencia(self):
        # despesa 200, meses_no_ano 6, empenhado 400 (2 meses); fim 30/04 => 4 meses vigentes =>
        # restantes 2 => necessidade 400 (era 800).
        _, sem_ne = self._por_ne({None: {"vigencia_fim": pd.Timestamp("2026-04-30")}})
        self.assertEqual(sem_ne.iloc[0]["meses_restantes"], 2.0)
        self.assertEqual(sem_ne.iloc[0]["necessidade"], 400.0)

    def test_vigencia_encerrada_antes_do_exercicio(self):
        por_ne, _ = self._por_ne({NE_A: {"vigencia_fim": pd.Timestamp("2025-12-31")}})
        self.assertEqual(por_ne.loc[NE_A, "necessidade"], 0.0)

    def test_sem_exercicio_mantem_a_regra_anterior(self):
        por_ne, _ = self._por_ne({NE_A: {"status_contrato": "SUSPENSO"}}, exercicio=None)
        self.assertEqual(por_ne.loc[NE_A, "necessidade"], 4000.0)

    def test_total_do_relatorio_e_do_card_concordam(self):
        filtrado = _filtrado()
        filtrado.loc[filtrado["ne_curta"] == NE_A, "status_contrato"] = "SUSPENSO"
        relatorio = montar_relatorio(*necessidade_por_ne(filtrado, _meses_liquidados(), 2026), _liquidacao_mensal(), 2026, MES_REF)
        self.assertEqual(relatorio.total_necessidade, 5600.0 - 4000.0)
        self.assertIn("meses_vigentes", relatorio.linhas.columns)

    def test_excel_traz_meses_vigentes(self):
        filtrado = _filtrado()
        filtrado.loc[filtrado["ne_curta"] == NE_D, "vigencia_fim"] = pd.Timestamp("2026-03-15")
        relatorio = montar_relatorio(*necessidade_por_ne(filtrado, _meses_liquidados(), 2026), _liquidacao_mensal(), 2026, MES_REF)
        aba = load_workbook(BytesIO(gerar_xlsx(relatorio, _contexto())))["Resumo por NE"]
        cabecalho = [c.value for c in aba[1]]
        linhas = [dict(zip(cabecalho, [c.value for c in aba[n]])) for n in range(2, aba.max_row + 1)]
        d = next(l for l in linhas if l["NE"] == NE_D)
        self.assertAlmostEqual(d["Meses vigentes no exercício"], 2 + 15 / 31)
        a = next(l for l in linhas if l["NE"] == NE_A)
        self.assertIsNone(a["Meses vigentes no exercício"])  # sem limite pela vigência: vazio, não zero


class TestDataDaSuspensao(unittest.TestCase):
    """Data da suspensão (pedido explícito, 06/10/2026): com o status SUSPENSO, o contrato vale até a
    véspera da suspensão, como um fim de vigência (mês final proporcional); sem a data, SUSPENSO
    continua zerando o exercício inteiro. Só vale com o status SUSPENSO. Valores calculados à mão."""

    def test_meses_vigentes_ate_a_vespera_da_suspensao(self):
        casos = [
            (pd.Timestamp("2026-10-01"), pd.NaT, 9.0),  # véspera 30/09: jan–set
            (pd.Timestamp("2026-07-16"), pd.NaT, 6 + 15 / 31),  # véspera 15/07: jan–jun + 15/31 de julho
            (pd.Timestamp("2026-01-01"), pd.NaT, 0.0),  # suspenso desde o início do exercício
            (pd.Timestamp("2025-05-10"), pd.NaT, 0.0),  # suspenso antes do exercício
            (pd.Timestamp("2026-10-01"), pd.Timestamp("2026-06-30"), 6.0),  # vigência acaba antes: ela manda
        ]
        for suspensao, fim, esperado in casos:
            obtido = meses_vigentes_no_exercicio("SUSPENSO", fim, 2026, None, suspensao)
            self.assertAlmostEqual(obtido, esperado, msg=str((suspensao, fim)))

    def test_suspensao_depois_do_exercicio_nao_limita(self):
        self.assertIsNone(meses_vigentes_no_exercicio("SUSPENSO", pd.NaT, 2026, None, pd.Timestamp("2027-02-01")))

    def test_suspensao_respeita_o_inicio_da_execucao(self):
        # início 01/03, suspensão 01/10: mar–set = 7 meses
        obtido = meses_vigentes_no_exercicio("SUSPENSO", pd.NaT, 2026, pd.Timestamp("2026-03-01"), pd.Timestamp("2026-10-01"))
        self.assertAlmostEqual(obtido, 7.0)

    def test_sem_data_suspenso_continua_zerando_e_data_sem_status_suspenso_nao_tem_efeito(self):
        self.assertEqual(meses_vigentes_no_exercicio("SUSPENSO", pd.NaT, 2026, None, pd.NaT), 0.0)
        self.assertIsNone(meses_vigentes_no_exercicio("ATIVO", pd.NaT, 2026, None, pd.Timestamp("2026-10-01")))

    def test_necessidade_conta_so_ate_a_suspensao(self):
        # NE A: despesa 1000/mês, 12 meses, empenhado 8000 (8 meses). Necessidade sem suspensão: 4000.
        casos = [("2026-10-01", 1000.0), ("2026-09-16", 500.0), ("2026-09-01", 0.0)]  # 9, 8,5 e 8 meses vigentes
        for suspensao, esperado in casos:
            filtrado = _filtrado()
            filtrado.loc[filtrado["ne_curta"] == NE_A, "status_contrato"] = "SUSPENSO"
            filtrado.loc[filtrado["ne_curta"] == NE_A, "data_suspensao"] = pd.Timestamp(suspensao)
            por_ne, _ = necessidade_por_ne(filtrado, _meses_liquidados(), 2026)
            self.assertAlmostEqual(por_ne.set_index("ne_curta").loc[NE_A, "necessidade"], esperado, msg=suspensao)

    @staticmethod
    def _projecao_de_b(suspensao: str):
        filtrado = _filtrado()
        indice = filtrado.index[filtrado["ne_curta"] == NE_B][0]
        filtrado.loc[indice, "status_contrato"] = "SUSPENSO"
        filtrado.loc[indice, "data_suspensao"] = pd.Timestamp(suspensao)
        relatorio = _relatorio(_liquidacao_mensal(), filtrado=filtrado)
        linha = relatorio.mensal.loc[relatorio.linhas["ne_curta"] == NE_B].iloc[0]
        return relatorio, linha, [linha[f"p{m}"] for m in (10, 11, 12)]

    def test_projecao_para_na_vespera_com_mes_proporcional(self):
        # NE B projeta out–dez (out 500, nov 1000, dez 1000). Suspensão 16/11 → véspera 15/11:
        # out 500, nov 15/30 de 1000 = 500, dez nada.
        _, linha, meses = self._projecao_de_b("2026-11-16")
        self.assertEqual(meses[:2], [500.0, 500.0])
        self.assertTrue(math.isnan(meses[2]))
        self.assertEqual(linha["aviso_vigencia"], "suspenso")
        self.assertTrue(linha["observacao_projecao"].startswith("Suspenso em 16/11/2026"))

    def test_suspensao_antes_do_primeiro_mes_a_projetar_nao_projeta(self):
        _, linha, meses = self._projecao_de_b("2026-10-01")
        self.assertTrue(all(math.isnan(v) for v in meses))
        self.assertEqual(linha["observacao_projecao"], "Suspenso em 01/10/2026 — sem projeção")
        self.assertEqual(linha["aviso_vigencia"], "suspenso")

    def test_limite_de_projecao_com_data(self):
        limite = limite_de_projecao("SUSPENSO", pd.NaT, 2026, None, pd.Timestamp("2026-07-16"))
        self.assertEqual((limite.ultimo_mes, limite.mes_do_fim, limite.aviso), (7, 7, "suspenso"))
        self.assertAlmostEqual(limite.fracao_ultimo_mes, 15 / 31)
        sem_data = limite_de_projecao("SUSPENSO", pd.NaT, 2026, None, pd.NaT)
        self.assertEqual((sem_data.ultimo_mes, sem_data.motivo), (0, "Suspenso — sem projeção"))


class TestInicioDaExecucao(unittest.TestCase):
    """Início da execução (pedido explícito, 02/10/2026): os meses anteriores ao início não contam,
    com o mês inicial proporcional aos dias. Só vale o início INFORMADO (data ou mês manual); o
    mês detectado pelo primeiro empenho não corta nada. Valores calculados à mão."""

    def test_meses_vigentes_com_inicio(self):
        casos = [
            ((pd.Timestamp("2026-07-01"), None), 6.0),  # jul–dez
            ((pd.Timestamp("2026-07-16"), None), 5 + 16 / 31),  # jul tem 31 dias; do dia 16 ao 31 = 16 dias
            ((pd.Timestamp("2026-03-01"), pd.Timestamp("2026-06-15")), 3.5),  # mar, abr, mai + 15/30 de jun
            ((pd.Timestamp("2025-06-01"), None), None),  # início em ano anterior: não limita
            ((pd.Timestamp("2026-01-01"), None), None),  # início em 1º de janeiro: não limita
            ((pd.Timestamp("2027-01-01"), None), 0.0),  # início em ano posterior: nada no exercício
            ((pd.Timestamp("2026-08-01"), pd.Timestamp("2026-06-30")), 0.0),  # fim antes do início
        ]
        for (inicio, fim), esperado in casos:
            obtido = meses_vigentes_no_exercicio("ATIVO", fim if fim is not None else pd.NaT, 2026, inicio)
            if esperado is None:
                self.assertIsNone(obtido, (inicio, fim))
            else:
                self.assertAlmostEqual(obtido, esperado, msg=str((inicio, fim)))

    def test_suspenso_e_vencido_sem_data_zeram_mesmo_com_inicio(self):
        self.assertEqual(meses_vigentes_no_exercicio("SUSPENSO", pd.NaT, 2026, pd.Timestamp("2026-03-01")), 0.0)
        self.assertEqual(meses_vigentes_no_exercicio("VENCIDO", pd.NaT, 2026, pd.Timestamp("2026-03-01")), 0.0)

    def _por_ne(self, ne: str, campos: dict):
        filtrado = _filtrado()
        for campo, valor in campos.items():
            filtrado.loc[filtrado["ne_curta"] == ne, campo] = valor
        por_ne, _ = necessidade_por_ne(filtrado, _meses_liquidados(), 2026)
        return por_ne.set_index("ne_curta").loc[ne]

    def test_inicio_por_data_proporcional_reduz_os_meses_do_card(self):
        # C: despesa 100, 6 meses já empenhados. Início 16/02: o mês de fevereiro (28 dias) conta
        # 13/28 — vigente 11 − 15/28... = (12 − (1 + 15/28)) = 10,4643 meses; restantes 4,4643;
        # necessidade 446,43 (era 600 contando janeiro e fevereiro inteiros).
        c = self._por_ne(NE_C, {"inicio_execucao_data": pd.Timestamp("2026-02-16")})
        self.assertAlmostEqual(c["meses_vigentes"], 12 - (1 + 15 / 28))
        self.assertAlmostEqual(c["meses_restantes"], 12 - (1 + 15 / 28) - 6)
        self.assertAlmostEqual(c["necessidade"], 100 * (12 - (1 + 15 / 28) - 6))

    def test_inicio_por_mes_manual_conta_do_dia_primeiro(self):
        # início manual em julho = 1º/07 => 6 meses vigentes; C já empenhou 6 => nada a empenhar.
        c = self._por_ne(NE_C, {"inicio_execucao_mes": 7})
        self.assertEqual(c["meses_vigentes"], 6.0)
        self.assertEqual(c["necessidade"], 0.0)

    def test_data_manda_sobre_o_mes(self):
        c = self._por_ne(NE_C, {"inicio_execucao_mes": 7, "inicio_execucao_data": pd.Timestamp("2026-02-16")})
        self.assertAlmostEqual(c["necessidade"], 100 * (12 - (1 + 15 / 28) - 6))

    def test_mes_detectado_automaticamente_nao_corta_nada(self):
        c = self._por_ne(NE_C, {"inicio_execucao_efetivo": 7})  # só o auto-detectado, sem início manual
        self.assertTrue(pd.isna(c["meses_vigentes"]))
        self.assertEqual(c["necessidade"], 600.0)  # inalterada

    def test_inicio_combina_com_o_fim_da_vigencia(self):
        # início 1º/03 e fim 30/06: 4 meses vigentes (mar–jun); C empenhou 6 => nada a empenhar.
        c = self._por_ne(NE_C, {"inicio_execucao_data": pd.Timestamp("2026-03-01"), "vigencia_fim": pd.Timestamp("2026-06-30")})
        self.assertEqual(c["meses_vigentes"], 4.0)
        self.assertEqual(c["necessidade"], 0.0)

    def test_aviso_de_inicio_provavel_sem_definicao(self):
        filtrado = _filtrado()
        filtrado.loc[filtrado["ne_curta"] == NE_D, "inicio_execucao_efetivo"] = 7  # 1º empenho em julho
        relatorio = montar_relatorio(*necessidade_por_ne(filtrado, _meses_liquidados(), 2026), _liquidacao_mensal(), 2026, MES_REF)
        avisos = _avisos(relatorio, _contexto())
        self.assertTrue(any("sem início da execução definido" in a and f"{NE_D} (1º empenho em Jul)" in a for a in avisos))
        # definido o início (data), o aviso some
        filtrado.loc[filtrado["ne_curta"] == NE_D, "inicio_execucao_data"] = pd.Timestamp("2026-07-01")
        relatorio = montar_relatorio(*necessidade_por_ne(filtrado, _meses_liquidados(), 2026), _liquidacao_mensal(), 2026, MES_REF)
        self.assertFalse(any("sem início da execução definido" in a for a in _avisos(relatorio, _contexto())))


class TestInicioNaProjecaoDaGrade(unittest.TestCase):
    """B: despesa 1000, saldo 500, sem competência => projeta de outubro (referência = setembro)."""

    @staticmethod
    def _grade_de_b(inicio: str | None):
        filtrado = _filtrado()
        if inicio:
            filtrado.loc[filtrado["ne_curta"] == NE_B, "inicio_execucao_data"] = pd.Timestamp(inicio)
        relatorio = _relatorio(_liquidacao_mensal(), filtrado=filtrado)
        linha = relatorio.mensal.loc[relatorio.linhas["ne_curta"] == NE_B].iloc[0]
        return linha, [linha[f"p{m}"] for m in (10, 11, 12)]

    def test_funcao_fracao_do_primeiro_e_do_ultimo_mes(self):
        # primeiro mês só 16/31: gasto 1000×16/31 − saldo 500 => 16,13; depois a despesa cheia.
        meses = projetar_necessidade_mensal(1000.0, 500.0, 10, 3, fracao_primeiro_mes=16 / 31)
        self.assertAlmostEqual(meses[9], 1000 * 16 / 31 - 500)
        self.assertAlmostEqual(meses[10], 1000.0)
        self.assertAlmostEqual(meses[11], 1000.0)

    def test_funcao_mes_unico_combina_as_duas_fracoes(self):
        # começa dia 11 (21/31 do mês) e termina dia 20 (20/31): 10 dias => 10/31 da despesa.
        meses = projetar_necessidade_mensal(1000.0, 0.0, 10, 1, fracao_ultimo_mes=20 / 31, fracao_primeiro_mes=21 / 31)
        self.assertAlmostEqual(meses[9], 1000 * 10 / 31)

    def test_sem_inicio_nada_muda(self):
        _, meses = self._grade_de_b(None)
        self.assertEqual(meses, [500.0, 1000.0, 1000.0])

    def test_inicio_no_meio_do_primeiro_mes_projetado_e_proporcional(self):
        linha, meses = self._grade_de_b("2026-10-16")
        self.assertAlmostEqual(meses[0], 1000 * 16 / 31 - 500)
        self.assertAlmostEqual(meses[1], 1000.0)
        self.assertAlmostEqual(meses[2], 1000.0)
        self.assertIn("mês inicial proporcional: 16/31 dias", linha["observacao_projecao"])

    def test_inicio_depois_do_primeiro_mes_sem_liquidacao_adia_a_projecao(self):
        # início em 1º/11: outubro não projeta; novembro: 1000 − saldo 500 = 500; dezembro 1000.
        linha, meses = self._grade_de_b("2026-11-01")
        self.assertTrue(math.isnan(meses[0]))
        self.assertEqual(meses[1:], [500.0, 1000.0])
        self.assertEqual(linha["primeiro_mes_projecao"], 11)

    def test_inicio_no_ano_seguinte_nao_projeta(self):
        linha, meses = self._grade_de_b("2027-02-01")
        self.assertTrue(all(math.isnan(v) for v in meses))
        self.assertIn("sem projeção no exercício", linha["observacao_projecao"])

    def test_inicio_e_fim_no_mesmo_mes(self):
        filtrado = _filtrado()
        filtrado.loc[filtrado["ne_curta"].isna(), "inicio_execucao_data"] = pd.Timestamp("2026-10-11")
        filtrado.loc[filtrado["ne_curta"].isna(), "vigencia_fim"] = pd.Timestamp("2026-10-20")
        relatorio = _relatorio(_liquidacao_mensal(), filtrado=filtrado)
        linha = relatorio.mensal.loc[relatorio.linhas["ne_curta"].isna()].iloc[0]
        self.assertAlmostEqual(linha["p10"], 200 * 10 / 31)  # item sem NE, sem saldo: 10 dias de outubro
        self.assertTrue(math.isnan(linha["p11"]))

    def test_excel_traz_a_coluna_de_inicio(self):
        filtrado = _filtrado()
        filtrado.loc[filtrado["ne_curta"] == NE_B, "inicio_execucao_data"] = pd.Timestamp("2026-10-16")
        relatorio = _relatorio(_liquidacao_mensal(), filtrado=filtrado)
        aba = load_workbook(BytesIO(gerar_xlsx(relatorio, _contexto())))["Projeção mensal"]
        cabecalho = [c.value for c in aba[1]]
        linhas = [dict(zip(cabecalho, [c.value for c in aba[n]])) for n in range(2, aba.max_row + 1)]
        b = next(l for l in linhas if l["NE"] == NE_B)
        self.assertEqual(b["Início da execução"].date().isoformat(), "2026-10-16")
        a = next(l for l in linhas if l["NE"] == NE_A)
        self.assertIsNone(a["Início da execução"])  # não informado: vazio
        self.assertTrue(gerar_pdf(relatorio, _contexto()).startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
