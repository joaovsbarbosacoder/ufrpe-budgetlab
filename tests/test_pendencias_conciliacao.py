"""Testes de `src/pendencias_conciliacao.py` — pendências de conciliação por atualização do Contratos.gov (11/10/2026).

Sem rede nem leitura das planilhas reais: o cálculo recebe tabelas prontas; a persistência usa pasta temporária.
Casos modelados em dados reais (deslocamento dez/2025 → jan/2026 da NE 2025NE000604, R$ 8.680,00).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.pendencias_conciliacao import (
    ErroBaseline,
    calcular_pendencias,
    carregar_baseline,
    comparar,
    mensagem_delta,
    salvar_baseline,
)

NE_A, NE_B = "2025NE000604", "2026NE000100"
PI = "M20RKG01SCN - GESTAO"


def _empenhos() -> pd.DataFrame:
    return pd.DataFrame({
        "contrato_id": ["1", "1"], "ne": [NE_A, NE_B], "plano_interno": [PI, PI],
        "natureza_despesa": ["339037 - X", "339037 - X"],
    })


def _nota(fid, numero, valor, ne, ano, mes, liquidacao=date(2026, 2, 1)) -> dict:
    return {
        "contrato_id": "1", "fatura_id": fid, "numero": numero, "valor": Decimal(str(valor)), "data_liquidacao": liquidacao,
        "empenhos": ((ne, None, Decimal(str(valor))),), "referencias": ((ano, mes, Decimal(str(valor))),),
    }


def _relatorio(*linhas) -> pd.DataFrame:
    return pd.DataFrame(linhas, columns=["ne_curta", "ano_mes", "valor"])


class CalcularTests(unittest.TestCase):
    def test_deslocamento_vira_pendencia_nos_dois_meses(self) -> None:
        faturas = pd.DataFrame([_nota("1", "A", 8680.0, NE_A, 2026, 1)])
        relatorio = _relatorio((NE_A, 202512, 8680.0), (NE_B, 202601, 2560.24))
        resultado = calcular_pendencias([("23/2025", "1", NE_B)], faturas, _empenhos(), relatorio)
        self.assertEqual(resultado["23/2025"], {(202512, "deslocamento"), (202601, "deslocamento")})

    def test_mes_que_bate_nao_e_pendencia(self) -> None:
        faturas = pd.DataFrame([_nota("1", "A", 100.0, NE_B, 2026, 3)])
        resultado = calcular_pendencias([("23/2025", "1", NE_B)], faturas, _empenhos(), _relatorio((NE_B, 202603, 100.0)))
        self.assertEqual(resultado["23/2025"], set())

    def test_contrato_sem_ligacao_ou_sem_notas_nao_gera_pendencia(self) -> None:
        resultado = calcular_pendencias([("99/2026", None, None), ("23/2025", "1", NE_B)], None, _empenhos(), _relatorio())
        self.assertEqual(resultado, {"99/2026": set(), "23/2025": set()})

    def test_nota_pendente_explica_a_falta(self) -> None:
        pendente = _nota("2", "P", 500.0, NE_B, 2026, 2, liquidacao=None)
        faturas = pd.DataFrame([_nota("1", "A", 100.0, NE_B, 2026, 2), pendente])
        resultado = calcular_pendencias([("23/2025", "1", NE_B)], faturas, _empenhos(), _relatorio((NE_B, 202602, 600.0)))
        self.assertEqual(resultado["23/2025"], {(202602, "nota_pendente")})


class CompararTests(unittest.TestCase):
    def test_novas_e_resolvidas(self) -> None:
        anterior = {"a": {(202601, "deslocamento")}, "b": {(202602, "so_relatorio")}}
        atual = {"a": {(202601, "deslocamento"), (202603, "cancelamento")}, "b": set()}
        novas, resolvidas = comparar(anterior, atual)
        self.assertEqual(novas, {("a", 202603, "cancelamento")})
        self.assertEqual(resolvidas, {("b", 202602, "so_relatorio")})

    def test_sem_baseline_nada_e_novo(self) -> None:
        self.assertEqual(comparar(None, {"a": {(202601, "deslocamento")}}), (set(), set()))  # primeira vez: só registra

    def test_mensagem(self) -> None:
        self.assertIn("2 pendência(s) nova(s)", mensagem_delta({("a", 1, "x"), ("b", 2, "y")}, {("c", 3, "z")}, 7))
        self.assertIn("1 resolvida(s)", mensagem_delta(set(), {("c", 3, "z")}, 7))
        self.assertIn("nenhuma mudança", mensagem_delta(set(), set(), 7))
        self.assertIn("7 pendência(s)", mensagem_delta(set(), set(), 7))


class BaselineTests(unittest.TestCase):
    def test_salva_e_carrega_sem_perder_nada(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pendencias = {"23/2025": {(202601, "deslocamento")}, "00/0000": set()}
            salvar_baseline(pendencias, fotografia="abc123", diretorio=Path(tmp))
            lido = carregar_baseline(Path(tmp))
            self.assertEqual(lido["pendencias"], pendencias)
            self.assertEqual(lido["fotografia"], "abc123")

    def test_sem_arquivo_devolve_none_e_arquivo_ilegivel_e_erro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(carregar_baseline(Path(tmp)))
            (Path(tmp) / "ultima.json").write_text("{ quebrado", encoding="utf-8")
            with self.assertRaises(ErroBaseline):
                carregar_baseline(Path(tmp))  # nunca vira "sem baseline" em silêncio

    def test_formato_versionado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            salvar_baseline({}, fotografia="x", diretorio=Path(tmp))
            self.assertEqual(json.loads((Path(tmp) / "ultima.json").read_text(encoding="utf-8"))["versao_schema"], 1)


if __name__ == "__main__":
    unittest.main()
