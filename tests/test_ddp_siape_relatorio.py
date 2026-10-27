"""Testes de `src.ddp_siape_relatorio` (relatório em Excel da aba Folha (DDP), 27/10/2026).

Monta o relatório com a base sintética de `tests.test_ddp_siape` (folha + RPPS) e confere a
organização: abas, cabeçalhos em português, notas de empenho completas, totais por fórmula que
fecham com as tabelas da aba, e o resumo."""
from __future__ import annotations

import unittest
from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from src.ddp_siape import (
    conciliacao_por_acao, conferencia, confronto_liquidado, ddp_por_natureza, plano_operacoes, quadro_reforco,
    quadro_sem_ddp, reforco_por_acao_po, variacao_por_natureza,
)
from src.ddp_siape_relatorio import DadosRelatorio, LINHA_CABECALHO, relatorio_excel
from src.despesas_pessoal import GRUPO_RPPS
from tests.test_ddp_siape import RESERVA, _base_sintetica, _ddp_sintetica, _item, _relatorios_set

ABAS = ["Resumo", "Reforço por empenho", "Plano por item", "Dotação por ação e PO", "Painel × quadro",
        "Detalhe por item", "Conferência da DDP"]


def _dados(com_variacao=False):
    base = pd.concat([_base_sintetica(), pd.DataFrame(
        _item(10, "31911303", 1000.0, {202608: 300.0, 202609: 300.0}, acao="09HB", favorecido="FUNDO RPPS"))],
        ignore_index=True)
    grade = pd.DataFrame([{"grupo": GRUPO_RPPS, "natureza_detalhada_cod": "31911303", "natureza_detalhada_desc": "RPPS",
                           "meses": [None] * 7 + [300.0, 300.0, 350.0, 700.0, 350.0]}])
    natureza = _ddp_sintetica()
    itens, por_empenho = quadro_reforco(natureza, base, 202610, RESERVA)
    itens_rpps, por_empenho_rpps = quadro_sem_ddp(base, 202610, grade, GRUPO_RPPS)
    quadros = [(itens, por_empenho), (itens_rpps, por_empenho_rpps)]
    dotacao = pd.Series({("20TP", "X"): 7000.0, ("2004", "X"): 10500.0, ("09HB", "X"): 1900.0})
    relatorios = _relatorios_set()
    return DadosRelatorio(
        competencia=202610, procedencia="Procedência de teste.", conferencia=conferencia(relatorios), natureza=natureza,
        por_empenho=por_empenho, itens=itens, plano=plano_operacoes(itens), confronto=confronto_liquidado(natureza, base, 202610),
        rpps_itens=itens_rpps, rpps_por_empenho=por_empenho_rpps, acao_po=reforco_por_acao_po(quadros, base, 2026, dotacao),
        conciliacao=conciliacao_por_acao(quadros, base, 202610, grade, dotacao), ano_dotacao=2026,
        variacao=variacao_por_natureza(natureza, ddp_por_natureza(relatorios)) if com_variacao else None,
        competencia_anterior=202609 if com_variacao else None,
    )


def _valores(aba, coluna):
    """Valores numéricos de uma coluna de tabela (linhas de dados, sem a de total)."""
    valores = []
    for linha in aba.iter_rows(min_row=LINHA_CABECALHO + 1, min_col=coluna, max_col=coluna):
        v = linha[0].value
        if isinstance(v, str) and v.startswith("="):
            break
        if isinstance(v, (int, float)):
            valores.append(v)
    return valores


