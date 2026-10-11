"""Testes de `src/estimativa_reajuste.py` — estimativa de reajuste por competência (regras v2, 11/10/2026).

Specs: `docs/superpowers/specs/2026-10-11-estimativa-reajuste-contratos-design.md` e
`docs/superpowers/specs/2026-10-11-estimativa-reajuste-regras-v2.md`. Valores calculados à mão.
Contrato-base: R$ 10.000/mês; reajuste manual de 5%.
"""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.contratos_aditivos import Aditivo, validar_aditivos
from src.estimativa_reajuste import (
    Apostilamento,
    ParametrosReajuste,
    Retroativo,
    aditivo_previsto_do_ciclo,
    ciclos_do_contrato,
    estimar_contrato,
    liquidado_do_contrato,
    nes_do_gov,
    nes_em_conflito,
    termos_do_gov,
    ultimo_mes_coberto,
)

CINCO = ParametrosReajuste(indice=None, percentual_manual=5.0, data_base_manual=None)
IPCA = ParametrosReajuste(indice="IPCA", percentual_manual=None, data_base_manual=None)
EXERCICIO = date(2026, 1, 1)


def _estimar(inicio=date(2026, 6, 1), fim=date(2028, 5, 31), params=CINCO, aditivos=(), **extra):
    return estimar_contrato(
        contrato="01/2026", despesa_mensal=10_000.0, aditivos=list(aditivos),
        vigencia_inicio=inicio, vigencia_fim=fim, parametros=params, exercicio_inicial=2026, **extra,
    )


def _linha(estimativa, ano: int, mes: int):
    tabela = estimativa.matriz
    return tabela[(tabela["ano"] == ano) & (tabela["mes"] == mes)].iloc[0]


def _soma(estimativa, coluna: str = "acrescimo", **filtro) -> float:
    tabela = estimativa.matriz
    for campo, valor in filtro.items():
        tabela = tabela[tabela[campo] == valor]
    return float(tabela[coluna].dropna().sum())


def _ciclos(**kwargs):
    base = dict(
        inicio_contrato=date(2026, 6, 1), fim_efetivo=date(2028, 5, 31), aditivos=[], reajustes_gov=[],
        retroativos=[], apostilamentos=[], data_base_manual=None, inicio_exercicio=EXERCICIO,
    )
    base.update(kwargs)
    return ciclos_do_contrato(**base)


def _registrado(dia: date, valor: float = 10_500.0) -> Aditivo:
    return Aditivo(numero="TA", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=dia, valor_mensal=valor)


