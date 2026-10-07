"""Testes de `src/contratos_aditivos.py` — aditivos de Contratos Contínuos (06/10/2026).

Spec: `docs/superpowers/specs/2026-10-06-aditivos-contratos-design.md`. Valores esperados calculados
à mão no exemplo do spec: contrato de R$ 10.000/mês, 1º TA (01/07/2025, R$ 10.400) e 2º TA
(01/07/2026, R$ 10.800) → em 2026, 6 × 10.400 + 6 × 10.800 = R$ 127.200.
"""

from __future__ import annotations

import math
import unittest
from datetime import date

import pandas as pd

from src.contratos_aditivos import (
    SITUACOES,
    TIPOS,
    Aditivo,
    aditivo_para_registro,
    aditivos_do_registro,
    custo_mensal,
    meses_com_previsto,
    rateio_vigente_em,
    retroativo_por_aditivo,
    serie_valor_mensal,
    validar_aditivos,
    valor_vigente_em,
    vigencia_efetiva,
)


def _ta(numero="1º TA", inicio=date(2025, 7, 1), valor=10_400.0, vigencia=None, itens=None,
        tipo="REAJUSTE", situacao="ASSINADO", assinatura=None) -> Aditivo:
    return Aditivo(
        numero=numero, tipo=tipo, situacao=situacao, data_inicio=inicio, data_assinatura=assinatura,
        valor_mensal=valor, vigencia_fim=vigencia, itens=itens,
    )


class TestModelo(unittest.TestCase):
    def test_constantes(self):
        self.assertEqual(SITUACOES, ("PREVISTO", "ASSINADO"))
        self.assertEqual(
            TIPOS, ("REAJUSTE", "REPACTUACAO", "PRORROGACAO", "ACRESCIMO_SUPRESSAO", "OUTRO")
        )

    def test_ida_e_volta_preserva_tudo_e_o_numero_continua_texto(self):
        original = _ta(
            numero="002", inicio=date(2026, 7, 1), valor=10_800.0, vigencia=date(2027, 6, 30),
            itens=[{"numero": 1, "percentual": 60.0}, {"numero": 2, "percentual": 40.0}],
            assinatura=date(2026, 9, 15), situacao="PREVISTO",
        )
        registro = aditivo_para_registro(original)
        self.assertEqual(registro["data_inicio"], "2026-07-01")
        self.assertEqual(registro["data_assinatura"], "2026-09-15")
        self.assertEqual(registro["vigencia_fim"], "2027-06-30")
        self.assertEqual(registro["numero"], "002")
        self.assertEqual(aditivos_do_registro([registro]), [original])
        self.assertTrue(original.previsto)
        self.assertFalse(_ta().previsto)

    def test_registro_sem_aditivos_vira_lista_vazia(self):
        self.assertEqual(aditivos_do_registro(None), [])
        self.assertEqual(aditivos_do_registro(float("nan")), [])
        self.assertEqual(aditivos_do_registro([]), [])

    def test_lidos_em_ordem_de_data_de_inicio(self):
        tardio = aditivo_para_registro(_ta("2º TA", date(2026, 7, 1), 10_800.0))
        cedo = aditivo_para_registro(_ta("1º TA", date(2025, 7, 1), 10_400.0))
        self.assertEqual([a.numero for a in aditivos_do_registro([tardio, cedo])], ["1º TA", "2º TA"])

    def test_aceita_datas_como_timestamp_e_nulos_como_nulo(self):
        registro = aditivo_para_registro(_ta())
        registro["data_inicio"] = pd.Timestamp("2025-07-01")
        registro["valor_mensal"] = float("nan")
        lido = aditivos_do_registro([registro])[0]
        self.assertEqual(lido.data_inicio, date(2025, 7, 1))
        self.assertIsNone(lido.valor_mensal)  # nulo ≠ zero


