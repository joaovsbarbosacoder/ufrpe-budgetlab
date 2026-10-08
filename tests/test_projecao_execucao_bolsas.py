"""Testes da entrada de Bolsas e Auxílios no relatório "Projeção pela Execução"
(`src/projecao_execucao_bolsas.py` + `src/relatorio_projecao_execucao.py` com `custos`/`rotulos`).
Valores esperados calculados à mão em cada caso. O caso real usa a fixture congelada de Liquidação por
Competência (`tests/fixtures/liquidacao_competencia_2026-09-11.xlsx`), não `data/raw/`."""

from __future__ import annotations

import math
import unittest
from io import BytesIO
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from src.execucao_ne_utils import ne_curta
from src.liquidacao_competencia import ler_liquidacao_competencia, liquidado_por_ne_e_mes
from src.projecao_execucao_bolsas import custo_mensal_bolsa, entrada_relatorio, primeiro_mes_liquidado_por_ne
from src.relatorio_projecao_execucao import (
    BOLSAS_AUXILIOS,
    ORIGEM_EXECUCAO,
    TIPO_PROJETADO,
    ContextoProjecaoExecucao,
    gerar_pdf,
    gerar_xlsx,
    montar_relatorio,
)

FIXTURE_COMPETENCIA = Path(__file__).parent / "fixtures" / "liquidacao_competencia_2026-09-11.xlsx"


class TestCustoMensalBolsa(unittest.TestCase):
    def test_meses_a_partir_do_inicio(self):
        # 10 meses a partir de fevereiro: fev–nov; jan e dez fora
        custo = custo_mensal_bolsa(70000.0, 10, 2)
        self.assertEqual(custo, [0.0] + [70000.0] * 10 + [0.0])

    def test_para_em_dezembro(self):
        # 10 meses a partir de maio: mai–dez (8 meses); o resto cairia em 2027, fora do exercício
        custo = custo_mensal_bolsa(5600.0, 10, 5)
        self.assertEqual(custo, [0.0] * 4 + [5600.0] * 8)

    def test_sem_inicio_comeca_em_janeiro(self):
        self.assertEqual(custo_mensal_bolsa(1000.0, 3, None), [1000.0] * 3 + [0.0] * 9)
        self.assertEqual(custo_mensal_bolsa(1000.0, 3, float("nan")), [1000.0] * 3 + [0.0] * 9)

    def test_meses_no_ano_vazio_vale_12(self):
        self.assertEqual(custo_mensal_bolsa(1000.0, None, None), [1000.0] * 12)

    def test_fracao_de_mes(self):
        # 2,5 meses a partir de outubro: out 1.000, nov 1.000, dez 500
        self.assertEqual(custo_mensal_bolsa(1000.0, 2.5, 10), [0.0] * 9 + [1000.0, 1000.0, 500.0])

    def test_valor_nulo_continua_nulo_e_zero_continua_zero(self):
        self.assertTrue(all(math.isnan(v) for v in custo_mensal_bolsa(None, 12, 1)))
        self.assertEqual(custo_mensal_bolsa(0.0, 12, 1), [0.0] * 12)

    def test_inicio_invalido(self):
        with self.assertRaises(ValueError):
            custo_mensal_bolsa(1000.0, 12, 13)


def _programa(**campos: object) -> dict:
    base = {
        "ne_curta": None, "programa_bolsa": "P", "processo": "1/2026", "situacao_tg": "ATUALIZADO",
        "valor_mensal": 1000.0, "meses_no_ano": 12, "inicio_execucao_mes": None, "inicio_execucao_efetivo": None,
        "valor_empenhado_execucao": None, "valor_empenhado_tg": None,
        "saldo_execucao": None, "saldo_colado_planilha": None,
    }
    base.update(campos)
    return base


