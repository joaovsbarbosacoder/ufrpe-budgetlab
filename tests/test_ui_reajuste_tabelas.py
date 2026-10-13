"""Tabelas da página "Reajuste estimado" refeitas em HTML (12/10/2026) e nome do credor no mapa.

Regras: nulo = "—" (nunca "None"), zero conhecido = "R$ 0,00" esmaecido; moeda em pt-BR; número do contrato acompanhado do nome
do credor; textos escapados; tudo vem de valores já estimados (nada é recalculado).
"""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.ui_reajuste_visual import html_mapa, html_tabela_competencias, html_tabela_resumo

ANO = 2026


def _resumo() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Contrato": "14/2022", "Fornecedor": "Inteligência Segurança Privada Ltda", "Situação": "Estimado",
            "Data-base": date(2026, 9, 1), "Estado do ciclo": "Formalizado, a confirmar", "Percentual (%)": 4.2576,
            "Origem do %": "Oficial (12 meses)", f"Formalizado a confirmar {ANO}": 318400.5, f"Projetado {ANO}": None,
            f"Acréscimo {ANO}": 318400.5, "Exercícios anteriores": 1234.56, "Acréscimo na vigência": 400000.0,
            "Competências sem estimativa": 0, "Ciclos a confirmar": "01/09/2026", "Retroativo no gov (contrato inteiro)": 412000.0,
        },
        {
            "Contrato": "99/2026", "Fornecedor": "A & B <Ltda>", "Situação": "Sem data-base (informe o início ou a data)",
            "Data-base": None, "Estado do ciclo": None, "Percentual (%)": None, "Origem do %": None,
            f"Formalizado a confirmar {ANO}": None, f"Projetado {ANO}": None, f"Acréscimo {ANO}": None,
            "Exercícios anteriores": None, "Acréscimo na vigência": None, "Competências sem estimativa": 13,
            "Ciclos a confirmar": None, "Retroativo no gov (contrato inteiro)": None,
        },
        {
            "Contrato": "07/2026", "Fornecedor": None, "Situação": "Estimado", "Data-base": date(2027, 1, 5),
            "Estado do ciclo": "Projetado", "Percentual (%)": 0.0, "Origem do %": "Manual",
            f"Formalizado a confirmar {ANO}": 0.0, f"Projetado {ANO}": 0.0, f"Acréscimo {ANO}": 0.0,
            "Exercícios anteriores": None, "Acréscimo na vigência": 12.5, "Competências sem estimativa": 0,
            "Ciclos a confirmar": None, "Retroativo no gov (contrato inteiro)": None,
        },
    ])


class TabelaResumoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = html_tabela_resumo(_resumo(), ANO)

    def test_numero_com_nome_do_credor_moeda_ptbr_e_nunca_none(self) -> None:
        self.assertIn("<b>14/2022</b>", self.html)
        self.assertIn("Inteligência Segurança Privada Ltda", self.html)
        self.assertIn("R$ 318.400,50", self.html)
        self.assertIn("R$ 1.234,56", self.html)
        self.assertIn("4,26 %", self.html)
        self.assertNotIn("None", self.html)
        self.assertNotIn("nan", self.html.lower().replace("inteligência", "").replace("manual", ""))
        self.assertNotIn("R$ 318400", self.html)  # nada de formato "R$ 318400.50"

    def test_nulo_e_traco_zero_conhecido_continua_zero(self) -> None:
        linha_99 = self.html.split("<b>99/2026</b>")[1].split("</tr>")[0]
        self.assertIn("—", linha_99)
        self.assertNotIn("R$ 0,00", linha_99)  # tudo nulo: traço, não zero
        linha_07 = self.html.split("<b>07/2026</b>")[1].split("</tr>")[0]
        self.assertIn("R$ 0,00", linha_07)       # zero conhecido
        self.assertIn("0,00 %", linha_07)        # percentual manual 0 continua 0

    def test_contrato_sem_estimativa_aparece_com_motivo_e_observacoes(self) -> None:
        linha_99 = self.html.split("<b>99/2026</b>")[1].split("</tr>")[0]
        self.assertIn("Sem estimativa", linha_99)
        self.assertIn("falta a data-base", linha_99)
        self.assertIn("13 competência(s) sem estimativa", linha_99)
        linha_14 = self.html.split("<b>14/2022</b>")[1].split("</tr>")[0]
        self.assertIn("01/09/2026", linha_14)            # ciclo a confirmar
        self.assertIn("R$ 412.000,00", linha_14)         # retroativo no gov, só referência

    def test_textos_escapados_e_linha_de_totais(self) -> None:
        self.assertIn("A &amp; B &lt;Ltda&gt;", self.html)
        self.assertIn("sem credor no cadastro", self.html)
        totais = self.html.split('class="rj-total"')[1]
        self.assertIn("R$ 318.400,50", totais)   # só o 14/2022 tem formalizado (nulos e zero não mudam a soma)
        self.assertIn("R$ 400.012,50", totais)   # acréscimo na vigência: 400000 + 12,5

    def test_sem_nenhum_valor_o_total_e_traco(self) -> None:
        vazio = _resumo().iloc[[1]]
        totais = html_tabela_resumo(vazio, ANO).split('class="rj-total"')[1]
        self.assertNotIn("R$ 0,00", totais)

    def test_rola_na_horizontal_em_tela_estreita(self) -> None:
        self.assertIn("rj-rolagem", self.html)


