"""Testes do relatório (PDF/Excel) de Empenhos com Execução Retardada —
`src/relatorio_empenhos_retardada.py`. Lista sintética, montada à mão, no mesmo formato de
colunas que a página passa (`saldo_por_ne(agregar_por_ne(...))` + `percentual_saldo` +
`passa_corte`)."""

from __future__ import annotations

import unittest
from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from src.relatorio_empenhos_retardada import ContextoRelatorio, gerar_pdf, gerar_xlsx, montar_lista_relatorio


def _lista() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ne_ccor": ["153165152662026NE000056", "153165152662026NE000123", "153165152662026NE000200"],
            "ano": [2026, 2026, 2026],
            "ne_favorecido": ["EMPRESA A", "EMPRESA B & CIA <LTDA>", None],
            "ne_descricao": ["Serviço", None, "Bolsa"],
            "processo_ne": ["23082.000001/2026-01", None, "23082.000003/2026-03"],
            "acao_cod": ["20RK", "20RK", "4002"],
            "acao_desc": ["FUNCIONAMENTO", "FUNCIONAMENTO", "ASSISTENCIA"],
            "ptres": ["012345", "012345", "000789"],
            "fonte_cod": ["1000000000", "1000000000", "1000000000"],
            "fonte_desc": ["RECURSOS", "RECURSOS", "RECURSOS"],
            "gnd_cod": ["3", "3", "3"],
            "natureza_despesa_cod": ["339039", "339039", "339018"],
            "natureza_despesa_desc": ["OUTROS SERV.", "OUTROS SERV.", "AUX. FINANC."],
            "natureza_detalhada_label": ["33903917", "33903917", "33901801"],
            "subitem_resumo": ["17", "17", "01"],
            "pi_cod": ["L20RKG0100N", "L20RKG0100N", "M4002G0101N"],
            "pi_desc": ["PI A", "PI A", "PI B"],
            "ugr_cod": ["153165", "153165", "153165"],
            "ugr_desc": ["UGR", "UGR", "UGR"],
            "ug_executora_cod": ["153165", "153165", "153165"],
            "ne_informacao_complementar": [None, None, None],
            "empenhada": [100_000.0, 50_000.0, None],
            "liquidada": [40_000.0, 0.0, None],
            "saldo": [60_000.0, 50_000.0, None],
            "percentual_saldo": [60.0, 100.0, None],
            "passa_corte": [True, True, False],
        }
    )


def _contexto(**kwargs) -> ContextoRelatorio:
    padrao = dict(
        visualizacao="Todos no escopo",
        descricao_corte="saldo ≥ R$ 10.000",
        data_extracao="28/09/2026",
        hash_manifesto="abcdef12",
        data_emissao="28/09/2026 10:00",
        busca="",
        filtros=[("Exercício", ["2026"])],
    )
    padrao.update(kwargs)
    return ContextoRelatorio(**padrao)


class MontarListaRelatorioTests(unittest.TestCase):
    def setUp(self) -> None:
        # ordem de entrada propositalmente fora da ordem de saldo; NE com saldo nulo no meio.
        self.visivel = pd.DataFrame(
            {"ne_ccor": ["A", "B", "C", "D"], "saldo": [5_000.0, None, 80_000.0, 20_000.0]},
            index=[10, 11, 12, 13],
        )
        self.destaque = pd.Series([False, False, True, True], index=self.visivel.index)

    def test_em_destaque_so_as_marcadas_ordenadas_por_saldo(self) -> None:
        lista = montar_lista_relatorio(self.visivel, self.destaque, cortes_ligados=True, todos=False)
        self.assertEqual(lista["ne_ccor"].tolist(), ["C", "D"])
        self.assertEqual(lista["passa_corte"].tolist(), [True, True])
        self.assertEqual(lista.index.tolist(), [0, 1])

    def test_todos_inclui_todas_com_nulo_por_ultimo(self) -> None:
        lista = montar_lista_relatorio(self.visivel, self.destaque, cortes_ligados=True, todos=True)
        self.assertEqual(lista["ne_ccor"].tolist(), ["C", "D", "A", "B"])
        self.assertEqual(lista["passa_corte"].tolist(), [True, True, False, False])
        self.assertTrue(pd.isna(lista["saldo"].iloc[-1]))  # nulo preservado, não virou zero

    def test_sem_corte_ligado_passa_corte_nulo(self) -> None:
        sem_destaque = pd.Series(False, index=self.visivel.index)
        lista = montar_lista_relatorio(self.visivel, sem_destaque, cortes_ligados=False, todos=True)
        self.assertEqual(len(lista), 4)
        self.assertTrue(lista["passa_corte"].isna().all())

    def test_nao_altera_a_entrada(self) -> None:
        original = self.visivel.copy()
        montar_lista_relatorio(self.visivel, self.destaque, cortes_ligados=True, todos=True)
        pd.testing.assert_frame_equal(self.visivel, original)


class GerarXlsxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lista = _lista()
        self.original = self.lista.copy()
        conteudo = gerar_xlsx(self.lista, _contexto())
        self.livro = load_workbook(BytesIO(conteudo))

    def _linhas(self) -> list[dict]:
        planilha = self.livro["Empenhos"]
        cabecalho = [c.value for c in planilha[1]]
        return [dict(zip(cabecalho, [c.value for c in linha])) for linha in planilha.iter_rows(min_row=2)]

    def test_uma_linha_por_empenho_sem_linha_de_total(self) -> None:
        self.assertEqual(len(self._linhas()), 3)

    def test_codigos_ficam_como_texto_com_zeros_iniciais(self) -> None:
        linha = self._linhas()[0]
        self.assertEqual(linha["PTRES"], "012345")
        self.assertEqual(linha["NE"], "2026NE000056")
        self.assertEqual(linha["NE (código completo)"], "153165152662026NE000056")
        self.assertEqual(self._linhas()[2]["Subitem"], "01")

    def test_valores_numericos_e_nulo_distinto_de_zero(self) -> None:
        linhas = self._linhas()
        self.assertEqual(linhas[0]["Saldo"], 60_000.0)
        self.assertEqual(linhas[1]["Liquidado"], 0.0)  # zero continua zero
        self.assertIsNone(linhas[2]["Empenhado"])  # nulo continua vazio
        self.assertIsNone(linhas[2]["% Saldo"])

    def test_passa_do_corte(self) -> None:
        self.assertEqual([l["Passa do corte"] for l in self._linhas()], ["Sim", "Sim", "Não"])

    def test_sem_corte_ligado_passa_do_corte_fica_vazio(self) -> None:
        lista = _lista().assign(passa_corte=pd.NA)
        livro = load_workbook(BytesIO(gerar_xlsx(lista, _contexto(descricao_corte=None))))
        planilha = livro["Empenhos"]
        cabecalho = [c.value for c in planilha[1]]
        coluna = cabecalho.index("Passa do corte")
        self.assertEqual([linha[coluna].value for linha in planilha.iter_rows(min_row=2)], [None, None, None])

    def test_aba_parametros_com_procedencia_filtros_e_totais(self) -> None:
        parametros = {linha[0].value: linha[1].value for linha in self.livro["Parâmetros"].iter_rows(min_row=2)}
        self.assertEqual(parametros["Visualização"], "Todos no escopo")
        self.assertEqual(parametros["Exercício"], "2026")
        self.assertIn("abcdef12", parametros["Procedência"])
        self.assertEqual(parametros["Empenhos listados"], "3")
        self.assertEqual(parametros["Total saldo"], "110.000,00")

    def test_nao_altera_a_lista_recebida(self) -> None:
        pd.testing.assert_frame_equal(self.lista, self.original)


class GerarPdfTests(unittest.TestCase):
    def test_gera_pdf_valido_com_texto_escapado(self) -> None:
        conteudo = gerar_pdf(_lista(), _contexto(busca="a & b"))
        self.assertTrue(conteudo.startswith(b"%PDF"))

    def test_gera_pdf_com_muitas_linhas_em_varias_paginas(self) -> None:
        lista = pd.concat([_lista()] * 200, ignore_index=True)
        conteudo = gerar_pdf(lista, _contexto(descricao_corte=None, filtros=[]))
        self.assertTrue(conteudo.startswith(b"%PDF"))
        self.assertGreater(conteudo.count(b"/Type /Page\n") + conteudo.count(b"/Type /Page "), 1)


if __name__ == "__main__":
    unittest.main()
