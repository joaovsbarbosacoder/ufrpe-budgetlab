"""
Testes da base MENSAL de Execução da Despesa (Tesouro Gerencial / BI CPOC).

Usa uma fixture congelada em `tests/fixtures/` (não um arquivo de `data/raw/` — esta base
ainda não tem importação versionada própria, ver docs/base_execucao_mensal.md) — pulado se o
arquivo não existir.

Dois níveis, mesmo espírito de `test_execucao_anual.py`:
  * INVARIANTES — valem para qualquer extração desta base.
  * REFERÊNCIA — totais absolutos da extração identificada por hash (`REFERENCIAS`). Ao
    trocar a fixture, NÃO edite os números existentes: acrescente uma entrada nova.

IMPORTANTE: ao atualizar a planilha de trabalho, NÃO sobrescreva uma fixture existente
automaticamente — mesma regra das demais fixtures deste diretório (ver AGENTS.md).

HISTÓRICO DE LAYOUT (21/09/2026): o export do BI CPOC mudou de 1 aba única (com coluna "Ano
Lançamento") para 1 aba POR EXERCÍCIO, com banner de relatório antes do cabeçalho e 2 colunas
dimensionais novas — ver docstring de `src/tesouro_execucao_mensal.py`. O leitor atual só
entende o layout novo; `execucao_mensal_2026-09-03.xlsx` (layout antigo) fica no repositório
como registro histórico, mas não é mais lida por nenhum teste aqui.

HISTÓRICO DE LAYOUT (22/09/2026): par `Fonte Recursos Detalhada` (código/descrição) inserido
logo após `Fonte Recursos` — pedido do usuário, viabiliza cruzar com a Dotação Anual no mesmo
nível de detalhe (ver `src/painel_acoes_empenho.py`). `CAMINHO_BASE` passou a apontar para
`execucao_mensal_2026-09-22.xlsx`; `execucao_mensal_2026-09-21.xlsx` (layout sem esse par) fica
como registro histórico, referência `672398fd` em `REFERENCIAS`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import openpyxl
import pandas as pd

from src.tesouro_execucao_mensal import (
    COLUNAS_DIMENSAO,
    _DIMENSOES_EXTRA_BLOCO,
    ErroLayoutBase,
    _blocos_mensais,
    _rotulo_mes,
    agregar_por_ne,
    ler_execucao_mensal,
    linha_do_tempo_por_ne,
    reconciliar,
    valor_empenhado_por_bloco,
    validar,
)

CAMINHO_BASE = Path("tests/fixtures/execucao_mensal_2026-09-22.xlsx")

# Extração recebida em 21/09/2026 (repassada pelo usuário via Downloads, hash 672398fd...),
# primeira no layout novo (multi-aba, 2024-2026). Ao trocar a fixture, NÃO edite estes
# números: acrescente uma entrada nova (o hash decide qual referência se aplica). Totais
# conferidos pela validação estrutural própria da base (`validar()`, sem erros nem alertas) —
# esta extração não tem manifesto da base Anual cobrindo os 3 exercícios para conferência
# cruzada externa (ver docstring do módulo).
REFERENCIAS = {
    "672398fd": {
        "descricao": "Extração recebida em 21/09/2026, abas 2024/2025/2026 (JAN-DEZ exceto "
        "2026: JAN-SET); blocos de encerramento '013'/'014' presentes em 2024/2025, ignorados. "
        "Layout SEM Fonte Recursos Detalhada (ver hash 0fa6c314 para o layout com esse par de "
        "colunas, 22/09/2026) — fixture não é mais apontada por CAMINHO_BASE, mantida como "
        "registro histórico.",
        "linhas_originais": 5773,
        "linhas_empenho": 4588,
        "linhas_item_execucao": 1185,
        "notas_empenho_distintas": 2567,
        "meses": [
            202401, 202402, 202403, 202404, 202405, 202406, 202407, 202408, 202409, 202410, 202411, 202412,
            202501, 202502, 202503, 202504, 202505, 202506, 202507, 202508, 202509, 202510, 202511, 202512,
            202601, 202602, 202603, 202604, 202605, 202606, 202607, 202608, 202609,
        ],
        "totais": {
            "empenhada": 2496385310.24,
            "liquidada": 2226631940.82,
            "paga": 2044328609.12,
        },
        "totais_por_ano": {
            2024: {"empenhada": 784086352.51, "liquidada": 759877180.18, "paga": 687779472.58},
            2025: {"empenhada": 931345340.39, "liquidada": 882774236.76, "paga": 790633667.10},
            2026: {"empenhada": 780953617.34, "liquidada": 583980523.88, "paga": 565915469.44},
        },
    },
    "0fa6c314": {
        "descricao": "Extração recebida em 22/09/2026, abas 2024/2025/2026 (JAN-DEZ exceto "
        "2026: JAN-SET); primeira com o par Fonte Recursos Detalhada (código/descrição) logo "
        "após Fonte Recursos — ver seção de layout na docstring de "
        "`src/tesouro_execucao_mensal.py`. Mesma extração-base de 672398fd, um dia depois "
        "(pequenas variações de totais e +1 NE nova).",
        "linhas_originais": 5773,
        "linhas_empenho": 4588,
        "linhas_item_execucao": 1185,
        "notas_empenho_distintas": 2568,
        "meses": [
            202401, 202402, 202403, 202404, 202405, 202406, 202407, 202408, 202409, 202410, 202411, 202412,
            202501, 202502, 202503, 202504, 202505, 202506, 202507, 202508, 202509, 202510, 202511, 202512,
            202601, 202602, 202603, 202604, 202605, 202606, 202607, 202608, 202609,
        ],
        "totais": {
            "empenhada": 2496385910.24,
            "liquidada": 2226639772.51,
            "paga": 2044402004.58,
        },
        "totais_por_ano": {
            2024: {"empenhada": 784086352.51, "liquidada": 759877180.18, "paga": 687779472.58},
            2025: {"empenhada": 931345340.39, "liquidada": 882774236.76, "paga": 790633667.10},
            2026: {"empenhada": 780954217.34, "liquidada": 583988355.57, "paga": 565988864.90},
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

    def test_detecta_meses_atravessando_exercicios(self):
        # Fecha a pendência documentada em docs/base_execucao_mensal.md: `_blocos_mensais`
        # já lê o ano de cada rótulo individualmente (não presume um único ano pro arquivo
        # inteiro) — este teste prova isso com uma extração sintética que atravessa dois
        # exercícios (DEZ/2026 seguido de JAN/2027 no MESMO arquivo), pedido do usuário
        # (10/09/2026: "quero que o sistema perdure por mais anos... 2027, 2028...").
        blocos = _blocos_mensais(self._linha1(["NOV/2026", "DEZ/2026", "JAN/2027", "FEV/2027"]))
        primeira = len(COLUNAS_DIMENSAO)
        self.assertEqual(blocos, [
            (primeira, 2026, 11), (primeira + 3, 2026, 12),
            (primeira + 6, 2027, 1), (primeira + 9, 2027, 2),
        ])

    def test_sem_nenhum_bloco_e_erro(self):
        with self.assertRaises(ErroLayoutBase):
            _blocos_mensais([None] * len(COLUNAS_DIMENSAO))

    def test_bloco_incompleto_e_erro(self):
        linha = self._linha1(["JAN/2026"])[:-1]  # falta a 3a coluna do bloco
        with self.assertRaises(ErroLayoutBase):
            _blocos_mensais(linha)

    def test_bloco_de_encerramento_e_ignorado_nao_e_erro(self):
        # "013/2025"/"014/2025" (períodos de encerramento além de DEZ) — decisão explícita do
        # usuário (21/09/2026): não entram no resultado, mas também não são erro de layout.
        blocos = _blocos_mensais(self._linha1(["JAN/2025", "DEZ/2025", "013/2025", "014/2025"]))
        primeira = len(COLUNAS_DIMENSAO)
        self.assertEqual(blocos, [(primeira, 2025, 1), (primeira + 3, 2025, 12)])

    def test_bloco_de_encerramento_no_meio_tambem_e_ignorado(self):
        blocos = _blocos_mensais(self._linha1(["013/2025", "JAN/2026"]))
        primeira = len(COLUNAS_DIMENSAO)
        self.assertEqual(blocos, [(primeira + 3, 2026, 1)])

    def test_rotulo_realmente_invalido_continua_erro(self):
        # distingue de propósito de um bloco de encerramento conhecido: qualquer outra coisa
        # não reconhecida ainda precisa falhar cedo, não ser silenciosamente ignorada.
        with self.assertRaises(ErroLayoutBase):
            _blocos_mensais(self._linha1(["JAN/2026", "XYZ/2026"]))


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestLeituraEValidacaoAssinatura(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_mensal(CAMINHO_BASE)

    def test_devolve_uma_linha_por_linha_bruta_vezes_mes_da_mesma_aba(self):
        # o invariante é POR ABA (por exercício): uma linha bruta só combina com os meses da
        # sua própria aba, nunca com os de outro exercício (ver docstring do módulo).
        for aba, grupo in self.df.groupby("aba_origem"):
            linhas_originais = grupo["linha_origem"].nunique()
            n_meses = grupo["ano_mes"].nunique()
            self.assertEqual(len(grupo), linhas_originais * n_meses, f"aba {aba!r}")

    def test_colunas_essenciais_presentes(self):
        for coluna in (
            "ne_ccor", "ne_item_cod", "ne_item_desc", "natureza_detalhada_cod", "subitem_cod",
            "ne_informacao_complementar", "unidade_orcamentaria_cod", "aba_origem",
            "mes", "ano_mes", "empenhada", "liquidada", "paga", "tipo_linha", "linha_origem",
        ):
            self.assertIn(coluna, self.df.columns)

    def test_tipo_linha_bate_com_a_referencia(self):
        por_linha_original = self.df.drop_duplicates("linha_origem")
        contagem = por_linha_original["tipo_linha"].value_counts()
        self.assertEqual(int(contagem.get("empenho", 0)), 4588)
        self.assertEqual(int(contagem.get("item_execucao", 0)), 1185)

    def test_fonte_recursos_detalhada_presente_e_com_10_caracteres(self):
        # Par código/descrição novo (22/09/2026, ver docstring do módulo) — inserido logo
        # após Fonte Recursos, desloca Grupo Despesa/PTRES/Unidade Orçamentária/NE em +2
        # posições (ver `_ANCORAS_LINHA1`); este teste garante que a coluna existe e que o
        # deslocamento não bagunçou as colunas vizinhas.
        codigos = self.df["fonte_recursos_detalhada_cod"].dropna()
        self.assertGreater(len(codigos), 0)
        self.assertTrue((codigos.str.len() == 10).all())
        self.assertTrue(self.df["fonte_recursos_detalhada_desc"].notna().any())
        # coluna vizinha seguinte (Grupo Despesa) não pode ter vazado dígitos de Fonte
        # Detalhada nem ficar vazia por causa do deslocamento de posição.
        self.assertTrue(self.df["gnd_cod"].notna().any())
        self.assertTrue(self.df["gnd_cod"].dropna().isin(["1", "2", "3", "4", "5", "6"]).all())

    def test_nenhum_bloco_de_encerramento_vaza_para_ano_mes(self):
        # "013"/"014" não têm mês real (1-12) — confirma que o descarte em _blocos_mensais
        # realmente não deixou nada com mes fora do intervalo válido.
        self.assertTrue(self.df["mes"].between(1, 12).all())

    def test_layout_diferente_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            wb = openpyxl.load_workbook(CAMINHO_BASE)
            aba = wb["2026"]
            aba.cell(row=4, column=1).value = "Outra Coisa"  # não mais "Iduso"
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

    def test_bloco_de_folha_de_pagamento_nao_multiplica_pelos_17_itens(self):
        linha = self._bloco("153165152392026NE000036", "43", 202601)
        self.assertAlmostEqual(linha["empenhada"], 5616221.04, places=2)
        self.assertEqual(linha["qtd_itens"], 17)

    def test_bloco_de_material_de_consumo_elemento_30(self):
        linha = self._bloco("153165152392026NE000062", "7", 202601)
        self.assertAlmostEqual(linha["empenhada"], 15005.95, places=2)
        self.assertEqual(linha["elemento_cod"], "30")
        self.assertEqual(linha["qtd_itens"], 100)

    def test_soma_ingenua_por_linha_de_item_superestima(self):
        # prova em código de que a deduplicação faz diferença de verdade: somar direto pelas
        # linhas de item (sem passar por valor_empenhado_por_bloco) dá um número maior.
        linhas_do_bloco = self.df[
            (self.df["ne_ccor"] == "153165152392026NE000036")
            & (self.df["subitem_cod"] == "43")
            & (self.df["ano_mes"] == 202601)
            & (self.df["tipo_linha"] == "empenho")
        ]
        soma_ingenua = linhas_do_bloco["empenhada"].sum()
        valor_correto = self._bloco("153165152392026NE000036", "43", 202601)["empenhada"]
        self.assertGreater(soma_ingenua, valor_correto)
        self.assertAlmostEqual(soma_ingenua, valor_correto * 17, places=2)


class TestFonteDetalhadaNoBloco(unittest.TestCase):
    """Fonte Recursos Detalhada no bloco de empenho (08/10/2026): a fonte é constante por NE,
    então `first` no bloco não mistura dado — permite cruzar empenhos com a Dotação Anual no
    nível da fonte detalhada. Sem fixture: DataFrame mínimo montado em memória."""

    def test_valor_empenhado_por_bloco_inclui_fonte_detalhada(self):
        base = {coluna: "x" for coluna in _DIMENSOES_EXTRA_BLOCO.values()}
        base.update({
            "tipo_linha": "empenho", "ne_ccor": "NE1", "natureza_detalhada_cod": "339030",
            "subitem_cod": "07", "ano_mes": 202601, "empenhada": 100.0,
            "fonte_recursos_detalhada_cod": "1000000000",
            "fonte_recursos_detalhada_desc": "Recursos ordinarios",
        })
        df = pd.DataFrame([
            {**base, "ne_item_cod": "1"},
            {**base, "ne_item_cod": "2"},
        ])

        resultado = valor_empenhado_por_bloco(df)

        self.assertEqual(resultado["fonte_recursos_detalhada_cod"].iloc[0], "1000000000")
        self.assertEqual(resultado["fonte_recursos_detalhada_desc"].iloc[0], "Recursos ordinarios")
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado["empenhada"].iloc[0], df["empenhada"].iloc[0])


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

    def test_uma_linha_por_ne_e_mes_sem_duplicar(self):
        # cada NE aparece só em quantos meses ela realmente teve movimento na extração — não
        # necessariamente todos os meses do exercício (nem todas as NEs vivem no mesmo
        # exercício, a base agora cobre 2024-2026) — o invariante é NÃO DUPLICAR o par
        # (NE, mês), não uma contagem fixa de meses por NE.
        self.assertEqual(len(self.tempo), len(self.tempo.drop_duplicates(["ne_ccor", "ano_mes"])))
        self.assertEqual(self.tempo["ne_ccor"].nunique(), 2568)
        self.assertEqual(len(self.tempo), 29124)

    def test_empenhado_soma_entre_blocos_diferentes_da_mesma_ne(self):
        # NE 153165152392026NE000036 tem 153 blocos (Natureza Detalhada/Subitem × mês)
        # diferentes; em janeiro, o bloco do subitem 43 (13º salário) sozinho vale
        # 5.616.221,04 (ver TestValorEmpenhadoPorBloco) — bem menos que o total desta NE no
        # mês, que soma TODOS os blocos daquele mês (nenhum duplicado dentro de si, ver
        # testes daquela função).
        linha = self._mes("153165152392026NE000036", 202601)
        self.assertAlmostEqual(linha["empenhada"], 68294924.73, places=2)
        self.assertGreater(linha["empenhada"], 5616221.04)

    def test_liquidado_e_pago_do_mes(self):
        linha = self._mes("153165152392026NE000036", 202601)
        self.assertAlmostEqual(linha["liquidada"], 32600555.50, places=2)
        self.assertAlmostEqual(linha["paga"], 6089.29, places=2)

        linha_fev = self._mes("153165152392026NE000036", 202602)
        self.assertAlmostEqual(linha_fev["empenhada"], 1378269.71, places=2)
        self.assertAlmostEqual(linha_fev["liquidada"], 30680277.16, places=2)
        self.assertAlmostEqual(linha_fev["paga"], 25577982.90, places=2)

    def test_soma_da_linha_do_tempo_bate_com_valor_empenhado_por_bloco_da_ne(self):
        # a linha do tempo de uma NE, somada em todos os meses, precisa bater com a soma de
        # TODOS os blocos daquela NE em valor_empenhado_por_bloco — prova de que somar entre
        # blocos aqui não perde nem duplica nada.
        dedup = valor_empenhado_por_bloco(self.df)
        esperado = dedup.loc[dedup["ne_ccor"] == "153165152392026NE000036", "empenhada"].sum()
        obtido = self.tempo.loc[self.tempo["ne_ccor"] == "153165152392026NE000036", "empenhada"].sum()
        self.assertAlmostEqual(obtido, esperado, places=2)


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestAgregarPorNe(unittest.TestCase):
    """`agregar_por_ne` — mesmo contrato de saída de `src.execucao_anual.agregar_por_ne`
    (usada por `app_pages/consulta_empenhos.py` desde 21/09/2026, ver docs/
    base_execucao_mensal.md, seção 10): uma linha por NE, Empenhado somado já deduplicado
    (todos os blocos, todos os meses), Liquidado/Pago somados direto."""

    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_mensal(CAMINHO_BASE)
        cls.por_ne = agregar_por_ne(cls.df)

    def test_uma_linha_por_ne_sem_duplicar(self):
        self.assertEqual(len(self.por_ne), self.df["ne_ccor"].nunique())
        self.assertEqual(self.por_ne["ne_ccor"].nunique(), len(self.por_ne))

    def test_colunas_essenciais_presentes(self):
        # ne_favorecido: regressão real encontrada ao trocar a fonte de
        # `app_pages/consulta_empenhos.py` para esta função — faltava na lista de dimensões
        # constantes, `visivel["ne_favorecido"]` quebrava a página com KeyError.
        for coluna in (
            "ne_ccor", "ano", "ne_descricao", "ne_favorecido", "processo_ne",
            "ne_informacao_complementar", "unidade_orcamentaria_cod",
            "natureza_detalhada_label", "subitem_resumo", "empenhada", "liquidada", "paga",
        ):
            self.assertIn(coluna, self.por_ne.columns)

    def test_empenhado_soma_todos_os_blocos_e_meses_da_ne(self):
        # NE 153165152392026NE000036 — mesma NE de TestLinhaDoTempoPorNe/TestValorEmpenhadoPorBloco,
        # 153 blocos (Natureza Detalhada/Subitem × mês) distintos.
        linha = self.por_ne.loc[self.por_ne["ne_ccor"] == "153165152392026NE000036"].iloc[0]
        self.assertAlmostEqual(linha["empenhada"], 363955553.69, places=2)
        self.assertAlmostEqual(linha["liquidada"], 268568535.73, places=2)
        self.assertAlmostEqual(linha["paga"], 261106290.39, places=2)
        self.assertEqual(linha["ne_favorecido"], "UNIVERSIDADE FEDERAL RURAL DE PERNAMBUCO")
        self.assertEqual(linha["natureza_detalhada_label"], "17 classificações")
        self.assertEqual(linha["ano"], 2026)

    def test_soma_geral_bate_com_reconciliar(self):
        # o total de `agregar_por_ne` somado tem que bater com `reconciliar()["totais"]`
        # (mesma fonte de verdade, dois caminhos de agregação diferentes).
        totais = reconciliar(self.df)["totais"]
        self.assertAlmostEqual(float(self.por_ne["empenhada"].sum()), totais["empenhada"], places=2)

    def test_liquidada_nula_preservada_nao_vira_zero(self):
        # NE sem nenhuma linha de item de execução (nunca liquidada) tem que continuar nula,
        # não virar 0.0 — só `saldo_por_ne`/`_saldo_e_a_pagar` (fora deste módulo) convertem
        # nulo em zero, de propósito, para a conta de saldo corrente.
        self.assertGreater(self.por_ne["liquidada"].isna().sum(), 0)


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

    def test_totais_batem_com_a_referencia_congelada(self):
        for medida, valor in self.ref["totais"].items():
            self.assertAlmostEqual(self.resumo["totais"][medida], valor, places=2)

    def test_totais_por_ano_batem_com_a_referencia_congelada(self):
        esperado = self.ref.get("totais_por_ano")
        if not esperado:
            self.skipTest("Referência sem totais_por_ano.")
        for ano, medidas in esperado.items():
            for medida, valor in medidas.items():
                self.assertAlmostEqual(self.resumo["totais_por_ano"][ano][medida], valor, places=2)


if __name__ == "__main__":
    unittest.main()
