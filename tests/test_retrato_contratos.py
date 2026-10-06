"""Não regressão dos aditivos: contrato SEM aditivo calcula exatamente o que calculava antes.

Compara o cálculo atual com o retrato congelado em `tests/fixtures/` (gerado em 06/10/2026 com o
código anterior aos aditivos). Se uma conta mudar de propósito, regenere o fixture deliberadamente
(`tests/_retrato_contratos.gerar_fixture`) e recalcule à mão o que mudou — nunca automaticamente.
"""

from __future__ import annotations

import json
import unittest

from tests._retrato_contratos import CAMINHO_FIXTURE, calcular_retrato, iguais


class TestRetratoSemAditivo(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(CAMINHO_FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_tem_contratos_e_todas_as_secoes(self) -> None:
        self.assertGreater(len(self.fixture["entradas"]), 0)
        self.assertEqual(
            set(self.fixture["esperado"]),
            {"necessidade_por_ne", "sem_ne", "projecao", "despesa_anual", "reforco"},
        )

    def test_numeros_identicos_ao_retrato(self) -> None:
        obtido = calcular_retrato(self.fixture["entradas"])
        diferencas = iguais(self.fixture["esperado"], json.loads(json.dumps(obtido)))
        self.assertEqual(diferencas, [], "\n".join(diferencas[:20]))


if __name__ == "__main__":
    unittest.main()
