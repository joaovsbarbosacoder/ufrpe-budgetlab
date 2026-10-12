"""Exportação (Excel/PDF) da visão consolidada da conciliação por competência (12/10/2026).

Entrada: as linhas de `consolidar_exercicio` com `ano` e `credor`. Nulo ≠ zero; valor ajustado por decisão marcado;
credor vem do cadastro de Contínuos.
"""

from __future__ import annotations

import unittest
from io import BytesIO

import pandas as pd

from src.relatorio_conciliacao_consolidada import gerar_pdf, gerar_xlsx, tabela_detalhe, tabela_matriz


def _mes(mes, rel=None, notas=None, classe="sem_registro", ajustadas=None, acao=""):
    return {"mes": mes, "relatorio": rel, "notas": notas, "classe": classe, "acao": acao, "assinatura": "x", "notas_ajustadas": ajustadas}


def _linhas() -> list[dict]:
    meses_a = [_mes(m) for m in range(1, 13)]
    meses_a[0] = _mes(1, 1000.0, 1000.0, "batem")
    meses_a[1] = _mes(2, 2560.24, 3810.24, "confirmada", ajustadas=2560.24)
    meses_a[2] = _mes(3, 500.0, 700.0, "deslocamento", acao="Corrigir a competência da nota no Contratos.gov")
    meses_a[3] = _mes(4, None, 90.0, "so_notas")
    meses_b = [_mes(m) for m in range(1, 13)]
    meses_b[0] = _mes(1, 0.0, 0.0, "batem")  # zero de verdade
    return [
        {"contrato": "23/2025", "ano": 2026, "credor": "Serval Serviços e Limpeza Ltda", "meses": meses_a,
         "total_relatorio": 4060.24, "total_notas": 5600.24, "total_notas_ajustado": 4350.24},
        {"contrato": "10/2026", "ano": 2026, "credor": None, "meses": meses_b,
         "total_relatorio": 0.0, "total_notas": 0.0, "total_notas_ajustado": 0.0},
    ]


class TabelasTests(unittest.TestCase):
    def test_matriz_traz_contrato_credor_12_meses_e_totais(self) -> None:
        t = tabela_matriz(_linhas())
        self.assertEqual(list(t.columns[:2]), ["Contrato", "Credor"])
        self.assertEqual(list(t.columns[2:14]), ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"])
        self.assertEqual(list(t.columns[14:]), ["Total relatório", "Total notas"])
        a = t.iloc[0]
        self.assertEqual((a["Contrato"], a["Credor"], a["Jan"], a["Fev"]), ("23/2025", "Serval Serviços e Limpeza Ltda", 1000.0, 2560.24))
        self.assertEqual(a["Abr"], 90.0)  # só nota: mostra a nota (como na tela)
        self.assertTrue(pd.isna(a["Mai"]))  # sem registro: nulo, não zero
        self.assertEqual(a["Total notas"], 4350.24)  # usa o total ajustado por decisão
        b = t.iloc[1]
        self.assertEqual(b["Jan"], 0.0)  # zero continua zero
        self.assertEqual(b["Credor"], "—")  # contrato sem credor no cadastro

    def test_detalhe_so_tem_meses_com_dado_e_marca_o_ajuste_e_a_diferenca(self) -> None:
        d = tabela_detalhe(_linhas())
        self.assertEqual(list(d["Competência"]), ["01/2026", "02/2026", "03/2026", "04/2026", "01/2026"])
        fev = d[(d["Contrato"] == "23/2025") & (d["Competência"] == "02/2026")].iloc[0]
        self.assertEqual((fev["Situação"], fev["Valor nas notas"], fev["Valor das notas ajustado"]), ("Sugestão confirmada", 3810.24, 2560.24))
        mar = d[d["Competência"] == "03/2026"].iloc[0]
        self.assertEqual((mar["Diferença"], mar["Ação sugerida"]), (200.0, "Corrigir a competência da nota no Contratos.gov"))
        abr = d[d["Competência"] == "04/2026"].iloc[0]
        self.assertTrue(pd.isna(abr["Valor no relatório"]) and pd.isna(abr["Diferença"]))  # nulo ≠ zero
        self.assertTrue(pd.isna(d.iloc[0]["Valor das notas ajustado"]))  # sem decisão: sem ajuste

    def test_sem_linhas_devolve_tabelas_vazias_com_colunas(self) -> None:
        self.assertTrue(tabela_matriz([]).empty)
        self.assertIn("Contrato", tabela_matriz([]).columns)
        self.assertIn("Competência", tabela_detalhe([]).columns)


class TelaTests(unittest.TestCase):
    def test_credor_aparece_ao_lado_do_contrato_e_escapado(self) -> None:
        from src.ui_conciliacao_competencia import html_consolidada
        linhas = _linhas()
        linhas[1]["credor"] = "A & B <Ltda>"
        html = html_consolidada(linhas)
        self.assertIn("Serval Serviços e Limpeza Ltda", html)
        self.assertIn("A &amp; B &lt;Ltda&gt;", html)
        self.assertEqual(html.count("cmp-credor"), 2)
        sem = html_consolidada([{**_linhas()[1], "credor": None}])
        self.assertNotIn('class="cmp-credor"', sem)  # sem credor no cadastro: nada é inventado


class ArquivosTests(unittest.TestCase):
    def test_excel_tem_as_abas_matriz_e_detalhe(self) -> None:
        xlsx = pd.ExcelFile(BytesIO(gerar_xlsx(_linhas(), 2026, "12/10/2026 10:00")))
        self.assertEqual(xlsx.sheet_names, ["Matriz", "Detalhe mensal"])
        matriz = xlsx.parse("Matriz", header=2)
        self.assertEqual(matriz.iloc[0]["Credor"], "Serval Serviços e Limpeza Ltda")
        self.assertEqual(len(xlsx.parse("Detalhe mensal", header=2)), 5)

    def test_pdf_e_gerado_com_credor_e_exercicio(self) -> None:
        pdf = gerar_pdf(_linhas(), 2026, "12/10/2026 10:00")
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1500)

    def test_pdf_e_excel_sem_linhas_nao_quebram(self) -> None:
        self.assertTrue(gerar_pdf([], 2026, "x").startswith(b"%PDF"))
        self.assertEqual(pd.ExcelFile(BytesIO(gerar_xlsx([], 2026, "x"))).sheet_names, ["Matriz", "Detalhe mensal"])


if __name__ == "__main__":
    unittest.main()
