"""Testes do painel Streamlit de Emendas com fontes controladas."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests._apptest import TEMPO_LIMITE_APPTEST

from src.ajustes_dotacao_emendas import desfazer_decisao, registrar_decisao
from src.emendas_parlamentares import vincular_execucao_emendas
from src.importacao_emendas import Manifesto as ManifestoEmendas
from src.tesouro_emendas_acompanhamento import ler_emendas_acompanhamento


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMINHO_BASE = Path("tests/fixtures/emendas_acompanhamento_2026-08-28.xlsx")
MANIFESTO_EMENDAS = Path("data/manifestos/emendas_acompanhamento_atual.json")


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Fixture ausente em {CAMINHO_BASE}")
@unittest.skipUnless(MANIFESTO_EMENDAS.exists(), f"Manifesto ausente em {MANIFESTO_EMENDAS}")
class EmendasParlamentaresPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_ajustes = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_ajustes.cleanup)
        self._ajustes_dir = Path(self._tmp_ajustes.name) / "ajustes"

    def _open_page(self) -> AppTest:
        relatorio = ler_emendas_acompanhamento(CAMINHO_BASE)
        execucao = pd.DataFrame(
            [
                {
                    "ano": 2026,
                    "resultado_primario_cod": "6",
                    "ptres": "269202",
                    "empenhada": 1_000_000.0,
                    "liquidada": pd.NA,
                    "paga": pd.NA,
                },
                {
                    "ano": 2026,
                    "resultado_primario_cod": "6",
                    "ptres": "267239",
                    "empenhada": 209_000.0,
                    "liquidada": 209_000.0,
                    "paga": 209_000.0,
                },
            ]
        )
        dotacao = pd.DataFrame(
            [
                {
                    "ano_lancamento": 2026,
                    "resultado_primario_codigo": "6",
                    "ptres_codigo": "269202",
                    "item_informacao_codigo": "dotacao_atualizada",
                    "valor_movimento_liquido": 1_234_567.0,
                }
            ]
        )
        st.cache_data.clear()
        with (
            patch("src.importacao_dotacao.carregar_atual", return_value=dotacao),
            patch("src.importacao_emendas.carregar_atual", return_value=relatorio),
            patch("src.importacao_execucao.carregar_atual", return_value=execucao),
            patch(
                "src.emendas_parlamentares.carregar_emendas_cadastradas",
                return_value=[],
            ),
            patch(
                "src.vinculos_emendas.carregar_eventos_vinculo",
                return_value=[],
            ),
            patch("src.ajustes_dotacao_emendas.DIRETORIO_AJUSTES", self._ajustes_dir),
        ):
            app = AppTest.from_file(
                str(PROJECT_ROOT / "app_pages" / "emendas_parlamentares.py"), default_timeout=TEMPO_LIMITE_APPTEST
            )
            app.run()
        return app

    def test_renderiza_base_real_sem_emendas_ficticias(self) -> None:
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Emendas Parlamentares")
        self.assertEqual(
            [metrica.label for metrica in app.metric],
            ["Emendas", "Dotação atualizada", "Empenhado", "Liquidado", "Pago"],
        )
        self.assertEqual(app.metric[0].value, "25")
        cartoes = [item.value for item in app.markdown if 'class="em-card"' in item.value]
        self.assertEqual(len(cartoes), 25)
        self.assertTrue(any("202632990006" in cartao for cartao in cartoes))
        self.assertFalse(any("Dep. Marcos Aurélio" in cartao for cartao in cartoes))

    def test_expoe_historico_no_filtro_e_na_legenda(self) -> None:
        app = self._open_page()

        filtro_ano = next(
            item for item in app.multiselect if item.label == "Exercício"
        )
        self.assertEqual(
            list(filtro_ano.options),
            ["2016", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"],
        )
        self.assertEqual(app.tabs, [])
        self.assertTrue(
            any("anteriores a 2026 permanecem estáticos" in item.value for item in app.caption)
        )

    def test_emenda_2026_recebe_execucao_pelo_ptres(self) -> None:
        app = self._open_page()
        cartao = next(
            item.value
            for item in app.markdown
            if 'class="em-card"' in item.value and "202632990006" in item.value
        )

        self.assertIn("261462", cartao)
        self.assertIn("269202", cartao)
        self.assertIn("R$ 1.000.000,00", cartao)
        self.assertIn("Execução parcial", cartao)

    def test_dotacao_anual_por_ptres_aparece_ao_lado_da_dotacao_do_relatorio(self) -> None:
        app = self._open_page()
        self.assertEqual(len(app.exception), 0)
        cartao = next(
            item.value
            for item in app.markdown
            if 'class="em-card"' in item.value and "202632990006" in item.value
        )

        self.assertIn("Dotação Anual (por PTRES)", cartao)
        self.assertIn("R$ 1.234.567,00", cartao)
        self.assertIn("1 de 2 PTRES com dotação", cartao)
        # a dotação do relatório continua exibida, nunca substituída
        self.assertIn("Dotação atualizada", cartao)

    def test_divergencia_de_dotacao_e_listada_com_os_dois_valores_sem_apontar_o_correto(self) -> None:
        app = self._open_page()
        self.assertEqual(len(app.exception), 0)
        titulos = [item.value for item in app.markdown if "Dotação informada ≠ Dotação Anual" in item.value]
        self.assertEqual(len(titulos), 1)
        tabela = app.dataframe[0].value
        self.assertEqual(
            list(tabela.columns),
            ["Exercício", "RP", "Emenda", "Parlamentar", "PTRES",
             "Dotação informada", "Dotação Anual (por PTRES)", "Diferença"],
        )
        self.assertIn("R$ 1.234.567,00", tabela["Dotação Anual (por PTRES)"].tolist())
        self.assertTrue(
            any("sem indicar qual está correto" in item.value for item in app.caption)
        )

    def test_exercicio_historico_nao_mostra_dotacao_anual(self) -> None:
        app = self._open_page()
        cartoes_historicos = [
            item.value
            for item in app.markdown
            if 'class="em-card"' in item.value and "EXERCÍCIO 2025" in item.value
        ]
        self.assertTrue(cartoes_historicos)
        self.assertFalse(any("Dotação Anual (por PTRES)" in c for c in cartoes_historicos))

    def test_procedencia_mostra_hash_da_carga_inicial(self) -> None:
        app = self._open_page()
        manifesto = ManifestoEmendas.atual()

        self.assertTrue(
            any(manifesto.sha256[:8] in item.value for item in app.caption)
        )


# ---------------------------------------------------------------------------- decisão de dotação (10/2026)

CHAVE_DIVERGENCIA = dict(ano=2026, resultado_primario_cod="6", emenda_numero="202632990006", ptres="269202")


def _fontes() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Mesmas fontes controladas de `EmendasParlamentaresPageTests._open_page`: a emenda 202632990006 tem R$ 1.000.000,00
    no PTRES 269202 no relatório e R$ 1.234.567,00 na Dotação Anual (a única divergência)."""

    relatorio = ler_emendas_acompanhamento(CAMINHO_BASE)
    execucao = pd.DataFrame(
        [
            {"ano": 2026, "resultado_primario_cod": "6", "ptres": "269202", "empenhada": 1_000_000.0,
             "liquidada": pd.NA, "paga": pd.NA},
            {"ano": 2026, "resultado_primario_cod": "6", "ptres": "267239", "empenhada": 209_000.0,
             "liquidada": 209_000.0, "paga": 209_000.0},
        ]
    )
    dotacao = pd.DataFrame(
        [
            {"ano_lancamento": 2026, "resultado_primario_codigo": "6", "ptres_codigo": "269202",
             "item_informacao_codigo": "dotacao_atualizada", "valor_movimento_liquido": 1_234_567.0}
        ]
    )
    return relatorio, execucao, dotacao