class TestValidacao(unittest.TestCase):
    def test_aditivo_valido_nao_tem_erro(self):
        self.assertEqual(validar_aditivos([_ta()]), [])

    def test_sem_numero(self):
        erros = validar_aditivos([_ta(numero="  ")])
        self.assertTrue(any(e.startswith("Aditivo sem nº") for e in erros))

    def test_sem_data_de_inicio(self):
        erros = validar_aditivos([_ta(inicio=None)])
        self.assertTrue(any("data de início" in e for e in erros))

    def test_tipo_ou_situacao_invalidos(self):
        self.assertTrue(validar_aditivos([_ta(tipo="XYZ")]))
        self.assertTrue(validar_aditivos([_ta(situacao="TALVEZ")]))

    def test_sem_nenhuma_alteracao(self):
        self.assertEqual(
            validar_aditivos([_ta("2º TA", valor=None)]),
            ["2º TA: informe ao menos novo valor, nova vigência ou novo rateio."],
        )

    def test_so_prorrogacao_e_valido(self):
        self.assertEqual(validar_aditivos([_ta(valor=None, vigencia=date(2027, 6, 30), tipo="PRORROGACAO")]), [])

    def test_rateio_precisa_somar_100(self):
        erros = validar_aditivos([_ta(valor=None, itens=[{"numero": 1, "percentual": 60.0}, {"numero": 2, "percentual": 30.0}])])
        self.assertTrue(any("100%" in e and e.startswith("1º TA") for e in erros))
        ok = [{"numero": 1, "percentual": 60.0}, {"numero": 2, "percentual": 40.0}]
        self.assertEqual(validar_aditivos([_ta(valor=None, itens=ok)]), [])

    def test_mesma_data_de_inicio_e_ambigua(self):
        erros = validar_aditivos([_ta("1º TA", date(2026, 7, 1)), _ta("2º TA", date(2026, 7, 1), 11_000.0)])
        self.assertEqual(len(erros), 1)
        self.assertIn("1º TA", erros[0])
        self.assertIn("2º TA", erros[0])

    def test_valor_negativo_e_aceito(self):
        self.assertEqual(validar_aditivos([_ta(valor=-50.0)]), [])


class TestVigentes(unittest.TestCase):
    def setUp(self):
        self.ta1 = _ta("1º TA", date(2025, 7, 1), 10_400.0, vigencia=date(2026, 6, 30))
        self.ta2 = _ta("2º TA", date(2026, 7, 1), 10_800.0, vigencia=date(2027, 6, 30))

    def test_valor_vigente_antes_e_depois_de_cada_aditivo(self):
        aditivos = [self.ta1, self.ta2]
        self.assertEqual(valor_vigente_em(10_000.0, aditivos, date(2025, 6, 30)), (10_000.0, None))
        self.assertEqual(valor_vigente_em(10_000.0, aditivos, date(2026, 6, 30)), (10_400.0, self.ta1))
        self.assertEqual(valor_vigente_em(10_000.0, aditivos, date(2026, 7, 1)), (10_800.0, self.ta2))
        self.assertEqual(valor_vigente_em(10_000.0, aditivos, pd.Timestamp("2027-01-01")), (10_800.0, self.ta2))

    def test_aditivo_sem_valor_nao_muda_o_valor(self):
        prorrogacao = _ta("3º TA", date(2027, 7, 1), valor=None, vigencia=date(2028, 6, 30), tipo="PRORROGACAO")
        self.assertEqual(valor_vigente_em(10_000.0, [self.ta1, prorrogacao], date(2027, 8, 1)), (10_400.0, self.ta1))

    def test_valor_original_nulo_continua_nulo_ate_o_primeiro_aditivo(self):
        self.assertEqual(valor_vigente_em(None, [self.ta2], date(2026, 1, 1)), (None, None))
        self.assertEqual(valor_vigente_em(float("nan"), [], date(2026, 1, 1)), (None, None))
        self.assertEqual(valor_vigente_em(None, [self.ta2], date(2026, 7, 1)), (10_800.0, self.ta2))

    def test_vigencia_efetiva_e_a_do_ultimo_aditivo_que_a_informa(self):
        self.assertEqual(vigencia_efetiva("2025-06-30", [self.ta1, self.ta2]), (pd.Timestamp("2027-06-30"), self.ta2))
        sem_vigencia = _ta("3º TA", date(2027, 1, 1), 11_000.0)
        self.assertEqual(vigencia_efetiva("2025-06-30", [self.ta1, sem_vigencia]), (pd.Timestamp("2026-06-30"), self.ta1))
        self.assertEqual(vigencia_efetiva("2025-06-30", [sem_vigencia]), (pd.Timestamp("2025-06-30"), None))
        efetiva, aditivo = vigencia_efetiva(None, [])
        self.assertTrue(pd.isna(efetiva))
        self.assertIsNone(aditivo)

    def test_rateio_vigente_muda_a_partir_do_aditivo(self):
        base = [{"numero": 1, "percentual": 100.0}]
        novo = [{"numero": 1, "percentual": 60.0}, {"numero": 2, "percentual": 40.0}]
        ta = _ta("2º TA", date(2026, 7, 1), valor=None, itens=novo, vigencia=date(2027, 6, 30))
        self.assertEqual(rateio_vigente_em(base, [ta], date(2026, 6, 30)), base)
        self.assertEqual(rateio_vigente_em(base, [ta], date(2026, 7, 1)), novo)

    def test_rateio_sem_base_cai_no_item_unico(self):
        self.assertEqual(rateio_vigente_em(None, [], date(2026, 1, 1)), [{"numero": 1, "percentual": 100.0}])


