"""Correção de 06/10/2026 — reforço de empenho em Contratos Contínuos:

1. NE na Execução Mensal sem nenhuma liquidação (nem lá, nem na Liquidação por Competência) passa a
   ter liquidado 0,00 confirmado, em vez de cair nos campos manuais do cadastro
   (`com_saldo_execucao`, `BASE_SEM_LIQUIDACAO`).
2. A projeção do relatório de Necessidade para essas NEs começa no início da execução, não no mês
   seguinte ao da extração (`montar_relatorio`).
3. A coluna "A empenhar" e a situação do Registro de contratos usam a Necessidade até dezembro
   (`necessidade_por_linha`, `situacao_contrato`), não o saldo.

Casos reais que motivaram (valores da base de 06/10/2026): NE 2026NE000522 (Prime, despesa mensal
R$ 63.702,83, empenho de um mês em set/2026, sem liquidação, início em 10/09/2026) e NE 2026NE000100
(saldo zero, vigência até 03/12/2026). Valores esperados calculados à mão em cada caso."""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.contratos_continuos import (
    SITUACAO_ATIVO,
    SITUACAO_NECESSITA_REFORCO,
    SITUACAO_SUSPENSO,
    SITUACAO_VENCIDO,
    SITUACAO_VIGENCIA_ENCERRADA,
    com_saldo_execucao,
    situacao_contrato,
)
from src.necessidade_empenho import calcular_necessidade_empenho
from src.relatorio_necessidade_empenho import (
    BASE_COMPETENCIA,
    BASE_SEM_LIQUIDACAO,
    _avisos,
    ContextoRelatorioNecessidade,
    montar_relatorio,
    necessidade_por_linha,
    necessidade_por_ne,
)

NE_PRIME = "2026NE000522"


def _por_ne_execucao(linhas: list[tuple[str, float, float | None]]) -> pd.DataFrame:
    registros = [
        {
            "ne_ccor": "00000000000" + curta, "empenhada": empenhada, "liquidada": liquidada,
            "saldo": empenhada - (liquidada or 0.0),
        }
        for curta, empenhada, liquidada in linhas
    ]
    return pd.DataFrame(registros, columns=["ne_ccor", "empenhada", "liquidada", "saldo"])


def _cadastro(linhas: list[dict]) -> pd.DataFrame:
    base = {
        "ne_curta": pd.NA, "despesa_mensal": 0.0, "valor_empenhado": 0.0,
        "saldo_colado_planilha": 0.0, "meses_empenhados": 0.0, "meses_liquidados": 0.0,
    }
    df = pd.DataFrame([{**base, **linha} for linha in linhas])
    df["meses_a_empenhar"], df["valor_a_empenhar"] = calcular_necessidade_empenho(
        df["meses_empenhados"], df["meses_liquidados"], df["despesa_mensal"]
    )
    return df


class TestLiquidadoZeroConfirmado(unittest.TestCase):
    def test_execucao_sem_liquidacao_nula_e_sem_competencia_vira_zero(self):
        # Prime: empenhado 63.702,83 na Execução, nenhuma liquidação lá (nula) nem na competência;
        # cadastro com campos manuais zerados. Antes: liquidado nulo → planilha (0 − 0) → A empenhar 0.
        df = _cadastro([{"ne_curta": NE_PRIME, "despesa_mensal": 63702.83}])
        indice_competencia = pd.Series({"2026NE000999": 10.0}, dtype="float64")
        resultado = com_saldo_execucao(df, _por_ne_execucao([(NE_PRIME, 63702.83, None)]), indice_competencia)
        self.assertEqual(resultado.loc[0, "valor_liquidado_execucao"], 0.0)
        self.assertTrue(bool(resultado.loc[0, "sem_liquidacao_confirmada"]))
        self.assertEqual(resultado.loc[0, "necessidade_via"], "execucao")
        self.assertAlmostEqual(resultado.loc[0, "meses_empenhados_execucao"], 1.0)
        self.assertAlmostEqual(resultado.loc[0, "meses_liquidados_execucao"], 0.0)

    def test_execucao_com_liquidacao_zero_tambem_confirma(self):
        df = _cadastro([{"ne_curta": NE_PRIME, "despesa_mensal": 1000.0}])
        indice_competencia = pd.Series({"2026NE000999": 10.0}, dtype="float64")
        resultado = com_saldo_execucao(df, _por_ne_execucao([(NE_PRIME, 1000.0, 0.0)]), indice_competencia)
        self.assertEqual(resultado.loc[0, "valor_liquidado_execucao"], 0.0)
        self.assertTrue(bool(resultado.loc[0, "sem_liquidacao_confirmada"]))

    def test_execucao_com_liquidacao_sem_competencia_continua_nulo(self):
        # as bases discordam (lançamento tem liquidação, competência não): nada é presumido
        df = _cadastro([{"ne_curta": NE_PRIME, "despesa_mensal": 1000.0, "meses_empenhados": 3.0, "meses_liquidados": 1.0}])
        indice_competencia = pd.Series({"2026NE000999": 10.0}, dtype="float64")
        resultado = com_saldo_execucao(df, _por_ne_execucao([(NE_PRIME, 5000.0, 2500.0)]), indice_competencia)
        self.assertTrue(pd.isna(resultado.loc[0, "valor_liquidado_execucao"]))
        self.assertFalse(bool(resultado.loc[0, "sem_liquidacao_confirmada"]))
        self.assertEqual(resultado.loc[0, "necessidade_via"], "planilha")

    def test_ne_fora_da_execucao_continua_nulo(self):
        df = _cadastro([{"ne_curta": "2026NE000777", "despesa_mensal": 1000.0}])
        indice_competencia = pd.Series({"2026NE000999": 10.0}, dtype="float64")
        resultado = com_saldo_execucao(df, _por_ne_execucao([(NE_PRIME, 1000.0, None)]), indice_competencia)
        self.assertTrue(pd.isna(resultado.loc[0, "valor_liquidado_execucao"]))
        self.assertFalse(bool(resultado.loc[0, "sem_liquidacao_confirmada"]))

    def test_sem_base_de_competencia_nada_muda(self):
        df = _cadastro([{"ne_curta": NE_PRIME, "despesa_mensal": 1000.0}])
        resultado = com_saldo_execucao(df, _por_ne_execucao([(NE_PRIME, 1000.0, None)]))
        self.assertTrue(pd.isna(resultado.loc[0, "valor_liquidado_execucao"]))
        self.assertFalse(bool(resultado.loc[0, "sem_liquidacao_confirmada"]))


