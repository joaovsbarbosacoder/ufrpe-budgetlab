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
aceitar essa lacuna): a tela de CONTEÚDO de cada relatório dentro do pop-up "Relatórios"
completo (`_abrir_relatorios`, escolha + conteúdo no MESMO dialog), que só aparece depois de
clicar num botão DENTRO do próprio pop-up já aberto, não é alcançável por ESTE helper
específico (`_abrir_pagina_e_clicar`, abaixo). `@st.dialog`, no Streamlit real, reinvoca a
função decorada automaticamente a cada rerun disparado por um widget dentro dele já aberto,
sem o código externo precisar chamá-la de novo (confirmado pelo comportamento documentado do
"Ver mais" em `app_pages/contratos_continuos.py`, nunca coberto por `AppTest` por esse mesmo
motivo) — `AppTest`, que roda o script em modo "bare" sem essa reinvocação automática, não
reproduz esse comportamento: só a PRIMEIRA invocação (a que reage de verdade ao clique do
botão que abre o pop-up) é executada; um clique simulado num botão que só existe DENTRO do
dialog já aberto não faz `AppTest` reinvocar a função.

A tela de CONTEÚDO em si (a grade feita à mão, `_render_conteudo_relatorio`) TEM cobertura
própria — `TestGradeFeitaAMao`, mais abaixo — chamando essa função diretamente (sem passar
pelo dialog/picker, mesma técnica de `tests/test_relatorio_reforco_empenho.py` para funções
internas), com dado sintético (não depende do cadastro real). Essa é a mesma grade que
substituiu o `st.data_editor` original — removido por um bug real visto em produção: a grade
nativa ficava permanentemente em branco dentro deste `st.dialog` no navegador real, apesar do
dado certo confirmado chegando até o front-end (inspeção direta do Arrow transmitido pelo
servidor) — nunca reproduzido a partir do servidor/`AppTest`, só visível no navegador real.

Seleciona sempre o exercício mais ANTIGO (`min(anos)`) antes de abrir o relatório — o mais
recente pode ter sido criado via "Duplicar" (execução em branco, sem NE nenhuma ainda) e nesse
caso não haveria nenhum "Processo" com empenho reconhecível para popular o relatório; o
exercício mais antigo é sempre o migrado da planilha original, com dado real.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from tests._apptest import TEMPO_LIMITE_APPTEST

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

    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=TEMPO_LIMITE_APPTEST)
    app.run()
    app.switch_page(pagina)
    app.run()

    botoes_ano = [b for b in app.button if b.key and b.key.startswith(f"{prefixo_ano}_ano_")]
    if botoes_ano:
        mais_antigo = min(botoes_ano, key=lambda b: int(b.key.rsplit("_", 1)[1]))
        mais_antigo.click().run()

    botao = next(b for b in app.button if "Relat" in b.label)
    botao.click().run()
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


def _bolsas_sintetico() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "processo": ["001167/2026-78", "001167/2026-78"],
            "programa_bolsa": ["PADPG", "ESO"],
            "unidade_cod": ["PRPG", "PREG"],
            "acao_cod": ["20GK", "20GK"],
            "ptres": ["230389", "230389"],
            "fonte_cod": ["1000", "1000"],
            "natureza_despesa_cod": ["339018", "339018"],
            "ugr_cod": ["151931", "157684"],
            "pi_cod": ["M20GKO94AXN", "M20GKG19AXN"],
            "ne_curta": ["2026NE000020", "2026NE000056"],
            "valor_mensal": [15750.0, 2500.0],
            "meses_a_empenhar": [0.9, 1.0],
        }
    )


def _app_fn(tipo_id: str, processo_key: str) -> None:
    """Corpo do app simulado (ver `_renderiza_conteudo`) — `AppTest.from_function` exige uma
    função "executável isoladamente" (sem depender de closures sobre variáveis externas), daí
    receber `tipo_id` (string) em vez do próprio `TipoRelatorio` e os imports todos aqui
    dentro."""

    from src.relatorio_reforco_empenho import BOLSAS_AUXILIOS, TIPO_ANULACAO, TIPO_REFORCO
    from src.ui_relatorio_reforco_empenho import _render_conteudo_relatorio
    from tests.test_ui_relatorio_reforco_empenho import _bolsas_sintetico

    tipo = TIPO_REFORCO if tipo_id == "reforco" else TIPO_ANULACAO
    _render_conteudo_relatorio(_bolsas_sintetico(), BOLSAS_AUXILIOS, tipo, processo_key, 2026)


