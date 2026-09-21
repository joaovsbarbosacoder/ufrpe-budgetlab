"""Testes de `src/importacao_execucao_mensal.py` — a especialização do núcleo genérico de
importação versionada (`src/importacao_versionada.py`) para a Execução Mensal.

O núcleo genérico (manifesto, delta, política de confirmação) já é testado por
`tests/test_importacao_versionada.py`; aqui o foco é só a amarração específica desta base:
`reconciliar`/`MEDIDAS` do leitor (`src/tesouro_execucao_mensal.py`) encaixando no contrato
que o núcleo exige (`anos`, `totais`, `totais_por_ano` por medida — ver
`src/tesouro_execucao_mensal.reconciliar`), e `carregar_atual` compondo por ano entre
manifestos diferentes.

Usa a fixture congelada `tests/fixtures/execucao_mensal_2026-09-21.xlsx` (multi-aba,
2024-2026) — pulado se o arquivo não existir. Todo teste que grava manifesto/arquivo usa um
diretório temporário próprio, nunca `data/raw/`/`data/manifestos/` reais.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import openpyxl

from src.importacao_execucao_mensal import (
    Manifesto,
    carregar_atual,
    comparar,
    exige_confirmacao,
    gerar_manifesto,
    importar,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMINHO_FIXTURE = PROJECT_ROOT / "tests/fixtures/execucao_mensal_2026-09-21.xlsx"

#: coluna 1-indexada (openpyxl) da "Empenhada" do bloco JAN — 0-indexada 41 (PRIMEIRA_COLUNA_MESES).
COL_EMPENHADA_JAN = 42
LINHA_DADOS = 7  # primeira linha de dado de qualquer aba (após banner + cabeçalho de 3 linhas)


def _copia_com_ano_alterado(caminho_base: Path, destino: Path, aba: str, delta: float) -> Path:
    """Cópia do arquivo de referência com a Empenhada de JAN de uma aba alterada — usada para
    simular uma reimportação com mudança retroativa naquele exercício."""

    wb = openpyxl.load_workbook(caminho_base)
    celula = wb[aba].cell(row=LINHA_DADOS, column=COL_EMPENHADA_JAN)
    celula.value = float(celula.value or 0) + delta
    wb.save(destino)
    return destino


@unittest.skipUnless(CAMINHO_FIXTURE.exists(), f"Fixture ausente em {CAMINHO_FIXTURE}")
class TestGerarManifesto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / CAMINHO_FIXTURE.name
            caminho.write_bytes(CAMINHO_FIXTURE.read_bytes())
            from src.tesouro_execucao_mensal import ler_execucao_mensal

            cls.df = ler_execucao_mensal(caminho)
            cls.manifesto = gerar_manifesto(cls.df, caminho)

    def test_base_e_anos(self):
        self.assertEqual(self.manifesto.base, "execucao_mensal")
        self.assertEqual(self.manifesto.anos, [2024, 2025, 2026])

    def test_totais_por_ano_tem_as_3_medidas(self):
        for ano in self.manifesto.anos:
            medidas = self.manifesto.totais_por_ano[str(ano)]
            self.assertIn("empenhada", medidas)
            self.assertIn("liquidada", medidas)
            self.assertIn("paga", medidas)

    def test_contagens_estruturais(self):
        self.assertEqual(self.manifesto.contagens.get("linhas_originais"), 5773)
        self.assertEqual(self.manifesto.contagens.get("notas_empenho_distintas"), 2567)


@unittest.skipUnless(CAMINHO_FIXTURE.exists(), f"Fixture ausente em {CAMINHO_FIXTURE}")
class TestImportarEComparar(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.raiz = Path(self._tmpdir.name)
        self.raw = self.raiz / "raw"
        self.manifestos = self.raiz / "manifestos"
        self.raw.mkdir()
        self.manifestos.mkdir()

    def _copiar_fixture(self, nome: str | None = None) -> Path:
        destino = self.raw / (nome or CAMINHO_FIXTURE.name)
        destino.write_bytes(CAMINHO_FIXTURE.read_bytes())
        return destino

    def test_primeira_importacao_nao_tem_anterior(self):
        caminho = self._copiar_fixture()
        resultado = importar(caminho, diretorio_manifestos=self.manifestos)
        self.assertTrue(resultado.ok, resultado.validacao.erros)
        self.assertFalse(resultado.delta.houve_anterior)
        self.assertIsNotNone(resultado.caminho_manifesto)
        self.assertEqual(Manifesto.atual(diretorio=self.manifestos).anos, [2024, 2025, 2026])

    def test_reimportar_arquivo_identico_nao_gera_novo_manifesto(self):
        caminho = self._copiar_fixture()
        importar(caminho, diretorio_manifestos=self.manifestos)

        caminho2 = self._copiar_fixture("copia_identica.xlsx")
        resultado = importar(caminho2, diretorio_manifestos=self.manifestos)
        self.assertTrue(resultado.delta.mesma_extracao)
        self.assertIsNone(resultado.caminho_manifesto)


@unittest.skipUnless(CAMINHO_FIXTURE.exists(), f"Fixture ausente em {CAMINHO_FIXTURE}")
class TestComparar(unittest.TestCase):
    """`comparar()` (delta + retroatividade) via `Manifesto` construído direto — mais rápido e
    mais confiável que editar célula por célula na planilha real (a mesma alteração de valor
    pode não aparecer em `totais_por_ano` se cair numa linha de item de execução ou não for a
    `"first"` escolhida por `valor_empenhado_por_bloco` dentro do grupo — a mecânica de
    detecção de retroatividade em si já é testada pelo núcleo genérico em
    `tests/test_importacao_versionada.py`; aqui só confere que esta base passa `anos`/
    `totais_por_ano` no formato que esse núcleo espera, ver `src.tesouro_execucao_mensal.
    reconciliar`)."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / CAMINHO_FIXTURE.name
            caminho.write_bytes(CAMINHO_FIXTURE.read_bytes())
            from src.tesouro_execucao_mensal import ler_execucao_mensal

            cls.df = ler_execucao_mensal(caminho)
            cls.manifesto_base = gerar_manifesto(cls.df, caminho)

    def _manifesto_com_2024_alterado(self, delta: float) -> Manifesto:
        totais_por_ano = {k: dict(v) for k, v in self.manifesto_base.totais_por_ano.items()}
        totais_por_ano["2024"]["empenhada"] += delta
        return Manifesto(
            base="execucao_mensal", arquivo="variante.xlsx", sha256="outro_hash",
            data_extracao=self.manifesto_base.data_extracao, importado_em=self.manifesto_base.importado_em,
            anos=self.manifesto_base.anos, totais=self.manifesto_base.totais,
            totais_por_ano=totais_por_ano, contagens=self.manifesto_base.contagens,
        )

    def test_mudanca_no_ano_mais_antigo_e_retroativa_e_exige_confirmacao(self):
        novo = self._manifesto_com_2024_alterado(12345.67)
        delta = comparar(self.manifesto_base, novo)

        self.assertIn(2024, delta.anos_retroativos)
        self.assertIsNotNone(exige_confirmacao(delta))
        self.assertAlmostEqual(delta.anos_alterados[2024]["empenhada"]["diferenca"], 12345.67, places=2)

    def test_mudanca_no_ano_mais_recente_nao_e_retroativa(self):
        totais_por_ano = {k: dict(v) for k, v in self.manifesto_base.totais_por_ano.items()}
        totais_por_ano["2026"]["empenhada"] += 500.0
        novo = Manifesto(
            base="execucao_mensal", arquivo="variante.xlsx", sha256="outro_hash2",
            data_extracao=self.manifesto_base.data_extracao, importado_em=self.manifesto_base.importado_em,
            anos=self.manifesto_base.anos, totais=self.manifesto_base.totais,
            totais_por_ano=totais_por_ano, contagens=self.manifesto_base.contagens,
        )
        delta = comparar(self.manifesto_base, novo)

        self.assertNotIn(2026, delta.anos_retroativos)
        self.assertIsNone(exige_confirmacao(delta))


