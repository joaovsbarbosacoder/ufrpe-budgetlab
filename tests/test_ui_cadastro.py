"""Testes dos componentes visuais dos cadastros (`src/ui_cadastro.py`) — funções puras, sem Streamlit.

O que mais importa aqui: texto vindo do cadastro (fornecedor, programa, processo) é digitado por
pessoas e vai para HTML — precisa sair escapado; e nulo, zero e negativo continuam distintos."""

from __future__ import annotations

import unittest

import pandas as pd

from src.ui_cadastro import (
    aviso_linha_do_tempo,
    cartao_cobertura_ptres,
    cartao_resumo,
    cartao_secao,
    celula_categoria,
    celula_principal,
    celula_saldo,
    celula_suave,
    celula_valor,
    chip,
    contagens_por_aba,
    css,
    formatar_brl,
    grade_indicadores,
    ordenar_por,
    tabela_html,
    topo_secao,
)


class TestFormatarBrl(unittest.TestCase):
    def test_nulo_zero_e_negativo_sao_distintos(self):
        self.assertEqual(formatar_brl(None), "—")
        self.assertEqual(formatar_brl(float("nan")), "—")
        self.assertEqual(formatar_brl(pd.NA), "—")
        self.assertEqual(formatar_brl(0), "R$ 0,00")
        self.assertEqual(formatar_brl(-1234.5), "-R$ 1.234,50")

    def test_pontuacao_pt_br(self):
        self.assertEqual(formatar_brl(1234567.891), "R$ 1.234.567,89")
        self.assertEqual(formatar_brl(0.5), "R$ 0,50")


class TestCelulas(unittest.TestCase):
    PERIGOSO = '<script>alert("x")</script> & Cia'

    def test_texto_do_cadastro_e_escapado(self):
        for html in (
            celula_principal(self.PERIGOSO, self.PERIGOSO),
            celula_categoria(self.PERIGOSO),
            celula_suave(self.PERIGOSO),
            chip(self.PERIGOSO, "ok"),
        ):
            self.assertNotIn("<script>", html)
            self.assertIn("&lt;script&gt;", html)

    def test_principal_sem_subtitulo_nao_cria_bloco_vazio(self):
        self.assertNotIn("cad-sub", celula_principal("Fornecedor", None))
        self.assertNotIn("cad-sub", celula_principal("Fornecedor", "  "))
        self.assertIn("cad-sub", celula_principal("Fornecedor", "Contrato 1/2026"))

    def test_nulo_vira_traco_nas_celulas_de_texto(self):
        self.assertIn(">—<", celula_suave(None))
        self.assertIn("—", celula_categoria(pd.NA))
        self.assertIn("—", celula_principal(None, None))

    def test_valor_mostra_zero_e_nulo_diferentes(self):
        self.assertIn("R$ 0,00", celula_valor(0))
        self.assertIn("—", celula_valor(None))
        self.assertNotIn("R$ 0,00", celula_valor(None))

    def test_valor_com_tom_so_aceita_tons_conhecidos(self):
        self.assertIn('class="cad-valor warn"', celula_valor(10, "warn"))
        self.assertIn('class="cad-valor"', celula_valor(10, "inexistente"))  # não vira classe arbitrária

    def test_chip_com_tom_desconhecido_cai_em_neutro(self):
        self.assertIn("cad-chip neutro", chip("Suspenso", "xyz"))
        self.assertIn("cad-chip bad", chip("Vencido", "bad"))


class TestCartaoResumo(unittest.TestCase):
    def test_conteudo_e_escape(self):
        html = cartao_resumo(
            "Necessidade <2026>", "Descrição & detalhe",
            {"rotulo": "Até dezembro", "valor": "R$ 1,00", "detalhe": "5 NEs", "tom": "warn"},
            [("Despesa anual", "R$ 10,00"), ("Contratos", "40")],
        )
        self.assertIn("Necessidade &lt;2026&gt;", html)
        self.assertIn("Descrição &amp; detalhe", html)
        self.assertIn("cad-faixa warn", html)
        self.assertIn("R$ 1,00", html)
        self.assertIn("5 NEs", html)
        self.assertEqual(html.count('class="cad-tile"'), 2)

    def test_sem_detalhe_nao_cria_bloco(self):
        html = cartao_resumo("T", "D", {"rotulo": "R", "valor": "V", "tom": "ok"}, [])
        self.assertNotIn("cad-faixa-detalhe", html)

    def test_tom_invalido_cai_em_neutro(self):
        html = cartao_resumo("T", "D", {"rotulo": "R", "valor": "V", "tom": "x"}, [])
        self.assertIn("cad-faixa neutro", html)


