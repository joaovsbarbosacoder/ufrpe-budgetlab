"""Testes de `src/estimativa_reajuste.py` — estimativa de reajuste por competência (11/10/2026).

Spec: `docs/superpowers/specs/2026-10-11-estimativa-reajuste-contratos-design.md`. Valores calculados à mão.
Contrato-base: R$ 10.000/mês; reajuste manual de 5%.
"""

from __future__ import annotations

import unittest
from datetime import date

from src.contratos_aditivos import Aditivo, validar_aditivos
from src.estimativa_reajuste import (
    ParametrosReajuste,
    aditivo_previsto_do_ciclo,
    datas_base,
    estimar_contrato,
    liquidado_do_contrato,
    nes_em_conflito,
    ultimo_mes_coberto,
)

import pandas as pd

CINCO = ParametrosReajuste(indice=None, percentual_manual=5.0, data_base_manual=None)


def _estimar(inicio=date(2026, 6, 1), fim=date(2028, 5, 31), params=CINCO, aditivos=(), **extra):
    return estimar_contrato(
        contrato="01/2026", despesa_mensal=10_000.0, aditivos=list(aditivos),
        vigencia_inicio=inicio, vigencia_fim=fim, parametros=params, exercicio_inicial=2026, **extra,
    )


def _linha(estimativa, ano: int, mes: int):
    tabela = estimativa.matriz
    return tabela[(tabela["ano"] == ano) & (tabela["mes"] == mes)].iloc[0]


def _soma(estimativa) -> float:
    return float(estimativa.matriz["acrescimo"].dropna().sum())


