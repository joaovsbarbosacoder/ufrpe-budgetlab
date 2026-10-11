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
    COLUNAS_INCONSISTENCIAS,
    comparar,
    excel_inconsistencias,
    mensagem_delta,
    tabela_inconsistencias,
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


class RelatorioInconsistenciasTests(unittest.TestCase):
    def _tabela(self):
        faturas = pd.DataFrame([_nota("1", "A", 8680.0, NE_A, 2026, 1)])
        relatorio = _relatorio((NE_A, 202512, 8680.0), (NE_B, 202601, 2560.24))
        return tabela_inconsistencias([("23/2025", "1", NE_B)], faturas, _empenhos(), relatorio)

    def test_uma_linha_por_mes_pendente_com_causa_valores_e_acao(self) -> None:
        tabela = self._tabela()
        self.assertEqual(list(tabela.columns), COLUNAS_INCONSISTENCIAS)
        self.assertEqual(tabela["Competência"].tolist(), ["12/2025", "01/2026"])
        jan = tabela[tabela["Competência"] == "01/2026"].iloc[0]
        self.assertEqual(jan["Causa"], "Deslocamento de competência")
        self.assertEqual(jan["Valor nas notas"], 8680.0)
        dez = tabela[tabela["Competência"] == "12/2025"].iloc[0]
        self.assertTrue(pd.isna(dez["Valor nas notas"]))  # sem nota no mês: nulo, nunca zero
        self.assertEqual(dez["Valor no relatório"], 8680.0)
        self.assertTrue(pd.isna(dez["Diferença"]))
        self.assertIn("12/2025", jan["Ação sugerida"])
        self.assertEqual(jan["Notas"], "A")

    def test_filtro_de_periodo_descarta_competencias_anteriores(self) -> None:
        faturas = pd.DataFrame([_nota("1", "A", 8680.0, NE_A, 2026, 1)])
        relatorio = _relatorio((NE_A, 202512, 8680.0), (NE_B, 202601, 2560.24))
        todas = tabela_inconsistencias([("23/2025", "1", NE_B)], faturas, _empenhos(), relatorio)
        so_2026 = tabela_inconsistencias([("23/2025", "1", NE_B)], faturas, _empenhos(), relatorio, a_partir_do_ano=2026)
        self.assertEqual(todas["Competência"].tolist(), ["12/2025", "01/2026"])
        self.assertEqual(so_2026["Competência"].tolist(), ["01/2026"])  # o par de dez/2025 sai junto com o ano

    def test_sem_pendencia_devolve_tabela_vazia_com_as_colunas(self) -> None:
        faturas = pd.DataFrame([_nota("1", "A", 100.0, NE_B, 2026, 3)])
        tabela = tabela_inconsistencias([("23/2025", "1", NE_B)], faturas, _empenhos(), _relatorio((NE_B, 202603, 100.0)))
        self.assertTrue(tabela.empty)
        self.assertEqual(list(tabela.columns), COLUNAS_INCONSISTENCIAS)

    def test_excel_tem_resumo_e_pendencias(self) -> None:
        from io import BytesIO

        planilhas = pd.read_excel(BytesIO(excel_inconsistencias(self._tabela())), sheet_name=None)
        self.assertEqual(set(planilhas), {"Resumo por causa", "Pendências"})
        self.assertEqual(planilhas["Resumo por causa"].iloc[0]["Meses"], 2)
        self.assertEqual(len(planilhas["Pendências"]), 2)
        self.assertEqual(len(pd.read_excel(BytesIO(excel_inconsistencias(pd.DataFrame(columns=COLUNAS_INCONSISTENCIAS))), sheet_name="Pendências")), 0)


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


# ------------------------------------------------------------------ página Contratos (aba Atualizar)

import pytest  # noqa: E402

from tests import test_contratos_page as pagina_contratos  # noqa: E402


@pytest.mark.skipif(not pagina_contratos.FIXTURE.exists(), reason="Fixture do Contratos.gov ausente")
def test_aba_atualizar_oferece_o_relatorio_de_inconsistencias(tmp_path, monkeypatch) -> None:
    dirs = pagina_contratos.dirs.__wrapped__(tmp_path, monkeypatch)
    pagina_contratos._gravar_fixture(dirs)
    app = pagina_contratos._app()
    pagina_contratos._aba(app, "Atualizar")
    assert not app.exception, [e.value for e in app.exception]
    assert any(b.label == "Gerar relatório de inconsistências" for b in app.button)
    assert next(s for s in app.selectbox if s.label == "Competências a partir de").value == 2025  # padrão: 2025 em diante
    assert "Relatório de inconsistências de conciliação" in " ".join(m.value for m in app.markdown)
