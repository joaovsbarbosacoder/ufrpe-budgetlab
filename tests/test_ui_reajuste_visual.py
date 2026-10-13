"""Componentes visuais da página "Reajuste estimado" (12/10/2026) — HTML puro, sem Streamlit.

Regras: nulo ≠ zero (traço, nunca R$ 0,00); número do contrato acompanhado só do nome do credor; textos escapados;
contrato sem estimativa visível; tudo calculado a partir de valores já estimados (nada é recalculado aqui).
"""

from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

import pandas as pd

from src.ui_reajuste_visual import html_ciclos, html_destaque, html_grafico_mensal, html_mapa, html_ranking


def _item(**extra) -> dict:
    base = {
        "contrato": "14/2022", "fornecedor": "Inteligência Segurança Privada Ltda", "situacao": "Estimado",
        "estado": "Formalizado, a confirmar", "data_base": date(2026, 9, 1), "percentual": 4.26, "origem": "Oficial (12 meses)",
        "formalizado": 318400.0, "projetado": None, "acrescimo": 318400.0,
    }
    base.update(extra)
    return base


class DestaqueTests(unittest.TestCase):
    def test_total_e_indicadores(self) -> None:
        html = html_destaque(2026, formalizado=612300.0, projetado=774120.0, anteriores=98750.0, sem_estimativa=4)
        self.assertIn("Reajuste estimado em 2026", html)
        self.assertIn("1.386.420", html)  # formalizado + projetado
        self.assertIn("612.300", html)
        self.assertIn("98.750", html)
        self.assertIn("4 contratos", html)
        self.assertIn("44%", html)  # formalizado / total

    def test_sem_nenhum_valor_mostra_traco_nunca_zero(self) -> None:
        html = html_destaque(2026, formalizado=None, projetado=None, anteriores=None, sem_estimativa=3)
        self.assertNotIn("R$ 0", html)
        self.assertIn("—", html)
        self.assertIn("3 contratos", html)

    def test_zero_conhecido_continua_zero_e_sem_divisao_por_zero(self) -> None:
        html = html_destaque(2026, formalizado=0.0, projetado=0.0, anteriores=None, sem_estimativa=0)
        self.assertIn("R$ 0", html)
        self.assertNotIn("%", html.split("barra-total")[1][:80] if "barra-total" in html else "")
        self.assertIn("1 contrato", html_destaque(2026, None, None, None, 1))


class RankingTests(unittest.TestCase):
    def test_numero_do_contrato_acompanhado_do_nome_e_escapado(self) -> None:
        html = html_ranking([_item(fornecedor="A & B <Ltda>")])
        self.assertIn("<b>14/2022</b>", html)
        self.assertIn("A &amp; B &lt;Ltda&gt;", html)
        self.assertNotIn("Contrato 14/2022", html)  # só o número, sem a palavra "Contrato"

    def test_ordena_por_acrescimo_com_nulos_por_ultimo_e_estados_visiveis(self) -> None:
        itens = [
            _item(contrato="B", acrescimo=None, situacao="Sem data-base (informe o início ou a data)", estado=None, data_base=None, percentual=None, origem=None, formalizado=None),
            _item(contrato="A", acrescimo=10.0, formalizado=None, projetado=10.0, estado="Projetado"),
            _item(contrato="C", acrescimo=500.0),
        ]
        html = html_ranking(itens)
        self.assertLess(html.index("<b>C</b>"), html.index("<b>A</b>"))
        self.assertLess(html.index("<b>A</b>"), html.index("<b>B</b>"))
        self.assertIn("Sem estimativa", html)      # contrato B continua visível, com o motivo
        self.assertIn("falta a data-base", html)
        self.assertIn("Projetado", html)

    def test_etiquetas_refletem_os_valores_formalizado_e_ou_projetado(self) -> None:
        ambos = html_ranking([_item(formalizado=100.0, projetado=50.0, estado="Projetado", acrescimo=150.0)])
        self.assertIn("Formalizado", ambos)
        self.assertIn("Projetado", ambos)
        so_projetado = html_ranking([_item(formalizado=None, projetado=50.0, estado="Projetado", acrescimo=50.0)])
        self.assertNotIn("Formalizado</span>", so_projetado)
        sem_valor = html_ranking([_item(formalizado=0.0, projetado=0.0, estado="Projetado", acrescimo=0.0)])
        self.assertIn("Projetado", sem_valor)  # sem valor positivo: cai no estado do próximo ciclo

    def test_valor_nulo_vira_traco(self) -> None:
        html = html_ranking([_item(acrescimo=None, formalizado=None)])
        self.assertNotIn("R$ 0,00", html)

    def test_limite_mostra_so_os_primeiros(self) -> None:
        itens = [_item(contrato=f"{i}/2026", acrescimo=float(i)) for i in range(1, 6)]
        html = html_ranking(itens, limite=2)
        self.assertEqual(html.count('class="rj-nome"'), 2)
        self.assertIn("<b>5/2026</b>", html)


