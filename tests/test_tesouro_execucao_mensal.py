"""
Testes da base MENSAL de Execução da Despesa (a partir de 2026).

Usa uma fixture congelada em `tests/fixtures/execucao_mensal_2026-09-03.xlsx` (não um arquivo
de `data/raw/` — esta base ainda não tem importação versionada própria, ver
docs/base_execucao_mensal.md) — pulado se o arquivo não existir.

Dois níveis, mesmo espírito de `test_execucao_anual.py`:
  * INVARIANTES — valem para qualquer extração desta base.
  * REFERÊNCIA — totais absolutos da extração identificada por hash (`REFERENCIAS`). Ao
    trocar a fixture, NÃO edite os números existentes: acrescente uma entrada nova.

IMPORTANTE: ao atualizar a planilha de trabalho, NÃO sobrescreva esta fixture automaticamente
— mesma regra das demais fixtures deste diretório (ver AGENTS.md).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import openpyxl

from src.tesouro_execucao_mensal import (
    COLUNAS_DIMENSAO,
    ErroLayoutBase,
    _blocos_mensais,
    _rotulo_mes,
    ler_execucao_mensal,
    linha_do_tempo_por_ne,
    reconciliar,
    valor_empenhado_por_bloco,
    validar,
)

CAMINHO_BASE = Path("tests/fixtures/execucao_mensal_2026-09-03.xlsx")

# Extração recebida em 03/09/2026 (repassada pelo usuário via Downloads, hash e39a028a...).
# Ao trocar a fixture, NÃO edite estes números: acrescente uma entrada nova (o hash decide
# qual referência se aplica).
REFERENCIAS = {
    "e39a028a": {
        "descricao": "Extração recebida em 03/09/2026, meses JAN-SET/2026",
        "linhas_originais": 4295,
        "linhas_empenho": 3869,
        "linhas_item_execucao": 426,
        "notas_empenho_distintas": 531,
        "meses": [202601, 202602, 202603, 202604, 202605, 202606, 202607, 202608, 202609],
        # Conferido, até o centavo, contra o manifesto da base ANUAL importado no mesmo dia
        # (src.importacao_execucao.Manifesto.atual(), base "execucao_anual") — ver
        # docs/base_execucao_mensal.md, seção de validação cruzada.
        "totais": {
            "empenhada": 779416610.23,
            "liquidada": 579124824.19,
            "paga": 537533784.32,
        },
    },
}


def _hash_curto(caminho: Path) -> str:
    import hashlib

    return hashlib.sha256(caminho.read_bytes()).hexdigest()[:8]


class TestRotuloMes(unittest.TestCase):
    def test_rotulo_valido(self):
        self.assertEqual(_rotulo_mes("JAN/2026"), (2026, 1))
        self.assertEqual(_rotulo_mes("set/2026"), (2026, 9))
        self.assertEqual(_rotulo_mes("DEZ/2027"), (2027, 12))

    def test_rotulo_invalido_devolve_none(self):
        self.assertIsNone(_rotulo_mes("Ano Lançamento"))
        self.assertIsNone(_rotulo_mes(None))
        self.assertIsNone(_rotulo_mes(float("nan")))
        self.assertIsNone(_rotulo_mes("XXX/2026"))


class TestBlocosMensais(unittest.TestCase):
    """`_blocos_mensais` nunca deve assumir uma quantidade fixa de meses — a extração cresce
    um bloco por vez ao longo do exercício."""

    def _linha1(self, rotulos: list[str]) -> list:
        base = [None] * len(COLUNAS_DIMENSAO)
        colunas = []
        for rotulo in rotulos:
            colunas.extend([rotulo, rotulo, rotulo])
        return base + colunas

    def test_detecta_um_unico_mes(self):
        blocos = _blocos_mensais(self._linha1(["JAN/2026"]))
        self.assertEqual(blocos, [(len(COLUNAS_DIMENSAO), 2026, 1)])

    def test_detecta_varios_meses_em_sequencia(self):
        blocos = _blocos_mensais(self._linha1(["JAN/2026", "FEV/2026", "MAR/2026"]))
        primeira = len(COLUNAS_DIMENSAO)
        self.assertEqual(blocos, [(primeira, 2026, 1), (primeira + 3, 2026, 2), (primeira + 6, 2026, 3)])

    def test_sem_nenhum_bloco_e_erro(self):
        with self.assertRaises(ErroLayoutBase):
            _blocos_mensais([None] * len(COLUNAS_DIMENSAO))

    def test_bloco_incompleto_e_erro(self):
        linha = self._linha1(["JAN/2026"])[:-1]  # falta a 3a coluna do bloco
        with self.assertRaises(ErroLayoutBase):
            _blocos_mensais(linha)


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestLeituraEValidacaoAssinatura(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_mensal(CAMINHO_BASE)

    def test_devolve_uma_linha_por_linha_bruta_vezes_mes(self):
        linhas_originais = self.df["linha_origem"].nunique()
        n_meses = self.df["ano_mes"].nunique()
        self.assertEqual(len(self.df), linhas_originais * n_meses)

    def test_colunas_essenciais_presentes(self):
        for coluna in (
            "ne_ccor", "ne_item_cod", "ne_item_desc", "natureza_detalhada_cod", "subitem_cod",
            "mes", "ano_mes", "empenhada", "liquidada", "paga", "tipo_linha", "linha_origem",
        ):
            self.assertIn(coluna, self.df.columns)

    def test_tipo_linha_reproduz_regra_da_base_anual(self):
        por_linha_original = self.df.drop_duplicates("linha_origem")
        contagem = por_linha_original["tipo_linha"].value_counts()
        self.assertEqual(int(contagem.get("empenho", 0)), 3869)
        self.assertEqual(int(contagem.get("item_execucao", 0)), 426)

    def test_layout_diferente_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            wb = openpyxl.load_workbook(CAMINHO_BASE)
            aba = wb.active
            aba.cell(row=1, column=1).value = "Outra Coisa"  # não mais "Iduso"
            destino = Path(tmp) / CAMINHO_BASE.name
            wb.save(destino)
            with self.assertRaises(ErroLayoutBase):
                ler_execucao_mensal(destino)


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestValorEmpenhadoPorBloco(unittest.TestCase):
    """A regra que evita contar o Empenhado a mais: o valor de um (NE, Natureza Detalhada,
    Subitem, mês) aparece repetido em toda linha de item daquele bloco — somar sem deduplicar
    multiplicaria o Empenhado pela quantidade de itens. Confirmado manualmente contra dois
    casos reais da extração de referência: um de folha de pagamento (GND 1, vários "itens"
    fixos por natureza) e um de material de consumo (Elemento 30, itens de compra reais)."""

    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_mensal(CAMINHO_BASE)
        cls.dedup = valor_empenhado_por_bloco(cls.df)

    def _bloco(self, ne_ccor: str, subitem_cod: str, ano_mes: int):
        alvo = self.dedup[
            (self.dedup["ne_ccor"] == ne_ccor)
            & (self.dedup["subitem_cod"] == subitem_cod)
            & (self.dedup["ano_mes"] == ano_mes)
        ]
        self.assertEqual(len(alvo), 1)
        return alvo.iloc[0]

    def test_bloco_de_folha_de_pagamento_nao_multiplica_pelos_7_itens(self):
        linha = self._bloco("153165152392026NE000033", "1", 202601)
        self.assertAlmostEqual(linha["empenhada"], 18359940.71, places=2)
        self.assertEqual(linha["qtd_itens"], 7)

    def test_bloco_de_material_de_consumo_elemento_30(self):
        linha = self._bloco("153165152392026NE000064", "7", 202601)
        self.assertAlmostEqual(linha["empenhada"], 6387.37, places=2)
        self.assertEqual(linha["elemento_cod"], "30")
        self.assertEqual(linha["qtd_itens"], 100)

    def test_soma_ingenua_por_linha_de_item_superestima(self):
        # prova em código de que a deduplicação faz diferença de verdade: somar direto pelas
        # linhas de item (sem passar por valor_empenhado_por_bloco) dá um número maior.
        linhas_do_bloco = self.df[
            (self.df["ne_ccor"] == "153165152392026NE000033")
            & (self.df["subitem_cod"] == "1")
            & (self.df["ano_mes"] == 202601)
            & (self.df["tipo_linha"] == "empenho")
        ]
        soma_ingenua = linhas_do_bloco["empenhada"].sum()
        valor_correto = self._bloco("153165152392026NE000033", "1", 202601)["empenhada"]
        self.assertGreater(soma_ingenua, valor_correto)
        self.assertAlmostEqual(soma_ingenua, valor_correto * 7, places=2)


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestLinhaDoTempoPorNe(unittest.TestCase):
    """Evolução mensal de uma NE — Empenhado somado entre os blocos (Natureza Detalhada ×
    Subitem) da MESMA NE, já deduplicado dentro de cada um (ver TestValorEmpenhadoPorBloco);
    Liquidado/Pago somados direto (não duplicam por item). Números conferidos manualmente
    contra a extração de referência (NE 153165152392026NE000033, que tem 7 blocos de Natureza
    Detalhada/Subitem diferentes — a soma cruza todos eles)."""

    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_mensal(CAMINHO_BASE)
        cls.tempo = linha_do_tempo_por_ne(cls.df)

    def _mes(self, ne_ccor: str, ano_mes: int):
        alvo = self.tempo[(self.tempo["ne_ccor"] == ne_ccor) & (self.tempo["ano_mes"] == ano_mes)]
        self.assertEqual(len(alvo), 1)
        return alvo.iloc[0]

    def test_uma_linha_por_ne_e_mes_presente_na_extracao(self):
        # 531 NEs × 9 meses (JAN-SET/2026) — nenhuma linha extra, nenhuma faltando.
        self.assertEqual(self.tempo["ne_ccor"].nunique(), 531)
        self.assertEqual(len(self.tempo), 531 * 9)

    def test_empenhado_soma_entre_blocos_diferentes_da_mesma_ne(self):
        # NE 153165152392026NE000033 tem 7 blocos (Natureza Detalhada/Subitem) diferentes;
        # em janeiro, o bloco do subitem 1 sozinho vale 18.359.940,71 (ver
        # TestValorEmpenhadoPorBloco) — bem menos que o total desta NE no mês, que soma TODOS
        # os blocos (nenhum duplicado dentro de si, ver testes daquela função).
        linha = self._mes("153165152392026NE000033", 202601)
        self.assertAlmostEqual(linha["empenhada"], 25497212.65, places=2)
        self.assertGreater(linha["empenhada"], 18359940.71)

    def test_liquidado_e_pago_do_mes(self):
        linha = self._mes("153165152392026NE000033", 202601)
        self.assertAlmostEqual(linha["liquidada"], 11568652.16, places=2)
        self.assertAlmostEqual(linha["paga"], 0.0, places=2)

        linha_fev = self._mes("153165152392026NE000033", 202602)
        self.assertAlmostEqual(linha_fev["paga"], 11568652.16, places=2)

    def test_soma_da_linha_do_tempo_bate_com_valor_empenhado_por_bloco_da_ne(self):
        # a linha do tempo de uma NE, somada em todos os meses, precisa bater com a soma de
        # TODOS os blocos daquela NE em valor_empenhado_por_bloco — prova de que somar entre
        # blocos aqui não perde nem duplica nada.
        dedup = valor_empenhado_por_bloco(self.df)
        esperado = dedup.loc[dedup["ne_ccor"] == "153165152392026NE000033", "empenhada"].sum()
        obtido = self.tempo.loc[self.tempo["ne_ccor"] == "153165152392026NE000033", "empenhada"].sum()
        self.assertAlmostEqual(obtido, esperado, places=2)


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestValidacaoEstrutural(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_mensal(CAMINHO_BASE)

    def test_sem_erros_estruturais(self):
        relatorio = validar(self.df)
        self.assertEqual(relatorio.erros, [])

    def test_ano_da_ne_bate_com_ano_lancamento(self):
        # usuário confirmou que, nesta base, Ano Lançamento não diverge do ano da NE.
        self.assertTrue(self.df["ne_ano"].eq(self.df["ano"].astype(str)).all())


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestReferenciaDaExtracao(unittest.TestCase):
    """Totais absolutos — só se aplicam à extração cujo hash está em REFERENCIAS."""

    @classmethod
    def setUpClass(cls):
        cls.hash_curto = _hash_curto(CAMINHO_BASE)
        cls.ref = REFERENCIAS.get(cls.hash_curto)
        if cls.ref is not None:
            cls.df = ler_execucao_mensal(CAMINHO_BASE)
            cls.resumo = reconciliar(cls.df)

    def setUp(self):
        if self.ref is None:
            self.skipTest(
                f"Extração {self.hash_curto} não catalogada em REFERENCIAS — "
                "totais absolutos não conferidos (fixture foi trocada)."
            )

    def test_contagens(self):
        self.assertEqual(self.resumo["linhas_originais"], self.ref["linhas_originais"])
        self.assertEqual(self.resumo["notas_empenho_distintas"], self.ref["notas_empenho_distintas"])
        self.assertEqual(self.resumo["meses"], self.ref["meses"])

    def test_totais_batem_com_o_manifesto_da_base_anual(self):
        for medida, valor in self.ref["totais"].items():
            self.assertAlmostEqual(self.resumo["totais"][medida], valor, places=2)


if __name__ == "__main__":
    unittest.main()
