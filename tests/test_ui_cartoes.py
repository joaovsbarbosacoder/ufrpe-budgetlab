"""Testes de `src.ui_cartoes` (blocos visuais de Despesas de Pessoal sem cara de planilha, 27/10/2026).

Funções puras que devolvem HTML: conferem o conteúdo, o escape de texto (nada de HTML vindo de
descrição de rubrica ou de nome de arquivo), nulo ≠ zero e as proporções das barras."""
from __future__ import annotations

import unittest

from src import ui_cartoes as cd


class TestFormatoEEscape(unittest.TestCase):
    def test_brl_preserva_nulo_zero_e_negativo(self):
        self.assertEqual(cd.brl(None), "—")
        self.assertEqual(cd.brl(float("nan")), "—")
        self.assertEqual(cd.brl(0), "R$ 0,00")
        self.assertEqual(cd.brl(-1e-9), "R$ 0,00")
        self.assertEqual(cd.brl(-1234.5), "−R$ 1.234,50")
        self.assertEqual(cd.brl(1234567.891), "R$ 1.234.567,89")

    def test_texto_de_fora_e_escapado_em_todos_os_blocos(self):
        perigo = '<img src=x onerror="alert(1)">'
        blocos = [
            cd.kpis([{"rotulo": perigo, "valor": perigo, "sub": perigo}]), cd.secao(perigo, perigo), cd.pill(perigo, "azul"), cd.chip(perigo, "azul"),
            cd.cartao_empenho(perigo, perigo, 1.0, 2.0, 1.0, 0.0, 0.0, 1.0, 1.0, [{"natureza": perigo, "descricao": perigo, "folha": 1.0}], perigo, 2026, perigo),
            cd.cartao_operacoes(perigo, perigo, [{"tipo": "remanejar", "de": perigo, "de_desc": perigo, "para": perigo, "para_desc": perigo, "valor": 1.0}]),
            cd.cartao_dotacao(perigo, perigo, 10.0, 5.0, 5.0, 1.0, 1.0, 4.0, 0.0, perigo),
            cd.cartao_conciliacao(perigo, perigo, [(perigo, 1.0, "normal")], 0.0),
            cd.cartao_conferencia(perigo, perigo, 1.0, 1.0, 0.0, 0.0, perigo, [perigo]),
            cd.barras_divergentes([{"nome": perigo, "detalhe": perigo, "valor": 1.0}]),
            cd.cartao_grupo_execucao(perigo, 10.0, 5.0, 4.0, 3.0), cd.cartao_serie_mensal(perigo, [1.0] * 12, 12.0, [perigo] * 12),
            cd.cartao_comparacao(perigo, 3, 1.0, 2.0, 1.0, perigo), cd.cartao_faixa(perigo, 1.0, 0.5, 2.0, 3.0, 1.0, 2.0, "Dentro da faixa", perigo),
        ]
        for i, html in enumerate(blocos):
            with self.subTest(bloco=i):
                self.assertNotIn("<img", html)
                self.assertIn("&lt;img", html)

    def test_css_define_todas_as_classes_usadas(self):
        for classe in ("cd-kpis", "cd-card", "cd-grid", "cd-bar", "cd-figs", "cd-op", "cd-passo", "cd-div", "cd-eq", "cd-meses", "cd-vs", "cd-faixa"):
            self.assertIn(f".{classe}", cd.CSS)


class TestCartaoEmpenho(unittest.TestCase):
    def _cartao(self, **kw):
        base = dict(nota="2026NE000041", acao="20TP", saldo=250.0, folha=1000.0, falta=750.0, sobra=0.0, coberto=0.0, reforco_mes=750.0,
                    reforco_dez=900.0, itens=[], mes="out/2026", ano=2026, origem=None)
        base.update(kw)
        return cd.cartao_empenho(base["nota"], base["acao"], base["saldo"], base["folha"], base["falta"], base["sobra"], base["coberto"],
                                 base["reforco_mes"], base["reforco_dez"], base["itens"], base["mes"], base["ano"], base["origem"])

    def test_situacao_e_barra_de_cobertura(self):
        html = self._cartao()
        self.assertIn("Reforço até dez: R$ 900,00", html)
        self.assertIn("cobre 25% da folha de out/2026", html)
        self.assertIn("falta R$ 750,00", html)
        self.assertIn("width:25.0%", html)

    def test_sem_reforco_fica_verde_e_cobertura_nunca_passa_de_100(self):
        html = self._cartao(saldo=5000.0, falta=0.0, reforco_mes=0.0, reforco_dez=0.0)
        self.assertIn("Sem reforço", html)
        self.assertIn("cobre 100% da folha", html)
        self.assertNotIn("falta R$", html)

    def test_folha_zero_nao_divide_por_zero(self):
        self.assertIn("cobre 100% da folha", self._cartao(folha=0.0, falta=0.0, reforco_mes=0.0, reforco_dez=0.0))

    def test_itens_aparecem_recolhidos_com_chips(self):
        html = self._cartao(itens=[{"natureza": "31901101", "descricao": "VENCIMENTOS", "folha": 10.0, "falta": 4.0, "sobra": 0.0},
                                   {"natureza": "31901143", "descricao": "13º", "folha": 0.0, "falta": 0.0, "sobra": 7.0}])
        self.assertIn("<details", html)
        self.assertIn("Itens do empenho (2)", html)
        self.assertIn("falta R$ 4,00", html)
        self.assertIn("sobra R$ 7,00", html)


