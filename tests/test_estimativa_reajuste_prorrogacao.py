"""Prorrogação com valor na data do reajuste já INCLUI o reajuste (regra confirmada pelo usuário em 13/10/2026).

Uma Prorrogação ASSINADA com valor mensal na MESMA data de um reajuste formalizado no gov (ou de um aditivo de Reajuste
assinado sem valor) conta como reajuste REGISTRADO: o ciclo sai do "formalizado a confirmar", ancora a anualidade e aparece
como "registrado" na linha do tempo. Prorrogação sem valor, prevista, ou em outra data não muda nada.
"""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.contratos_aditivos import Aditivo
from src.estimativa_reajuste import ParametrosReajuste, ciclos_do_contrato, estimar_contrato

DIA = date(2026, 8, 24)


def _prorrogacao(dia=DIA, valor=21_199.17, situacao="ASSINADO") -> Aditivo:
    return Aditivo(numero="02/2026", tipo="PRORROGACAO", situacao=situacao, data_inicio=dia, valor_mensal=valor)


def _ciclos(aditivos, reajustes_gov=(DIA,)):
    return ciclos_do_contrato(
        inicio_contrato=date(2024, 8, 24), fim_efetivo=date(2028, 8, 23), aditivos=aditivos, reajustes_gov=list(reajustes_gov),
        retroativos=[], data_base_manual=None, inicio_exercicio=date(2026, 1, 1),
    )


class CiclosComProrrogacaoTests(unittest.TestCase):
    def test_prorrogacao_com_valor_na_data_do_reajuste_o_registra_e_ancora_a_projecao(self) -> None:
        ciclos, motivo = _ciclos([_prorrogacao()])
        self.assertEqual(motivo, "ok")
        self.assertEqual([(d, estado) for d, estado, _ in ciclos], [(date(2027, 8, 24), "projetado")])  # ancora: +12 meses

    def test_sem_a_prorrogacao_o_ciclo_continua_formalizado(self) -> None:
        ciclos, _ = _ciclos([])
        self.assertEqual(ciclos[0][:2], (DIA, "formalizado"))

    def test_prorrogacao_sem_valor_continua_a_confirmar(self) -> None:
        ciclos, _ = _ciclos([_prorrogacao(valor=None)])
        self.assertEqual(ciclos[0][:2], (DIA, "formalizado"))

    def test_prorrogacao_prevista_ou_em_outra_data_nao_registra(self) -> None:
        self.assertEqual(_ciclos([_prorrogacao(situacao="PREVISTO")])[0][0][:2], (DIA, "formalizado"))
        self.assertEqual(_ciclos([_prorrogacao(dia=date(2026, 9, 24))])[0][0][:2], (DIA, "formalizado"))

    def test_prorrogacao_com_valor_sem_reajuste_na_data_nao_vira_reajuste(self) -> None:
        # nenhum reajuste do gov nessa data: a prorrogação é só prorrogação (não cria nem ancora ciclo de reajuste)
        ciclos, _ = _ciclos([_prorrogacao()], reajustes_gov=[])
        self.assertEqual(ciclos[0][:2], (date(2026, 8, 24), "projetado"))  # aniversário do início do contrato, como antes


class EstimativaComProrrogacaoTests(unittest.TestCase):
    def _estimar(self, aditivos):
        return estimar_contrato(
            contrato="29/2024", despesa_mensal=20_000.0, aditivos=aditivos, vigencia_inicio=date(2024, 8, 24),
            vigencia_fim=date(2028, 8, 23), parametros=ParametrosReajuste(percentual_manual=4.44), exercicio_inicial=2026,
            reajustes_gov=[DIA],
        )

    def test_expoe_as_prorrogacoes_que_ja_incluem_o_reajuste_e_nao_ha_ciclo_formalizado(self) -> None:
        estimativa = self._estimar([_prorrogacao()])
        self.assertEqual([a.numero for a in estimativa.registrados_por_prorrogacao], ["02/2026"])
        self.assertNotIn("formalizado", [c.estado for c in estimativa.ciclos])
        self.assertEqual(float(estimativa.matriz["acrescimo_formalizado"].fillna(0).sum()), 0.0)  # nada a confirmar

    def test_sem_a_prorrogacao_nada_e_registrado_e_o_formalizado_incide(self) -> None:
        estimativa = self._estimar([])
        self.assertEqual(estimativa.registrados_por_prorrogacao, [])
        self.assertIn("formalizado", [c.estado for c in estimativa.ciclos])


if __name__ == "__main__":
    unittest.main()
