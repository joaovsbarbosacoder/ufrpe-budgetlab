"""
Testes da base ANUAL de Execução da Despesa.

Dois níveis, propositalmente separados para sobreviver a reimportações:

  * INVARIANTES — valem para qualquer extração desta base. Se um deles quebrar, a extração
    mudou de natureza e a análise precisa ser repensada. Nunca afrouxar.
  * REFERÊNCIA — totais absolutos de UMA extração específica, identificada por hash.
    Só são conferidos quando o arquivo em disco é exatamente aquela extração; com outro
    arquivo, o teste é pulado em vez de falhar. É isso que permite trocar a base sem
    mexer na suíte.

Ajuste CAMINHO_BASE e os imports ao pacote do projeto.
"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.execucao_anual import (
    COLUNAS,
    LINHAS_CABECALHO,
    MEDIDAS,
    ErroLayoutBase,
    _SENTINELAS_PROCESSO,
    agregar,
    agregar_por_ne,
    ler_execucao_anual,
    reconciliar,
    validar,
)
from src.importacao_execucao import (
    Manifesto,
    carregar_atual,
    comparar,
    gerar_manifesto,
    historico,
    historico_como_tabela,
    importar,
)

CAMINHO_BASE = Path("data/raw/BI CPOC - EXEC. DESPESAS - Por Ano - com processo.xlsx")

# Extração de referência recebida em 11/08/2026. Ao substituir a base por uma extração mais
# recente, NÃO edite estes números: registre a nova referência acrescentando outra entrada
# (o hash é que decide qual se aplica).
REFERENCIAS = {
    "7d09c278": {
        "descricao": "Extração recebida em 11/08/2026, exercícios 2023-2026 (layout antigo, "
        "39 colunas, sem Núm. Processo — arquivo mantido só como registro histórico)",
        "linhas": 7779,
        "linhas_empenho": 4092,
        "linhas_item_execucao": 3687,
        "notas_empenho_distintas": 3700,
        "anos": [2023, 2024, 2025, 2026],
        "totais": {
            "empenhada": 3232327499.34,
            "liquidada": 2864970004.16,
            "paga": 2616012762.14,
        },
        "totais_por_ano": {
            2023: {"empenhada": 762455916.88, "liquidada": 723987833.09, "paga": 651361558.65},
            2024: {"empenhada": 784086352.51, "liquidada": 759877180.18, "paga": 687779472.58},
            2025: {"empenhada": 931345340.39, "liquidada": 882774236.76, "paga": 790633667.10},
            2026: {"empenhada": 754439889.56, "liquidada": 498330754.13, "paga": 486238063.81},
        },
    },
    # Extração recebida em 13/08/2026: mesmo layout + coluna "NE - Núm. Processo" (posição 33).
    "0a60d0a4": {
        "descricao": "Extração recebida em 13/08/2026, exercícios 2023-2026, com Núm. Processo",
        "linhas": 7800,
        "linhas_empenho": 4109,
        "linhas_item_execucao": 3691,
        "notas_empenho_distintas": 3716,
        "anos": [2023, 2024, 2025, 2026],
        "totais": {
            "empenhada": 3232578961.58,
            "liquidada": 2865398089.09,
            "paga": 2616648887.32,
        },
        "totais_por_ano": {
            2023: {"empenhada": 762455916.88, "liquidada": 723987833.09, "paga": 651361558.65},
            2024: {"empenhada": 784086352.51, "liquidada": 759877180.18, "paga": 687779472.58},
            2025: {"empenhada": 931345340.39, "liquidada": 882774236.76, "paga": 790633667.10},
            2026: {"empenhada": 754691351.80, "liquidada": 498758839.06, "paga": 486874188.99},
        },
    },
}


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Base ausente em {CAMINHO_BASE}")
class TestInvariantesDaBase(unittest.TestCase):
    """Verdades estruturais que qualquer extração desta base precisa respeitar."""

    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_anual(CAMINHO_BASE)

    def test_colunas_e_tipos(self):
        for col in COLUNAS:
            self.assertIn(col, self.df.columns)
        self.assertEqual(str(self.df["ano"].dtype), "int16")
        for m in MEDIDAS:
            self.assertTrue(pd.api.types.is_float_dtype(self.df[m]))

    def test_codigos_permanecem_texto_com_zeros_a_esquerda(self):
        self.assertTrue(self.df["fonte_cod"].str.len().eq(3).all())
        self.assertTrue((self.df["acao_cod"].str.len() >= 4).all())

    def test_liquidado_e_pago_so_em_linhas_de_item(self):
        empenho = self.df[self.df["tipo_linha"] == "empenho"]
        self.assertEqual(int(empenho["liquidada"].notna().sum()), 0)
        self.assertEqual(int(empenho["paga"].notna().sum()), 0)

    def test_empenhado_nas_linhas_de_item_se_anula(self):
        itens = self.df[self.df["tipo_linha"] == "item_execucao"]
        self.assertAlmostEqual(float(itens["empenhada"].sum()), 0.0, places=2)

    def test_ano_lancamento_igual_ao_ano_da_ne(self):
        self.assertTrue(self.df["ne_ano"].eq(self.df["ano"].astype(str)).all())

    def test_sentinelas_de_processo_viram_nulo(self):
        self.assertFalse(self.df["processo_ne"].isin(["'-9", "'-8"]).any())

    def test_coerencia_financeira_por_ano(self):
        por_ano = self.df.groupby("ano")[MEDIDAS].sum()
        for ano, linha in por_ano.iterrows():
            self.assertLessEqual(linha["liquidada"], linha["empenhada"] + 0.01, f"{ano}")
            self.assertLessEqual(linha["paga"], linha["liquidada"] + 0.01, f"{ano}")

    def test_sem_duplicatas_na_chave_dimensional(self):
        chave = [c for c in COLUNAS if c not in MEDIDAS]
        self.assertEqual(int(self.df.duplicated(subset=chave).sum()), 0)

    def test_agregacao_preserva_total(self):
        por_gnd = agregar(self.df, por=["gnd_cod", "gnd_desc"])
        for m in MEDIDAS:
            self.assertAlmostEqual(float(por_gnd[m].sum()), float(self.df[m].sum()), places=2, msg=m)

    def test_rastreabilidade_ate_a_linha_de_origem(self):
        self.assertEqual(int(self.df["linha_origem"].min()), 3)
        self.assertEqual(int(self.df["linha_origem"].nunique()), len(self.df))

    def test_validacao_sem_erros(self):
        rel = validar(self.df)
        self.assertTrue(rel.ok, rel.erros)
        self.assertEqual(rel.alertas, [])


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Base ausente em {CAMINHO_BASE}")
class TestAgregacaoPorNE(unittest.TestCase):
    """`agregar_por_ne` — base da futura Consulta de Empenhos: uma linha por NE."""

    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_anual(CAMINHO_BASE)
        cls.por_ne = agregar_por_ne(cls.df)

    def test_uma_linha_por_ne_distinta(self):
        self.assertEqual(len(self.por_ne), self.df["ne_ccor"].nunique())
        self.assertEqual(self.por_ne["ne_ccor"].nunique(), len(self.por_ne))

    def test_soma_por_ne_preserva_o_total_da_base(self):
        for m in MEDIDAS:
            self.assertAlmostEqual(
                float(self.por_ne[m].sum(min_count=1)), float(self.df[m].sum(min_count=1)), places=2, msg=m
            )

    def test_ne_descricao_vem_da_linha_de_empenho_no_marcador_de_item(self):
        # Nenhuma NE deve carregar o marcador de item de execução como descrição.
        self.assertFalse(self.por_ne["ne_descricao"].eq("NAO SE APLICA").any())

    def test_ne_com_classificacao_unica_mostra_o_valor_direto(self):
        unica = self.por_ne[~self.por_ne["subitem_resumo"].str.contains("classifica", na=False)]
        self.assertFalse(unica.empty)
        # não deve sobrar o marcador de resumo em quem tem só uma classificação
        self.assertTrue((unica["subitem_resumo"] != "").all())

    def test_ne_com_classificacoes_multiplas_mostra_contagem(self):
        multipla = self.por_ne[self.por_ne["subitem_resumo"].str.contains("classifica", na=False)]
        self.assertFalse(multipla.empty)
        for texto in multipla["subitem_resumo"]:
            self.assertRegex(texto, r"^\d+ classifica")

    def test_dimensoes_constantes_nao_variam_dentro_da_ne(self):
        # amostra: Ação e Fonte não podem divergir de uma NE para a raw dela.
        amostra = self.por_ne["ne_ccor"].iloc[0]
        linhas = self.df[self.df["ne_ccor"] == amostra]
        agregado = self.por_ne[self.por_ne["ne_ccor"] == amostra].iloc[0]
        self.assertEqual(linhas["acao_cod"].nunique(), 1)
        self.assertEqual(agregado["acao_cod"], linhas["acao_cod"].iloc[0])


# `TestIndiceValorPagoPorNeCurta`/`TestNeCurta` mudaram para `tests/test_execucao_ne_utils.py`
# em 22/09/2026, junto com as funções que testam (ver docstring de `src.execucao_ne_utils`).


def _linha_execucao_anual_sintetica(**overrides) -> dict:
    """Uma linha mínima e válida de Execução Anual (todas as colunas de `COLUNAS`, mais
    `tipo_linha`/`ne_ano`), para testar `validar()` sem depender da base real."""
    base = {coluna: f"valor_{coluna}" for coluna in COLUNAS}
    base.update(
        ano=2026,
        empenhada=100.0,
        liquidada=None,
        paga=None,
        ne_ccor="153165152392026NE000001",
        ne_ano="2026",
        tipo_linha="empenho",
    )
    base.update(overrides)
    return base


class TestValidarSinalizaNeSemLinhaDeEmpenho(unittest.TestCase):
    """`validar()` deve alertar (não falhar silenciosamente) quando uma NE não tem nenhuma
    linha do tipo "empenho" — cenário em que `agregar_por_ne` deixaria `ne_descricao`/
    `processo_ne` nulos sem explicação (ver `agregar_por_ne`)."""

    def test_ne_so_com_item_de_execucao_gera_alerta(self):
        df = pd.DataFrame(
            [
                _linha_execucao_anual_sintetica(
                    ne_ccor="153165152392026NE000002",
                    ne_ano="2026",
                    tipo_linha="item_execucao",
                    empenhada=0.0,
                ),
            ]
        )
        rel = validar(df)
        self.assertTrue(any("sem nenhuma linha do tipo 'empenho'" in a for a in rel.alertas))

    def test_ne_com_linha_de_empenho_nao_gera_o_alerta(self):
        df = pd.DataFrame([_linha_execucao_anual_sintetica()])
        rel = validar(df)
        self.assertFalse(any("sem nenhuma linha do tipo 'empenho'" in a for a in rel.alertas))


class TestSentinelasDeProcesso(unittest.TestCase):
    """`_SENTINELAS_PROCESSO` — valores do BI para "sem processo vinculado" na coluna
    "NE - Núm. Processo", mascarados para nulo (ver `ler_execucao_anual`)."""

    def test_sentinelas_viram_nulo_valor_real_passa_incolume(self):
        serie = pd.Series(["'-9", "'-8", "23083.012345/2026-11", None])
        mascarada = serie.mask(serie.isin(_SENTINELAS_PROCESSO))
        self.assertTrue(pd.isna(mascarada.iloc[0]))
        self.assertTrue(pd.isna(mascarada.iloc[1]))
        self.assertEqual(mascarada.iloc[2], "23083.012345/2026-11")
        self.assertTrue(pd.isna(mascarada.iloc[3]))


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Base ausente em {CAMINHO_BASE}")
class TestReferenciaDaExtracao(unittest.TestCase):
    """Totais absolutos — só se aplicam à extração cujo hash está em REFERENCIAS."""

    @classmethod
    def setUpClass(cls):
        cls.df = ler_execucao_anual(CAMINHO_BASE)
        cls.manifesto = gerar_manifesto(cls.df, CAMINHO_BASE)
        cls.ref = REFERENCIAS.get(cls.manifesto.sha256[:8])

    def setUp(self):
        if self.ref is None:
            self.skipTest(
                f"Extração {self.manifesto.sha256[:8]} não catalogada em REFERENCIAS — "
                "acrescente uma entrada ao trocar a base."
            )

    def test_contagens(self):
        r = reconciliar(self.df)
        for campo in ("linhas", "linhas_empenho", "linhas_item_execucao", "notas_empenho_distintas"):
            self.assertEqual(r[campo], self.ref[campo], campo)
        self.assertEqual(r["anos"], self.ref["anos"])

    def test_reconciliacao_total(self):
        r = reconciliar(self.df)
        for medida, valor in self.ref["totais"].items():
            self.assertAlmostEqual(r["totais"][medida], valor, places=2, msg=medida)

    def test_reconciliacao_por_ano(self):
        r = reconciliar(self.df)
        for ano, medidas in self.ref["totais_por_ano"].items():
            for medida, valor in medidas.items():
                self.assertAlmostEqual(
                    r["totais_por_ano"][ano][medida], valor, places=2, msg=f"{ano}/{medida}"
                )


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Base ausente em {CAMINHO_BASE}")
class TestImportacaoVersionada(unittest.TestCase):
    def test_primeira_importacao_registra_manifesto(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = importar(CAMINHO_BASE, tmp)
            self.assertTrue(res.ok, res.validacao.erros)
            self.assertFalse(res.delta.houve_anterior)
            self.assertIsNotNone(res.caminho_manifesto)
            self.assertEqual(len(historico(tmp)), 1)
            self.assertEqual(Manifesto.atual(tmp).sha256, res.manifesto.sha256)

    def test_reimportar_o_mesmo_arquivo_e_idempotente(self):
        with tempfile.TemporaryDirectory() as tmp:
            importar(CAMINHO_BASE, tmp)
            segunda = importar(CAMINHO_BASE, tmp)
            self.assertTrue(segunda.delta.mesma_extracao)
            self.assertIsNone(segunda.caminho_manifesto)
            self.assertEqual(len(historico(tmp)), 1)

    def test_manifesto_carrega_igual_ao_que_foi_salvo(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = importar(CAMINHO_BASE, tmp)
            recarregado = Manifesto.carregar(res.caminho_manifesto)
            self.assertEqual(recarregado.sha256, res.manifesto.sha256)
            self.assertEqual(recarregado.totais, res.manifesto.totais)
            self.assertEqual(recarregado.data_extracao, res.manifesto.data_extracao)

    def test_historico_como_tabela(self):
        with tempfile.TemporaryDirectory() as tmp:
            importar(CAMINHO_BASE, tmp)
            tabela = historico_como_tabela(tmp)
            self.assertEqual(len(tabela), 1)
            for coluna in ("data_extracao", "arquivo", "sha256_curto", "linhas", *MEDIDAS):
                self.assertIn(coluna, tabela.columns)


_COL_ANO = 36  # posição 0-indexada da coluna "ano" no arquivo bruto (ver test_execucao_orcamentaria_reimportacao.py)


def _dados_por_ano(caminho_base: Path, anos: set[int]) -> pd.DataFrame:
    dados = pd.read_excel(caminho_base, header=None, skiprows=LINHAS_CABECALHO, dtype=str)
    return dados[dados[_COL_ANO].astype(int).isin(anos)]


def _variante_por_anos(caminho_base: Path, destino: Path, anos: set[int]) -> Path:
    """Cópia da fixture só com as linhas dos anos pedidos — cabeçalho preservado (2 linhas),
    mesma técnica de `test_execucao_orcamentaria_reimportacao.py::_build_variant`."""
    cabecalho = pd.read_excel(caminho_base, header=None, nrows=LINHAS_CABECALHO, dtype=str)
    filtrado = _dados_por_ano(caminho_base, anos).reset_index(drop=True)
    completo = pd.concat([cabecalho, filtrado], ignore_index=True)
    completo.to_excel(destino, header=False, index=False, engine="openpyxl")
    return destino


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Base ausente em {CAMINHO_BASE}")
class TestCarregarAtualComposicaoPorAno(unittest.TestCase):
    """`carregar_atual` — composição por ano (pedido explícito do usuário): subir só o
    exercício corrente não apaga os exercícios fechados já importados antes."""

    def test_importacao_parcial_de_2026_mantem_anos_anteriores_disponiveis(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            caminho_fechados = _variante_por_anos(
                CAMINHO_BASE, tmp_path / "ate_2025.xlsx", {2023, 2024, 2025}
            )
            importar(caminho_fechados, tmp_path)
            caminho_2026 = _variante_por_anos(CAMINHO_BASE, tmp_path / "2026.xlsx", {2026})
            segunda = importar(caminho_2026, tmp_path)

            # a importação em si continua marcando 2023-2025 como "não trazidos" (informativo,
            # ver Delta.anos_removidos) — só não bloqueia mais (ver exige_confirmacao).
            self.assertEqual(segunda.delta.anos_removidos, [2023, 2024, 2025])

            composto = carregar_atual(tmp_path, tmp_path)
            self.assertEqual(sorted(composto["ano"].unique().tolist()), [2023, 2024, 2025, 2026])

    def test_ano_corrigido_substitui_so_esse_ano_no_composto(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            importar(_variante_por_anos(CAMINHO_BASE, tmp_path / "2024.xlsx", {2024}), tmp_path)
            importar(_variante_por_anos(CAMINHO_BASE, tmp_path / "2025.xlsx", {2025}), tmp_path)
            importar(_variante_por_anos(CAMINHO_BASE, tmp_path / "2024_v2.xlsx", {2024}), tmp_path)

            composto = carregar_atual(tmp_path, tmp_path)
            self.assertEqual(sorted(composto["ano"].unique().tolist()), [2024, 2025])
            # nenhuma linha de 2024 duplicada — a segunda importação de 2024 substituiu a
            # primeira por inteiro, não somou.
            linhas_2024_originais = len(_dados_por_ano(CAMINHO_BASE, {2024}))
            self.assertEqual(int((composto["ano"] == 2024).sum()), linhas_2024_originais)


class TestDelta(unittest.TestCase):
    """Comparação entre extrações — não depende do arquivo real."""

    def _manifesto(self, sha: str, anos_totais: dict) -> Manifesto:
        totais = {m: round(sum(v[m] for v in anos_totais.values()), 2) for m in MEDIDAS}
        return Manifesto(
            base="execucao_anual",
            arquivo="x.xlsx",
            sha256=sha,
            data_extracao="2026-08-11T10:00:00",
            importado_em="2026-08-11T10:00:00",
            linhas=10,
            linhas_empenho=6,
            linhas_item_execucao=4,
            notas_empenho_distintas=6,
            anos=sorted(int(a) for a in anos_totais),
            totais=totais,
            totais_por_ano={str(a): v for a, v in anos_totais.items()},
        )

    def test_primeira_importacao(self):
        d = comparar(None, self._manifesto("a" * 64, {2025: dict(empenhada=1.0, liquidada=1.0, paga=1.0)}))
        self.assertFalse(d.houve_anterior)

    def test_hash_igual_significa_mesma_extracao(self):
        m = self._manifesto("b" * 64, {2025: dict(empenhada=1.0, liquidada=1.0, paga=1.0)})
        d = comparar(m, m)
        self.assertTrue(d.mesma_extracao)
        self.assertEqual(d.anos_alterados, {})

    def test_exercicio_em_andamento_avancou(self):
        antes = self._manifesto("c" * 64, {
            2025: dict(empenhada=100.0, liquidada=90.0, paga=80.0),
            2026: dict(empenhada=50.0, liquidada=30.0, paga=20.0),
        })
        depois = self._manifesto("d" * 64, {
            2025: dict(empenhada=100.0, liquidada=90.0, paga=80.0),
            2026: dict(empenhada=70.0, liquidada=45.0, paga=35.0),
        })
        d = comparar(antes, depois)
        self.assertEqual(list(d.anos_alterados), [2026])
        self.assertAlmostEqual(d.anos_alterados[2026]["empenhada"]["diferenca"], 20.0)
        self.assertEqual(d.alertas, [])  # avanço do exercício corrente não é alerta

    def test_mudanca_retroativa_gera_alerta(self):
        antes = self._manifesto("e" * 64, {
            2024: dict(empenhada=100.0, liquidada=90.0, paga=80.0),
            2025: dict(empenhada=100.0, liquidada=90.0, paga=80.0),
        })
        depois = self._manifesto("f" * 64, {
            2024: dict(empenhada=95.0, liquidada=90.0, paga=80.0),
            2025: dict(empenhada=100.0, liquidada=90.0, paga=80.0),
        })
        d = comparar(antes, depois)
        self.assertIn(2024, d.anos_alterados)
        self.assertTrue(any("retroativ" in a for a in d.alertas))

    def test_exercicio_que_some_gera_alerta(self):
        antes = self._manifesto("1" * 64, {
            2023: dict(empenhada=10.0, liquidada=9.0, paga=8.0),
            2024: dict(empenhada=10.0, liquidada=9.0, paga=8.0),
        })
        depois = self._manifesto("2" * 64, {2024: dict(empenhada=10.0, liquidada=9.0, paga=8.0)})
        d = comparar(antes, depois)
        self.assertEqual(d.anos_removidos, [2023])
        self.assertTrue(any("2023" in a for a in d.alertas))

    def test_ano_novo_e_detectado(self):
        antes = self._manifesto("3" * 64, {2025: dict(empenhada=10.0, liquidada=9.0, paga=8.0)})
        depois = self._manifesto("4" * 64, {
            2025: dict(empenhada=10.0, liquidada=9.0, paga=8.0),
            2026: dict(empenhada=5.0, liquidada=1.0, paga=1.0),
        })
        d = comparar(antes, depois)
        self.assertEqual(d.anos_novos, [2026])


class TestContratoDeLayout(unittest.TestCase):
    def test_arquivo_inexistente(self):
        with self.assertRaises(FileNotFoundError):
            ler_execucao_anual(Path("nao_existe.xlsx"))

    @unittest.skipUnless(CAMINHO_BASE.exists(), f"Base ausente em {CAMINHO_BASE}")
    def test_layout_diferente_e_rejeitado(self):
        df = pd.read_excel(CAMINHO_BASE, header=None, nrows=5, dtype=str).drop(columns=[0])
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            df.to_excel(tmp.name, header=False, index=False)
            with self.assertRaises(ErroLayoutBase):
                ler_execucao_anual(tmp.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
