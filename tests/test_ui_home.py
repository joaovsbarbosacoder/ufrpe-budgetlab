"""Testes de `src.ui_home` (blocos visuais da página inicial, 28/10/2026): HTML escapado e estados sem inventar dado."""
from __future__ import annotations

import unittest
from datetime import date, datetime

from src import ui_home as hm


class TestBlocosDaPaginaInicial(unittest.TestCase):
    def test_texto_de_fora_e_escapado(self):
        perigo = '<img src=x onerror="alert(1)">'
        prazo = {"titulo": perigo, "data_prazo": date(2026, 10, 19), "dias_para_vencer": -8, "criticidade": "Atrasado",
                 "categoria": perigo, "responsavel": perigo}
        blocos = [hm.chip(perigo, "azul"), hm.kpis([{"rotulo": perigo, "valor": perigo, "complemento": perigo, "sub": perigo}]),
                  hm.painel_prazos([prazo], 1), hm.painel_bases([(perigo, True, datetime(2026, 10, 23, 11, 18))]),
                  hm.secao(perigo, perigo), hm.cabecalho_grupo(perigo, perigo, perigo)]
        for i, html in enumerate(blocos):
            with self.subTest(bloco=i):
                self.assertNotIn("<img", html)
                self.assertIn("&lt;img", html)

    def test_prazos_com_tempo_relativo_e_cor_da_criticidade(self):
        base = {"categoria": "SIAFI", "responsavel": "PROPLAD", "data_prazo": date(2026, 11, 3)}
        html = hm.painel_prazos([
            {**base, "titulo": "A", "dias_para_vencer": -1, "criticidade": "Atrasado"},
            {**base, "titulo": "B", "dias_para_vencer": 0, "criticidade": "Vencendo"},
            {**base, "titulo": "C", "dias_para_vencer": 1, "criticidade": "Vencendo"},
            {**base, "titulo": "D", "dias_para_vencer": 30, "criticidade": "Em dia"}], 9)
        for texto in ("atrasado há 1 dia", "vence hoje", "em 1 dia", "em 30 dias", "4 de 9 prazo(s)", "SIAFI · PROPLAD", "03/11/2026"):
            self.assertIn(texto, html)
        self.assertNotIn("atrasado há 1 dias", html)
        self.assertEqual(html.count('class="hm-linha"'), 4)

    def test_sem_prazos_mostra_vazio_e_nao_zero_inventado(self):
        html = hm.painel_prazos([], 0)
        self.assertIn("Nenhum prazo orçamentário pendente cadastrado.", html)
        self.assertNotIn('class="hm-linha"', html)

    def test_base_ausente_fica_vermelha_e_sem_data(self):
        html = hm.painel_bases([("Execução Anual", True, datetime(2026, 9, 3, 17, 5)), ("Dotação Anual", False, None),
                                ("Sem data", True, None)])
        self.assertIn("03/09/2026", html)
        self.assertIn("17:05", html)
        self.assertIn("não encontrada", html)
        self.assertEqual(html.count('class="data">—</div>'), 2)  # ausente e sem data: traço, nunca data inventada
        self.assertIn(hm.TONS["vermelho"], html)

    def test_kpi_zero_e_exibido_como_zero(self):
        html = hm.kpis([{"rotulo": "Atrasados", "valor": 0, "tom": "verde"}])
        self.assertIn('<div class="val">0</div>', html)

    def test_css_define_as_classes_usadas(self):
        for classe in ("hm-faixa", "hm-chip", "hm-kpis", "hm-kpi", "hm-par", "hm-painel", "hm-linha", "hm-ponto", "hm-grupo"):
            self.assertIn(f".{classe}", hm.CSS)


if __name__ == "__main__":
    unittest.main()