class CiclosTests(unittest.TestCase):
    def test_sem_reajuste_algum_projeta_do_aniversario_do_inicio(self) -> None:
        self.assertEqual(_ciclos(), ([(date(2027, 6, 1), "projetado", date(2026, 6, 1))], "ok"))

    def test_projetados_se_repetem_e_param_no_fim_da_vigencia(self) -> None:
        ciclos, _ = _ciclos(fim_efetivo=date(2029, 5, 31))
        self.assertEqual([c[0] for c in ciclos], [date(2027, 6, 1), date(2028, 6, 1)])
        self.assertEqual(ciclos[1][2], date(2027, 6, 1))  # janela do índice: os 12 meses anteriores

    def test_contrato_curto_sem_ciclo_na_vigencia(self) -> None:
        self.assertEqual(_ciclos(fim_efetivo=date(2027, 5, 31)), ([], "sem_reajuste_na_vigencia"))

    def test_sem_inicio_nem_reajuste_nem_data_manual(self) -> None:
        self.assertEqual(_ciclos(inicio_contrato=None), ([], "sem_data_base"))

    def test_reajuste_do_gov_no_exercicio_e_formalizado_e_ancora_a_projecao(self) -> None:
        ciclos, motivo = _ciclos(
            inicio_contrato=date(2025, 5, 7), fim_efetivo=date(2027, 12, 31), reajustes_gov=[date(2026, 5, 8)]
        )
        self.assertEqual(motivo, "ok")
        self.assertEqual(ciclos, [
            (date(2026, 5, 8), "formalizado", date(2025, 5, 8)),
            (date(2027, 5, 8), "projetado", date(2026, 5, 8)),
        ])

    def test_reajuste_do_gov_com_aditivo_registrado_e_registrado_e_so_ancora(self) -> None:
        ciclos, motivo = _ciclos(
            inicio_contrato=date(2025, 5, 7), fim_efetivo=date(2027, 5, 7), reajustes_gov=[date(2026, 5, 10)],
            aditivos=[_registrado(date(2026, 5, 8))],  # a 2 dias: o mesmo ciclo
        )
        self.assertEqual((ciclos, motivo), ([], "sem_reajuste_na_vigencia"))

    def test_aditivo_assinado_sem_valor_conta_como_formalizado(self) -> None:
        sem_valor = Aditivo(numero="TA", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2026, 5, 8))
        ciclos, _ = _ciclos(inicio_contrato=date(2025, 5, 7), fim_efetivo=date(2027, 5, 7), aditivos=[sem_valor])
        self.assertEqual(ciclos, [(date(2026, 5, 8), "formalizado", date(2025, 5, 8))])

    def test_formalizado_antes_do_exercicio_sem_retroativo_esta_incorporado(self) -> None:
        ciclos, _ = _ciclos(
            inicio_contrato=date(2024, 5, 7), fim_efetivo=date(2027, 5, 7), reajustes_gov=[date(2025, 5, 8)]
        )
        self.assertEqual(ciclos, [(date(2026, 5, 8), "projetado", date(2025, 5, 8))])

    def test_formalizado_antes_do_exercicio_coberto_por_retroativo_do_exercicio_e_pendente(self) -> None:
        retro = Retroativo(assinatura=date(2026, 2, 3), inicio=date(2024, 10, 1), fim=date(2026, 2, 28), valor=769_359.2)
        ciclos, _ = _ciclos(
            inicio_contrato=date(2024, 10, 16), fim_efetivo=date(2026, 6, 16),
            reajustes_gov=[date(2025, 10, 17), date(2026, 2, 17)], retroativos=[retro],
        )
        # 17/02/2026 está a 4 meses do reajuste anterior: pela anualidade, não é um ciclo novo
        self.assertEqual(ciclos, [(date(2025, 10, 17), "formalizado", date(2024, 10, 17))])

    def test_anualidade_termo_com_reajuste_a_menos_de_um_ano_do_inicio_nao_e_ciclo(self) -> None:
        # emergencial iniciado em 17/06/2026 com termo "acréscimo/supressão; reajuste" em 30/09/2026
        ciclos, motivo = _ciclos(
            inicio_contrato=date(2026, 6, 17), fim_efetivo=date(2026, 12, 17), reajustes_gov=[date(2026, 9, 30)]
        )
        self.assertEqual((ciclos, motivo), ([], "sem_reajuste_na_vigencia"))

    def test_ultimo_formalizado_antes_do_exercicio_implantado_por_apostilamento_no_exercicio_e_pendente(self) -> None:
        ciclos, _ = _ciclos(
            inicio_contrato=date(2023, 5, 7), fim_efetivo=date(2027, 5, 7),
            reajustes_gov=[date(2024, 5, 8), date(2025, 5, 8)],
            apostilamentos=[Apostilamento(assinatura=date(2026, 3, 1), novo_valor=date(2026, 3, 1))],
        )
        self.assertEqual(ciclos, [  # o de 2024 é anterior ao último: incorporado
            (date(2025, 5, 8), "formalizado", date(2024, 5, 8)),
            (date(2026, 5, 8), "projetado", date(2025, 5, 8)),
        ])

    def test_retroativo_assinado_antes_do_exercicio_nao_reabre_o_ciclo(self) -> None:
        retro = Retroativo(assinatura=date(2025, 12, 1), inicio=date(2025, 1, 1), fim=date(2025, 12, 31), valor=1.0)
        ciclos, _ = _ciclos(
            inicio_contrato=date(2024, 5, 7), fim_efetivo=date(2026, 12, 31), reajustes_gov=[date(2025, 5, 8)],
            retroativos=[retro],
        )
        self.assertEqual(ciclos, [(date(2026, 5, 8), "projetado", date(2025, 5, 8))])

    def test_apostilamento_sem_termo_e_reajuste_formalizado_por_apostila(self) -> None:
        # modelo do 21/2017: TA de reajuste em 08/07/2022; apostilamento assinado em 20/01/2026 com novo valor desde
        # 20/01/2025 (reajuste por apostila, sem termo aditivo)
        ciclos, _ = _ciclos(
            inicio_contrato=date(2017, 5, 29), fim_efetivo=date(2027, 5, 28), reajustes_gov=[date(2017, 5, 29), date(2022, 7, 8)],
            apostilamentos=[Apostilamento(assinatura=date(2026, 1, 20), novo_valor=date(2025, 1, 20))],
        )
        self.assertEqual(ciclos, [  # o de 2022 não é implantado por esse apostilamento (2,5 anos depois): incorporado
            (date(2025, 1, 20), "formalizado", date(2024, 1, 20)),
            (date(2026, 1, 20), "projetado", date(2025, 1, 20)),
            (date(2027, 1, 20), "projetado", date(2026, 1, 20)),
        ])

    def test_apostilamento_perto_de_termo_de_reajuste_e_implantacao_nao_ciclo_proprio(self) -> None:
        # modelo do 10/2025: apostilamentos em 31/03 e 23/04/2026, termo de reajuste em 08/05/2026
        ciclos, _ = _ciclos(
            inicio_contrato=date(2025, 5, 7), fim_efetivo=date(2027, 5, 7), reajustes_gov=[date(2026, 5, 8)],
            apostilamentos=[Apostilamento(date(2026, 3, 31), date(2026, 3, 31)), Apostilamento(date(2026, 4, 26), date(2026, 4, 23))],
        )
        self.assertEqual(ciclos, [(date(2026, 5, 8), "formalizado", date(2025, 5, 8))])

    def test_apostilamento_assinado_antes_da_data_base_nao_a_implanta(self) -> None:
        from src.estimativa_reajuste import implantacao_do_ciclo

        anterior = Apostilamento(date(2026, 3, 31), date(2026, 3, 31))
        self.assertIsNone(implantacao_do_ciclo(date(2026, 5, 8), [anterior]))
        retro = Apostilamento(date(2026, 7, 20), date(2026, 7, 21))
        self.assertEqual(implantacao_do_ciclo(date(2025, 9, 2), [retro]), date(2026, 7, 21))
        por_apostila = Apostilamento(date(2026, 1, 20), date(2025, 1, 20))
        self.assertEqual(implantacao_do_ciclo(date(2025, 1, 20), [por_apostila]), date(2026, 1, 20))

    def test_data_base_manual_substitui_a_projecao(self) -> None:
        ciclos, _ = _ciclos(data_base_manual=date(2027, 6, 16))
        self.assertEqual(ciclos, [(date(2027, 6, 16), "projetado", date(2026, 6, 16))])

    def test_previsto_nao_e_reajuste_formalizado(self) -> None:
        previsto = Aditivo(numero="x", tipo="REAJUSTE", situacao="PREVISTO", data_inicio=date(2026, 9, 1), valor_mensal=11_000.0)
        ciclos, _ = _ciclos(aditivos=[previsto])
        self.assertEqual(ciclos, [(date(2027, 6, 1), "projetado", date(2026, 6, 1))])


