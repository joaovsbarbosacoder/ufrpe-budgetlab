"""Registro do reajuste FORMALIZADO ("a confirmar") a partir da página Reajuste estimado (12/10/2026).

`aditivos_sugeridos_dos_ciclos_formalizados` só PROPÕE (nada é gravado): um aditivo REAJUSTE/ASSINADO por ciclo formalizado
ainda sem aditivo na mesma data, com o valor mensal sugerido = valor em vigor × (1 + percentual) — editável e conferido por
quem registra. Percentual ou valor vigente desconhecido: valor sugerido nulo (nunca zero).
"""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.contratos_aditivos import Aditivo
from src.estimativa_reajuste import Ciclo, EstimativaContrato, aditivos_sugeridos_dos_ciclos_formalizados


def _est(*ciclos: Ciclo) -> EstimativaContrato:
    return EstimativaContrato(matriz=pd.DataFrame(), situacao="estimado", ciclos=list(ciclos))


def _ciclo(dia, estado="formalizado", pct=5.0, origem="manual") -> Ciclo:
    return Ciclo(data_base=dia, estado=estado, desde=date(dia.year - 1, dia.month, dia.day), percentual=pct, origem=origem)


class SugestaoTests(unittest.TestCase):
    def test_um_aditivo_assinado_por_ciclo_formalizado_com_valor_sugerido(self) -> None:
        est = _est(_ciclo(date(2026, 9, 1), pct=5.0))
        (a,) = aditivos_sugeridos_dos_ciclos_formalizados(est, [], 1000.0)
        self.assertEqual((a.tipo, a.situacao, a.data_inicio), ("REAJUSTE", "ASSINADO", date(2026, 9, 1)))
        self.assertEqual(a.valor_mensal, 1050.0)
        self.assertEqual(a.numero, "Reajuste 09/2026")

    def test_so_formalizados_projetado_nao_entra(self) -> None:
        est = _est(_ciclo(date(2026, 9, 1)), _ciclo(date(2027, 9, 1), estado="projetado"))
        self.assertEqual([a.data_inicio for a in aditivos_sugeridos_dos_ciclos_formalizados(est, [], 1000.0)], [date(2026, 9, 1)])

    def test_nao_duplica_data_que_ja_tem_aditivo(self) -> None:
        existente = Aditivo(numero="9", tipo="REAJUSTE", situacao="PREVISTO", data_inicio=date(2026, 9, 1), valor_mensal=1040.0)
        self.assertEqual(aditivos_sugeridos_dos_ciclos_formalizados(_est(_ciclo(date(2026, 9, 1))), [existente], 1000.0), [])

    def test_aditivo_assinado_sem_valor_e_proposto_para_completar_nao_para_duplicar(self) -> None:
        sem_valor = Aditivo(numero="TA 7", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2026, 9, 1), valor_mensal=None)
        (a,) = aditivos_sugeridos_dos_ciclos_formalizados(_est(_ciclo(date(2026, 9, 1), pct=5.0)), [sem_valor], 1000.0)
        self.assertEqual((a.numero, a.valor_mensal), ("TA 7", 1050.0))  # mantém o nº do termo já cadastrado
        com_valor = Aditivo(numero="TA 7", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2026, 9, 1), valor_mensal=1040.0)
        self.assertEqual(aditivos_sugeridos_dos_ciclos_formalizados(_est(_ciclo(date(2026, 9, 1))), [com_valor], 1000.0), [])

    def test_valor_sugerido_parte_do_valor_em_vigor_na_data(self) -> None:
        anterior = Aditivo(numero="1", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2025, 9, 1), valor_mensal=2000.0)
        (a,) = aditivos_sugeridos_dos_ciclos_formalizados(_est(_ciclo(date(2026, 9, 1), pct=10.0)), [anterior], 1000.0)
        self.assertEqual(a.valor_mensal, 2200.0)

    def test_percentual_ou_valor_desconhecido_deixa_o_valor_nulo_nunca_zero(self) -> None:
        (sem_pct,) = aditivos_sugeridos_dos_ciclos_formalizados(_est(_ciclo(date(2026, 9, 1), pct=None, origem="sem_indice")), [], 1000.0)
        self.assertIsNone(sem_pct.valor_mensal)
        (sem_valor,) = aditivos_sugeridos_dos_ciclos_formalizados(_est(_ciclo(date(2026, 9, 1))), [], None)
        self.assertIsNone(sem_valor.valor_mensal)

    def test_varios_ciclos_em_ordem_e_sem_ciclos(self) -> None:
        est = _est(_ciclo(date(2025, 9, 1)), _ciclo(date(2026, 9, 1)))
        self.assertEqual([a.data_inicio for a in aditivos_sugeridos_dos_ciclos_formalizados(est, [], 1000.0)], [date(2025, 9, 1), date(2026, 9, 1)])
        self.assertEqual(aditivos_sugeridos_dos_ciclos_formalizados(_est(), [], 1000.0), [])


if __name__ == "__main__":
    unittest.main()
