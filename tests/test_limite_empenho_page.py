"""Teste de página do Limite de Empenho — remanejamento entre IDUSOs (28/09/2026).

Bases sintéticas (mesmos construtores de `tests/test_limite_empenho.py`) injetadas no lugar de
`carregar_atual`/`Manifesto.atual`; fração e remanejamentos gravados em diretório temporário —
o teste não toca em `data/manifestos/` nem em `data/limite_empenho/`.
"""

from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.limite_empenho_remanejamentos import carregar_remanejamentos, registrar_remanejamento
from tests._apptest import TEMPO_LIMITE_APPTEST
from tests.test_limite_empenho import _linha_dotacao, _linha_execucao

PAGINA = Path(__file__).resolve().parents[1] / "app_pages" / "limite_empenho.py"


def _dotacao() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _linha_dotacao("100001", "dotacao_atualizada", 1200.0),
            _linha_dotacao(
                "100002", "dotacao_atualizada", 2400.0,
                iduso_codigo="8", iduso_descricao="CONTRAPARTIDA", acao_codigo="20RK",
            ),
        ]
    )


def _execucao() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _linha_execucao("NE001", "100001", 202601, 100.0),
            _linha_execucao("NE002", "100002", 202601, 400.0, iduso_cod="8", acao_cod="20RK"),
        ]
    )


def _textos(app: AppTest) -> str:
    return "\n".join(str(bloco.value) for bloco in app.markdown)


class LimiteEmpenhoRemanejamentoPageTests(unittest.TestCase):
    def setUp(self) -> None:
        st.cache_data.clear()
        diretorio = tempfile.TemporaryDirectory()
        self.addCleanup(diretorio.cleanup)
        self.caminho = Path(diretorio.name) / "remanejamentos.json"
        manifesto = SimpleNamespace(sha256="0" * 64, data_extracao="2026-09-28T10:00:00")
        for alvo, valor in (
            ("src.importacao_dotacao.Manifesto.atual", manifesto),
            ("src.importacao_execucao_mensal.Manifesto.atual", manifesto),
            ("src.importacao_dotacao.carregar_atual", _dotacao()),
            ("src.importacao_execucao_mensal.carregar_atual", _execucao()),
            ("src.limite_empenho_preferencias.carregar_fracao_liberada", (12, 12)),
            ("src.limite_empenho_preferencias.salvar_fracao_liberada", None),
        ):
            patcher = patch(alvo, return_value=valor)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("src.limite_empenho_remanejamentos.CAMINHO_PADRAO", self.caminho)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _app(self) -> AppTest:
        app = AppTest.from_file(str(PAGINA), default_timeout=TEMPO_LIMITE_APPTEST)
        app.run()
        self.assertFalse(app.exception, [e.value for e in app.exception])
        return app

    def test_fracao_salva_em_disco_e_carregada_sem_aviso_de_session_state(self):
        # o campo de fração não pode receber `value=` fixo junto com a chave semeada do disco:
        # o Streamlit registrava "created with a default value but also had its value set via
        # the Session State API" a cada abertura da página (28/09/2026).
        with patch("src.limite_empenho_preferencias.carregar_fracao_liberada", return_value=(9, 12)):
            with self.assertNoLogs("streamlit.elements.lib.policies", level="WARNING"):
                app = self._app()
        numerador = app.number_input(key="limite_empenho_numerador")
        denominador = app.number_input(key="limite_empenho_denominador")
        self.assertEqual((numerador.value, denominador.value), (9, 12))
        self.assertIsInstance(numerador.value, int)

    def test_coleta_lixo_no_inicio_e_no_fim_da_pagina(self):
        # cópias das bases devolvidas pelo st.cache_data ficavam presas em ciclos (~0,25 GB por interação)
        with patch("gc.collect", return_value=0) as coleta:
            self._app()
        self.assertEqual(coleta.call_count, 2)

    def test_sem_remanejamento_resumo_mostra_limite_original(self):
        app = self._app()
        texto = _textos(app)
        self.assertIn("Limite compartilhado <strong>R$", texto)
        self.assertNotIn("ajustado", texto)

    def test_remanejamento_em_vigor_ajusta_resumo_e_pode_ser_desfeito(self):
        registrar_remanejamento(2026, "0", "8", Decimal("300"), "teste", caminho=self.caminho)
        app = self._app()
        texto = _textos(app)
        self.assertIn("Limite compartilhado ajustado", texto)
        self.assertIn("Remanejado <strong>−R$", texto)
        self.assertIn("Remanejado <strong>+R$", texto)

        botoes = [b for b in app.button if b.key and b.key.startswith("le_desfazer_")]
        self.assertEqual(len(botoes), 1)
        botoes[0].click().run()

        registros = carregar_remanejamentos(self.caminho)
        self.assertEqual(len(registros), 1)
        self.assertIsNotNone(registros[0].desfeito_em)
        self.assertNotIn("ajustado", _textos(app))

    def test_com_filtro_ativo_nao_aplica_ajuste_e_avisa(self):
        registrar_remanejamento(2026, "0", "8", Decimal("300"), caminho=self.caminho)
        app = self._app()
        filtro_acao = app.selectbox(key="le_filtro_acao")
        filtro_acao.select(filtro_acao.options[1]).run()

        self.assertNotIn("Limite compartilhado ajustado", _textos(app))
        self.assertTrue(any("só são aplicados ao resumo" in str(i.value) for i in app.info))


if __name__ == "__main__":
    unittest.main()