class MapaTests(unittest.TestCase):
    def test_celulas_por_intensidade_nulo_como_traco_e_mes_da_data_base(self) -> None:
        pivot = pd.DataFrame({1: [None, 0.0], 9: [79000.0, None], 10: [79000.0, 5.0]}, index=["14/2022", "07/2026"])
        pivot = pivot.reindex(columns=range(1, 13))
        html = html_mapa(pivot, 2026, {"14/2022": {9}})
        self.assertIn("79 mil", html)
        self.assertIn("rj-base", html)  # contorno no mês da data-base
        self.assertEqual(html.count("rj-base"), 1)
        self.assertIn("—", html)        # nulo
        self.assertIn(">0<", html)      # zero conhecido continua zero
        self.assertIn("rj-h3", html)    # o maior valor tem a cor mais forte

    def test_so_mostra_contratos_com_acrescimo_ordenados_pelo_total_e_avisa_dos_ocultos(self) -> None:
        pivot = pd.DataFrame(
            {10: [0.0, 5.0, None, 900.0], 11: [0.0, 5.0, None, 900.0]}, index=["ZERO", "PEQUENO", "NULO", "GRANDE"]
        ).reindex(columns=range(1, 13))
        html = html_mapa(pivot, 2026, {})
        self.assertLess(html.index("GRANDE"), html.index("PEQUENO"))
        self.assertNotIn(">ZERO<", html)
        self.assertNotIn(">NULO<", html)
        self.assertIn("2 contratos sem acréscimo", html)  # o zero e o nulo ficaram de fora, avisados

    def test_sem_nenhum_acrescimo_diz_isso_em_vez_de_mapa_vazio(self) -> None:
        html = html_mapa(pd.DataFrame({10: [0.0]}, index=["A"]).reindex(columns=range(1, 13)), 2026, {})
        self.assertNotIn("<table", html)
        self.assertIn("nenhum acréscimo", html.lower())

    def test_sem_dados_nao_quebra(self) -> None:
        self.assertIn("Sem estimativa", html_mapa(pd.DataFrame(), 2026, {}))