class TermosDoGovTests(unittest.TestCase):
    def _termos(self) -> pd.DataFrame:
        return pd.DataFrame({
            "contrato_id": ["1", "1", "1", "1", "1", "2"],
            "tipo": ["Contrato", "Termo Aditivo", "Termo Aditivo", "Termo de Apostilamento", "Termo de Apostilamento", "Termo Aditivo"],
            "qualificacao_termo": [None, "VIGÊNCIA; REAJUSTE", "VIGÊNCIA", None, None, "ACRESCIMO / SUPRESSAO; REAJUSTE"],
            "vigencia_inicio": [date(2024, 10, 16), date(2025, 10, 17), date(2026, 2, 17), date(2024, 10, 16), None, date(2026, 3, 1)],
            "data_inicio_novo_valor": [None, date(2025, 10, 17), None, date(2026, 2, 3), date(2026, 4, 1), None],
            "data_assinatura": [date(2024, 10, 1), date(2025, 10, 15), date(2026, 2, 13), date(2026, 2, 3), date(2026, 4, 1), date(2026, 2, 20)],
            "retroativo": [False, False, False, True, False, False],
            "retroativo_valor": [0.0, 0.0, 0.0, 769_359.2, 0.0, 0.0],
            "retroativo_periodo": [None, None, None, "10/2024–02/2026", None, None],
        })

    def test_reajustes_vem_de_termo_aditivo_com_reajuste(self) -> None:
        termos = termos_do_gov(self._termos())
        self.assertEqual(termos["1"]["reajustes"], [date(2025, 10, 17)])
        self.assertEqual(termos["2"]["reajustes"], [date(2026, 3, 1)])  # sem data do novo valor: início do termo

    def test_apostilamento_retroativo_vira_periodo_de_meses_inteiros(self) -> None:
        self.assertEqual(
            termos_do_gov(self._termos())["1"]["retroativos"],
            [Retroativo(assinatura=date(2026, 2, 3), inicio=date(2024, 10, 1), fim=date(2026, 2, 28), valor=769_359.2)],
        )
        self.assertEqual(termos_do_gov(self._termos())["2"]["retroativos"], [])

    def test_apostilamentos_trazem_a_data_do_novo_valor(self) -> None:
        self.assertEqual(termos_do_gov(self._termos())["1"]["apostilamentos"], [
            Apostilamento(assinatura=date(2026, 2, 3), novo_valor=date(2026, 2, 3)),
            Apostilamento(assinatura=date(2026, 4, 1), novo_valor=date(2026, 4, 1)),
        ])


