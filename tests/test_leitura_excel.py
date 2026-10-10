"""Paridade entre o motor rápido de Excel (python-calamine) e o padrão do pandas (openpyxl), para cada
leitor que passa por `src/leitura_excel.py` — sobre as fixtures congeladas (`tests/fixtures/`): o
DataFrame tem de ser idêntico (tipos, nulos, textos, zeros à esquerda). Única diferença conhecida e
aceita: célula marcada como data com número fora do intervalo de datas — o openpyxl a descarta (vira
nulo, com aviso), o calamine preserva o número na coluna bruta (`test_data_invalida_preservada`)."""

from __future__ import annotations

import os
import unittest
import warnings
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from src.bolsas_auxilios import ler_bolsas_auxilios
from src.contratos_continuos import ler_contratos_continuos
from src.contratos_pagamentos import ler_pagamentos
from src.execucao_anual import ler_execucao_anual
from src.leitura_excel import MOTOR_RAPIDO, VARIAVEL_AMBIENTE, motor_excel
from src.liquidacao_competencia import ler_liquidacao_competencia
from src.tesouro_execucao_mensal import ler_execucao_mensal

FIXTURES = Path(__file__).parent / "fixtures"
TEM_CALAMINE = motor_excel() == MOTOR_RAPIDO


@contextmanager
def _motor_padrao():
    anterior = os.environ.get(VARIAVEL_AMBIENTE)
    os.environ[VARIAVEL_AMBIENTE] = "padrao"
    try:
        yield
    finally:
        if anterior is None:
            os.environ.pop(VARIAVEL_AMBIENTE, None)
        else:
            os.environ[VARIAVEL_AMBIENTE] = anterior


def _pelos_dois(leitor, arquivo: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with _motor_padrao():
            padrao = leitor(FIXTURES / arquivo)
        rapido = leitor(FIXTURES / arquivo)
    return padrao, rapido


class TestMotor(unittest.TestCase):
    def test_variavel_forca_o_padrao(self):
        with _motor_padrao():
            self.assertIsNone(motor_excel())

    @unittest.skipUnless(TEM_CALAMINE, "python-calamine não instalado")
    def test_calamine_quando_instalado(self):
        self.assertEqual(motor_excel(), MOTOR_RAPIDO)


@unittest.skipUnless(TEM_CALAMINE, "python-calamine não instalado")
class TestParidade(unittest.TestCase):
    CASOS = [
        (ler_bolsas_auxilios, "bolsas_auxilios_2026-08-13.xlsx"),
        (ler_contratos_continuos, "contratos_continuos_2026-08-13.xlsm"),
        (ler_pagamentos, "contratos_pagamentos_2026-08-15.xlsx"),
        (ler_liquidacao_competencia, "liquidacao_competencia_2026-09-11.xlsx"),
        (ler_execucao_anual, "execucao_anual_2026-08-13.xlsx"),
        (ler_execucao_mensal, "execucao_mensal_2026-09-22.xlsx"),
    ]

    def test_leitores_identicos(self):
        for leitor, arquivo in self.CASOS:
            with self.subTest(leitor=leitor.__name__, arquivo=arquivo):
                padrao, rapido = _pelos_dois(leitor, arquivo)
                assert_frame_equal(padrao, rapido, check_dtype=True, check_exact=True)


if __name__ == "__main__":
    unittest.main()