class CiclosEGraficoTests(unittest.TestCase):
    def test_linha_do_tempo_dos_ciclos(self) -> None:
        ciclos = [
            SimpleNamespace(data_base=date(2026, 9, 1), estado="formalizado", percentual=4.26, origem="oficial"),
            SimpleNamespace(data_base=date(2027, 9, 1), estado="projetado", percentual=None, origem="sem_indice"),
        ]
        html = html_ciclos(ciclos)
        self.assertIn("01/09/2026", html)
        self.assertIn("4,26 %", html)
        self.assertIn("formalizado", html)
        self.assertIn("projetado", html)
        self.assertIn("sem percentual", html)  # percentual nulo não vira 0 %
        self.assertIn("Nenhum ciclo", html_ciclos([]))

    def test_grafico_mensal_barras_base_e_acrescimo(self) -> None:
        matriz = pd.DataFrame({
            "ano": [2026] * 3, "mes": [8, 9, 10], "base_valor": [1000.0, 1000.0, None],
            "acrescimo_formalizado": [None, 40.0, 40.0], "acrescimo_projetado": [None, None, None],
            "acrescimo": [None, 40.0, 40.0],
        })
        html = html_grafico_mensal(matriz, 2026)
        self.assertEqual(html.count('class="rj-col"'), 12)
        self.assertIn("rj-ac-f", html)
        self.assertNotIn("rj-ac-p", html)
        self.assertIn("set", html)
        self.assertIn("Sem estimativa", html_grafico_mensal(pd.DataFrame(), 2026))

    def _matriz_so_base(self) -> pd.DataFrame:
        return pd.DataFrame({
            "ano": [2026] * 4, "mes": [6, 7, 10, 11], "base_valor": [None, 704241.49, 792141.84, 792141.84],
            "base_origem": ["sem_liquidado", "liquidado", "contratado", "contratado"],
            "acrescimo_formalizado": [0.0] * 4, "acrescimo_projetado": [0.0] * 4, "acrescimo": [0.0] * 4,
        })

    def test_valor_sobre_cada_barra_e_origem_da_base_diferenciada(self) -> None:
        html = html_grafico_mensal(self._matriz_so_base(), 2026)
        self.assertIn("704 mil", html)   # valor compacto sobre a barra
        self.assertIn("792 mil", html)
        self.assertEqual(html.count('class="b teto"'), 2)   # meses de teto contratado, em estilo próprio
        self.assertEqual(html.count('class="b"'), 1)        # o liquidado (julho)
        self.assertIn("sem liquidado apurado", html)        # legenda dos meses sem barra

    def test_acrescimo_fica_empilhado_em_cima_da_base(self) -> None:
        matriz = pd.DataFrame({
            "ano": [2026], "mes": [9], "base_valor": [1000.0], "base_origem": ["liquidado"],
            "acrescimo_formalizado": [40.0], "acrescimo_projetado": [20.0], "acrescimo": [60.0],
        })
        coluna = html_grafico_mensal(matriz, 2026).split('title="set/2026')[1].split("</div></div>")[0]
        # de cima para baixo: valor, formalizado, projetado, base
        self.assertLess(coluna.index("rj-v"), coluna.index("rj-ac-f"))
        self.assertLess(coluna.index("rj-ac-f"), coluna.index("rj-ac-p"))
        self.assertLess(coluna.index("rj-ac-p"), coluna.index('class="b"'))
        self.assertIn("1,1 mil", coluna)  # valor sobre a coluna = base + acréscimo

    def test_sem_acrescimo_no_exercicio_avisa_que_so_ha_a_base(self) -> None:
        html = html_grafico_mensal(self._matriz_so_base(), 2026)
        self.assertIn("Sem acréscimo de reajuste neste exercício", html)
        com_acrescimo = self._matriz_so_base().assign(acrescimo_formalizado=[0.0, 0.0, 10.0, 10.0], acrescimo=[0.0, 0.0, 10.0, 10.0])
        self.assertNotIn("Sem acréscimo de reajuste neste exercício", html_grafico_mensal(com_acrescimo, 2026))

    def test_mes_sem_base_nao_ganha_barra_nem_valor_inventado(self) -> None:
        html = html_grafico_mensal(self._matriz_so_base(), 2026)
        import re
        coluna_junho = re.search(r'title="jun/2026[^"]*">(.*?)<div class="rj-col"', html, re.S).group(1)
        self.assertEqual(coluna_junho, "</div>")  # coluna vazia: sem barra e sem valor


if __name__ == "__main__":
    unittest.main()