class NesDoGovTests(unittest.TestCase):
    def test_so_entram_as_nes_do_contrato_com_plano_interno_do_cadastro(self) -> None:
        empenhos = pd.DataFrame({
            "contrato_id": ["326557", "326557", "326557", "999"],
            "ne": ["2024NE000630", "2024NE000631", "2025NE000059", "2025NE000001"],
            "plano_interno": [
                "M20RKG01SCN - GESTAO DA UNIDADE", "L20RLP01SCN - CONSULTORIA EM TI", "M20RKG01SCN - GESTAO", "M20RKG01SCN - X",
            ],
        })
        self.assertEqual(nes_do_gov(empenhos, "326557", {"M20RKG01SCN"}), {"2024NE000630", "2025NE000059"})
        self.assertEqual(nes_do_gov(empenhos, "326557", set()), set())  # sem PI no cadastro: nada é presumido
        self.assertEqual(nes_do_gov(None, "326557", {"M20RKG01SCN"}), set())


class MatrizPorCompetenciaTests(unittest.TestCase):
    def test_contrato_de_dois_anos_so_acrescenta_a_partir_da_data_base(self) -> None:
        estimativa = _estimar()
        self.assertEqual(estimativa.situacao, "estimado")
        self.assertEqual(len(estimativa.matriz), 24)  # jun/2026 .. mai/2028
        self.assertAlmostEqual(_linha(estimativa, 2027, 5)["acrescimo"], 0.0)
        self.assertAlmostEqual(_linha(estimativa, 2027, 6)["acrescimo"], 500.0)
        self.assertAlmostEqual(_linha(estimativa, 2027, 6)["acrescimo_projetado"], 500.0)
        self.assertAlmostEqual(_linha(estimativa, 2027, 6)["acrescimo_formalizado"], 0.0)
        self.assertAlmostEqual(_soma(estimativa), 6_000.0)
        self.assertEqual(_linha(estimativa, 2027, 6)["estado_ciclo"], "projetado")

    def test_contrato_de_doze_meses_sem_prorrogacao_nao_tem_reajuste(self) -> None:
        estimativa = _estimar(fim=date(2027, 5, 31))
        self.assertEqual(estimativa.situacao, "sem_reajuste_na_vigencia")
        self.assertAlmostEqual(_soma(estimativa), 0.0)

    def test_prorrogacao_prevista_cria_o_ciclo_e_marca_as_competencias(self) -> None:
        prorrogacao = Aditivo(
            numero="1º TA", tipo="PRORROGACAO", situacao="PREVISTO", data_inicio=date(2027, 6, 1), vigencia_fim=date(2028, 5, 31)
        )
        estimativa = _estimar(fim=date(2027, 5, 31), aditivos=[prorrogacao])
        self.assertAlmostEqual(_soma(estimativa), 6_000.0)
        self.assertFalse(bool(_linha(estimativa, 2027, 5)["prorrogacao_prevista"]))
        self.assertTrue(bool(_linha(estimativa, 2027, 6)["prorrogacao_prevista"]))

    def test_data_base_no_meio_do_mes_e_proporcional_aos_dias(self) -> None:
        estimativa = _estimar(params=ParametrosReajuste(percentual_manual=5.0, data_base_manual=date(2027, 6, 16)))
        self.assertAlmostEqual(_linha(estimativa, 2027, 6)["acrescimo"], 250.0)  # 16..30 = 15/30
        self.assertAlmostEqual(_soma(estimativa), 5_750.0)

    def test_ciclos_sao_compostos(self) -> None:
        estimativa = _estimar(fim=date(2029, 5, 31))
        self.assertAlmostEqual(_linha(estimativa, 2028, 6)["acrescimo"], 1_025.0)  # 10.000 × (1,05² − 1)
        self.assertAlmostEqual(_soma(estimativa), 18_300.0)

    def test_reajuste_registrado_e_base_do_contratado_e_desloca_a_data_base(self) -> None:
        estimativa = _estimar(aditivos=[_registrado(date(2027, 1, 1))])
        self.assertAlmostEqual(_linha(estimativa, 2028, 1)["base_valor"], 10_500.0)
        self.assertAlmostEqual(_linha(estimativa, 2028, 1)["acrescimo"], 525.0)
        self.assertAlmostEqual(_soma(estimativa), 2_625.0)  # jan..mai/2028