class TestGradeIndicadores(unittest.TestCase):
    def test_grade_com_escape_e_sem_titulo(self):
        html = grade_indicadores([("A <b>", "R$ 1,00"), ("B", "2")])
        self.assertEqual(html.count('class="cad-tile"'), 2)
        self.assertIn("A &lt;b&gt;", html)
        self.assertNotIn("cad-resumo", html)
        self.assertEqual(grade_indicadores([]), '<div class="cad-tiles"></div>')


class TestAvisoLinhaDoTempo(unittest.TestCase):
    """Quando nenhuma linha do Resumo Consolidado abre a linha do tempo, a tela explica por quê (05/10/2026)."""

    def test_sem_aviso_quando_alguma_ne_e_clicavel(self):
        self.assertIsNone(aviso_linha_do_tempo(["2026NE000001", "2026NE000002"], {"2026NE000002"}))

    def test_aviso_quando_nenhuma_ne_tem_dado_na_base_mensal(self):
        aviso = aviso_linha_do_tempo(["2027NE000001"], {"2026NE000002"})
        self.assertIn("Execução Mensal", aviso)
        self.assertIn("só abre", aviso)

    def test_recorte_sem_nenhuma_ne_tambem_avisa(self):
        self.assertIsNotNone(aviso_linha_do_tempo([None, float("nan"), pd.NA], {"2026NE000002"}))
        self.assertIsNotNone(aviso_linha_do_tempo([], {"2026NE000002"}))

    def test_ne_nula_nao_conta_como_clicavel(self):
        self.assertIsNone(aviso_linha_do_tempo([None, "2026NE000002"], {"2026NE000002"}))

    def test_base_indisponivel_tem_texto_proprio(self):
        aviso = aviso_linha_do_tempo(["2026NE000001"], set(), base_disponivel=False)
        self.assertIn("não pôde ser carregada", aviso)
        self.assertNotIn("Nenhuma NE deste recorte", aviso)

    def test_aviso_nao_depende_de_base_quando_ha_clicavel(self):
        self.assertIsNone(aviso_linha_do_tempo(["2026NE000002"], {"2026NE000002"}, base_disponivel=True))


class TestContagensEOrdenacao(unittest.TestCase):
    def test_contagens_por_aba_aceita_sobreposicao_e_nulos(self):
        mascaras = {
            "Ativo": pd.Series([True, True, False, None]),
            "Necessita reforço": pd.Series([True, False, False, False]),
        }
        self.assertEqual(contagens_por_aba(mascaras), {"Ativo": 2, "Necessita reforço": 1})

    def test_ordenar_texto_sem_diferenciar_maiusculas_e_nulo_por_ultimo(self):
        df = pd.DataFrame({"nome": ["beta", None, "Alfa", "ALFA2"], "v": [1, 2, 3, 4]})
        ordenado = ordenar_por(df, "nome")
        self.assertEqual(ordenado["nome"].tolist()[:3], ["Alfa", "ALFA2", "beta"])
        self.assertTrue(pd.isna(ordenado["nome"].iloc[3]))
        self.assertNotIn("_chave_ordem", ordenado.columns)

    def test_ordenar_numerico_decrescente_com_nulo_por_ultimo(self):
        df = pd.DataFrame({"valor": [10.0, float("nan"), 30.0, 20.0]})
        self.assertEqual(ordenar_por(df, "valor", crescente=False)["valor"].tolist()[:3], [30.0, 20.0, 10.0])
        self.assertTrue(pd.isna(ordenar_por(df, "valor", crescente=False)["valor"].iloc[3]))

    def test_ordenar_nao_altera_a_entrada_e_tolera_coluna_ausente(self):
        df = pd.DataFrame({"nome": ["b", "a"]})
        copia = df.copy(deep=True)
        ordenar_por(df, "nome")
        pd.testing.assert_frame_equal(df, copia)
        self.assertIs(ordenar_por(df, "nao_existe"), df)

    def test_ordenacao_e_estavel(self):
        df = pd.DataFrame({"nome": ["a", "a", "a"], "ordem": [1, 2, 3]})
        self.assertEqual(ordenar_por(df, "nome")["ordem"].tolist(), [1, 2, 3])