def _custo(despesa, aditivos=(), exercicio=2026, **kwargs):
    kwargs.setdefault("status", "ATIVO")
    kwargs.setdefault("vigencia_fim", pd.NaT)
    return custo_mensal(despesa, list(aditivos), exercicio, **kwargs)


class TestSerieECusto(unittest.TestCase):
    """Valores calculados à mão (ver docstring do módulo de testes)."""

    def assertSerie(self, obtido, esperado, places=6):
        self.assertEqual(len(obtido), len(esperado))
        for mes, (a, b) in enumerate(zip(obtido, esperado), start=1):
            if b is None:
                self.assertTrue(math.isnan(a), f"mês {mes}: esperado NaN, obtido {a}")
            else:
                self.assertAlmostEqual(a, b, places=places, msg=f"mês {mes}")

    def test_sem_aditivo_a_serie_e_constante_e_o_custo_soma_o_ano(self):
        self.assertSerie(serie_valor_mensal(1000.0, [], 2026), [1000.0] * 12)
        self.assertAlmostEqual(sum(_custo(1000.0)), 12_000.0)

    def test_reajuste_no_meio_do_mes_e_proporcional_aos_dias(self):
        # julho: 15 dias a 1.000 e 16 dias a 1.310 → (15×1000 + 16×1310) / 31 = 1.160
        ta = _ta("1º TA", date(2026, 7, 16), 1_310.0)
        serie = serie_valor_mensal(1000.0, [ta], 2026)
        self.assertSerie(serie, [1000.0] * 6 + [1160.0] + [1310.0] * 5)
        self.assertSerie(_custo(1000.0, [ta]), serie)

    def test_dois_aditivos_no_mesmo_ano_exemplo_do_spec(self):
        ta1 = _ta("1º TA", date(2025, 7, 1), 10_400.0, vigencia=date(2026, 6, 30))
        ta2 = _ta("2º TA", date(2026, 7, 1), 10_800.0, vigencia=date(2027, 6, 30))
        self.assertAlmostEqual(sum(serie_valor_mensal(10_000.0, [ta1, ta2], 2026)), 127_200.0)
        self.assertAlmostEqual(sum(_custo(10_000.0, [ta1, ta2], vigencia_fim="2025-06-30")), 127_200.0)
        self.assertSerie(serie_valor_mensal(10_000.0, [ta1, ta2], 2027), [10_800.0] * 12)

    def test_aditivo_do_ano_anterior_vale_desde_janeiro(self):
        ta = _ta("1º TA", date(2025, 7, 1), 10_400.0)
        self.assertSerie(serie_valor_mensal(10_000.0, [ta], 2026), [10_400.0] * 12)

    def test_so_prorrogacao_nao_muda_o_valor_mas_estende_a_vigencia(self):
        ta = _ta("1º TA", date(2026, 7, 1), valor=None, vigencia=date(2027, 6, 30), tipo="PRORROGACAO")
        self.assertSerie(serie_valor_mensal(1000.0, [ta], 2026), [1000.0] * 12)
        custo = _custo(1000.0, [ta], vigencia_fim="2026-06-30")
        self.assertSerie(custo, [1000.0] * 12)  # sem a prorrogação, julho–dezembro seriam 0

    def test_sem_aditivo_posterior_a_vigencia_a_serie_para_no_vencimento(self):
        self.assertSerie(_custo(1000.0, vigencia_fim="2026-06-30"), [1000.0] * 6 + [0.0] * 6)

    def test_dias_entre_a_vigencia_original_e_o_aditivo_contam_pelo_valor_anterior(self):
        # Review Focus 4: vigência original 30/06; 2º TA só em 15/07 (vigência 2027). Julho:
        # 14 dias a 1.000 + 17 dias a 1.200 → (14×1000 + 17×1200) / 31 = 34.400 / 31.
        ta2 = _ta("2º TA", date(2026, 7, 15), 1_200.0, vigencia=date(2027, 6, 30))
        custo = _custo(1000.0, [ta2], vigencia_fim="2026-06-30")
        self.assertAlmostEqual(custo[6], 34_400 / 31)
        self.assertSerie(custo[:6] + custo[7:], [1000.0] * 6 + [1200.0] * 5)

    def test_meses_no_ano_menor_que_12_conta_os_primeiros_n_meses_em_execucao(self):
        custo = _custo(1000.0, meses_no_ano=6, inicio=date(2026, 3, 1))
        self.assertSerie(custo, [0.0, 0.0] + [1000.0] * 6 + [0.0] * 4)

    def test_inicio_no_meio_do_mes_e_proporcional(self):
        custo = _custo(1000.0, inicio=date(2026, 7, 16))
        self.assertAlmostEqual(custo[6], 1000.0 * 16 / 31)
        self.assertSerie(custo[:6], [0.0] * 6)

    def test_suspenso_com_data_so_conta_ate_a_vespera(self):
        custo = _custo(1000.0, status="SUSPENSO", data_suspensao=date(2026, 10, 1))
        self.assertSerie(custo, [1000.0] * 9 + [0.0] * 3)

    def test_suspenso_sem_data_e_vencido_sem_data_zeram_o_exercicio(self):
        self.assertSerie(_custo(1000.0, status="SUSPENSO"), [0.0] * 12)
        self.assertSerie(_custo(1000.0, status="VENCIDO"), [0.0] * 12)

    def test_despesa_mensal_nula_continua_nula_nunca_zero(self):
        self.assertSerie(serie_valor_mensal(None, [], 2026), [None] * 12)
        self.assertSerie(_custo(float("nan")), [None] * 12)
        self.assertSerie(_custo(None, status="VENCIDO"), [None] * 12)

    def test_valor_nulo_antes_do_primeiro_aditivo(self):
        ta = _ta("1º TA", date(2026, 7, 1), 500.0)
        self.assertSerie(serie_valor_mensal(None, [ta], 2026), [None] * 6 + [500.0] * 6)

    def test_serie_por_item_usa_o_rateio_vigente(self):
        base = [{"numero": 1, "percentual": 100.0}]
        novo = [{"numero": 1, "percentual": 60.0}, {"numero": 2, "percentual": 40.0}]
        ta = _ta("2º TA", date(2026, 7, 1), valor=None, itens=novo, vigencia=date(2027, 6, 30))
        item1 = serie_valor_mensal(1000.0, [ta], 2026, numero_item=1, itens_base=base)
        item2 = serie_valor_mensal(1000.0, [ta], 2026, numero_item=2, itens_base=base)
        self.assertSerie(item1, [1000.0] * 6 + [600.0] * 6)
        self.assertSerie(item2, [0.0] * 6 + [400.0] * 6)