class FormalizadoTests(unittest.TestCase):
    def test_reajuste_formalizado_no_exercicio_continua_estimado(self) -> None:
        # contrato 07/05/2025–07/05/2027, reajuste no gov em 08/05/2026, sem valor registrado
        estimativa = _estimar(inicio=date(2025, 5, 7), fim=date(2027, 5, 7), reajustes_gov=[date(2026, 5, 8)])
        self.assertEqual(estimativa.situacao, "estimado")
        maio = _linha(estimativa, 2026, 5)
        self.assertEqual(maio["estado_ciclo"], "formalizado")
        self.assertAlmostEqual(maio["acrescimo_formalizado"], 10_000 * 0.05 * 24 / 31)  # 8..31 de maio
        self.assertAlmostEqual(_linha(estimativa, 2026, 6)["acrescimo_formalizado"], 500.0)
        self.assertAlmostEqual(_soma(estimativa, "acrescimo_formalizado"), 6_000.0)  # 24/31 + 11 meses + 7/31
        self.assertAlmostEqual(_soma(estimativa, "acrescimo_projetado"), 0.0)
        self.assertIsNone(aditivo_previsto_do_ciclo(estimativa, [], 10_000.0))  # só ciclo projetado se promove

    def _modelo_35_2024(self, **extra):
        # reajustes no gov em 17/10/2025 e 17/02/2026; apostilamento retroativo (10/2024–02/2026) em 03/02/2026,
        # com o novo valor a partir de 03/02/2026
        retro = Retroativo(assinatura=date(2026, 2, 3), inicio=date(2024, 10, 1), fim=date(2026, 2, 28), valor=769_359.2)
        return _estimar(
            inicio=date(2024, 10, 16), fim=date(2026, 6, 16), reajustes_gov=[date(2025, 10, 17), date(2026, 2, 17)],
            retroativos=[retro], apostilamentos=[Apostilamento(date(2026, 2, 3), date(2026, 2, 3))], **extra,
        ), retro

    def test_retroativo_alcanca_competencias_de_anos_anteriores_separadas(self) -> None:
        estimativa, retro = self._modelo_35_2024()
        self.assertEqual(estimativa.matriz.iloc[0]["competencia"], "10/2025")  # começa no ciclo pendente
        self.assertAlmostEqual(_linha(estimativa, 2025, 10)["acrescimo"], 10_000 * 0.05 * 15 / 31)
        self.assertTrue(bool(_linha(estimativa, 2025, 12)["exercicio_anterior"]))
        self.assertAlmostEqual(_soma(estimativa, exercicio_anterior=True), 10_000 * 0.05 * 15 / 31 + 1_000.0)
        self.assertAlmostEqual(_linha(estimativa, 2026, 1)["acrescimo"], 500.0)  # janeiro entra
        # base contratada (teto): o cadastro não tem o valor novo, então o acréscimo segue até o fim (16/06)
        self.assertAlmostEqual(_linha(estimativa, 2026, 6)["acrescimo"], 10_000 * 16 / 30 * 0.05)
        self.assertAlmostEqual(_soma(estimativa, exercicio_anterior=False), 5 * 500 + 10_000 * 16 / 30 * 0.05)
        self.assertEqual(estimativa.retroativos_exercicio, [retro])

    def test_liquidado_depois_do_apostilamento_ja_vem_reajustado(self) -> None:
        estimativa, _ = self._modelo_35_2024(
            liquidado={(2026, 1): 10_000.0, (2026, 2): 10_000.0, (2026, 3): 10_500.0}, ultimo_mes_coberto=(2026, 3)
        )
        self.assertAlmostEqual(_linha(estimativa, 2026, 1)["acrescimo"], 500.0)
        self.assertAlmostEqual(_linha(estimativa, 2026, 2)["acrescimo"], 500.0)  # implantado em 03/02: fevereiro ainda conta
        self.assertAlmostEqual(_linha(estimativa, 2026, 3)["acrescimo"], 0.0)  # liquidado de março já reajustado
        self.assertEqual(estimativa.ciclos[0].implementado_em, date(2026, 2, 3))

    def test_projetado_depois_de_formalizado_fica_separado(self) -> None:
        estimativa = _estimar(inicio=date(2025, 5, 7), fim=date(2027, 12, 31), reajustes_gov=[date(2026, 5, 8)])
        junho_2027 = _linha(estimativa, 2027, 6)
        self.assertAlmostEqual(junho_2027["acrescimo_formalizado"], 500.0)
        self.assertAlmostEqual(junho_2027["acrescimo_projetado"], 525.0)  # 10.000 × 1,05 × 5%
        self.assertAlmostEqual(junho_2027["acrescimo"], 1_025.0)


