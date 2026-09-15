"""Testes do botão/pop-up "Relatórios" (Reforço de Empenho / Anulação de Saldo de Empenho —
src/ui_relatorio_reforco_empenho.py) em cada página que o usa — Bolsas e Auxílios e Contratos
Contínuos.

Usa o cadastro nativo real dessas páginas (`data/bolsas_auxilios/`, `data/contratos_continuos/`
— ver `src/cadastro_por_exercicio.py`), sem fixtures sintéticas — pulado se a base
correspondente não existir. A lógica de negócio em si (mapeamento de colunas, cálculo do valor
a lançar, geração do PDF, um tipo por tipo — inclusive `TIPO_ANULACAO`) já é testada em
isolamento por `tests/test_relatorio_reforco_empenho.py`; aqui só confere que o botão abre o
pop-up e a tela de escolha do relatório (Reforço/Anulação) aparece sem erro, com os dois
botões esperados.

LIMITAÇÃO CONHECIDA DE `AppTest` (não é bug do app — verificado com um repro mínimo antes de
aceitar essa lacuna): a tela de CONTEÚDO de cada relatório (seletor de Processo, tabela,
downloads), que só aparece depois de clicar num botão DENTRO do próprio pop-up, não é
alcançável por este teste. `@st.dialog`, no Streamlit real, reinvoca a função decorada
automaticamente a cada rerun disparado por um widget dentro dele já aberto, sem o código
externo precisar chamá-la de novo (confirmado pelo comportamento documentado do "Ver mais" em
`app_pages/contratos_continuos.py`, nunca coberto por `AppTest` por esse mesmo motivo) —
`AppTest`, que roda o script em modo "bare" sem essa reinvocação automática, não reproduz esse
comportamento: só a PRIMEIRA invocação (a que reage de verdade ao clique do botão que abre o
pop-up) é executada; um clique simulado num botão que só existe DENTRO do dialog já aberto não
faz `AppTest` reinvocar a função. Pré-semear `st.session_state` antes do clique de abertura
também não escapa disso, porque `_limpar_estado_relatorio` (chamada nesse mesmo clique, de
propósito, para sempre voltar à tela de escolha numa abertura nova) apaga qualquer valor
pré-semeado antes da função de conteúdo chegar a lê-lo. A tela de conteúdo em si (mesmo
`st.data_editor`/mecânica de edição do Reforço original, só parametrizada por `TipoRelatorio`)
foi conferida manualmente no app rodando.

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
    """Abre a página, escolhe o exercício mais antigo e clica em "📄 Relatórios" — devolve o
    app com a tela de ESCOLHA do relatório visível (ver limitação de `AppTest` na docstring do
    módulo sobre por que este helper não vai além disso)."""

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
    def test_clicar_no_botao_abre_a_escolha_de_relatorio_sem_erro(self) -> None:
        app = _abrir_pagina_e_clicar("app_pages/bolsas_auxilios.py", "bls")

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("Reforço" in b.label for b in app.button))
        self.assertTrue(any("Anulação" in b.label for b in app.button))


@unittest.skipUnless(
    _tem_exercicio_cadastrado(DIRETORIO_CONTINUOS) and MANIFESTO_EXECUCAO.exists(),
    f"Base ausente em {DIRETORIO_CONTINUOS} ou manifesto em {MANIFESTO_EXECUCAO}",
)
class TestBotaoRelatorioEmContratosContinuos(unittest.TestCase):
    def test_clicar_no_botao_abre_a_escolha_de_relatorio_sem_erro(self) -> None:
        app = _abrir_pagina_e_clicar("app_pages/contratos_continuos.py", "cc")

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("Reforço" in b.label for b in app.button))
        self.assertTrue(any("Anulação" in b.label for b in app.button))


if __name__ == "__main__":
    unittest.main()