class TestCelulaValorVazio(unittest.TestCase):
    def test_nulo_com_texto_proprio_e_zero_continua_zero(self):
        self.assertIn("sem NE", celula_valor(None, vazio="sem NE"))
        self.assertIn("vazio", celula_valor(pd.NA, vazio="sem NE"))
        self.assertIn("R$ 0,00", celula_valor(0, vazio="sem NE"))  # zero NUNCA vira "sem NE"
        self.assertNotIn("sem NE", celula_valor(0, vazio="sem NE"))

    def test_sem_texto_proprio_nulo_vira_traco(self):
        self.assertIn("—", celula_valor(None))

    def test_texto_do_vazio_e_escapado(self):
        self.assertIn("&lt;b&gt;", celula_valor(None, vazio="<b>"))


class TestTabelaHtml(unittest.TestCase):
    def test_estrutura_cabecalho_linhas_e_rodape(self):
        html = tabela_html(
            [("Nome <x>", False), ("Valor", True)],
            [[celula_suave("a"), celula_valor(1)], [celula_suave("b"), celula_valor(2)]],
            [2.0, 1.0],
            rodape=['<div class="cad-total-rotulo">Total</div>', celula_valor(3)],
        )
        self.assertEqual(html.count("cad-tabela-linha"), 2)
        self.assertEqual(html.count("cad-tabela-rodape"), 1)
        self.assertIn("Nome &lt;x&gt;", html)  # rótulo escapado
        self.assertIn("cad-tabela-rotulo direita", html)  # só a coluna da direita
        self.assertIn("minmax(0,2.0fr) minmax(0,1.0fr)", html)

    def test_celula_vazia_ocupa_a_coluna_e_nao_desloca_as_seguintes(self):
        # sem o `<span>` de preenchimento, o "" sumia do HTML e a grade (3 colunas) recebia só 2 filhos
        html = tabela_html([("A", False), ("B", False), ("C", True)], [["<i>a</i>", "", "<i>c</i>"]], [1, 1, 1], rodape=["<b>t</b>", "", "<b>v</b>"])
        self.assertEqual(html.count("<span></span>"), 2)  # uma na linha, uma no rodapé

    def test_sem_rodape_nao_cria_o_bloco(self):
        self.assertNotIn("cad-tabela-rodape", tabela_html([("A", False)], [[celula_suave("x")]], [1.0]))

    def test_colunas_e_proporcoes_precisam_casar(self):
        with self.assertRaises(ValueError):
            tabela_html([("A", False), ("B", False)], [], [1.0])

    def test_sem_linhas_ainda_gera_o_cabecalho(self):
        self.assertIn("cad-tabela-cab", tabela_html([("A", False)], [], [1.0]))


class TestCartaoSecao(unittest.TestCase):
    def test_conteudo_escape_e_corpo_sem_escape(self):
        html = cartao_secao(
            "Título <t>", "Descrição & mais", {"rotulo": "Saldo", "valor": "R$ 1,00", "detalhe": "3 PTRES", "tom": "ok"},
            "<table>corpo</table>", kicker="AÇÃO <1>",
        )
        self.assertIn("Título &lt;t&gt;", html)
        self.assertIn("Descrição &amp; mais", html)
        self.assertIn("AÇÃO &lt;1&gt;", html)
        self.assertIn("<table>corpo</table>", html)  # o corpo já vem em HTML
        self.assertIn("cad-cartao-valor ok", html)
        self.assertIn("3 PTRES", html)

    def test_sem_destaque_nem_kicker_nem_descricao(self):
        html = cartao_secao("Só título", None, None, "")
        for classe in ("cad-cartao-destaque", "cad-cartao-kicker", "cad-cartao-desc"):
            self.assertNotIn(classe, html)

    def test_tom_desconhecido_cai_em_neutro(self):
        self.assertIn("cad-cartao-valor neutro", cartao_secao("T", None, {"rotulo": "r", "valor": "v", "tom": "xx"}, ""))