class BaseLiquidadoTests(unittest.TestCase):
    def test_competencia_apurada_usa_o_liquidado_e_sem_lancamento_fica_vazia(self) -> None:
        estimativa = _estimar(liquidado={(2027, 6): 8_000.0, (2027, 7): 9_000.0}, ultimo_mes_coberto=(2027, 8))
        self.assertEqual(_linha(estimativa, 2027, 6)["base_origem"], "liquidado")
        self.assertAlmostEqual(_linha(estimativa, 2027, 6)["acrescimo"], 400.0)
        self.assertAlmostEqual(_linha(estimativa, 2027, 7)["acrescimo"], 450.0)
        agosto = _linha(estimativa, 2027, 8)
        self.assertEqual(agosto["base_origem"], "sem_liquidado")
        self.assertTrue(pd.isna(agosto["acrescimo"]))  # ausência ≠ zero
        self.assertEqual(_linha(estimativa, 2027, 9)["base_origem"], "contratado")

    def test_lancamento_em_mes_futuro_vale_como_liquidado(self) -> None:
        estimativa = _estimar(liquidado={(2027, 9): 7_000.0}, ultimo_mes_coberto=(2026, 9))
        self.assertEqual(_linha(estimativa, 2027, 9)["base_origem"], "liquidado")
        self.assertAlmostEqual(_linha(estimativa, 2027, 9)["acrescimo"], 350.0)

    def test_liquidado_zero_e_negativo_sao_preservados(self) -> None:
        estimativa = _estimar(liquidado={(2027, 6): 0.0, (2027, 7): -1_000.0}, ultimo_mes_coberto=(2027, 7))
        self.assertAlmostEqual(_linha(estimativa, 2027, 6)["acrescimo"], 0.0)
        self.assertAlmostEqual(_linha(estimativa, 2027, 7)["acrescimo"], -50.0)
        self.assertTrue(bool(_linha(estimativa, 2027, 7)["estorno_liquido"]))

    def test_sem_base_de_liquidacao_tudo_e_teto_contratado(self) -> None:
        self.assertTrue((_estimar().matriz["base_origem"] == "contratado").all())


