"""Testes do botão/pop-up "Relatório de Reforço de Empenho" (src/ui_relatorio_reforco_empenho.py)
em cada página que o usa — Bolsas e Auxílios e Contratos Contínuos.

Usa as extrações reais apontadas pelos manifestos/planilhas de trabalho, sem fixtures
sintéticas — pulado se a base correspondente não existir. A lógica de negócio em si (mapeamento
de colunas, cálculo de "Empenhar (R$)", geração do PDF) já é testada em isolamento por
`tests/test_relatorio_reforco_empenho.py`; aqui só confere que o botão abre o pop-up sem erro
dentro de cada página real.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMINHO_BOLSAS = Path("data/raw/BOLSAS E AUXÍLIOS 2026 - AGO A DEZ.xlsx")
CAMINHO_CONTINUOS = Path("data/raw/SERVIÇOS CONTÍNUOS - 2026 - AGO A DEZ.xlsm")
MANIFESTO_EXECUCAO = Path("data/manifestos/execucao_anual_atual.json")


def _abrir_pagina_e_clicar(pagina: str) -> AppTest:
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
    app.run()
    app.switch_page(pagina)
    app.run(timeout=60)
    botao = next(b for b in app.button if "Relat" in b.label)
    botao.click().run(timeout=60)
    return app


@unittest.skipUnless(
    CAMINHO_BOLSAS.exists() and MANIFESTO_EXECUCAO.exists(),
    f"Base ausente em {CAMINHO_BOLSAS} ou manifesto em {MANIFESTO_EXECUCAO}",
)
class TestBotaoRelatorioEmBolsasAuxilios(unittest.TestCase):
    def test_clicar_no_botao_abre_o_pop_up_sem_erro(self) -> None:
        app = _abrir_pagina_e_clicar("app_pages/bolsas_auxilios.py")

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(s.label == "Processo" for s in app.selectbox))
        self.assertTrue(any("Modelo Detalhado" in b.label for b in app.download_button))
        self.assertTrue(any("Modelo Resumido" in b.label for b in app.download_button))


@unittest.skipUnless(
    CAMINHO_CONTINUOS.exists() and MANIFESTO_EXECUCAO.exists(),
    f"Base ausente em {CAMINHO_CONTINUOS} ou manifesto em {MANIFESTO_EXECUCAO}",
)
class TestBotaoRelatorioEmContratosContinuos(unittest.TestCase):
    def test_clicar_no_botao_abre_o_pop_up_sem_erro(self) -> None:
        app = _abrir_pagina_e_clicar("app_pages/contratos_continuos.py")

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(s.label == "Processo" for s in app.selectbox))
        self.assertTrue(any("Modelo Detalhado" in b.label for b in app.download_button))
        self.assertTrue(any("Modelo Resumido" in b.label for b in app.download_button))


if __name__ == "__main__":
    unittest.main()
