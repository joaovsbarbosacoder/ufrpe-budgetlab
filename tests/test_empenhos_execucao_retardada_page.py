"""Testes da página Empenhos com Execução Retardada.

Espelha `test_consulta_empenhos_page.py`/`test_execucao_orcamentaria_page.py`: usa a extração
real apontada pelo manifesto atual, sem fixtures sintéticas — pulado se esse manifesto não
existir. Cobre as regras descritas na docstring de `app_pages/empenhos_execucao_retardada.py`:
exercício vigente pré-selecionado, os dois cortes de destaque (R$ e %, independentes,
combinados com OU quando ambos ligados), aviso quando nenhum corte está ligado, e busca livre.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.importacao_execucao import Manifesto

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFESTO_ATUAL = Path("data/manifestos/execucao_anual_atual.json")


@unittest.skipUnless(MANIFESTO_ATUAL.exists(), f"Manifesto ausente em {MANIFESTO_ATUAL}")
class EmpenhosExecucaoRetardadaPageTests(unittest.TestCase):
    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        app.switch_page("app_pages/empenhos_execucao_retardada.py")
        app.run(timeout=60)
        return app

    def test_renders_page_from_current_manifest(self) -> None:
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Empenhos com Execução Retardada")
        labels = [metric.label for metric in app.metric]
        self.assertEqual(labels, ["Empenhos no escopo", "Empenhado", "Liquidado", "Saldo total (empenhado − liquidado)"])

    def test_shows_procedencia_footer_with_manifest_hash(self) -> None:
        app = self._open_page()
        manifesto = Manifesto.atual()

        self.assertTrue(any(f"hash {manifesto.sha256[:8]}" in item.value for item in app.caption))

    def test_exercicio_vigente_pre_selecionado(self) -> None:
        app = self._open_page()
        manifesto = Manifesto.atual()
        ano_extracao = datetime.fromisoformat(manifesto.data_extracao).year

        filtro_ano = next(m for m in app.multiselect if m.label == "Exercício")
        self.assertEqual(filtro_ano.value, [str(ano_extracao)])

    def test_corte_rs_ligado_por_padrao_pct_desligado(self) -> None:
        app = self._open_page()

        usar_rs = next(t for t in app.toggle if t.key and "usar_rs" in t.key)
        usar_pct = next(t for t in app.toggle if t.key and "usar_pct" in t.key)
        self.assertTrue(usar_rs.value)
        self.assertFalse(usar_pct.value)
        self.assertTrue(any("saldo ≥" in item.value for item in app.caption))

    def test_desligar_os_dois_cortes_mostra_aviso_sem_tabela(self) -> None:
        app = self._open_page()

        usar_rs = next(t for t in app.toggle if t.key and "usar_rs" in t.key)
        usar_rs.set_value(False)
        app.run(timeout=60)

        self.assertTrue(
            any("Ligue pelo menos um dos dois cortes" in item.value for item in app.warning)
        )

    def test_ligar_os_dois_cortes_combina_com_ou(self) -> None:
        app = self._open_page()

        usar_pct = next(t for t in app.toggle if t.key and "usar_pct" in t.key)
        usar_pct.set_value(True)
        app.run(timeout=60)

        self.assertTrue(
            any("saldo ≥" in item.value and " ou " in item.value for item in app.caption)
        )

    def test_busca_livre_narrows_scope(self) -> None:
        app = self._open_page()

        empenhos_no_escopo_antes = next(m for m in app.metric if m.label == "Empenhos no escopo").value

        busca = next(t for t in app.text_input if t.label == "Busca livre")
        busca.set_value("termo-que-nao-deve-existir-em-nenhuma-ne-xyzxyz")
        app.run(timeout=60)

        self.assertTrue(any("Nenhum empenho encontrado" in item.value for item in app.warning))
        self.assertNotEqual(empenhos_no_escopo_antes, "0")


if __name__ == "__main__":
    unittest.main()