class PercentualTests(unittest.TestCase):
    def _variacoes(self, inicio=(2024, 1), meses=48, valor=1.0):
        ano, mes = inicio
        resultado = {}
        for _ in range(meses):
            resultado[(ano, mes)] = valor
            ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
        return resultado

    def test_sem_indice_e_sem_manual_os_acrescimos_sao_nulos_nunca_zero(self) -> None:
        estimativa = _estimar(params=IPCA)
        self.assertEqual(estimativa.situacao, "sem_indice")
        self.assertTrue(pd.isna(_linha(estimativa, 2027, 6)["acrescimo"]))
        self.assertAlmostEqual(_linha(estimativa, 2027, 5)["acrescimo"], 0.0)  # antes da data-base não incide

    def test_percentual_oficial_dos_doze_meses_desde_o_inicio(self) -> None:
        estimativa = _estimar(params=IPCA, variacoes=self._variacoes())
        linha = _linha(estimativa, 2027, 6)
        self.assertEqual(linha["percentual_origem"], "oficial")
        self.assertAlmostEqual(linha["percentual"], (1.01**12 - 1) * 100, places=6)

    def test_cada_ciclo_usa_os_doze_meses_anteriores_mesmo_sem_reajuste_formal_antes(self) -> None:
        # contrato antigo sem reajuste no gov: o ciclo de 2026 não acumula os anos anteriores (anualidade)
        estimativa = _estimar(inicio=date(2021, 12, 21), fim=date(2027, 12, 21), params=IPCA, variacoes=self._variacoes())
        self.assertEqual(estimativa.ciclos[0].data_base, date(2026, 12, 21))
        self.assertAlmostEqual(estimativa.ciclos[0].percentual, (1.01**12 - 1) * 100, places=6)

    def test_manual_sobrescreve_o_oficial_e_zero_vale(self) -> None:
        manual = ParametrosReajuste(indice="IPCA", percentual_manual=5.0)
        self.assertAlmostEqual(_linha(_estimar(params=manual, variacoes=self._variacoes()), 2027, 6)["acrescimo"], 500.0)
        zero = _estimar(params=ParametrosReajuste(percentual_manual=0.0))
        self.assertEqual(zero.situacao, "estimado")
        self.assertAlmostEqual(_linha(zero, 2027, 6)["acrescimo"], 0.0)


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
    def test_aditivo_previsto_do_proximo_ciclo_projetado_sem_dupla_contagem(self) -> None:
        estimativa = _estimar()
        aditivo = aditivo_previsto_do_ciclo(estimativa, [], 10_000.0)
        self.assertEqual((aditivo.tipo, aditivo.situacao, aditivo.data_inicio), ("REAJUSTE", "PREVISTO", date(2027, 6, 1)))
        self.assertAlmostEqual(aditivo.valor_mensal, 10_500.0)
        self.assertEqual(validar_aditivos([aditivo]), [])
        depois = _estimar(aditivos=[aditivo])
        self.assertAlmostEqual(_soma(depois), _soma(estimativa))
        self.assertIsNone(aditivo_previsto_do_ciclo(depois, [aditivo], 10_000.0))

    def test_sem_percentual_conhecido_nao_ha_o_que_promover(self) -> None:
        self.assertIsNone(aditivo_previsto_do_ciclo(_estimar(params=IPCA), [], 10_000.0))


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
        self.assertEqual(ultimo_mes_coberto(self._base(), hoje=date(2026, 10, 11)), (2026, 9))
        self.assertEqual(ultimo_mes_coberto(self._base(), hoje=date(2030, 1, 5)), (2027, 6))
        self.assertEqual(ultimo_mes_coberto(self._base(), hoje=date(2027, 1, 5)), (2026, 12))
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