class DatasBaseTests(unittest.TestCase):
    def test_primeira_data_base_e_doze_meses_apos_o_inicio_e_so_dentro_da_vigencia(self) -> None:
        datas, motivo = datas_base(
            vigencia_inicio=date(2026, 6, 1), vigencia_fim_efetiva=date(2028, 5, 31), aditivos=[], data_base_manual=None
        )
        self.assertEqual((datas, motivo), ([date(2027, 6, 1)], "ok"))  # 01/06/2028 já é depois do fim

    def test_ciclos_se_repetem_a_cada_doze_meses(self) -> None:
        datas, _ = datas_base(
            vigencia_inicio=date(2026, 6, 1), vigencia_fim_efetiva=date(2029, 5, 31), aditivos=[], data_base_manual=None
        )
        self.assertEqual(datas, [date(2027, 6, 1), date(2028, 6, 1)])

    def test_ultimo_reajuste_assinado_manda_sobre_o_inicio(self) -> None:
        reajuste = Aditivo(numero="1º TA", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2027, 1, 1), valor_mensal=10_500.0)
        previsto = Aditivo(numero="x", tipo="REAJUSTE", situacao="PREVISTO", data_inicio=date(2027, 3, 1), valor_mensal=11_000.0)
        datas, _ = datas_base(
            vigencia_inicio=date(2026, 6, 1), vigencia_fim_efetiva=date(2028, 5, 31),
            aditivos=[reajuste, previsto], data_base_manual=None,
        )
        self.assertEqual(datas, [date(2028, 1, 1)])  # o PREVISTO não conta

    def test_data_base_e_o_inicio_da_vigencia_de_renovacao_mais_recente_e_se_repete(self) -> None:
        datas, _ = datas_base(
            vigencia_inicio=date(2022, 1, 27), inicios_vigencia=[date(2025, 1, 27), date(2026, 1, 27), date(2023, 1, 27)],
            vigencia_fim_efetiva=date(2027, 12, 31), aditivos=[], data_base_manual=None, a_partir_de=date(2026, 1, 1),
        )
        # a renovação de 27/01/2026 é a data-base; o contrato original (2022) e as renovações antigas não mandam
        self.assertEqual(datas, [date(2026, 1, 27), date(2027, 1, 27)])

    def test_renovacao_antiga_cai_no_aniversario_do_exercicio(self) -> None:
        datas, _ = datas_base(
            vigencia_inicio=date(2022, 1, 27), inicios_vigencia=[date(2025, 6, 10)], vigencia_fim_efetiva=date(2027, 12, 31),
            aditivos=[], data_base_manual=None, a_partir_de=date(2026, 1, 1),
        )
        self.assertEqual(datas, [date(2026, 6, 10), date(2027, 6, 10)])

    def test_reajuste_assinado_na_renovacao_ja_esta_refletido(self) -> None:
        reajuste = Aditivo(numero="5º TA", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2026, 1, 27), valor_mensal=11_000.0)
        datas, _ = datas_base(
            vigencia_inicio=date(2022, 1, 27), inicios_vigencia=[date(2026, 1, 27)], vigencia_fim_efetiva=date(2028, 12, 31),
            aditivos=[reajuste], data_base_manual=None, a_partir_de=date(2026, 1, 1),
        )
        self.assertEqual(datas, [date(2027, 1, 27), date(2028, 1, 27)])  # o de 2026 já está no valor em vigor

    def test_aditivo_assinado_de_vigencia_ancora_e_o_previsto_nao(self) -> None:
        prorrogacao = Aditivo(
            numero="3º TA", tipo="PRORROGACAO", situacao="ASSINADO", data_inicio=date(2026, 3, 1), vigencia_fim=date(2027, 12, 31)
        )
        previsto = Aditivo(
            numero="4º TA", tipo="PRORROGACAO", situacao="PREVISTO", data_inicio=date(2026, 9, 1), vigencia_fim=date(2028, 12, 31)
        )
        datas, _ = datas_base(
            vigencia_inicio=date(2022, 1, 27), vigencia_fim_efetiva=date(2028, 12, 31), aditivos=[prorrogacao, previsto],
            data_base_manual=None, a_partir_de=date(2026, 1, 1),
        )
        self.assertEqual(datas, [date(2026, 3, 1), date(2027, 3, 1), date(2028, 3, 1)])

    def test_data_base_manual_e_a_proxima_data_base(self) -> None:
        datas, _ = datas_base(
            vigencia_inicio=date(2026, 6, 1), vigencia_fim_efetiva=date(2028, 5, 31), aditivos=[], data_base_manual=date(2027, 6, 16)
        )
        self.assertEqual(datas, [date(2027, 6, 16)])

    def test_motivos_sem_data_sem_fim_e_sem_ciclo_na_vigencia(self) -> None:
        sem_data = datas_base(vigencia_inicio=None, vigencia_fim_efetiva=date(2028, 5, 31), aditivos=[], data_base_manual=None)
        self.assertEqual(sem_data, ([], "sem_data_base"))
        sem_fim = datas_base(vigencia_inicio=date(2026, 6, 1), vigencia_fim_efetiva=None, aditivos=[], data_base_manual=None)
        self.assertEqual(sem_fim, ([], "sem_vigencia_fim"))
        curto = datas_base(vigencia_inicio=date(2026, 6, 1), vigencia_fim_efetiva=date(2027, 5, 31), aditivos=[], data_base_manual=None)
        self.assertEqual(curto, ([], "sem_reajuste_na_vigencia"))


