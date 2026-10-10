"""Testes do painel Streamlit de Emendas com fontes controladas."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests._apptest import TEMPO_LIMITE_APPTEST

from src.acompanhamento_emendas import cancelar_status, definir_complemento, registrar_status
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

    def _open_page(self, abrir: tuple[str, ...] = (), anos: list[str] | None = None) -> AppTest:
        """Página com as fontes controladas. `abrir`: chaves ("2026_6_202632990006") cujo "Detalhes" é clicado;
        `anos=[]` = filtro de Exercício limpo (toda a base)."""

        with _sessao(self._ajustes_dir, self._ajustes_dir.parent / "acompanhamento", anos) as app:
            for chave in abrir:
                next(b for b in app.button if b.key == f"em_detalhe_{chave}").click().run()
        return app

    def test_renderiza_base_real_sem_emendas_ficticias(self) -> None:
        app = self._open_page(anos=[])  # filtro limpo: toda a base, como antes do filtro padrão de 2026+

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Emendas Parlamentares")
        self.assertEqual(
            [metrica.label for metrica in app.metric],
            ["Emendas", "Dotação atualizada", "Empenhado", "Liquidado", "Pago"],
        )
        self.assertEqual(app.metric[0].value, "25")
        linhas = [item.value for item in app.markdown if 'class="cad-principal"' in item.value]
        self.assertEqual(len(linhas), 25)  # uma linha por emenda no registro compacto
        self.assertTrue(any("202632990006" in linha for linha in linhas))
        self.assertFalse(any("Dep. Marcos Aurélio" in linha for linha in linhas))
        # os cartões só abrem sob demanda ("Detalhes")
        self.assertEqual([item for item in app.markdown if 'class="em-card"' in item.value], [])

    def test_abre_no_exercicio_vigente_com_o_historico_a_um_clique(self) -> None:
        app = self._open_page()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(next(m for m in app.multiselect if m.label == "Exercício").value, ["2026"])
        self.assertEqual(app.metric[0].value, "5")  # as 5 emendas de 2026
        self.assertEqual(next(m for m in app.metric if m.label == "Dotação atualizada").value, "R$ 3.560.000,00")
        linhas = [item.value for item in app.markdown if 'class="cad-principal"' in item.value]
        self.assertEqual(len(linhas), 5)
        self.assertTrue(
            any("20 emenda(s) de exercícios anteriores a 2026 ocultas" in c.value for c in app.caption),
            [c.value for c in app.caption],
        )

    def test_expoe_historico_no_filtro_e_na_legenda(self) -> None:
        app = self._open_page(anos=[])

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
        app = self._open_page(abrir=("2026_6_202632990006",))
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
        app = self._open_page(abrir=("2026_6_202632990006",))
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
        ano, rp, numero = next(c for c in _chaves_validas() if c[0] == 2025)
        app = self._open_page(anos=[], abrir=(f"{ano}_{rp}_{numero}",))
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
def _sessao(ajustes_dir: Path, acompanhamento_dir: Path | None = None, anos_filtro: list[str] | None = None):
    """Página aberta com as fontes controladas e o diretório de decisões trocado por `ajustes_dir`. Os patches
    ficam ATIVOS durante todo o `with`: a página relê cadastros e eventos a cada execução (cliques incluídos).
    `anos_filtro=[]` simula o filtro de Exercício limpo (toda a base, histórico incluído); sem ele a página abre no
    padrão novo: só 2026 em diante."""

    relatorio, execucao, dotacao = _fontes()
    st.cache_data.clear()
    with ExitStack() as pilha:
        pilha.enter_context(patch("src.importacao_dotacao.carregar_atual", return_value=dotacao))
        pilha.enter_context(patch("src.importacao_emendas.carregar_atual", return_value=relatorio))
        pilha.enter_context(patch("src.importacao_execucao.carregar_atual", return_value=execucao))
        pilha.enter_context(patch("src.emendas_parlamentares.carregar_emendas_cadastradas", return_value=[]))
        pilha.enter_context(patch("src.vinculos_emendas.carregar_eventos_vinculo", return_value=[]))
        pilha.enter_context(patch("src.ajustes_dotacao_emendas.DIRETORIO_AJUSTES", ajustes_dir))
        pilha.enter_context(
            patch("src.acompanhamento_emendas.DIRETORIO_ACOMPANHAMENTO", acompanhamento_dir or ajustes_dir.parent / "acomp_vazio")
        )
        app = AppTest.from_file(
            str(PROJECT_ROOT / "app_pages" / "emendas_parlamentares.py"), default_timeout=TEMPO_LIMITE_APPTEST
        )
        if anos_filtro is not None:
            app.session_state["emendas_filtro_ano"] = anos_filtro
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
            self.assertEqual(total.value, "R$ 3.794.567,00")  # 3.560.000,00 (2026+) + (1.234.567,00 − 1.000.000,00)
            registro = " ".join(m.value for m in app.markdown if "cad-" in m.value)
            self.assertIn("Dotação decidida", registro)  # chip na linha
            next(b for b in app.button if b.key == "em_detalhe_2026_6_202632990006").click().run()
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
            self.assertEqual(total.value, "R$ 3.560.000,00")  # o valor novo do relatório (2026+), sem ajuste

    def test_evento_corrompido_mostra_erro_explicito_sem_exceção(self) -> None:
        self.dir.mkdir(parents=True)
        (self.dir / "quebrado.json").write_text("{ isto nao e json", encoding="utf-8")
        with _sessao(self.dir) as app:
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("decisão de dotação" in e.value for e in app.error), [e.value for e in app.error])


# ------------------------------------------------------------------ acompanhamento (10/2026)

E_2026 = (2026, "6", "202632990006")
E_2024 = (2024, "6", "202438130004")  # histórico: o acompanhamento vale para qualquer exercício


def _chaves_validas() -> set[tuple]:
    relatorio, _, _ = _fontes()
    return {(int(r.ano), str(r.resultado_primario_cod), str(r.emenda_numero)) for r in relatorio.itertuples()}


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Fixture ausente em {CAMINHO_BASE}")
@unittest.skipUnless(MANIFESTO_EMENDAS.exists(), f"Manifesto ausente em {MANIFESTO_EMENDAS}")
class EmendasAcompanhamentoPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ajustes = Path(self._tmp.name) / "ajustes"
        self.acomp = Path(self._tmp.name) / "acompanhamento"

    def _sessao(self, anos=None):
        return _sessao(self.ajustes, self.acomp, anos)

    @contextmanager
    def _aberta(self, *chaves_texto: str, anos=None):
        """Sessão com o "Detalhes" das emendas indicadas já aberto (o acompanhamento mora no detalhe)."""

        with _sessao(self.ajustes, self.acomp, anos) as app:
            for chave in chaves_texto:
                next(b for b in app.button if b.key == f"em_detalhe_{chave}").click().run()
            yield app

    def _status(self, chave=E_2026, status="Em análise técnica", data=date(2026, 8, 12), observacao=None) -> dict:
        return registrar_status(
            chave=chave, status=status, status_outro=None, data_status=data, observacao=observacao, responsavel="Maria",
            chaves_validas=_chaves_validas(), hoje=date(2026, 10, 10), diretorio=self.acomp,
        )

    @staticmethod
    def _chave_texto(chave: tuple) -> str:
        return f"{chave[0]}_{chave[1]}_{chave[2]}"

    def test_cada_emenda_tem_acoes_de_acompanhamento_inclusive_as_historicas(self) -> None:
        with self._aberta(self._chave_texto(E_2024), self._chave_texto(E_2026), anos=[]) as app:
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(_botoes(app, "em_detalhe_")), 25)  # todas as emendas têm "Detalhes"
            for chave in (E_2024, E_2026):  # histórico (2024) e vigente (2026): o acompanhamento vale para os dois
                self.assertIn(f"em_status_{self._chave_texto(chave)}", [b.key for b in app.button])
                self.assertIn(f"em_complemento_{self._chave_texto(chave)}", [b.key for b in app.button])
            self.assertTrue(any(e.label.startswith("Acompanhamento") for e in app.expander))
            texto = " ".join(m.value for m in app.markdown)
            self.assertIn("não informado", texto)  # objeto/destinatário ausentes

    def test_status_atual_aparece_no_cartao_e_o_historico_na_secao(self) -> None:
        self._status(status="Em análise técnica", data=date(2026, 8, 12))
        self._status(status="Proposta aceita", data=date(2026, 9, 1), observacao="Parecer favorável.")
        with self._aberta(self._chave_texto(E_2026)) as app:
            self.assertEqual(len(app.exception), 0)
            self.assertIn("Tramitação: Proposta aceita", " ".join(m.value for m in app.markdown if "cad-" in m.value))
            cartao = next(m.value for m in app.markdown if 'class="em-card"' in m.value and "202632990006" in m.value)
            self.assertIn("Tramitação: Proposta aceita", cartao)
            texto = " ".join(m.value for m in app.markdown)
            for esperado in ("Em análise técnica", "Proposta aceita", "12/08/2026", "01/09/2026", "Maria", "Parecer favorável."):
                self.assertIn(esperado, texto)

    def test_registro_cancelado_fica_no_historico_e_nao_e_o_status_atual(self) -> None:
        self._status(status="Em análise técnica", data=date(2026, 8, 12))
        errado = self._status(status="Paga", data=date(2026, 9, 1))
        cancelar_status(evento_id=errado["evento_id"], motivo="Registrado por engano em outra emenda.", responsavel="João", diretorio=self.acomp)
        with self._aberta(self._chave_texto(E_2026)) as app:
            cartao = next(m.value for m in app.markdown if 'class="em-card"' in m.value and "202632990006" in m.value)
            self.assertIn("Tramitação: Em análise técnica", cartao)
            texto = " ".join(m.value for m in app.markdown)
            self.assertIn("Registrado por engano em outra emenda.", texto)
            self.assertIn("cancelado", texto)
            self.assertEqual(  # só o registro ativo tem "Cancelar registro"
                [b.key for b in _botoes(app, "em_cancelar_status_")], [f"em_cancelar_status_{self._primeiro_ativo()}"]
            )

    def _primeiro_ativo(self) -> str:
        from src.acompanhamento_emendas import carregar_eventos, reconstruir_tramitacao

        tramitacao = reconstruir_tramitacao(carregar_eventos(self.acomp))
        return str(tramitacao[~tramitacao["cancelado"]].iloc[0]["evento_id"])

    def test_janela_registrar_status_abre_com_os_campos_e_nao_grava(self) -> None:
        with self._aberta(self._chave_texto(E_2026)) as app:
            next(b for b in app.button if b.key == f"em_status_{self._chave_texto(E_2026)}").click().run()
            self.assertEqual(len(app.exception), 0)
            seletor = next(sb for sb in app.selectbox if sb.label == "Status")
            self.assertIn("Outro", seletor.options)
            self.assertIn("Em análise técnica", seletor.options)
            self.assertIn("Data do status", [d.label for d in app.date_input])
            self.assertIn("Observação", [t.label for t in app.text_area])
            self.assertIn("Responsável", [t.label for t in app.text_input])
        self.assertEqual(list(self.acomp.glob("*.json")) if self.acomp.exists() else [], [])

    def test_objeto_e_destinatario_aparecem_e_a_janela_traz_os_valores_atuais(self) -> None:
        definir_complemento(
            chave=E_2026, objeto="Aquisição de equipamentos de laboratório", destinatario="Pró-Reitoria de Pesquisa",
            responsavel="Maria", motivo=None, chaves_validas=_chaves_validas(), diretorio=self.acomp,
        )
        with self._aberta(self._chave_texto(E_2026)) as app:
            texto = " ".join(m.value for m in app.markdown)
            self.assertIn("Aquisição de equipamentos de laboratório", texto)
            self.assertIn("Pró-Reitoria de Pesquisa", texto)
            next(b for b in app.button if b.key == f"em_complemento_{self._chave_texto(E_2026)}").click().run()
            self.assertEqual(len(app.exception), 0)
            objeto = next(t for t in app.text_area if t.label == "Objeto")
            destinatario = next(t for t in app.text_input if t.label == "Destinatário")
            self.assertEqual(objeto.value, "Aquisição de equipamentos de laboratório")
            self.assertEqual(destinatario.value, "Pró-Reitoria de Pesquisa")

    def test_registros_de_emenda_inexistente_sao_listados_como_orfaos(self) -> None:
        registrar_status(
            chave=(2026, "6", "EMENDA-QUE-SUMIU"), status="Indicada", status_outro=None, data_status=date(2026, 7, 1),
            observacao=None, responsavel="Maria", chaves_validas={(2026, "6", "EMENDA-QUE-SUMIU")},
            hoje=date(2026, 10, 10), diretorio=self.acomp,
        )
        with self._sessao() as app:
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any(e.label.startswith("Registros sem emenda correspondente") for e in app.expander))
            self.assertIn("EMENDA-QUE-SUMIU", " ".join(m.value for m in app.markdown))

    def test_evento_corrompido_mostra_erro_explicito_sem_excecao(self) -> None:
        self.acomp.mkdir(parents=True)
        (self.acomp / "quebrado.json").write_text("{ isto nao e json", encoding="utf-8")
        with self._sessao() as app:
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("acompanhamento" in e.value for e in app.error), [e.value for e in app.error])

    def test_cadastro_manual_tem_o_campo_destinatario(self) -> None:
        with self._sessao() as app:
            next(b for b in app.button if b.label == "Cadastrar emenda").click().run()
            self.assertEqual(len(app.exception), 0)
            rotulos = [t.label for t in app.text_input]
            self.assertIn("Destinatário (opcional)", rotulos)
            self.assertIn("Objeto ou observação", [t.label for t in app.text_area])


# ------------------------------------------------------------------ registro compacto e novo visual (10/2026)


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Fixture ausente em {CAMINHO_BASE}")
@unittest.skipUnless(MANIFESTO_EMENDAS.exists(), f"Manifesto ausente em {MANIFESTO_EMENDAS}")
class EmendasRegistroPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ajustes = Path(self._tmp.name) / "ajustes"
        self.acomp = Path(self._tmp.name) / "acompanhamento"

    @contextmanager
    def _aberta(self, *chaves_texto: str, anos=None):
        with _sessao(self.ajustes, self.acomp, anos) as app:
            for chave in chaves_texto:
                next(b for b in app.button if b.key == f"em_detalhe_{chave}").click().run()
            yield app

    @staticmethod
    def _celulas_da_linha(app: AppTest, numero: str) -> list[str]:
        """As 7 células (HTML) da linha da emenda `numero`, na ordem das colunas do registro."""

        valores = [m.value for m in app.markdown]
        posicao = next(i for i, v in enumerate(valores) if 'class="cad-principal"' in v and numero in v)
        return valores[posicao : posicao + 7]

    def test_situacao_aguardando_execucao_nao_e_vermelha_e_divergencia_e_aviso(self) -> None:
        with self._aberta() as app:
            html = " ".join(m.value for m in app.markdown)
            self.assertIn("Aguardando execução", html)
            self.assertIn("cad-chip info", html)
            self.assertIn("Divergência de dotação", html)  # a emenda 202632990006 (1.000.000 × 1.234.567)
            self.assertIn("cad-chip warn", html)
            self.assertNotIn("cad-chip bad", html)  # nenhum problema "real" classificado como erro neste cenário

    def test_barra_de_execucao_mostra_empenhado_sobre_dotacao_e_nulo_nao_vira_zero(self) -> None:
        with self._aberta() as app:
            executada = self._celulas_da_linha(app, "202632990006")[3]
            self.assertIn("width:100%", executada)  # 1.000.000 empenhado de 1.000.000 de dotação
            self.assertIn("cheia", executada)
            sem_execucao = self._celulas_da_linha(app, "202641750010")[3]
            self.assertIn("width:0%", sem_execucao)
            self.assertIn("—", sem_execucao)  # empenhado nulo: "—", não "R$ 0,00"
            self.assertNotIn("R$ 0,00", sem_execucao)

    def test_detalhes_abre_e_fecha_o_cartao_na_propria_linha(self) -> None:
        with self._aberta() as app:
            chave = "em_detalhe_2026_6_202632990006"
            botao = next(b for b in app.button if b.key == chave)
            self.assertEqual(botao.label, "Detalhes")
            self.assertEqual([m for m in app.markdown if 'class="em-card"' in m.value], [])
            botao.click().run()
            self.assertEqual(len([m for m in app.markdown if 'class="em-card"' in m.value]), 1)
            self.assertEqual(next(b for b in app.button if b.key == chave).label, "Fechar")
            next(b for b in app.button if b.key == chave).click().run()
            self.assertEqual([m for m in app.markdown if 'class="em-card"' in m.value], [])
            self.assertEqual(next(b for b in app.button if b.key == chave).label, "Detalhes")

    def test_emenda_com_um_ptres_nao_repete_a_tabela_e_com_varios_mostra(self) -> None:
        with self._aberta("2026_6_202641750010", "2026_6_202632990006") as app:
            cartoes = {
                numero: next(m.value for m in app.markdown if 'class="em-card"' in m.value and numero in m.value)
                for numero in ("202641750010", "202632990006")
            }
            self.assertNotIn('class="em-scroll"', cartoes["202641750010"])  # um PTRES: sem tabela repetida
            self.assertIn("PTRES 261463", cartoes["202641750010"])  # o código do PTRES continua visível
            self.assertIn('class="em-scroll"', cartoes["202632990006"])  # dois PTRES: tabela por PTRES

    def test_linha_e_filtro_de_tramitacao(self) -> None:
        registrar_status(
            chave=E_2026, status="Proposta aceita", status_outro=None, data_status=date(2026, 9, 1), observacao=None,
            responsavel="Maria", chaves_validas=_chaves_validas(), hoje=date(2026, 10, 10), diretorio=self.acomp,
        )
        with self._aberta() as app:
            self.assertIn("Tramitação: Proposta aceita", self._celulas_da_linha(app, "202632990006")[6])
            self.assertIn("Tramitação: —", self._celulas_da_linha(app, "202641750010")[6])  # sem status: "—"
            filtro = next(m for m in app.multiselect if m.label == "Tramitação")
            self.assertEqual(sorted(filtro.options), ["Proposta aceita", "Sem status"])
            filtro.select("Proposta aceita").run()
            self.assertEqual(app.metric[0].value, "1")
            linhas = [m.value for m in app.markdown if 'class="cad-principal"' in m.value]
            self.assertEqual(len(linhas), 1)
            self.assertIn("202632990006", linhas[0])

    def test_totais_do_registro_sao_os_mesmos_da_base_sem_filtro(self) -> None:
        with self._aberta(anos=[]) as app:
            self.assertEqual(app.metric[0].value, "25")
            self.assertEqual(next(m for m in app.metric if m.label == "Dotação atualizada").value, "R$ 10.525.108,00")
            html = " ".join(m.value for m in app.markdown)
            self.assertIn("25 emenda(s)", html)  # contagem do registro
            self.assertIn("R$ 10.525.108,00 de dotação", html)


if __name__ == "__main__":
    unittest.main()
