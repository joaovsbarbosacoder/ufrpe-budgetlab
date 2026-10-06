"""Testes de `src/contratos_aditivos.py` — aditivos de Contratos Contínuos (06/10/2026).

Spec: `docs/superpowers/specs/2026-10-06-aditivos-contratos-design.md`. Valores esperados calculados
à mão no exemplo do spec: contrato de R$ 10.000/mês, 1º TA (01/07/2025, R$ 10.400) e 2º TA
(01/07/2026, R$ 10.800) → em 2026, 6 × 10.400 + 6 × 10.800 = R$ 127.200.
"""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.contratos_aditivos import (
    SITUACOES,
    TIPOS,
    Aditivo,
    aditivo_para_registro,
    aditivos_do_registro,
    rateio_vigente_em,
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


if __name__ == "__main__":
    unittest.main()