class TestRetroativoEPrevistos(unittest.TestCase):
    def setUp(self):
        self.ta = _ta("2º TA", date(2026, 7, 1), 10_800.0, assinatura=date(2026, 9, 15))

    def test_retroativo_so_nos_meses_realizados_entre_inicio_e_assinatura(self):
        # +400/mês; julho e agosto realizados (dias 1/7 a 14/9 ∩ {7, 8}) → 2 × 400
        resultado = retroativo_por_aditivo(10_400.0, [self.ta], 2026, {7, 8})
        self.assertEqual(len(resultado), 1)
        self.assertIs(resultado[0][0], self.ta)
        self.assertAlmostEqual(resultado[0][1], 800.0)

    def test_setembro_realizado_conta_ate_o_dia_anterior_a_assinatura(self):
        # setembro: 14 dias (1 a 14) × 400/30
        resultado = retroativo_por_aditivo(10_400.0, [self.ta], 2026, {7, 8, 9})
        self.assertAlmostEqual(resultado[0][1], 800.0 + 400.0 * 14 / 30)

    def test_sem_data_de_assinatura_ou_previsto_nao_tem_retroativo(self):
        sem_assinatura = _ta("2º TA", date(2026, 7, 1), 10_800.0)
        previsto = _ta("2º TA", date(2026, 7, 1), 10_800.0, assinatura=date(2026, 9, 15), situacao="PREVISTO")
        self.assertEqual(retroativo_por_aditivo(10_400.0, [sem_assinatura], 2026, {7, 8}), [])
        self.assertEqual(retroativo_por_aditivo(10_400.0, [previsto], 2026, {7, 8}), [])

    def test_assinado_no_dia_do_inicio_ou_sem_valor_nao_tem_retroativo(self):
        no_dia = _ta("2º TA", date(2026, 7, 1), 10_800.0, assinatura=date(2026, 7, 1))
        sem_valor = _ta("2º TA", date(2026, 7, 1), valor=None, vigencia=date(2027, 6, 30), assinatura=date(2026, 9, 15))
        self.assertEqual(retroativo_por_aditivo(10_400.0, [no_dia], 2026, {7, 8}), [])
        self.assertEqual(retroativo_por_aditivo(10_400.0, [sem_valor], 2026, {7, 8}), [])

    def test_meses_com_previsto_pelo_valor(self):
        previsto = _ta("2º TA", date(2026, 7, 1), 10_800.0, situacao="PREVISTO")
        self.assertEqual(meses_com_previsto([previsto], 2026), {7, 8, 9, 10, 11, 12})
        self.assertEqual(meses_com_previsto([self.ta], 2026), set())
        self.assertEqual(meses_com_previsto([], 2026), set())

    def test_meses_com_previsto_pela_vigencia(self):
        # vigência assinada até 30/09; o previsto a estende até 2027: out–dez são previstos
        assinado = _ta("1º TA", date(2025, 7, 1), 10_400.0, vigencia=date(2026, 9, 30))
        previsto = _ta("2º TA", date(2026, 10, 1), valor=None, vigencia=date(2027, 9, 30), situacao="PREVISTO")
        self.assertEqual(meses_com_previsto([assinado, previsto], 2026), {10, 11, 12})