class TestTopoSecaoESaldo(unittest.TestCase):
    def test_topo_sem_caixa_e_com_escape(self):
        html = topo_secao("T <1>", "d & e", {"rotulo": "r", "valor": "v", "tom": "warn"}, kicker="K")
        self.assertIn("cad-cartao-topo", html)
        self.assertNotIn('class="cad-cartao"', html)  # a caixa é o container do Streamlit
        self.assertIn("T &lt;1&gt;", html)
        self.assertIn("cad-cartao-valor warn", html)

    def test_cartao_secao_envolve_o_topo_e_o_corpo(self):
        html = cartao_secao("T", None, None, "<p>corpo</p>")
        self.assertTrue(html.startswith('<div class="cad-cartao">'))
        self.assertIn("cad-cartao-topo", html)
        self.assertIn("<p>corpo</p>", html)

    def test_saldo_positivo_negativo_zero_e_nulo(self):
        self.assertIn("Sobra", celula_saldo(10))
        self.assertIn("cad-valor ok", celula_saldo(10))
        self.assertIn("Insuficiência", celula_saldo(-10))
        self.assertIn("cad-valor bad", celula_saldo(-10))
        zero = celula_saldo(0)
        self.assertIn("Sobra", zero)
        self.assertIn("R$ 0,00", zero)  # zero NÃO é "sem NE"
        nulo = celula_saldo(None)
        self.assertIn("sem NE", nulo)
        self.assertNotIn("Sobra", nulo)  # nulo nunca vira "Sobra"

    def test_saldo_com_rotulos_proprios(self):
        self.assertIn("Folga", celula_saldo(1, rotulo_positivo="Folga"))


class TestCartaoCoberturaPtres(unittest.TestCase):
    """Valores à mão: B falta 300 (200 − 500), A sobra 600 (1000 − 400), C sem dotação (nulo, despesa 100).
    Totais: dotação 1.200, despesa 1.000, saldo 300 (C fica fora da soma do saldo)."""

    @staticmethod
    def _grupo() -> pd.DataFrame:
        nan = float("nan")
        return pd.DataFrame(
            {
                "plano_orcamentario_descricao": ["Plano A", "Plano <B>", None],
                "plano_orcamentario_codigo": ["0001", "0002", None],
                "ptres_codigo": ["230001", "230002", "230003"],
                "dotacao_atualizada": [1000.0, 200.0, nan],
                "despesa_estimada": [400.0, 500.0, 100.0],
                "saldo": [600.0, -300.0, nan],
            }
        )

    def test_linhas_do_mais_deficitario_ao_mais_folgado_e_nulo_por_ultimo(self):
        html = cartao_cobertura_ptres("20RK", "Ação X", self._grupo())
        self.assertLess(html.index("Plano &lt;B&gt;"), html.index("Plano A"))  # B (−300) antes de A (+600)
        self.assertLess(html.index("Plano A"), html.index("(não informado)"))  # sem dotação por último

    def test_saldo_com_tom_e_nulo_sem_dotacao(self):
        html = cartao_cobertura_ptres("20RK", "Ação X", self._grupo())
        self.assertIn("cad-valor bad", html)  # saldo de B
        self.assertIn("cad-valor ok", html)  # saldo de A
        self.assertIn("sem dotação", html)  # C: nulo, não zero
        self.assertIn("-R$ 300,00", html)

    def test_totais_e_destaque(self):
        html = cartao_cobertura_ptres("20RK", "Ação X", self._grupo())
        self.assertIn("R$ 1.200,00", html)  # dotação total (C é nulo e não entra)
        self.assertIn("R$ 1.000,00", html)  # despesa total (400 + 500 + 100)
        self.assertIn("cad-cartao-valor ok", html)  # saldo total 300 >= 0
        self.assertIn("R$ 300,00", html)
        self.assertIn("3 PTRES", html)
        self.assertIn("AÇÃO DE GOVERNO 20RK", html)

    def test_acao_toda_sem_dotacao_mostra_sem_dotacao_no_destaque(self):
        nan = float("nan")
        grupo = pd.DataFrame(
            {
                "plano_orcamentario_descricao": ["P"], "plano_orcamentario_codigo": ["1"], "ptres_codigo": ["9"],
                "dotacao_atualizada": [nan], "despesa_estimada": [50.0], "saldo": [nan],
            }
        )
        html = cartao_cobertura_ptres(None, None, grupo)
        self.assertIn("cad-cartao-valor neutro", html)
        self.assertIn("AÇÃO DE GOVERNO —", html)

    def test_nao_altera_a_entrada(self):
        grupo = self._grupo()
        copia = grupo.copy(deep=True)
        cartao_cobertura_ptres("20RK", "Ação X", grupo)
        pd.testing.assert_frame_equal(grupo, copia)


class TestCss(unittest.TestCase):
    def test_css_traz_as_classes_usadas_pelas_paginas(self):
        estilo = css()
        for classe in ("cad-resumo", "cad-faixa", "cad-tile", "cad-chip", "st-key-cad_registro", "cad_linha_", "cad_acoes_"):
            self.assertIn(classe, estilo)
        self.assertTrue(estilo.lstrip().startswith("<style>"))


if __name__ == "__main__":
    unittest.main()
