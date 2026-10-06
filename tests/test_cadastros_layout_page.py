"""Testes de página da repaginação dos cadastros de Contratos Contínuos e de Bolsas e Auxílios
(05/10/2026: "muita cara de planilha" — cartão-resumo, registro em tabela e edição em janela).

Usa o cadastro nativo real (`data/contratos_continuos/`, `data/bolsas_auxilios/`), como
`tests/test_ui_relatorio_reforco_empenho.py` — pulado se a base não existir. A regra de negócio
(necessidade, vigência, gravação) tem testes próprios; aqui só se confere que a tela nova carrega sem
erro, mostra o registro e abre as janelas de edição, de remoção e de cadastro novo com o conteúdo
esperado, SEM gravar nada (nenhum clique em "Salvar"/"Remover"/"Adicionar").

Limitação de `AppTest` (a mesma explicada em `tests/test_ui_relatorio_reforco_empenho.py`): só a
PRIMEIRA invocação de um `@st.dialog` — a que reage ao clique que o abre — é executada; interações
dentro da janela já aberta não são alcançáveis. Por isso o que se testa são as janelas ao abrir.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests._apptest import TEMPO_LIMITE_APPTEST, aquecer_pagina

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIRETORIO_CONTINUOS = Path("data/contratos_continuos")
DIRETORIO_BOLSAS = Path("data/bolsas_auxilios")
MANIFESTO_EXECUCAO = Path("data/manifestos/execucao_mensal_atual.json")


def _tem_cadastro(diretorio: Path) -> bool:
    return diretorio.exists() and any(item.is_dir() for item in diretorio.iterdir())


def _html(app: AppTest) -> str:
    return " ".join(m.value for m in app.markdown)


class _BaseCadastroLayout:
    """Casos comuns às duas páginas; a subclasse define a página e os prefixos de chave."""

    PAGINA: str
    PREFIXO: str  # "cc" ou "bls"
    SECOES_EDICAO: tuple[str, ...]
    TITULO_REGISTRO: str

    @classmethod
    def setUpClass(cls) -> None:
        # 1ª carga lê os .xlsx reais (~40 s a frio): aquece uma vez, fora dos testes cronometrados
        aquecer_pagina(str(PROJECT_ROOT / "app_pages" / cls.PAGINA))

    def _abrir(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app_pages" / self.PAGINA), default_timeout=TEMPO_LIMITE_APPTEST)
        app.run()
        return app

    def _botoes(self, app: AppTest, prefixo: str) -> list:
        return [b for b in app.button if b.key and b.key.startswith(f"{self.PREFIXO}_{prefixo}_")]

    def test_pagina_carrega_com_resumo_e_registro(self) -> None:
        app = self._abrir()
        self.assertEqual(len(app.exception), 0)
        html = _html(app)
        self.assertIn("cad-resumo", html)  # cartão-resumo com faixa e indicadores
        self.assertIn("cad-faixa", html)
        self.assertIn(self.TITULO_REGISTRO, html)
        self.assertGreater(html.count("cad-principal"), 0)  # ao menos uma linha no registro
        self.assertGreater(html.count("cad-chip"), 0)  # situação em chip

    def test_cada_linha_tem_acoes_de_editar_e_remover(self) -> None:
        app = self._abrir()
        editar = self._botoes(app, "editar")
        remover = self._botoes(app, "remover")
        self.assertGreater(len(editar), 0)
        self.assertEqual(len(editar), len(remover))

    def test_editar_abre_a_janela_em_secoes_sem_erro(self) -> None:
        app = self._abrir()
        self._botoes(app, "editar")[0].click().run()
        self.assertEqual(len(app.exception), 0)
        html = _html(app)
        for secao in self.SECOES_EDICAO:
            self.assertIn(secao, html)
        self.assertTrue(any(b.key and b.key.endswith("_salvar") for b in app.button))
        self.assertTrue(any(b.key and b.key.endswith("_cancelar") for b in app.button))

    def test_remover_abre_a_confirmacao_sem_remover(self) -> None:
        app = self._abrir()
        self._botoes(app, "remover")[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(b.key and "_remover_confirmar_" in b.key for b in app.button))
        self.assertTrue(any(b.key and "_remover_cancelar_" in b.key for b in app.button))

    def _linhas_com_linha_do_tempo(self, app: AppTest) -> int:
        return len([b for b in app.button if b.key and b.key.startswith(f"{self.PREFIXO}_resumo_tempo_")])

    def _avisos_linha_do_tempo(self, app: AppTest) -> list[str]:
        return [c.value for c in app.caption if "linha do tempo mensal" in c.value]

    def test_aviso_da_linha_do_tempo_so_aparece_sem_linhas_clicaveis(self) -> None:
        app = self._abrir()
        clicaveis = self._linhas_com_linha_do_tempo(app)
        avisos = self._avisos_linha_do_tempo(app)
        # regra: ou há linhas clicáveis e NENHUM aviso, ou não há e o aviso explica
        self.assertEqual(bool(avisos), clicaveis == 0)

    def test_secoes_analiticas_usam_o_layout_novo(self) -> None:
        # 05/10/2026: Resumo Consolidado, Empenhado × Liquidado (só Contratos) e Cobertura por PTRES no mesmo
        # desenho dos cadastros — cartão com kicker/título/destaque e tabela
        app = self._abrir()
        self.assertEqual(len(app.exception), 0)
        html = _html(app)
        self.assertIn("RESUMO CONSOLIDADO", html)
        self.assertIn("cad-cartao-kicker", html)
        if "Cobertura orçamentária por PTRES" in html:  # depende da Dotação Anual estar importada
            self.assertIn("AÇÃO DE GOVERNO", html)
            self.assertGreater(html.count("cad-tabela"), 0)
        for classe_antiga in ("cc-resumo", "cc-dotacao", "bls-resumo", "bls-dotacao"):
            self.assertNotIn(classe_antiga, html)

    def test_resumo_tem_o_botao_de_icone_da_linha_do_tempo_e_ele_abre(self) -> None:
        app = self._abrir()
        botoes = [b for b in app.button if b.key and b.key.startswith(f"{self.PREFIXO}_resumo_tempo_")]
        if not botoes:
            self.skipTest("Nenhuma NE com linha do tempo na base atual")
        botoes[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("linha do tempo", _html(app).lower())

    def test_novo_abre_o_formulario_em_janela(self) -> None:
        app = self._abrir()
        novo = [b for b in app.button if b.key and b.key.startswith(f"{self.PREFIXO}_novo_")]
        self.assertEqual(len(novo), 1)
        novo[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("cad-secao-dialogo", _html(app))


@unittest.skipUnless(
    _tem_cadastro(DIRETORIO_CONTINUOS) and MANIFESTO_EXECUCAO.exists(),
    f"Base ausente em {DIRETORIO_CONTINUOS} ou manifesto em {MANIFESTO_EXECUCAO}",
)
class TestLayoutContratosContinuos(_BaseCadastroLayout, unittest.TestCase):
    PAGINA = "contratos_continuos.py"
    PREFIXO = "cc"
    TITULO_REGISTRO = "Registro de contratos"
    SECOES_EDICAO = ("Identificação", "Período de execução", "Classificação orçamentária", "Empenho e valores", "Itens de licitação")

    def test_busca_que_so_acha_contrato_sem_ne_explica_a_linha_do_tempo(self) -> None:
        # contrato SEM NE vira texto simples no Resumo Consolidado; se a busca isola só esses, a tela diz por quê
        from src.contratos_continuos_cadastro import anos_disponiveis, carregar_contratos, como_dataframe

        ano = max(anos_disponiveis())
        cadastro = como_dataframe(carregar_contratos(ano))
        sem_ne = cadastro[cadastro["ne_curta"].isna() & cadastro["contrato_numero"].notna()]
        unicos = [n for n in sem_ne["contrato_numero"] if int((cadastro["contrato_numero"] == n).sum()) == 1]
        if not unicos:
            self.skipTest("Nenhum contrato sem NE (e de número único) na base atual")
        app = self._abrir()
        campo = next(t for t in app.text_input if t.key == f"contratos_continuos_busca_{ano}")
        campo.set_value(unicos[0]).run()
        self.assertEqual(len(app.exception), 0)
        if self._linhas_com_linha_do_tempo(app) > 0:
            self.skipTest("A busca também achou contratos com NE")
        avisos = self._avisos_linha_do_tempo(app)
        self.assertGreaterEqual(len(avisos), 1)
        self.assertIn("Execução Mensal", avisos[0])

    def test_empenhado_x_liquidado_no_layout_novo(self) -> None:
        app = self._abrir()
        html = _html(app)
        self.assertIn("EMPENHADO × LIQUIDADO", html)
        self.assertIn("Sobra ou Insuficiência no Empenho, por NE", html)
        self.assertIn("cad-saldo", html)  # saldo com o chip Sobra/Insuficiência

    def test_janela_traz_vigencia_e_inicio_da_execucao(self) -> None:
        app = self._abrir()
        self._botoes(app, "editar")[0].click().run()
        datas = [d.key for d in app.date_input if d.key]
        self.assertTrue(any(chave.endswith("_vigencia") for chave in datas))
        self.assertTrue(any(chave.endswith("_inicio_data") for chave in datas))


@unittest.skipUnless(
    _tem_cadastro(DIRETORIO_BOLSAS) and MANIFESTO_EXECUCAO.exists(),
    f"Base ausente em {DIRETORIO_BOLSAS} ou manifesto em {MANIFESTO_EXECUCAO}",
)
class TestLayoutBolsasAuxilios(_BaseCadastroLayout, unittest.TestCase):
    PAGINA = "bolsas_auxilios.py"
    PREFIXO = "bls"
    TITULO_REGISTRO = "Registro de programas"
    SECOES_EDICAO = ("Identificação", "Classificação orçamentária", "Quantidade e valores", "Empenho e execução")

    def _abrir_exercicio(self, ano: int) -> AppTest | None:
        app = self._abrir()
        botao = next((b for b in app.button if b.key == f"bls_ano_{ano}"), None)
        if botao is None:
            return None
        botao.click().run()
        return app

    def test_exercicio_com_ne_abre_a_linha_do_tempo_e_nao_mostra_aviso(self) -> None:
        app = self._abrir_exercicio(2026)
        if app is None or self._linhas_com_linha_do_tempo(app) == 0:
            self.skipTest("Exercício 2026 sem NE na base atual")
        self.assertEqual(self._avisos_linha_do_tempo(app), [])
        self._botao_resumo(app).click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("linha do tempo", _html(app).lower())

    def test_exercicio_sem_ne_explica_por_que_nao_ha_linha_do_tempo(self) -> None:
        # 2027 (criado por duplicação, sem NE ainda): as linhas do Resumo viram texto simples, e a tela diz por quê
        app = self._abrir_exercicio(2027)
        if app is None or self._linhas_com_linha_do_tempo(app) > 0:
            self.skipTest("Exercício 2027 ausente ou já com NE na base atual")
        avisos = self._avisos_linha_do_tempo(app)
        self.assertEqual(len(avisos), 1)
        self.assertIn("Execução Mensal", avisos[0])

    def _botao_resumo(self, app: AppTest):
        return next(b for b in app.button if b.key and b.key.startswith("bls_resumo_tempo_"))


if __name__ == "__main__":
    unittest.main()