def _linha_prime(**campos: object) -> dict:
    base = {
        "ne_curta": NE_PRIME, "fornecedor": "PRIME", "contrato_numero": "13/2026", "despesa_mensal": 63702.83,
        "meses_no_ano": 12.0, "valor_empenhado": 0.0, "valor_empenhado_execucao": 63702.83,
        "valor_empenhado_planilha_total_ne": 0.0, "valor_liquidado_execucao": 0.0,
        "liquidado_via_competencia": True, "saldo_execucao": 63702.83, "saldo_colado_planilha": 0.0,
        "status_contrato": "ATIVO", "vigencia_fim": pd.Timestamp("2027-09-10"),
        "inicio_execucao_data": pd.Timestamp("2026-09-10"), "inicio_execucao_mes": 9.0,
        "sem_liquidacao_confirmada": True,
    }
    base.update(campos)
    return base


def _relatorio(filtrado: pd.DataFrame, mes_ref: int = 10):
    por_ne, sem_ne = necessidade_por_ne(filtrado, None, 2026)
    return por_ne, montar_relatorio(por_ne, sem_ne, pd.DataFrame(columns=["ne_curta", "ano_mes", "valor"]), 2026, mes_ref)


class TestProjecaoSemLiquidacao(unittest.TestCase):
    def test_prime_projeta_desde_o_inicio_e_concorda_com_o_resumo(self):
        # custo: set 21/30 × 63.702,83 = 44.591,981 + out/nov/dez 3 × 63.702,83 = 235.700,471;
        # − empenhado 63.702,83 = 171.997,641 (Resumo). Grade: set 0 (saldo cobre), out 44.591,98,
        # nov e dez 63.702,83 cada → mesma soma.
        por_ne, relatorio = _relatorio(pd.DataFrame([_linha_prime()]))
        self.assertEqual(por_ne.loc[0, "base_saldo"], BASE_SEM_LIQUIDACAO)
        self.assertAlmostEqual(por_ne.loc[0, "necessidade"], 171997.641, places=2)
        self.assertEqual(int(relatorio.mensal.loc[0, "primeiro_mes_projecao"]), 9)
        self.assertAlmostEqual(relatorio.projetado_da_linha(0), 171997.641, places=2)
        self.assertAlmostEqual(relatorio.mensal.loc[0, "p9"], 0.0, places=2)
        self.assertAlmostEqual(relatorio.mensal.loc[0, "p10"], 44591.981, places=2)
        self.assertEqual(relatorio.nes_sem_realizado, [])

    def test_sem_inicio_informado_projeta_desde_janeiro(self):
        # 12 × 1000 − 1000 empenhado = 11.000 (Resumo); grade de jan a dez abatendo 1000 → mesma soma
        linha = _linha_prime(despesa_mensal=1000.0, valor_empenhado_execucao=1000.0, saldo_execucao=1000.0,
                             inicio_execucao_data=pd.NaT, inicio_execucao_mes=None, vigencia_fim=pd.NaT)
        por_ne, relatorio = _relatorio(pd.DataFrame([linha]))
        self.assertAlmostEqual(por_ne.loc[0, "necessidade"], 11000.0)
        self.assertEqual(int(relatorio.mensal.loc[0, "primeiro_mes_projecao"]), 1)
        self.assertAlmostEqual(relatorio.projetado_da_linha(0), 11000.0)

    def test_ne_sem_competencia_mas_com_liquidacao_segue_regra_antiga(self):
        # sem a confirmação (base por lançamento): começa no mês seguinte ao da extração (nov)
        linha = _linha_prime(liquidado_via_competencia=False, valor_liquidado_execucao=None,
                             sem_liquidacao_confirmada=False)
        por_ne, relatorio = _relatorio(pd.DataFrame([linha]))
        self.assertNotEqual(por_ne.loc[0, "base_saldo"], BASE_SEM_LIQUIDACAO)
        self.assertEqual(int(relatorio.mensal.loc[0, "primeiro_mes_projecao"]), 11)
        self.assertEqual(relatorio.nes_sem_realizado, [NE_PRIME])

    def test_sem_a_coluna_de_confirmacao_mantem_competencia(self):
        # chamador antigo (sem `sem_liquidacao_confirmada`): base continua "Competência"
        linha = _linha_prime()
        del linha["sem_liquidacao_confirmada"]
        por_ne, _ = _relatorio(pd.DataFrame([linha]))
        self.assertEqual(por_ne.loc[0, "base_saldo"], BASE_COMPETENCIA)

    def test_aviso_lista_a_ne_sem_liquidacao(self):
        _, relatorio = _relatorio(pd.DataFrame([_linha_prime()]))
        contexto = ContextoRelatorioNecessidade(
            exercicio=2026, data_extracao="06/10/2026", hash_manifesto="abcd", data_emissao="06/10/2026 12:00",
            origem_competencia="Liquidação por Competência.xlsx",
        )
        avisos = _avisos(relatorio, contexto)
        self.assertTrue(any("sem nenhuma liquidação" in a and NE_PRIME in a for a in avisos))
        self.assertFalse(any("projeção começa no mês seguinte ao da extração" in a and NE_PRIME in a for a in avisos))


