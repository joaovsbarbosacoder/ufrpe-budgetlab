"""Testes de interação da aba "Aditivos" (`src/ui_aditivos.py`, 06/10/2026).

O `AppTest` só executa a abertura de um `@st.dialog` (ver `tests/test_cadastros_layout_page.py`), então a
aba é testada aqui fora do diálogo, dentro de um `@st.fragment` — o mesmo mecanismo de recarga parcial
(`st.rerun(scope="fragment")`) que ela usa dentro da janela. Cobre adicionar, editar, remover (sem
deslocar o estado dos outros cartões), valor negativo, rateio e a validação.
"""

from __future__ import annotations

import unittest
from datetime import date

from streamlit.testing.v1 import AppTest

from tests._apptest import TEMPO_LIMITE_APPTEST


def _pagina() -> None:
    from datetime import date

    import streamlit as st

    from src.contratos_aditivos import Aditivo, validar_aditivos
    from src.ui_aditivos import render_aba_aditivos

    existentes = [
        Aditivo(numero="1º TA", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2025, 7, 1), valor_mensal=10_400.0),
        Aditivo(
            numero="002", tipo="PRORROGACAO", situacao="PREVISTO", data_inicio=date(2026, 7, 1), valor_mensal=10_800.0,
            vigencia_fim=date(2027, 6, 30),
        ),
    ]
    itens = [{"numero": 1, "percentual": 60.0}, {"numero": 2, "percentual": 40.0}]

    @st.fragment
    def aba() -> None:
        digitados = render_aba_aditivos("t", existentes, itens)
        st.session_state["digitados"] = digitados
        st.session_state["erros"] = validar_aditivos(digitados)

    aba()


def _abrir() -> AppTest:
    app = AppTest.from_function(_pagina, default_timeout=TEMPO_LIMITE_APPTEST)
    app.run()
    return app


class TestAbaAditivos(unittest.TestCase):
    def test_mostra_um_cartao_por_aditivo_com_os_valores_do_registro(self):
        app = _abrir()
        self.assertEqual(len(app.exception), 0)
        numeros = {t.key: t.value for t in app.text_input}
        self.assertEqual(numeros["t_aditivos_0_numero"], "1º TA")
        self.assertEqual(numeros["t_aditivos_1_numero"], "002")  # nº é texto, "002" preservado
        digitados = app.session_state["digitados"]
        self.assertEqual([a.numero for a in digitados], ["1º TA", "002"])
        self.assertEqual(digitados[0].valor_mensal, 10_400.0)
        self.assertEqual(digitados[1].vigencia_fim, date(2027, 6, 30))
        self.assertEqual(digitados[1].situacao, "PREVISTO")
        self.assertEqual(app.session_state["erros"], [])

    def test_adicionar_aditivo_cria_cartao_incompleto_e_a_validacao_acusa(self):
        app = _abrir()
        app.button(key="t_adt_add").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.session_state["digitados"]), 3)
        erros = app.session_state["erros"]
        self.assertTrue(any("sem nº" in e for e in erros))
        self.assertTrue(any("data de início" in e for e in erros))

    def test_editar_um_campo_atualiza_o_aditivo_digitado(self):
        app = _abrir()
        app.number_input(key="t_aditivos_0_valor").set_value(11_000.0).run()
        self.assertEqual(app.session_state["digitados"][0].valor_mensal, 11_000.0)
        app.text_input(key="t_aditivos_1_numero").input("2º TA").run()
        self.assertEqual(app.session_state["digitados"][1].numero, "2º TA")

    def test_remover_tira_o_cartao_clicado_e_preserva_o_estado_dos_outros(self):
        app = _abrir()
        app.text_input(key="t_aditivos_1_numero").input("2º TA").run()  # edita o segundo
        app.button(key="t_aditivos_0_rem").click().run()  # remove o PRIMEIRO
        self.assertEqual(len(app.exception), 0)
        digitados = app.session_state["digitados"]
        self.assertEqual([a.numero for a in digitados], ["2º TA"])  # sobrou o segundo, com a edição
        self.assertEqual(digitados[0].valor_mensal, 10_800.0)

    def test_aditivo_novo_nasce_com_campos_opcionais_nulos_nunca_zero(self):
        app = _abrir()
        app.button(key="t_adt_add").click().run()
        novo = app.session_state["digitados"][2]
        self.assertIsNone(novo.valor_mensal)
        self.assertIsNone(novo.vigencia_fim)
        self.assertIsNone(novo.data_assinatura)
        self.assertIsNone(novo.itens)

    def test_valor_negativo_e_aceito_com_destaque(self):
        app = _abrir()
        app.number_input(key="t_aditivos_0_valor").set_value(-50.0).run()
        self.assertEqual(app.session_state["digitados"][0].valor_mensal, -50.0)
        self.assertEqual(app.session_state["erros"], [])  # negativo é aceito
        self.assertTrue(any("valor negativo" in c.value for c in app.caption))

    def test_alterar_rateio_so_aparece_marcado_e_grava_os_percentuais(self):
        app = _abrir()
        self.assertIsNone(app.session_state["digitados"][0].itens)
        app.checkbox(key="t_aditivos_0_altera_rateio").check().run()
        app.number_input(key="t_aditivos_0_rateio_1").set_value(50.0).run()
        app.number_input(key="t_aditivos_0_rateio_2").set_value(50.0).run()
        self.assertEqual(
            app.session_state["digitados"][0].itens, [{"numero": 1, "percentual": 50.0}, {"numero": 2, "percentual": 50.0}]
        )
        self.assertEqual(app.session_state["erros"], [])
        app.number_input(key="t_aditivos_0_rateio_2").set_value(30.0).run()
        self.assertTrue(any("100%" in e for e in app.session_state["erros"]))

    def test_mesma_data_de_inicio_e_bloqueada(self):
        app = _abrir()
        app.date_input(key="t_aditivos_1_inicio").set_value(date(2025, 7, 1)).run()
        self.assertTrue(any("ordem ambígua" in e for e in app.session_state["erros"]))


if __name__ == "__main__":
    unittest.main()