class MatrizPorCompetenciaTests(unittest.TestCase):
    def test_contrato_de_dois_anos_so_acrescenta_a_partir_da_data_base(self) -> None:
        estimativa = _estimar()
        self.assertEqual(estimativa.situacao, "estimado")
        self.assertEqual(len(estimativa.matriz), 24)  # jun/2026 .. mai/2028
        self.assertAlmostEqual(_linha(estimativa, 2027, 5)["acrescimo"], 0.0)
        self.assertAlmostEqual(_linha(estimativa, 2027, 6)["acrescimo"], 500.0)
        self.assertAlmostEqual(_linha(estimativa, 2028, 5)["acrescimo"], 500.0)
        self.assertAlmostEqual(_soma(estimativa), 6_000.0)  # 12 x 500
        self.assertEqual(_linha(estimativa, 2027, 6)["base_origem"], "contratado")
        self.assertEqual(_linha(estimativa, 2027, 6)["percentual_origem"], "manual")

    def test_contrato_de_doze_meses_sem_prorrogacao_nao_tem_reajuste_nem_zero_presumido(self) -> None:
        estimativa = _estimar(fim=date(2027, 5, 31))
        self.assertEqual(estimativa.situacao, "sem_reajuste_na_vigencia")
        self.assertEqual(len(estimativa.matriz), 12)
        self.assertAlmostEqual(_soma(estimativa), 0.0)

    def test_prorrogacao_prevista_cria_o_ciclo_e_marca_as_competencias(self) -> None:
        prorrogacao = Aditivo(
            numero="1º TA", tipo="PRORROGACAO", situacao="PREVISTO", data_inicio=date(2027, 6, 1), vigencia_fim=date(2028, 5, 31)
        )
        estimativa = _estimar(fim=date(2027, 5, 31), aditivos=[prorrogacao])
        self.assertEqual(estimativa.situacao, "estimado")
        self.assertAlmostEqual(_soma(estimativa), 6_000.0)
        self.assertFalse(bool(_linha(estimativa, 2027, 5)["prorrogacao_prevista"]))
        self.assertTrue(bool(_linha(estimativa, 2027, 6)["prorrogacao_prevista"]))

    def test_data_base_no_meio_do_mes_e_proporcional_aos_dias(self) -> None:
        params = ParametrosReajuste(indice=None, percentual_manual=5.0, data_base_manual=date(2027, 6, 16))
        estimativa = _estimar(params=params)
        self.assertAlmostEqual(_linha(estimativa, 2027, 6)["acrescimo"], 250.0)  # 16..30 = 15/30 do mês
        self.assertAlmostEqual(_linha(estimativa, 2027, 7)["acrescimo"], 500.0)
        self.assertAlmostEqual(_soma(estimativa), 5_750.0)  # 250 + 11 x 500

    def test_ciclos_sao_compostos(self) -> None:
        estimativa = _estimar(fim=date(2029, 5, 31))
        self.assertAlmostEqual(_linha(estimativa, 2027, 6)["acrescimo"], 500.0)
        self.assertAlmostEqual(_linha(estimativa, 2028, 6)["acrescimo"], 1_025.0)  # 10.000 x (1,05² − 1)
        self.assertAlmostEqual(_soma(estimativa), 18_300.0)  # 12 x 500 + 12 x 1.025
        self.assertEqual(int(_linha(estimativa, 2028, 6)["ciclo"]), 2)

    def test_reajuste_assinado_vira_base_do_contratado_e_desloca_a_data_base(self) -> None:
        assinado = Aditivo(numero="1º TA", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2027, 1, 1), valor_mensal=10_500.0)
        estimativa = _estimar(aditivos=[assinado])
        self.assertAlmostEqual(_linha(estimativa, 2027, 12)["acrescimo"], 0.0)
        self.assertAlmostEqual(_linha(estimativa, 2028, 1)["base_valor"], 10_500.0)
        self.assertAlmostEqual(_linha(estimativa, 2028, 1)["acrescimo"], 525.0)  # 10.500 x 5%
        self.assertAlmostEqual(_soma(estimativa), 2_625.0)  # jan..mai/2028