class TestNecessidadePorLinha(unittest.TestCase):
    def test_mapeia_ne_sem_ne_compartilhada_e_ausente(self):
        filtrado = pd.DataFrame(
            {"ne_curta": ["2026NE000001", None, "2026NE000002", "2026NE000002", "2026NE000003"]},
            index=[10, 11, 12, 13, 14],
        )
        por_ne = pd.DataFrame({"ne_curta": ["2026NE000001", "2026NE000002"], "necessidade": [500.0, 0.0]})
        sem_ne = pd.DataFrame({"necessidade": [800.0]}, index=[11])
        resultado = necessidade_por_linha(filtrado, por_ne, sem_ne)
        self.assertEqual(resultado.loc[10], 500.0)
        self.assertEqual(resultado.loc[11], 800.0)
        self.assertEqual(resultado.loc[12], 0.0)  # zero declarado
        self.assertEqual(resultado.loc[13], 0.0)  # NE compartilhada: o valor da NE em cada linha
        self.assertTrue(pd.isna(resultado.loc[14]))  # sem cálculo: nulo, não zero


HOJE = date(2026, 10, 6)


class TestSituacaoContrato(unittest.TestCase):
    def test_status_do_cadastro_vem_primeiro(self):
        self.assertEqual(situacao_contrato("VENCIDO", pd.Timestamp("2027-01-01"), 9999.0, HOJE)[0], SITUACAO_VENCIDO)
        self.assertEqual(situacao_contrato("SUSPENSO", pd.Timestamp("2025-01-01"), 9999.0, HOJE)[0], SITUACAO_SUSPENSO)

    def test_ativo_com_vigencia_encerrada(self):
        # Brascon: ATIVO com vigência até 23/08/2026 (aditivo ainda não cadastrado)
        self.assertEqual(
            situacao_contrato("ATIVO", pd.Timestamp("2026-08-23"), 41434.20, HOJE),
            (SITUACAO_VIGENCIA_ENCERRADA, "bad"),
        )

    def test_vigencia_ate_hoje_ainda_vigente(self):
        self.assertEqual(situacao_contrato("ATIVO", pd.Timestamp("2026-10-06"), 0.0, HOJE)[0], SITUACAO_ATIVO)

    def test_reforco_vem_da_necessidade_nao_do_saldo(self):
        # NE100: saldo zero, necessidade 7.928,49 → reforço
        self.assertEqual(
            situacao_contrato("ATIVO", pd.Timestamp("2026-12-03"), 7928.49, HOJE),
            (SITUACAO_NECESSITA_REFORCO, "warn"),
        )
        # Minha Biblioteca: necessidade 0 (pagamento único já empenhado) → ativo
        self.assertEqual(situacao_contrato("ATIVO", pd.Timestamp("2027-09-28"), 0.0, HOJE)[0], SITUACAO_ATIVO)

    def test_necessidade_nula_e_sem_vigencia(self):
        self.assertEqual(situacao_contrato("ATIVO", pd.NaT, None, HOJE)[0], SITUACAO_ATIVO)
        self.assertEqual(situacao_contrato(None, None, float("nan"), HOJE)[0], SITUACAO_ATIVO)


if __name__ == "__main__":
    unittest.main()
