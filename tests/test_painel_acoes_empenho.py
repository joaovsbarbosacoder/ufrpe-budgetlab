"""Testes do cruzamento Dotação Anual (subdivisão) x Execução Anual (Empenhada) usado
pela coluna "Empenhado" do Painel por Ação de Governo."""

from __future__ import annotations

import unittest

import pandas as pd

from src.painel_acoes_empenho import (
    anexar_empenhado_por_subdivisao,
    derivar_fonte_execucao,
    empenhado_total_por_acao,
)


def _linha_subdivisao(
    acao_codigo="0181", ptres_codigo="137087", plano_orcamentario_codigo="0002",
    grupo_despesa_codigo="3", resultado_primario_codigo="2", iduso_codigo="0",
    fonte_recursos_detalhada_codigo="1050000000", dotacao_atualizada=100_000.0,
):
    return dict(
        acao_codigo=acao_codigo, acao_descricao="APOSENTADORIAS",
        ptres_codigo=ptres_codigo,
        plano_orcamentario_codigo=plano_orcamentario_codigo, plano_orcamentario_descricao="PO",
        grupo_despesa_codigo=grupo_despesa_codigo, grupo_despesa_descricao="GND",
        resultado_primario_codigo=resultado_primario_codigo, resultado_primario_descricao="RP",
        iduso_codigo=iduso_codigo, iduso_descricao="IDUSO",
        fonte_recursos_detalhada_codigo=fonte_recursos_detalhada_codigo, fonte_recursos_detalhada_descricao="FONTE",
        dotacao_inicial=dotacao_atualizada, dotacao_suplementar=0.0,
        dotacao_cancelada_remanejada=0.0, dotacao_atualizada=dotacao_atualizada,
    )


def _linha_execucao(
    acao_cod="0181", ptres="137087", po_cod="0002", gnd_cod="3",
    resultado_primario_cod="2", iduso_cod="0", fonte_cod="050",
    ano=2026, empenhada=40_000.0, liquidada=0.0, paga=0.0,
):
    return dict(
        acao_cod=acao_cod, ptres=ptres, po_cod=po_cod, gnd_cod=gnd_cod,
        resultado_primario_cod=resultado_primario_cod, iduso_cod=iduso_cod, fonte_cod=fonte_cod,
        ano=ano, empenhada=empenhada, liquidada=liquidada, paga=paga,
    )


class TestDerivarFonteExecucao(unittest.TestCase):
    def test_descarta_o_primeiro_digito_e_pega_os_3_seguintes(self):
        serie = pd.Series(["1050000000", "3050000000", "1051000390"])
        resultado = derivar_fonte_execucao(serie)
        self.assertEqual(list(resultado), ["050", "050", "051"])

    def test_preserva_nulo(self):
        serie = pd.Series([None, "1050000000"])
        resultado = derivar_fonte_execucao(serie)
        self.assertTrue(pd.isna(resultado.iloc[0]))
        self.assertEqual(resultado.iloc[1], "050")