@unittest.skipUnless(CAMINHO_FIXTURE.exists(), f"Fixture ausente em {CAMINHO_FIXTURE}")
class TestCarregarAtualComposicaoPorAno(unittest.TestCase):
    """`carregar_atual` precisa compor anos de manifestos DIFERENTES — mesmo comportamento de
    `importacao_execucao.carregar_atual` (Execução Anual), ver docstring de
    `src/importacao_versionada.py`."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.raiz = Path(self._tmpdir.name)
        self.raw = self.raiz / "raw"
        self.manifestos = self.raiz / "manifestos"
        self.raw.mkdir()
        self.manifestos.mkdir()

    def test_segunda_importacao_so_atualiza_o_ano_que_mudou(self):
        base = self.raw / CAMINHO_FIXTURE.name
        base.write_bytes(CAMINHO_FIXTURE.read_bytes())
        importar(base, diretorio_manifestos=self.manifestos)

        # segunda extração: só 2026 mudou (mesmo espírito de um upload trazendo só o
        # exercício corrente) — 2024/2025 devem continuar vindo do arquivo ORIGINAL.
        variante = _copia_com_ano_alterado(base, self.raw / "atualizacao_2026.xlsx", "2026", 999.99)
        resultado2 = importar(variante, diretorio_manifestos=self.manifestos)
        self.assertTrue(resultado2.ok, resultado2.validacao.erros)
        self.assertIsNotNone(resultado2.caminho_manifesto)

        composto = carregar_atual(diretorio_dados_brutos=self.raw, diretorio_manifestos=self.manifestos)
        self.assertEqual(sorted(composto["ano"].unique().tolist()), [2024, 2025, 2026])
        # nenhuma linha duplicada entre os dois arquivos para o mesmo ano.
        self.assertEqual(
            len(composto), len(composto.drop_duplicates(["ano", "aba_origem", "linha_origem", "ano_mes"]))
        )

    def test_nenhuma_importacao_devolve_none(self):
        self.assertIsNone(carregar_atual(diretorio_dados_brutos=self.raw, diretorio_manifestos=self.manifestos))


if __name__ == "__main__":
    unittest.main()
