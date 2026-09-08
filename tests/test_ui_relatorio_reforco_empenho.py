"""Testes do botão/pop-up "Relatório de Reforço de Empenho" (src/ui_relatorio_reforco_empenho.py)
em cada página que o usa — Bolsas e Auxílios e Contratos Contínuos.

Usa o cadastro nativo real dessas páginas (`data/bolsas_auxilios/`, `data/contratos_continuos/`
— ver `src/cadastro_por_exercicio.py`), sem fixtures sintéticas — pulado se a base
correspondente não existir. A lógica de negócio em si (mapeamento de colunas, cálculo de
"Empenhar (R$)", geração do PDF) já é testada em isolamento por
`tests/test_relatorio_reforco_empenho.py`; aqui só confere que o botão abre o pop-up sem erro
dentro de cada página real.

Seleciona sempre o exercício mais ANTIGO (`min(anos)`) antes de abrir o relatório — o mais
recente pode ter sido criado via "Duplicar" (execução em branco, sem NE nenhuma ainda) e nesse
caso não haveria nenhum "Processo" com empenho reconhecível para popular o relatório; o
exercício mais antigo é sempre o migrado da planilha original, com dado real.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIRETORIO_BOLSAS = Path("data/bolsas_auxilios")
DIRETORIO_CONTINUOS = Path("data/contratos_continuos")
MANIFESTO_EXECUCAO = Path("data/manifestos/execucao_anual_atual.json")


def _tem_exercicio_cadastrado(diretorio: Path) -> bool:
    return diretorio.exists() and any(item.is_dir() for item in diretorio.iterdir())


def _abrir_pagina_e_clicar(pagina: str, prefixo_ano: str) -> AppTest:
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
    app.run()
    app.switch_page(pagina)
    app.run(timeout=60)

    botoes_ano = [b for b in app.button if b.key and b.key.startswith(f"{prefixo_ano}_ano_")]
    if botoes_ano:
        mais_antigo = min(botoes_ano, key=lambda b: int(b.key.rsplit("_", 1)[1]))
        mais_antigo.click().run(timeout=60)

    botao = next(b for b in app.button if "Relat" in b.label)
    botao.click().run(timeout=60)
    return app


@unittest.skipUnless(
    _tem_exercicio_cadastrado(DIRETORIO_BOLSAS) and MANIFESTO_EXECUCAO.exists(),
    f"Base ausente em {DIRETORIO_BOLSAS} ou manifesto em {MANIFESTO_EXECUCAO}",
)
class TestBotaoRelatorioEmBolsasAuxilios(unittest.TestCase):
    def test_clicar_no_botao_abre_o_pop_up_sem_erro(self) -> None:
        app = _abrir_pagina_e_clicar("app_pages/bolsas_auxilios.py", "bls")

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(s.label == "Processo" for s in app.selectbox))
        self.assertTrue(any("Modelo Detalhado" in b.label for b in app.download_button))
        self.assertTrue(any("Modelo Resumido" in b.label for b in app.download_button))


@unittest.skipUnless(
    _tem_exercicio_cadastrado(DIRETORIO_CONTINUOS) and MANIFESTO_EXECUCAO.exists(),
    f"Base ausente em {DIRETORIO_CONTINUOS} ou manifesto em {MANIFESTO_EXECUCAO}",
)
class TestBotaoRelatorioEmContratosContinuos(unittest.TestCase):
    def test_clicar_no_botao_abre_o_pop_up_sem_erro(self) -> None:
        app = _abrir_pagina_e_clicar("app_pages/contratos_continuos.py", "cc")

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(s.label == "Processo" for s in app.selectbox))
        self.assertTrue(any("Modelo Detalhado" in b.label for b in app.download_button))
        self.assertTrue(any("Modelo Resumido" in b.label for b in app.download_button))


if __name__ == "__main__":
    unittest.main()