class BaseLiquidadoTests(unittest.TestCase):
    def test_competencia_apurada_usa_o_liquidado_e_sem_lancamento_fica_vazia(self) -> None:
        estimativa = _estimar(liquidado={(2027, 6): 8_000.0, (2027, 7): 9_000.0}, ultimo_mes_coberto=(2027, 8))
        junho, julho, agosto, setembro = (_linha(estimativa, 2027, m) for m in (6, 7, 8, 9))
        self.assertEqual(junho["base_origem"], "liquidado")
        self.assertAlmostEqual(junho["acrescimo"], 400.0)
        self.assertAlmostEqual(julho["acrescimo"], 450.0)
        self.assertEqual(agosto["base_origem"], "sem_liquidado")
        self.assertTrue(agosto["base_valor"] != agosto["base_valor"])  # NaN: ausência ≠ zero
        self.assertTrue(agosto["acrescimo"] != agosto["acrescimo"])
        self.assertEqual(setembro["base_origem"], "contratado")  # além da cobertura: teto
        self.assertAlmostEqual(setembro["acrescimo"], 500.0)

    def test_lancamento_em_mes_futuro_vale_como_liquidado(self) -> None:
        estimativa = _estimar(liquidado={(2027, 9): 7_000.0}, ultimo_mes_coberto=(2026, 9))
        setembro = _linha(estimativa, 2027, 9)
        self.assertEqual(setembro["base_origem"], "liquidado")
        self.assertAlmostEqual(setembro["acrescimo"], 350.0)
        self.assertEqual(_linha(estimativa, 2027, 10)["base_origem"], "contratado")

    def test_liquidado_zero_e_negativo_sao_preservados(self) -> None:
        estimativa = _estimar(liquidado={(2027, 6): 0.0, (2027, 7): -1_000.0}, ultimo_mes_coberto=(2027, 7))
        self.assertAlmostEqual(_linha(estimativa, 2027, 6)["acrescimo"], 0.0)
        self.assertEqual(_linha(estimativa, 2027, 6)["base_origem"], "liquidado")
        self.assertAlmostEqual(_linha(estimativa, 2027, 7)["acrescimo"], -50.0)
        self.assertTrue(bool(_linha(estimativa, 2027, 7)["estorno_liquido"]))

    def test_sem_base_de_liquidacao_tudo_e_teto_contratado(self) -> None:
        estimativa = _estimar(liquidado=None, ultimo_mes_coberto=None)
        self.assertTrue((estimativa.matriz["base_origem"] == "contratado").all())