class TestEntradaRelatorio(unittest.TestCase):
    def test_uma_linha_por_ne_e_sem_ne_a_parte(self):
        filtrado = pd.DataFrame([
            # dois programas na mesma NE: valor mensal e custo somam; saldo/empenhado da NE entram uma vez
            _programa(ne_curta="2026NE000001", programa_bolsa="A", processo="10/2026", valor_mensal=1000.0,
                      meses_no_ano=12, valor_empenhado_execucao=9000.0, saldo_execucao=2000.0),
            _programa(ne_curta="2026NE000001", programa_bolsa="B", processo="10/2026", valor_mensal=500.0,
                      meses_no_ano=6, inicio_execucao_efetivo=7, valor_empenhado_execucao=9000.0,
                      saldo_execucao=2000.0),
            # sem saldo na Execução Mensal: usa o colado na planilha
            _programa(ne_curta="2026NE000002", programa_bolsa="C", valor_mensal=200.0,
                      valor_empenhado_tg=600.0, saldo_colado_planilha=150.0),
            _programa(ne_curta=None, programa_bolsa="SEM NE"),
        ])
        por_ne, sem_ne, custos = entrada_relatorio(filtrado)

        self.assertEqual(por_ne["ne_curta"].tolist(), ["2026NE000001", "2026NE000002"])
        self.assertEqual(len(sem_ne), 1)
        ne1 = por_ne.set_index("ne_curta").loc["2026NE000001"]
        self.assertEqual(ne1["fornecedor"], "A; B")
        self.assertEqual(ne1["contrato_numero"], "10/2026")
        self.assertEqual(ne1["despesa_mensal"], 1500.0)
        self.assertEqual(ne1["valor_empenhado_exibido"], 9000.0)
        self.assertEqual(ne1["saldo_para_necessidade"], 2000.0)
        # necessidade do Resumo: A = 1.000 × (12 − 9) = 3.000; B = 500 × max(0, 6 − 18) = 0
        self.assertEqual(ne1["necessidade"], 3000.0)
        self.assertEqual(custos["2026NE000001"], [1000.0] * 6 + [1500.0] * 6)
        ne2 = por_ne.set_index("ne_curta").loc["2026NE000002"]
        self.assertEqual(ne2["valor_empenhado_exibido"], 600.0)
        self.assertEqual(ne2["saldo_para_necessidade"], 150.0)
        self.assertEqual(ne2["necessidade"], 200.0 * 9)  # 12 − 600/200

    def test_inicio_pelo_primeiro_mes_liquidado(self):
        # NE 1: empenho em jan (efetivo 1), liquidação a partir de fev → início fev: fev–nov.
        # NE 2: início manual em mar prevalece sobre a liquidação (fev).
        # NE 3: sem liquidação no exercício → primeiro empenho (abr).
        # NE 4: só estorno/zero no exercício e liquidação em 2025 → não contam; sem empenho → janeiro.
        filtrado = pd.DataFrame([
            _programa(ne_curta="2026NE000001", meses_no_ano=10, inicio_execucao_efetivo=1),
            _programa(ne_curta="2026NE000002", meses_no_ano=10, inicio_execucao_mes=3, inicio_execucao_efetivo=3),
            _programa(ne_curta="2026NE000003", meses_no_ano=2, inicio_execucao_efetivo=4),
            _programa(ne_curta="2026NE000004", meses_no_ano=2),
        ])
        competencia = pd.DataFrame({
            "ne_curta": ["2026NE000001", "2026NE000001", "2026NE000002", "2026NE000004", "2026NE000004", "2026NE000004"],
            "ano_mes": [202602, 202603, 202602, 202505, 202606, 202607],
            "valor": [1000.0, 1000.0, 1000.0, 1000.0, -50.0, 0.0],
        })
        _, _, custos = entrada_relatorio(filtrado, competencia, 2026)
        self.assertEqual(custos["2026NE000001"], [0.0] + [1000.0] * 10 + [0.0])
        self.assertEqual(custos["2026NE000002"], [0.0] * 2 + [1000.0] * 10)
        self.assertEqual(custos["2026NE000003"], [0.0] * 3 + [1000.0] * 2 + [0.0] * 7)
        self.assertEqual(custos["2026NE000004"], [1000.0] * 2 + [0.0] * 10)

    def test_primeiro_mes_liquidado_por_ne(self):
        competencia = pd.DataFrame({
            "ne_curta": ["A", "A", "B", "C"], "ano_mes": [202605, 202603, 202512, 202604], "valor": [1.0, 2.0, 5.0, -1.0],
        })
        self.assertEqual(primeiro_mes_liquidado_por_ne(competencia, 2026).to_dict(), {"A": 3})
        self.assertTrue(primeiro_mes_liquidado_por_ne(None, 2026).empty)

    def test_nao_altera_a_entrada(self):
        filtrado = pd.DataFrame([_programa(ne_curta="2026NE000001")])
        copia = filtrado.copy()
        entrada_relatorio(filtrado)
        pd.testing.assert_frame_equal(filtrado, copia)


def _competencia_fixture() -> pd.DataFrame:
    tempo = liquidado_por_ne_e_mes(ler_liquidacao_competencia(FIXTURE_COMPETENCIA))
    tempo["ne_curta"] = tempo["ne_ccor"].apply(ne_curta)
    return tempo


NE_REAL = "2026NE000022"  # bolsa real: 70.000/mês, 10 meses, início em fevereiro


def _relatorio_real():
    filtrado = pd.DataFrame([
        _programa(ne_curta=NE_REAL, programa_bolsa="PROGRAMA REAL", processo="23082.000000/2026-00",
                  valor_mensal=70000.0, meses_no_ano=10, inicio_execucao_efetivo=1,
                  valor_empenhado_execucao=560000.0, saldo_execucao=10000.0),
        _programa(ne_curta=None, programa_bolsa="SEM NE"),
    ])
    competencia = _competencia_fixture()
    # início pela competência (fev), não pelo primeiro empenho (jan) — caso real que motivou a regra
    por_ne, sem_ne, custos = entrada_relatorio(filtrado, competencia, 2026)
    # extração da fixture: 11/09/2026 → mês de referência 9, fechados até junho
    return montar_relatorio(por_ne, sem_ne, competencia, 2026, 9, custos=custos, rotulos=BOLSAS_AUXILIOS)


