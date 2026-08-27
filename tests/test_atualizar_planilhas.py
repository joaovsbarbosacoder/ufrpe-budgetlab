"""Testes de src/atualizar_planilhas.py — validação de layout antes de aceitar, backup da
versão anterior com carimbo de data/hora, e nenhuma escrita quando a validação falha.

Usa as fixtures congeladas das 4 bases (ver AGENTS.md), mas todo teste que grava arquivo
constrói seu próprio `EspecificacaoBase` apontando pra um diretório temporário — nunca pra
`data/raw/` real, mesmo reaproveitando `ESPECIFICACOES` só para os testes de estrutura.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import openpyxl

from src.atualizar_planilhas import ESPECIFICACOES, EspecificacaoBase, substituir_planilha
from src.bolsas_auxilios import NOME_ABA, ler_bolsas_auxilios

FIXTURE_BOLSAS = Path("tests/fixtures/bolsas_auxilios_2026-08-13.xlsx")


def _variante_bolsas_com_layout_invalido(caminho: Path, destino: Path) -> Path:
    """Cópia da fixture de Bolsas com o cabeçalho "EMPENHO" renomeado — mesmo truque de
    `tests/test_bolsas_auxilios.py::_variante_com_coluna_renomeada`, duplicado aqui porque
    este módulo testa a camada de substituição, não a validação de layout em si (já coberta
    lá base a base)."""
    wb = openpyxl.load_workbook(caminho)
    aba = wb[NOME_ABA]
    for linha in aba.iter_rows(min_row=4, max_row=4):
        for celula in linha:
            if celula.value == "EMPENHO":
                celula.value = "EMPENHO RENOMEADO"
    wb.save(destino)
    return destino


class TestEspecificacoes(unittest.TestCase):
    """As 4 bases sem reimportação versionada precisam estar cadastradas — ver AGENTS.md,
    seção "Fixtures de teste vs. dados de trabalho"."""

    def test_quatro_bases_cadastradas(self):
        self.assertEqual(len(ESPECIFICACOES), 4)
        for chave in ("contratos_continuos", "bolsas_auxilios", "contratos_vigencia", "contratos_pagamentos"):
            self.assertIn(chave, ESPECIFICACOES)

    def test_extensao_bate_com_o_sufixo_do_arquivo_atual(self):
        for spec in ESPECIFICACOES.values():
            self.assertEqual(spec.caminho.suffix, f".{spec.extensao}")


@unittest.skipUnless(FIXTURE_BOLSAS.exists(), f"Fixture ausente em {FIXTURE_BOLSAS}")
class TestSubstituirPlanilha(unittest.TestCase):
    def _spec(self, diretorio: Path) -> EspecificacaoBase:
        return EspecificacaoBase(
            chave="teste", nome="Base de Teste",
            caminho=diretorio / "base.xlsx", extensao="xlsx", validar=ler_bolsas_auxilios,
        )

    def test_primeira_substituicao_nao_gera_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = self._spec(Path(tmp))
            resultado = substituir_planilha(spec, FIXTURE_BOLSAS)
            self.assertIsNone(resultado.caminho_backup)
            self.assertTrue(spec.caminho.exists())
            self.assertGreater(resultado.linhas_lidas, 0)

    def test_segunda_substituicao_preserva_a_anterior_em_backup_com_carimbo(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = self._spec(Path(tmp))
            substituir_planilha(spec, FIXTURE_BOLSAS)
            conteudo_anterior = spec.caminho.read_bytes()

            resultado = substituir_planilha(spec, FIXTURE_BOLSAS, agora=datetime(2026, 8, 26, 14, 30))

            self.assertIsNotNone(resultado.caminho_backup)
            self.assertTrue(resultado.caminho_backup.exists())
            self.assertEqual(resultado.caminho_backup.read_bytes(), conteudo_anterior)
            self.assertIn("2026-08-26-14h30", resultado.caminho_backup.name)
            # backup fica ao lado do arquivo, não em data/raw/_backup/ real (ver
            # `_caminho_backup`) — confirma que o teste não vazou pra fora do tmp_dir.
            self.assertEqual(resultado.caminho_backup.parent, spec.caminho.parent / "_backup")
            # arquivo atual continua existindo, com o conteúdo da segunda substituição
            self.assertTrue(spec.caminho.exists())

    def test_layout_invalido_e_rejeitado_sem_alterar_nada_no_disco(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            spec = self._spec(tmp_path)
            substituir_planilha(spec, FIXTURE_BOLSAS)
            conteudo_original = spec.caminho.read_bytes()

            variante = _variante_bolsas_com_layout_invalido(FIXTURE_BOLSAS, tmp_path / "invalida.xlsx")

            with self.assertRaises(Exception):
                substituir_planilha(spec, variante)

            self.assertEqual(spec.caminho.read_bytes(), conteudo_original)
            backup_dir = spec.caminho.parent / "_backup"
            self.assertTrue(not backup_dir.exists() or not any(backup_dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