class TestRelatorioExcel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dados = _dados(com_variacao=True)
        cls.livro = load_workbook(BytesIO(relatorio_excel(cls.dados)))

    def test_abas_na_ordem_de_leitura(self):
        self.assertEqual(self.livro.sheetnames, ABAS)

    def test_cabecalhos_em_portugues_sem_nomes_tecnicos(self):
        for nome in ABAS:
            aba = self.livro[nome]
            cabecalho = [c.value for c in aba[LINHA_CABECALHO] if c.value]
            self.assertTrue(cabecalho, nome)
            for titulo in cabecalho:
                with self.subTest(aba=nome, titulo=titulo):
                    self.assertNotIn("_", str(titulo))

    def test_resumo_traz_os_totais_das_tabelas(self):
        resumo = {r[0].value: r[1].value for r in self.livro["Resumo"].iter_rows(min_row=LINHA_CABECALHO + 1) if r[0].value}
        d = self.dados
        self.assertEqual(resumo["DDP líquida do mês (servidor + pensionista)"], round(d.natureza["liquido"].sum(), 2))
        self.assertEqual(resumo["Reforço do mês — empenhos da folha"], 246.0)
        self.assertEqual(resumo["Coberto anulando sobra de outro item da mesma NE"], 200.0)
        self.assertEqual(resumo["Reforço até dezembro — RPPS patronal (projeção)"], 1000.0)
        # 2004/X: falta de dotação de 300 (ver test_ddp_siape.TestReforcoPorAcaoPo)
        self.assertEqual(resumo["2004 / X"], 300.0)

    def test_reforco_por_empenho_com_nota_completa_e_total_por_formula(self):
        aba = self.livro["Reforço por empenho"]
        notas = [c.value for c in aba["B"][LINHA_CABECALHO:] if c.value]
        self.assertIn("2026NE000001", notas)
        self.assertIn("2026NE000004, 2026NE000005", notas)
        self.assertIn("(sem empenho)", notas)
        reforco_mes = _valores(aba, 9)
        self.assertEqual(round(sum(reforco_mes), 2), 246.0)
        linha_total = LINHA_CABECALHO + 1 + len(self.dados.por_empenho)
        self.assertEqual(aba.cell(row=linha_total, column=1).value, "Total")
        self.assertTrue(str(aba.cell(row=linha_total, column=9).value).startswith("=SUM(I"))

    def test_plano_com_descricoes_e_totais_por_operacao(self):
        aba = self.livro["Plano por item"]
        linhas = [[c.value for c in r] for r in aba.iter_rows(min_row=LINHA_CABECALHO + 1, max_row=LINHA_CABECALHO + len(self.dados.plano))]
        remanejo = next(l for l in linhas if l[0] == "NE000001")
        self.assertEqual(remanejo[2], "Anular e reforçar no mesmo empenho")
        self.assertEqual((remanejo[3], remanejo[5], remanejo[7]), ("31901143", "31901101", 200.0))
        self.assertEqual(remanejo[6], "DESC 31901101")
        self.assertEqual(round(sum(l[7] for l in linhas), 2), 446.0)
        textos = [c.value for c in aba["A"] if c.value]
        self.assertIn("Por tipo de operação", textos)

    def test_dotacao_por_acao_com_situacao(self):
        aba = self.livro["Dotação por ação e PO"]
        situacao = {aba.cell(row=r, column=1).value: aba.cell(row=r, column=9).value
                    for r in range(LINHA_CABECALHO + 1, LINHA_CABECALHO + 1 + len(self.dados.acao_po))}
        self.assertEqual(situacao["2004"], "Não cabe")
        self.assertEqual(situacao["20TP"], "Cabe")
        self.assertEqual(situacao["0181"], "Sem dotação na base")

    def test_conferencia_com_variacao_e_confronto(self):
        textos = [c.value for c in self.livro["Conferência da DDP"]["A"] if isinstance(c.value, str)]
        self.assertIn("O que mudou de set/2026 para out/2026", textos)
        self.assertIn("DDP × Liquidada na base em out/2026", textos)

    def test_sem_dotacao_nem_variacao_omite_as_abas_correspondentes(self):
        dados = _dados()
        dados.acao_po = dados.conciliacao = None
        livro = load_workbook(BytesIO(relatorio_excel(dados)))
        self.assertEqual(livro.sheetnames, ["Resumo", "Reforço por empenho", "Plano por item", "Detalhe por item", "Conferência da DDP"])
        textos = [c.value for c in livro["Conferência da DDP"]["A"] if isinstance(c.value, str)]
        self.assertFalse(any(t.startswith("O que mudou") for t in textos))


if __name__ == "__main__":
    unittest.main()