class TestRelatorioBolsasFixture(unittest.TestCase):
    def test_projecao_calculada_a_mao(self):
        # Fixture (competência de 2026): fev–abr 70.000, mai 69.300, jun–ago 70.000.
        # Meses fechados com registro: fev–jun (5). Observada = 349.300 ÷ 350.000 = 0,998.
        # Razões 1; 1; 1; 0,99; 1 → média 0,998; variância amostral = (4 × 0,002² + 0,008²) ÷ 4 = 0,00002.
        # Peso = 5 × 0,01 ÷ (0,05 + 0,00002) = 0,9996002; fator = 1 − 0,002 × 0,9996002 = 0,9980008.
        # Jul e ago (em aberto) com 70.000 ≥ 50% do esperado → completos. Set, out, nov: 70.000 × fator
        # cada (dez fora: 10 meses a partir de fevereiro). Projetado = 210.000 × 0,9980008 = 209.580,17.
        # Valor cheio = 210.000. Necessidade pela execução = 209.580,17 − saldo 10.000 = 199.580,17.
        # Necessidade do Resumo = 70.000 × (10 − 560.000/70.000) = 140.000.
        relatorio = _relatorio_real()
        linha = relatorio.linhas.set_index("ne_curta").loc[NE_REAL]
        self.assertEqual(linha["origem_fator"], ORIGEM_EXECUCAO)
        self.assertEqual(linha["meses_usados"], "Fev, Mar, Abr, Mai, Jun")
        self.assertAlmostEqual(linha["execucao_observada"], 0.998, places=9)
        self.assertAlmostEqual(linha["peso"], 0.05 / 0.05002, places=9)
        self.assertAlmostEqual(linha["fator"], 1 - 0.002 * 0.05 / 0.05002, places=9)
        self.assertAlmostEqual(linha["restante_em_aberto"], 0.0)
        self.assertAlmostEqual(linha["projetado_execucao"], 209580.17, places=2)
        self.assertAlmostEqual(linha["projetado_valor_cheio"], 210000.0)
        self.assertAlmostEqual(linha["necessidade_execucao"], 199580.17, places=2)
        self.assertAlmostEqual(linha["necessidade_contratual"], 140000.0)
        indice = relatorio.linhas.index[relatorio.linhas["ne_curta"] == NE_REAL][0]
        self.assertEqual([relatorio.mensal.at[indice, f"t{m}"] for m in (9, 10, 11)], [TIPO_PROJETADO] * 3)
        self.assertIsNone(relatorio.mensal.at[indice, "t12"])
        self.assertEqual(relatorio.qtd_sem_ne, 1)
        self.assertTrue(any("programa(s) sem NE" in a and "Resumo Consolidado" in a for a in relatorio.avisos))

    def test_arquivos_com_rotulos_de_bolsas(self):
        relatorio = _relatorio_real()
        contexto = ContextoProjecaoExecucao(2026, "11/09/2026", "abcd1234", "07/10/2026 12:00", FIXTURE_COMPETENCIA.name)
        self.assertTrue(gerar_pdf(relatorio, contexto).startswith(b"%PDF"))
        livro = load_workbook(BytesIO(gerar_xlsx(relatorio, contexto)))
        cabecalho = [c.value for c in livro["Resumo por NE"][1]]
        for coluna in ("Programa", "Processo", "Situação", "Despesa projetada (valor cadastrado)",
                       "Necessidade até dezembro (Resumo Consolidado)"):
            self.assertIn(coluna, cabecalho)
        self.assertNotIn("Fornecedor", cabecalho)
        linha = next(r for r in livro["Resumo por NE"].iter_rows(min_row=2, values_only=True) if r[0] == NE_REAL)
        self.assertEqual(linha[cabecalho.index("Programa")], "PROGRAMA REAL")
        self.assertEqual([c.value for c in livro["Grade mensal"][1]][1], "Programa")
        parametros = {r[0]: r[1] for r in livro["Parâmetros"].iter_rows(min_row=2, values_only=True)}
        self.assertIn("Despesa projetada pelo valor cadastrado (R$)", parametros)
        self.assertIn("início da execução", parametros["Regra"])

    def test_nota_descreve_a_ordem_do_inicio(self):
        # a nota impressa segue a ordem de `primeiro_mes_liquidado_por_ne`/`entrada_relatorio`:
        # cadastro → liquidação por competência → primeiro empenho → janeiro
        nota = BOLSAS_AUXILIOS.nota_regra
        posicoes = [nota.index(t) for t in ("informado no cadastro", "liquidação positiva por competência",
                                            "primeiro empenho", "janeiro")]
        self.assertEqual(posicoes, sorted(posicoes))


if __name__ == "__main__":
    unittest.main()