def _vinculos_originais() -> pd.DataFrame:
    relatorio, execucao, dotacao = _fontes()
    return vincular_execucao_emendas(relatorio, execucao, dotacao=dotacao).vinculos


@contextmanager
def _sessao(ajustes_dir: Path):
    """Página aberta com as fontes controladas e o diretório de decisões trocado por `ajustes_dir`. Os patches
    ficam ATIVOS durante todo o `with`: a página relê cadastros e eventos a cada execução (cliques incluídos)."""

    relatorio, execucao, dotacao = _fontes()
    st.cache_data.clear()
    with ExitStack() as pilha:
        pilha.enter_context(patch("src.importacao_dotacao.carregar_atual", return_value=dotacao))
        pilha.enter_context(patch("src.importacao_emendas.carregar_atual", return_value=relatorio))
        pilha.enter_context(patch("src.importacao_execucao.carregar_atual", return_value=execucao))
        pilha.enter_context(patch("src.emendas_parlamentares.carregar_emendas_cadastradas", return_value=[]))
        pilha.enter_context(patch("src.vinculos_emendas.carregar_eventos_vinculo", return_value=[]))
        pilha.enter_context(patch("src.ajustes_dotacao_emendas.DIRETORIO_AJUSTES", ajustes_dir))
        app = AppTest.from_file(
            str(PROJECT_ROOT / "app_pages" / "emendas_parlamentares.py"), default_timeout=TEMPO_LIMITE_APPTEST
        )
        app.run()
        yield app


def _botoes(app: AppTest, prefixo: str) -> list:
    return [b for b in app.button if (b.key or "").startswith(prefixo)]