class PercentualTests(unittest.TestCase):
    def test_sem_indice_e_sem_manual_os_acrescimos_sao_nulos_nunca_zero(self) -> None:
        estimativa = _estimar(params=ParametrosReajuste(indice="IPCA", percentual_manual=None, data_base_manual=None))
        self.assertEqual(estimativa.situacao, "sem_indice")
        linha = _linha(estimativa, 2027, 6)
        self.assertEqual(linha["percentual_origem"], "sem_indice")
        self.assertTrue(linha["acrescimo"] != linha["acrescimo"])
        self.assertAlmostEqual(_linha(estimativa, 2027, 5)["acrescimo"], 0.0)  # antes da data-base não incide

    def test_percentual_oficial_do_acumulado_de_12_meses(self) -> None:
        variacoes = {(2026 + (5 + i) // 12, (5 + i) % 12 + 1): 1.0 for i in range(12)}  # jun/2026 .. mai/2027
        estimativa = _estimar(
            params=ParametrosReajuste(indice="IPCA", percentual_manual=None, data_base_manual=None), variacoes=variacoes
        )
        linha = _linha(estimativa, 2027, 6)
        self.assertEqual(linha["percentual_origem"], "oficial")
        self.assertAlmostEqual(linha["percentual"], 12.682503013196977, places=6)
        self.assertAlmostEqual(linha["acrescimo"], 1_268.2503013, places=4)

    def test_manual_sobrescreve_o_oficial(self) -> None:
        variacoes = {(2026 + (5 + i) // 12, (5 + i) % 12 + 1): 1.0 for i in range(12)}
        params = ParametrosReajuste(indice="IPCA", percentual_manual=5.0, data_base_manual=None)
        self.assertAlmostEqual(_linha(_estimar(params=params, variacoes=variacoes), 2027, 6)["acrescimo"], 500.0)

    def test_percentual_manual_zero_e_valido_e_diferente_de_ausente(self) -> None:
        params = ParametrosReajuste(indice=None, percentual_manual=0.0, data_base_manual=None)
        estimativa = _estimar(params=params)
        self.assertEqual(estimativa.situacao, "estimado")
        self.assertAlmostEqual(_linha(estimativa, 2027, 6)["acrescimo"], 0.0)


class SemDadosTests(unittest.TestCase):
    def test_sem_inicio_nem_data_manual_acrescimos_desconhecidos(self) -> None:
        estimativa = _estimar(inicio=None)
        self.assertEqual(estimativa.situacao, "sem_data_base")
        self.assertTrue(estimativa.matriz["acrescimo"].isna().all())

    def test_sem_vigencia_fim_nao_gera_matriz(self) -> None:
        estimativa = _estimar(fim=None)
        self.assertEqual(estimativa.situacao, "sem_vigencia_fim")
        self.assertTrue(estimativa.matriz.empty)


class PromocaoTests(unittest.TestCase):
    def test_aditivo_previsto_do_proximo_ciclo_e_valido_e_nao_altera_a_estimativa(self) -> None:
        estimativa = _estimar()
        aditivo = aditivo_previsto_do_ciclo(estimativa, [], 10_000.0)
        self.assertIsNotNone(aditivo)
        self.assertEqual((aditivo.tipo, aditivo.situacao, aditivo.data_inicio), ("REAJUSTE", "PREVISTO", date(2027, 6, 1)))
        self.assertAlmostEqual(aditivo.valor_mensal, 10_500.0)
        self.assertEqual(validar_aditivos([aditivo]), [])
        depois = _estimar(aditivos=[aditivo])
        self.assertAlmostEqual(_soma(depois), _soma(estimativa))  # o previsto é a própria estimativa: sem dupla contagem
        self.assertIsNone(aditivo_previsto_do_ciclo(depois, [aditivo], 10_000.0))

    def test_sem_percentual_conhecido_nao_ha_o_que_promover(self) -> None:
        estimativa = _estimar(params=ParametrosReajuste(indice="IPCA", percentual_manual=None, data_base_manual=None))
        self.assertIsNone(aditivo_previsto_do_ciclo(estimativa, [], 10_000.0))


class LiquidadoDoContratoTests(unittest.TestCase):
    def _base(self) -> pd.DataFrame:
        return pd.DataFrame({
            "ne_curta": ["2026NE000001", "2026NE000001", "2027NE000002", "2026NE000009"],
            "ano_mes": [202606, 202607, 202706, 202606],
            "valor": [8_000.0, -500.0, 9_000.0, 1_234.0],
        })

    def test_soma_as_nes_do_contrato_em_todos_os_exercicios_com_estorno(self) -> None:
        resultado = liquidado_do_contrato({"2026NE000001", "2027NE000002"}, self._base())
        self.assertEqual(resultado, {(2026, 6): 8_000.0, (2026, 7): -500.0, (2027, 6): 9_000.0})

    def test_sem_base_ou_sem_nes_devolve_vazio_e_ultimo_mes_coberto(self) -> None:
        self.assertEqual(liquidado_do_contrato({"2026NE000001"}, None), {})
        self.assertEqual(liquidado_do_contrato(set(), self._base()), {})
        # a base traz competências futuras esparsas: cobertura = mês anterior a "hoje", nunca o maior mês da base
        self.assertEqual(ultimo_mes_coberto(self._base(), hoje=date(2026, 10, 11)), (2026, 9))
        self.assertEqual(ultimo_mes_coberto(self._base(), hoje=date(2030, 1, 5)), (2027, 6))  # não passa do maior mês
        self.assertEqual(ultimo_mes_coberto(self._base(), hoje=date(2027, 1, 5)), (2026, 12))  # virada de ano
        self.assertIsNone(ultimo_mes_coberto(None))

    def test_ne_em_dois_contratos_e_inconsistencia_sinalizada(self) -> None:
        registros = [
            {"ne_curta": "2026NE000001", "contrato_numero": "01/2026"},
            {"ne_curta": "2026NE000001", "contrato_numero": "02/2026"},
            {"ne_curta": "2026NE000002", "contrato_numero": "02/2026"},
            {"ne_curta": None, "contrato_numero": "03/2026"},
        ]
        self.assertEqual(nes_em_conflito(registros), {"2026NE000001": {"01/2026", "02/2026"}})


if __name__ == "__main__":
    unittest.main()