def _renderiza_conteudo(tipo_id: str, processo_key: str = "teste") -> AppTest:
    """Chama `_render_conteudo_relatorio` diretamente, sem passar pelo dialog/picker (mesma
    técnica de `tests/test_relatorio_reforco_empenho.py` para funções internas) — com dado
    sintético, não depende do cadastro real. `AppTest.from_function` monta um app de uma
    função Python só para este teste, sem precisar de um arquivo `.py` à parte."""

    app = AppTest.from_function(_app_fn, args=(tipo_id, processo_key), default_timeout=TEMPO_LIMITE_APPTEST)
    app.run()
    return app


class TestGradeFeitaAMao(unittest.TestCase):
    """Grade de edição feita à mão (`st.columns` + `st.text_input` mascarado em pt-BR, uma
    célula por widget) que substituiu o `st.data_editor` — ver docstring do módulo sobre o
    motivo (e sobre a troca de `number_input` por `text_input`, pra ganhar pontuação de milhar,
    pedido explícito). Testada aqui de verdade (com interação simulada, não só presença de
    widgets), coisa que o `st.data_editor` antigo nunca teve (bloqueado pela limitação de
    `AppTest` com dialogs)."""

    def test_reforco_sugere_valor_inicial_a_partir_de_meses_sugeridos(self) -> None:
        app = _renderiza_conteudo("reforco")

        self.assertEqual(len(app.exception), 0)
        meses = [ti for ti in app.text_input if ti.label == "Meses a Empenhar"]
        self.assertEqual(len(meses), 2)
        self.assertEqual(meses[0].value, "0,90")

    def test_anulacao_comeca_zerada(self) -> None:
        app = _renderiza_conteudo("anulacao")

        self.assertEqual(len(app.exception), 0)
        meses = [ti for ti in app.text_input if ti.label == "Meses a Anular"]
        valores = [ti for ti in app.text_input if ti.label == "ANULAR (R$)"]
        self.assertTrue(all(m.value == "0,00" for m in meses))
        self.assertTrue(all(v.value == "0,00" for v in valores))
        self.assertEqual(app.metric[0].value, "R$ 0,00")

    def test_editar_meses_recalcula_valor_sem_atraso(self) -> None:
        app = _renderiza_conteudo("anulacao")
        meses = [ti for ti in app.text_input if ti.label == "Meses a Anular"]
        meses[0].set_value("2").run()

        self.assertEqual(len(app.exception), 0)
        valores = [ti for ti in app.text_input if ti.label == "ANULAR (R$)"]
        # valor_mensal da linha 0 no fixture sintético é 15750.0 -> 2 meses = 31500.0, com
        # pontuação de milhar (pedido explícito) já aplicada no próprio campo.
        self.assertEqual(valores[0].value, "31.500,00")
        self.assertEqual(app.metric[0].value, "R$ 31.500,00")
        # "Meses" também reformata (pedido explícito: pontuação correta nas duas colunas).
        meses2 = [ti for ti in app.text_input if ti.label == "Meses a Anular"]
        self.assertEqual(meses2[0].value, "2,00")

    def test_editar_valor_direto_nao_mexe_em_meses_e_persiste(self) -> None:
        app = _renderiza_conteudo("anulacao")
        valores = [ti for ti in app.text_input if ti.label == "ANULAR (R$)"]
        valores[1].set_value("999").run()

        self.assertEqual(len(app.exception), 0)
        meses = [ti for ti in app.text_input if ti.label == "Meses a Anular"]
        valores2 = [ti for ti in app.text_input if ti.label == "ANULAR (R$)"]
        self.assertEqual(meses[1].value, "0,00")
        self.assertEqual(valores2[1].value, "999,00")

        # editar "Meses" de novo na MESMA linha ainda sobrescreve o valor digitado direto.
        meses[1].set_value("1").run()
        valores3 = [ti for ti in app.text_input if ti.label == "ANULAR (R$)"]
        # valor_mensal da linha 1 no fixture sintético é 2500.0
        self.assertEqual(valores3[1].value, "2.500,00")

    def test_editar_valor_direto_aplica_pontuacao_de_milhar(self) -> None:
        """Pedido explícito: pontuação correta também quando o valor é digitado direto (não só
        quando vem do recálculo por "Meses") — "123456,7" (sem separador de milhar, como
        alguém digitaria de corrido) vira "123.456,70" assim que o campo perde o foco."""

        app = _renderiza_conteudo("anulacao")
        valores = [ti for ti in app.text_input if ti.label == "ANULAR (R$)"]
        valores[0].set_value("123456,7").run()

        self.assertEqual(len(app.exception), 0)
        valores2 = [ti for ti in app.text_input if ti.label == "ANULAR (R$)"]
        self.assertEqual(valores2[0].value, "123.456,70")


if __name__ == "__main__":
    unittest.main()
