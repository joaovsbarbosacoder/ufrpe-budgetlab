"""
Testes do leitor de execução por NE do Tesouro Gerencial. Layout ainda não confirmado com
extração real (ver docstring de `src/teds_importacao_tesouro_gerencial.py`) — os testes
cobrem o contrato assumido, não um formato validado contra planilha real.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

import pandas as pd

from src.teds_importacao_tesouro_gerencial import ler_execucao_tg


class LerExecucaoTgTests(unittest.TestCase):
    def test_linha_completa_com_competencia(self):
        df = pd.DataFrame(
            [
                {
                    "Número Completo NE": "2026NE000422",
                    "Favorecido": "Fornecedor X",
                    "Descrição": "Serviço Y",
                    "Valor Empenhado": "388.300,00",
                    "Valor Liquidado": "100.000,00",
                    "Valor Pago": "100.000,00",
                    "Documento Hábil": "2026DH000010",
                    "Documento Contábil": "2026NL000010",
                    "Ano Competência": 2026,
                    "Mês Competência": 8,
                    "Valor Competência": "100.000,00",
                }
            ]
        )
        resultado = ler_execucao_tg(df)
        self.assertEqual(len(resultado.registros), 1)
        r = resultado.registros[0]
        self.assertEqual(r["numero_completo_ne"], "2026NE000422")
        self.assertEqual(r["empenhado"], Decimal("388300.00"))
        self.assertEqual(r["ano_competencia"], 2026)
        self.assertEqual(r["mes_competencia"], 8)

    def test_linha_sem_competencia_fica_com_campos_none(self):
        df = pd.DataFrame(
            [
                {
                    "Número Completo NE": "2026NE000427",
                    "Valor Empenhado": "154.496,00",
                }
            ]
        )
        resultado = ler_execucao_tg(df)
        r = resultado.registros[0]
        self.assertEqual(r["empenhado"], Decimal("154496.00"))
        self.assertIsNone(r["ano_competencia"])
        self.assertIsNone(r["valor_competencia"])

    def test_linha_sem_numero_de_ne_e_rejeitada(self):
        df = pd.DataFrame([{"Número Completo NE": None, "Valor Empenhado": "1.000,00"}])
        resultado = ler_execucao_tg(df)
        self.assertEqual(len(resultado.registros), 0)
        self.assertEqual(len(resultado.rejeitadas), 1)

    def test_coluna_de_ne_ausente_levanta_erro_explicito(self):
        df = pd.DataFrame([{"Alguma Outra Coluna": "x"}])
        with self.assertRaises(ValueError):
            ler_execucao_tg(df)


if __name__ == "__main__":
    unittest.main()
