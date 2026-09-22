"""Testes de `src/limite_empenho_preferencias.py` — persistência em disco da fração liberada
do Limite de Empenho (pedido explícito do usuário, 22/09/2026: "ao atualizar a página, ele
volta pra o 12")."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.limite_empenho_preferencias import carregar_fracao_liberada, salvar_fracao_liberada


class FracaoLiberadaPreferenciasTests(unittest.TestCase):
    def setUp(self) -> None:
        self._diretorio_temporario = TemporaryDirectory()
        self.addCleanup(self._diretorio_temporario.cleanup)
        self.caminho = Path(self._diretorio_temporario.name) / "fracao_liberada.json"

    def test_carregar_sem_arquivo_devolve_none(self):
        self.assertIsNone(carregar_fracao_liberada(self.caminho))

    def test_salvar_e_carregar_bate_com_o_valor_gravado(self):
        salvar_fracao_liberada(9, 12, self.caminho)
        self.assertEqual(carregar_fracao_liberada(self.caminho), (9, 12))

    def test_salvar_sobrescreve_valor_anterior(self):
        salvar_fracao_liberada(9, 12, self.caminho)
        salvar_fracao_liberada(7, 12, self.caminho)
        self.assertEqual(carregar_fracao_liberada(self.caminho), (7, 12))

    def test_salvar_cria_diretorio_pai_se_nao_existir(self):
        caminho_aninhado = Path(self._diretorio_temporario.name) / "subdir" / "fracao_liberada.json"
        salvar_fracao_liberada(9, 12, caminho_aninhado)
        self.assertTrue(caminho_aninhado.exists())

    def test_salvar_nao_deixa_arquivo_temporario_para_tras(self):
        salvar_fracao_liberada(9, 12, self.caminho)
        arquivos = list(self.caminho.parent.iterdir())
        self.assertEqual(arquivos, [self.caminho])

    def test_carregar_arquivo_corrompido_devolve_none_em_vez_de_lancar_excecao(self):
        self.caminho.write_text("{ isso nao e json valido", encoding="utf-8")
        self.assertIsNone(carregar_fracao_liberada(self.caminho))

    def test_carregar_arquivo_sem_os_campos_esperados_devolve_none(self):
        self.caminho.write_text(json.dumps({"outra_coisa": 1}), encoding="utf-8")
        self.assertIsNone(carregar_fracao_liberada(self.caminho))


if __name__ == "__main__":
    unittest.main()