def _conteudo(diretorio: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(diretorio.glob("*.json"))} if diretorio.exists() else {}


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Fixture ausente em {CAMINHO_BASE}")
@unittest.skipUnless(MANIFESTO_EMENDAS.exists(), f"Manifesto ausente em {MANIFESTO_EMENDAS}")
class EmendasDecisaoDotacaoPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "ajustes"

    def _decidir(self, decisao="adotar_dotacao_anual", vinculos=None) -> dict:
        return registrar_decisao(
            vinculos=_vinculos_originais() if vinculos is None else vinculos, **CHAVE_DIVERGENCIA, decisao=decisao,
            valor_informado=None, justificativa="Dotação ampliada conforme a Dotação Anual de 2026.",
            responsavel="Maria", diretorio=self.dir,
        )

    def test_quadro_de_divergencia_tem_botao_resolver(self) -> None:
        with _sessao(self.dir) as app:
            self.assertEqual(len(app.exception), 0)
            resolver = _botoes(app, "em_resolver_")
            self.assertEqual([b.key for b in resolver], ["em_resolver_2026_6_202632990006_269202"])
            self.assertTrue(any("sem indicar qual está correto" in c.value for c in app.caption))

    def test_resolver_abre_janela_com_os_valores_e_as_tres_opcoes_sem_gravar(self) -> None:
        with _sessao(self.dir) as app:
            _botoes(app, "em_resolver_")[0].click().run()
            self.assertEqual(len(app.exception), 0)
            texto = " ".join(m.value for m in app.markdown) + " " + " ".join(c.value for c in app.caption)
            # `$` escapado no markdown (`\\$`): sem isso dois valores no mesmo bloco viram fórmula e o texto quebra
            for esperado in ("R\\$ 1.000.000,00", "R\\$ 1.234.567,00", "R\\$ 234.567,00"):
                self.assertIn(esperado, texto)
            opcoes = app.radio[0].options
            self.assertEqual(len(opcoes), 3)
            self.assertTrue(any("Adotar a Dotação Anual" in o for o in opcoes))
            self.assertTrue(any("Manter o relatório" in o for o in opcoes))
            self.assertTrue(any("Informar outro valor" in o for o in opcoes))
            self.assertIn("Justificativa", [t.label for t in app.text_area])
            self.assertIn("Responsável", [t.label for t in app.text_input])
        self.assertEqual(_conteudo(self.dir), {})  # abrir a janela não grava nada

    def test_decisao_gravada_encerra_o_alerta_marca_o_cartao_e_corrige_o_total(self) -> None:
        self._decidir()
        with _sessao(self.dir) as app:
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(_botoes(app, "em_resolver_"), [])  # nada pendente
            self.assertFalse(any("Dotação informada ≠ Dotação Anual" in m.value for m in app.markdown))
            total = next(m for m in app.metric if m.label == "Dotação atualizada")
            self.assertEqual(total.value, "R$ 10.759.675,00")  # 10.525.108,00 + (1.234.567,00 − 1.000.000,00)
            cartoes = [m.value for m in app.markdown if 'class="em-card"' in m.value]
            decidido = next(c for c in cartoes if "202632990006" in c)
            self.assertIn("dotação decidida", decidido)
            self.assertIn("Relatório: R$ 1.000.000,00", decidido)  # o valor original continua visível

    def test_secao_decisoes_lista_a_decisao_e_oferece_desfazer(self) -> None:
        evento = self._decidir()
        with _sessao(self.dir) as app:
            self.assertEqual([b.key for b in _botoes(app, "em_desfazer_")], [f"em_desfazer_{evento['decisao_id']}"])
            texto = " ".join(m.value for m in app.markdown)
            self.assertIn("Decisões de dotação", " ".join(e.label for e in app.expander) + texto)
            for esperado in ("Maria", "Dotação ampliada conforme a Dotação Anual de 2026.", "Dotação Anual adotada"):
                self.assertIn(esperado, texto)

    def test_decisao_desfeita_volta_a_divergencia_pendente(self) -> None:
        evento = self._decidir()
        desfazer_decisao(decisao_id=evento["decisao_id"], justificativa="Lançamento equivocado, voltando.",
                         responsavel="João", diretorio=self.dir)
        with _sessao(self.dir) as app:
            self.assertEqual(len(_botoes(app, "em_resolver_")), 1)
            self.assertEqual(_botoes(app, "em_desfazer_"), [])  # só ativas/obsoletas têm "Desfazer"

    def test_decisao_obsoleta_avisa_e_nao_e_aplicada(self) -> None:
        antigo = _vinculos_originais()
        antigo.loc[antigo["emenda_numero"].eq("202632990006") & antigo["ptres"].eq("269202"), "dotacao_atualizada"] = 900_000.0
        self._decidir("manter_relatorio", vinculos=antigo)  # a decisão viu R$ 900.000,00; o relatório atual diz R$ 1.000.000,00
        with _sessao(self.dir) as app:
            self.assertEqual(len(_botoes(app, "em_resolver_")), 1)  # a divergência voltou a ser pendente
            avisos = " ".join(c.value for c in app.caption)
            self.assertIn("obsoleta", avisos)
            self.assertIn("R\\$ 900.000,00", avisos)
            self.assertIn("R\\$ 1.000.000,00", avisos)
            total = next(m for m in app.metric if m.label == "Dotação atualizada")
            self.assertEqual(total.value, "R$ 10.525.108,00")  # o valor novo do relatório, sem ajuste

    def test_evento_corrompido_mostra_erro_explicito_sem_exceção(self) -> None:
        self.dir.mkdir(parents=True)
        (self.dir / "quebrado.json").write_text("{ isto nao e json", encoding="utf-8")
        with _sessao(self.dir) as app:
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("decisão de dotação" in e.value for e in app.error), [e.value for e in app.error])


if __name__ == "__main__":
    unittest.main()