def _matriz() -> pd.DataFrame:
    return pd.DataFrame({
        "competencia": ["07/2026", "08/2026", "09/2026", "01/2026"], "exercicio_anterior": [False, False, False, True],
        "base_valor": [None, 704241.49, 792141.84, 500.0], "base_origem": ["sem_liquidado", "liquidado", "contratado", "liquidado"],
        "ciclo": [0, 1, 1, 1], "data_base": [None, date(2026, 8, 1), date(2026, 8, 1), date(2025, 12, 1)],
        "estado_ciclo": [None, "formalizado", "projetado", "formalizado"], "percentual": [None, 4.26, 4.26, 3.9],
        "percentual_origem": [None, "oficial", "oficial", "manual"], "acrescimo_formalizado": [0.0, 1000.0, None, 5.0],
        "acrescimo_projetado": [0.0, 0.0, 2000.0, 0.0], "acrescimo": [0.0, 1000.0, 2000.0, 5.0],
        "prorrogacao_prevista": [False, False, True, False],
    })


class TabelaCompetenciasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = html_tabela_competencias(_matriz())

    def test_formato_ptbr_sem_none_e_sem_inventar_valor(self) -> None:
        self.assertIn("R$ 704.241,49", self.html)
        self.assertIn("R$ 792.141,84", self.html)
        self.assertNotIn("None", self.html)
        linha_07 = self.html.split("07/2026")[1].split("</tr>")[0]
        self.assertIn("—", linha_07)  # base sem liquidado apurado: nulo, não zero
        self.assertIn("Sem liquidado apurado", linha_07)

    def test_origem_estado_e_percentual_legiveis(self) -> None:
        self.assertIn("Contratado (teto)", self.html)
        self.assertIn("Liquidado", self.html)
        self.assertIn("4,26 %", self.html)
        self.assertIn("Manual", self.html)
        self.assertIn("Formalizado", self.html)
        self.assertIn("Projetado", self.html)
        self.assertIn("01/08/2026", self.html)

    def test_marcas_de_exercicio_anterior_e_prorrogacao(self) -> None:
        self.assertIn("exercício anterior", self.html)
        self.assertEqual(self.html.count("prorrogação prevista"), 1)

    def test_vazio_nao_quebra(self) -> None:
        self.assertIn("Sem estimativa", html_tabela_competencias(pd.DataFrame()))


class MapaComCredorTests(unittest.TestCase):
    def test_linha_do_mapa_traz_o_numero_com_o_nome_do_credor_escapado(self) -> None:
        pivot = pd.DataFrame({10: [100.0]}, index=["14/2022"]).reindex(columns=range(1, 13))
        html = html_mapa(pivot, 2026, {}, {"14/2022": "A & B <Ltda>"})
        self.assertIn("<b>14/2022</b>", html)
        self.assertIn("A &amp; B &lt;Ltda&gt;", html)

    def test_sem_credor_so_o_numero(self) -> None:
        pivot = pd.DataFrame({10: [100.0]}, index=["14/2022"]).reindex(columns=range(1, 13))
        html = html_mapa(pivot, 2026, {})
        self.assertIn("<b>14/2022</b>", html)
        self.assertNotIn("rj-credor", html)


if __name__ == "__main__":
    unittest.main()
