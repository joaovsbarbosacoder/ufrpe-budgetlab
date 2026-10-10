"""Testes de `src/indices_economicos.py` — índices oficiais (BCB/SGS) para a estimativa de reajuste.

Sem rede: o cliente HTTP é injetado (`buscar`). Valor esperado calculado à mão: 12 meses de 1,00% →
1,01^12 − 1 = 12,682503...%.
"""

from __future__ import annotations

import unittest
from datetime import date

from src.indices_economicos import (
    SERIES_BCB,
    ErroIndiceEconomico,
    acumulado_12m,
    variacoes_bcb,
)


def _meses(inicio: tuple[int, int], quantidade: int, valor: float) -> dict[tuple[int, int], float]:
    ano, mes = inicio
    resultado = {}
    for _ in range(quantidade):
        resultado[(ano, mes)] = valor
        mes += 1
        if mes == 13:
            ano, mes = ano + 1, 1
    return resultado


class AcumuladoDozeMesesTests(unittest.TestCase):
    def test_doze_meses_completos_sao_oficiais(self) -> None:
        variacoes = _meses((2026, 6), 12, 1.0)  # jun/2026..mai/2027
        percentual, origem = acumulado_12m(variacoes, 2027, 6)  # data-base jun/2027
        self.assertEqual(origem, "oficial")
        self.assertAlmostEqual(percentual, 12.682503013196977, places=9)

    def test_serie_curta_usa_os_ultimos_doze_disponiveis_e_marca_como_ultimo(self) -> None:
        variacoes = _meses((2025, 9), 12, 1.0)  # set/2025..ago/2026; a data-base pede jun/2026..mai/2027
        percentual, origem = acumulado_12m(variacoes, 2027, 6)
        self.assertEqual(origem, "oficial_ultimo")
        self.assertAlmostEqual(percentual, 12.682503013196977, places=9)

    def test_menos_de_doze_meses_disponiveis_e_ausente_nunca_zero(self) -> None:
        percentual, origem = acumulado_12m(_meses((2026, 1), 5, 1.0), 2027, 6)
        self.assertIsNone(percentual)
        self.assertEqual(origem, "ausente")
        self.assertEqual(acumulado_12m({}, 2027, 6), (None, "ausente"))

    def test_variacao_zero_e_negativa_sao_preservadas(self) -> None:
        variacoes = _meses((2026, 6), 12, 0.0)
        self.assertEqual(acumulado_12m(variacoes, 2027, 6), (0.0, "oficial"))  # zero informado ≠ ausente
        variacoes[(2026, 6)] = -1.0
        percentual, _ = acumulado_12m(variacoes, 2027, 6)
        self.assertAlmostEqual(percentual, -1.0, places=9)


class VariacoesBcbTests(unittest.TestCase):
    def test_converte_a_resposta_da_api_em_mapa_por_mes(self) -> None:
        chamadas = []

        def buscar(url: str) -> list[dict]:
            chamadas.append(url)
            return [{"data": "01/01/2025", "valor": "0.16"}, {"data": "01/02/2025", "valor": "1.31"}]

        variacoes = variacoes_bcb("IPCA", date(2025, 1, 1), date(2025, 2, 28), buscar=buscar)
        self.assertEqual(variacoes, {(2025, 1): 0.16, (2025, 2): 1.31})
        self.assertIn(f"sgs.{SERIES_BCB['IPCA']}", chamadas[0])
        self.assertIn("dataInicial=01/01/2025", chamadas[0])

    def test_indice_desconhecido_e_resposta_invalida_levantam_erro_explicito(self) -> None:
        with self.assertRaises(ErroIndiceEconomico):
            variacoes_bcb("XYZ", date(2025, 1, 1), date(2025, 2, 1), buscar=lambda url: [])
        with self.assertRaises(ErroIndiceEconomico):
            variacoes_bcb("IPCA", date(2025, 1, 1), date(2025, 2, 1), buscar=lambda url: [{"data": "01/01/2025", "valor": "abc"}])
        with self.assertRaises(ErroIndiceEconomico):
            variacoes_bcb("IPCA", date(2025, 1, 1), date(2025, 2, 1), buscar=lambda url: {"erro": "x"})

    def test_falha_de_rede_vira_erro_do_modulo(self) -> None:
        def buscar(url: str) -> list[dict]:
            raise OSError("sem rede")

        with self.assertRaises(ErroIndiceEconomico):
            variacoes_bcb("IPCA", date(2025, 1, 1), date(2025, 2, 1), buscar=buscar)


if __name__ == "__main__":
    unittest.main()