class TestMesesComPrevistoUsaAVigenciaDoContrato(unittest.TestCase):
    """Revisão final (06/10/2026): prorrogação PREVISTA sem valor novo estende a vigência do contrato — os
    meses estimados precisam ser marcados mesmo quando nenhum aditivo ASSINADO informa vigência."""

    def test_prorrogacao_prevista_sem_valor_marca_os_meses_da_extensao(self):
        previsto = _ta("1º TA", date(2026, 7, 1), valor=None, vigencia=date(2027, 6, 30), tipo="PRORROGACAO", situacao="PREVISTO")
        self.assertEqual(
            meses_com_previsto([previsto], 2026, vigencia_fim=date(2026, 6, 30)), {7, 8, 9, 10, 11, 12}
        )

    def test_sem_vigencia_do_contrato_nao_ha_extensao_a_marcar(self):
        previsto = _ta("1º TA", date(2026, 7, 1), valor=None, vigencia=date(2027, 6, 30), tipo="PRORROGACAO", situacao="PREVISTO")
        self.assertEqual(meses_com_previsto([previsto], 2026), set())

    def test_prorrogacao_assinada_nao_marca_nada(self):
        assinado = _ta("1º TA", date(2026, 7, 1), valor=None, vigencia=date(2027, 6, 30), tipo="PRORROGACAO")
        self.assertEqual(meses_com_previsto([assinado], 2026, vigencia_fim=date(2026, 6, 30)), set())


if __name__ == "__main__":
    unittest.main()