class TestAnexarEmpenhadoPorSubdivisao(unittest.TestCase):
    def test_junta_quando_as_6_dimensoes_mais_fonte_derivada_batem(self):
        subdivisoes = pd.DataFrame([_linha_subdivisao()])
        execucao = pd.DataFrame([_linha_execucao()])
        resultado = anexar_empenhado_por_subdivisao(subdivisoes, execucao, 2026)
        self.assertAlmostEqual(float(resultado.iloc[0]["empenhada"]), 40_000.0)

    def test_nulo_quando_a_combinacao_nao_existe_na_execucao(self):
        subdivisoes = pd.DataFrame([_linha_subdivisao(ptres_codigo="999999")])
        execucao = pd.DataFrame([_linha_execucao()])
        resultado = anexar_empenhado_por_subdivisao(subdivisoes, execucao, 2026)
        self.assertTrue(pd.isna(resultado.iloc[0]["empenhada"]))

    def test_derivacao_ignora_o_valor_do_1o_digito_sempre(self):
        # A regra sempre descarta o 1º dígito e usa os 3 seguintes, mesmo quando ele
        # não é 1 nem 3 (ex.: 0) — o achado do módulo é que, NA BASE REAL, códigos com
        # 1º dígito fora de {1, 3} simplesmente não têm nenhum `fonte_cod`
        # correspondente na Execução (dotação sem despesa vinculada ainda), não que a
        # função deva bloquear ativamente por causa do 1º dígito.
        subdivisoes = pd.DataFrame([_linha_subdivisao(fonte_recursos_detalhada_codigo="0150000000")])
        execucao = pd.DataFrame([_linha_execucao(fonte_cod="150")])
        resultado = anexar_empenhado_por_subdivisao(subdivisoes, execucao, 2026)
        self.assertAlmostEqual(float(resultado.iloc[0]["empenhada"]), 40_000.0)

    def test_filtra_pelo_ano_pedido(self):
        subdivisoes = pd.DataFrame([_linha_subdivisao()])
        execucao = pd.DataFrame([_linha_execucao(ano=2025, empenhada=999_999.0)])
        resultado = anexar_empenhado_por_subdivisao(subdivisoes, execucao, 2026)
        self.assertTrue(pd.isna(resultado.iloc[0]["empenhada"]))

    def test_nao_altera_o_dataframe_original(self):
        subdivisoes = pd.DataFrame([_linha_subdivisao()])
        execucao = pd.DataFrame([_linha_execucao()])
        anexar_empenhado_por_subdivisao(subdivisoes, execucao, 2026)
        self.assertNotIn("empenhada", subdivisoes.columns)


class TestColisaoDeFonteDetalhada(unittest.TestCase):
    """Achado real (22/09/2026): 32/245 combinações têm mais de uma Fonte Detalhada
    mapeando pra mesma Fonte de 3 dígitos — a linha de subdivisão repete o valor, mas
    o TOTAL por Ação nunca pode ser a soma das linhas (dobraria o valor)."""

    def _cenario(self):
        subdivisoes = pd.DataFrame([
            _linha_subdivisao(fonte_recursos_detalhada_codigo="1050000000", dotacao_atualizada=60_000.0),
            _linha_subdivisao(fonte_recursos_detalhada_codigo="1050000390", dotacao_atualizada=40_000.0),
        ])
        execucao = pd.DataFrame([_linha_execucao(fonte_cod="050", empenhada=40_000.0)])
        return subdivisoes, execucao

    def test_as_duas_linhas_mostram_o_mesmo_valor_empenhado(self):
        subdivisoes, execucao = self._cenario()
        resultado = anexar_empenhado_por_subdivisao(subdivisoes, execucao, 2026)
        self.assertAlmostEqual(float(resultado.iloc[0]["empenhada"]), 40_000.0)
        self.assertAlmostEqual(float(resultado.iloc[1]["empenhada"]), 40_000.0)

    def test_total_por_acao_nao_duplica_o_valor(self):
        _, execucao = self._cenario()
        total = empenhado_total_por_acao(execucao, 2026)
        self.assertAlmostEqual(float(total["0181"]), 40_000.0)  # não 80.000


class TestEmpenhadoTotalPorAcao(unittest.TestCase):
    def test_soma_todas_as_combinacoes_da_acao(self):
        execucao = pd.DataFrame([
            _linha_execucao(ptres="137087", empenhada=40_000.0),
            _linha_execucao(ptres="137088", empenhada=25_000.0),
            _linha_execucao(acao_cod="20TP", empenhada=999_999.0),
        ])
        total = empenhado_total_por_acao(execucao, 2026)
        self.assertAlmostEqual(float(total["0181"]), 65_000.0)
        self.assertAlmostEqual(float(total["20TP"]), 999_999.0)


if __name__ == "__main__":
    unittest.main()