class TestOutrosCartoes(unittest.TestCase):
    def test_operacoes_somam_o_valor(self):
        html = cd.cartao_operacoes("2026NE000036", "20TP", [
            {"tipo": "remanejar", "de": "31901143", "de_desc": "13º", "para": "31901101", "para_desc": "VENC", "valor": 200.0},
            {"tipo": "reforco", "de": None, "de_desc": None, "para": "31901101", "para_desc": "VENC", "valor": 50.0}])
        self.assertIn("2 operação(ões)", html)
        self.assertIn("R$ 250,00", html)
        self.assertIn("Valor novo", html)
        self.assertIn("Cede", html)

    def test_dotacao_cabe_nao_cabe_e_sem_dotacao(self):
        self.assertIn("Cabe na dotação", cd.cartao_dotacao("2004", "0001", 100.0, 40.0, 60.0, 5.0, 10.0, 50.0, 0.0, ""))
        nao = cd.cartao_dotacao("20TP", "0000", 100.0, 90.0, 10.0, 5.0, 30.0, -20.0, 0.0, "NE000036")
        self.assertIn("Falta R$ 20,00", nao)
        self.assertIn("NE000036", nao)
        sem = cd.cartao_dotacao("6294", "0000", None, 19.0, None, 0.0, 0.0, None, 1.0, "")
        self.assertIn("Sem dotação na base", sem)
        self.assertIn("—", sem)  # dotação nula não vira zero

    def test_conciliacao_fecha_ou_mostra_a_diferenca(self):
        passos = [("Saldo", 10.0, "normal"), ("= Final", 12.0, "total")]
        self.assertIn("Fecha: diferença R$ 0,00", cd.cartao_conciliacao("20TP", "Ativo", passos, 0.0))
        self.assertIn("Diferença R$ 3,00", cd.cartao_conciliacao("20TP", "Ativo", passos, 3.0))
        self.assertIn("Sem dotação na base", cd.cartao_conciliacao("0181", "Inativo", passos, None))

    def test_conferencia(self):
        ok = cd.cartao_conferencia("Servidor", "out/2026", 100.0, 40.0, 60.0, 60.0, "Confere", [])
        self.assertIn("✓ Confere", ok)
        self.assertIn("R$ 60,00", ok)
        ruim = cd.cartao_conferencia("Servidor", "out/2026", 100.0, 40.0, 60.0, 50.0, "Há diferença", ["crédito bancário ≠ líquido: −R$ 10,00"])
        self.assertIn("✗", ruim)
        self.assertIn("−R$ 10,00", ruim)

    def test_barras_divergentes_proporcionais_e_cores(self):
        html = cd.barras_divergentes([{"nome": "A", "valor": 100.0}, {"nome": "B", "valor": -50.0}])
        self.assertIn("left:50%;width:50.0%", html)       # alta: do centro para a direita, largura cheia
        self.assertIn("left:25.0%;width:25.0%", html)     # queda: metade do maior, para a esquerda
        self.assertIn("+R$ 100,00", html)
        self.assertIn("−R$ 50,00", html)
        self.assertEqual(cd.barras_divergentes([]), "")

    def test_serie_mensal_mes_sem_dado_nao_vira_zero(self):
        html = cd.cartao_serie_mensal("Ativo", [10.0, None] + [5.0] * 10, 60.0, ["Jan", "Fev"] + ["Mês"] * 10)
        self.assertIn("Fev: sem dado", html)
        self.assertIn("cd-mes vazio", html)
        self.assertEqual(html.count('class="cd-mes"') + html.count('class="cd-mes vazio"'), 12)

    def test_comparacao_e_faixa(self):
        self.assertIn("+R$ 40,00 (+10,0%)", cd.cartao_comparacao("TOTAL", 4, 400.0, 440.0, 40.0, "+10,0%"))
        self.assertIn("Sem comparação", cd.cartao_comparacao("TOTAL", 0, None, None, None, "—"))
        dentro = cd.cartao_faixa("Ativo", 100.0, 90.0, 110.0, 120.0, 10.0, 30.0, "Dentro da faixa", "2025: 1,000")
        self.assertIn("Dentro da faixa", dentro)
        self.assertIn("projetado", dentro)
        sem = cd.cartao_faixa("RPPS", 100.0, None, None, None, None, None, "—", "sem exercício completo")
        self.assertIn("Sem faixa histórica", sem)

    def test_mapa_de_calor_nulo_zero_negativo_e_escape(self):
        html = cd.mapa_calor(["Jan", "Fev", "Mar"], ["Ativo", "<b>x</b>"], [[0.10, None], [-0.05, 0.0], [0.05, -0.02]], "Mês")
        self.assertIn("+10,0%", html)
        self.assertIn("−5,0%", html)
        self.assertIn("+0,0%", html)                       # zero é zero, não vazio
        self.assertEqual(html.count("cd-hm-c vazio"), 1)   # nulo vira "—", nunca zero
        self.assertIn("&lt;b&gt;", html)
        self.assertNotIn("<b>x", html)
        forte = "color-mix(in srgb,#" if "color-mix(in srgb,#" in html else "color-mix"
        self.assertIn(forte, html)
        self.assertIn("55%", html)                         # maior módulo da coluna = intensidade máxima

    def test_comparacao_com_detalhe_escapado(self):
        html = cd.cartao_comparacao("Ação 2004 · PO 0001", 3, 1.0, 2.0, 1.0, "+100,0%", detalhe="<i>x</i>")
        self.assertIn("&lt;i&gt;x", html)
        self.assertNotIn("<i>x", html)

    def test_execucao_por_grupo(self):
        html = cd.cartao_grupo_execucao("Ativo", 1000.0, 900.0, 750.0, 700.0)
        self.assertIn("75.0%", html)
        self.assertIn("R$ 1.000,00", html)
        self.assertNotIn("cd-bar", cd.cartao_grupo_execucao("Ativo", None, 1.0, 1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
