"""Preferências de tela persistidas (12/10/2026): `src/preferencias_ui.py`.

Persistência autorizada pelo usuário para lembrar a "Base da necessidade de empenho" (Contratos Contínuos). Arquivo único
`data/preferencias/ui.json` (fora do Git), gravação atômica; arquivo ilegível é erro explícito (nunca sobrescrito).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.preferencias_ui import ErroPreferencia, carregar, salvar


class PreferenciasTests(unittest.TestCase):
    def test_sem_arquivo_devolve_o_padrao(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(carregar("base", "padrao", diretorio=Path(tmp)), "padrao")

    def test_salva_e_carrega(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            salvar("base", "execucao", diretorio=Path(tmp))
            self.assertEqual(carregar("base", "padrao", diretorio=Path(tmp)), "execucao")
            self.assertEqual(json.loads((Path(tmp) / "ui.json").read_text(encoding="utf-8"))["versao_schema"], 1)

    def test_salvar_uma_chave_preserva_as_outras(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            salvar("a", 1, diretorio=Path(tmp))
            salvar("b", 2, diretorio=Path(tmp))
            salvar("a", 3, diretorio=Path(tmp))
            self.assertEqual((carregar("a", 0, diretorio=Path(tmp)), carregar("b", 0, diretorio=Path(tmp))), (3, 2))

    def test_valor_fora_das_validas_cai_no_padrao(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            salvar("base", "opcao_antiga_removida", diretorio=Path(tmp))
            self.assertEqual(carregar("base", "contratual", validas=("contratual", "execucao"), diretorio=Path(tmp)), "contratual")
            salvar("base", "execucao", diretorio=Path(tmp))
            self.assertEqual(carregar("base", "contratual", validas=("contratual", "execucao"), diretorio=Path(tmp)), "execucao")

    def test_arquivo_ilegivel_e_erro_e_nao_e_sobrescrito(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "ui.json"
            arquivo.write_text("{ quebrado", encoding="utf-8")
            with self.assertRaises(ErroPreferencia):
                carregar("base", "padrao", diretorio=Path(tmp))
            with self.assertRaises(ErroPreferencia):
                salvar("base", "x", diretorio=Path(tmp))
            self.assertEqual(arquivo.read_text(encoding="utf-8"), "{ quebrado")  # nada foi perdido

    def test_chave_ausente_no_arquivo_devolve_o_padrao(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            salvar("a", 1, diretorio=Path(tmp))
            self.assertEqual(carregar("outra", "padrao", diretorio=Path(tmp)), "padrao")


if __name__ == "__main__":
    unittest.main()
