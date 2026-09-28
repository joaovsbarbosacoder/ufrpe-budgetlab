"""Testes do painel Streamlit de Emendas com fontes controladas."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests._apptest import TEMPO_LIMITE_APPTEST

from src.importacao_emendas import Manifesto as ManifestoEmendas
from src.tesouro_emendas_acompanhamento import ler_emendas_acompanhamento


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMINHO_BASE = Path("tests/fixtures/emendas_acompanhamento_2026-08-28.xlsx")
MANIFESTO_EMENDAS = Path("data/manifestos/emendas_acompanhamento_atual.json")


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Fixture ausente em {CAMINHO_BASE}")
@unittest.skipUnless(MANIFESTO_EMENDAS.exists(), f"Manifesto ausente em {MANIFESTO_EMENDAS}")
class EmendasParlamentaresPageTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
