"""Alerta gerencial "Conciliação por competência — pendências novas" (12/10/2026).

Só aparece o que AUMENTOU desde a última atualização do Contratos.gov (as `novas` do baseline); some o que o usuário
confirmou depois. Rejeitada continua pendente. Sem baseline ou sem novas = categoria "Ok".
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.alertas_gerenciais import pendencias_conciliacao_novas

NOVAS = {("23/2025", 202601, "deslocamento"), ("23/2025", 202602, "ambiguo"), ("10/2024", 202511, "cancelamento")}


def _decisao(contrato, am, classe, decisao):
    return SimpleNamespace(contrato=contrato, ano_mes=am, classe=classe, decisao=decisao)


class AlertaPendenciasTests(unittest.TestCase):
    def test_agrupa_por_contrato_e_lista_os_meses(self) -> None:
        itens = pendencias_conciliacao_novas(NOVAS, {})
        self.assertEqual([i["nome"] for i in itens], ["Contrato 10/2024", "Contrato 23/2025"])
        d23 = itens[1]["detalhe"]
        self.assertIn("jan/2026", d23)
        self.assertIn("fev/2026", d23)
        self.assertIn("2 pendência(s)", d23)
        self.assertEqual(itens[0]["valor"], 0)

    def test_sem_novas_nao_ha_alerta(self) -> None:
        self.assertEqual(pendencias_conciliacao_novas(set(), {}), [])
        self.assertEqual(pendencias_conciliacao_novas(None, {}), [])  # sem baseline

    def test_confirmada_depois_some_do_alerta_e_rejeitada_continua(self) -> None:
        decisoes = {
            ("23/2025", 202601): _decisao("23/2025", 202601, "deslocamento", "confirmada"),
            ("23/2025", 202602): _decisao("23/2025", 202602, "ambiguo", "rejeitada"),
        }
        itens = pendencias_conciliacao_novas(NOVAS, decisoes)
        d23 = [i for i in itens if i["nome"] == "Contrato 23/2025"][0]["detalhe"]
        self.assertNotIn("jan/2026", d23)
        self.assertIn("fev/2026", d23)

    def test_decisao_de_outra_classe_nao_resolve(self) -> None:
        decisoes = {("23/2025", 202601): _decisao("23/2025", 202601, "cancelamento", "confirmada")}
        itens = pendencias_conciliacao_novas(NOVAS, decisoes)
        self.assertIn("jan/2026", [i for i in itens if i["nome"] == "Contrato 23/2025"][0]["detalhe"])

    def test_todas_confirmadas_zera_o_alerta(self) -> None:
        decisoes = {(c, am): _decisao(c, am, k, "confirmada") for c, am, k in NOVAS if k != "ambiguo"}
        decisoes[("23/2025", 202602)] = _decisao("23/2025", 202602, "ambiguo", "rejeitada")
        self.assertEqual(len(pendencias_conciliacao_novas(NOVAS, decisoes)), 1)  # só o ambíguo rejeitado


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------------------ página Alertas Gerenciais
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest import mock  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

import src.decisoes_conciliacao as dc  # noqa: E402
import src.pendencias_conciliacao as pc  # noqa: E402


def _rodar_pagina(baseline_dir: Path, decisoes_dir: Path):
    with mock.patch.object(pc, "DIRETORIO_PADRAO", baseline_dir), mock.patch.object(dc, "DIRETORIO_DECISOES", decisoes_dir):
        at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app_pages" / "alertas_gerenciais.py"), default_timeout=60)
        at.run()
    return at


def _textos(at) -> str:
    return " ".join(m.value for m in at.markdown)


class PaginaAlertasTests(unittest.TestCase):
    def test_sem_baseline_a_categoria_nao_aparece(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            at = _rodar_pagina(Path(a), Path(b))
            self.assertFalse(at.exception)
            self.assertNotIn("pendências novas", _textos(at))

    def test_com_novas_aparece_sem_valor_em_reais(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            pc.salvar_baseline({"23/2025": {(202601, "deslocamento")}}, "abc", Path(a), novas=NOVAS)
            at = _rodar_pagina(Path(a), Path(b))
            self.assertFalse(at.exception)
            texto = _textos(at)
            self.assertIn("Conciliação por competência — pendências novas", texto)
            self.assertIn("Contratos.gov, atualização de", texto)

    def test_baseline_ilegivel_avisa_em_vez_de_sumir(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            (Path(a) / "ultima.json").write_text("{ quebrado", encoding="utf-8")
            at = _rodar_pagina(Path(a), Path(b))
            self.assertFalse(at.exception)
            self.assertTrue(any("indisponível" in w.value for w in at.warning))
