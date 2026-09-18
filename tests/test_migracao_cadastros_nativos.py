"""Testes do comando seguro de migração dos cadastros nativos."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import src.bolsas_auxilios_cadastro as bolsas_cadastro
import src.contratos_continuos_cadastro as contratos_cadastro
from scripts.migrar_cadastros_nativos import construir_parser
from src.migracao_cadastros_nativos import (
    ErroMigracaoCadastros,
    migrar_cadastros_nativos,
)


def _bolsas() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "processo": "001",
                "programa_bolsa": "REGULAR",
                "qtd_efetiva": 2,
                "valor_unitario": 500.0,
                "valor_mensal": 1000.0,
                "valor_anual": 12000.0,
                "meses_no_ano": 12,
            },
            {
                "processo": "002",
                "programa_bolsa": "COMPLEMENTO",
                "qtd_efetiva": 0,
                "valor_unitario": 6136.0,
                "valor_mensal": 6136.0,
                "valor_anual": 6136.0,
                "meses_no_ano": 1,
            },
        ]
    )


def _contratos() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contrato_numero": "01/2026",
                "ne_curta": "2026NE000001",
                "despesa_mensal": 600.0,
                "valor_empenhado": 6000.0,
                "item_licitacao": 1,
                "item_percentual": 0.6,
            },
            {
                "contrato_numero": "01/2026",
                "ne_curta": "2026NE000001",
                "despesa_mensal": 400.0,
                "valor_empenhado": 4000.0,
                "item_licitacao": 2,
                "item_percentual": 0.4,
            },
        ]
    )


class TestMigracaoCadastrosNativos(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)
        self.origem_bolsas = self.raiz / "bolsas.xlsx"
        self.origem_contratos = self.raiz / "contratos.xlsm"
        self.origem_bolsas.write_bytes(b"bolsas-integra")
        self.origem_contratos.write_bytes(b"contratos-integra")
        self.destino_bolsas = self.raiz / "dados" / "bolsas"
        self.destino_contratos = self.raiz / "dados" / "contratos"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _executar(
        self,
        *,
        aplicar: bool,
        bolsas_para_validacao: pd.DataFrame | None = None,
    ) -> dict:
        if bolsas_para_validacao is None:
            bolsas_para_validacao = _bolsas()
        with (
            patch(
                "src.migracao_cadastros_nativos.ler_bolsas_auxilios",
                return_value=bolsas_para_validacao,
            ),
            patch(
                "src.migracao_cadastros_nativos.ler_contratos_continuos",
                return_value=_contratos(),
            ),
            patch.object(bolsas_cadastro, "ler_bolsas_auxilios", return_value=_bolsas()),
            patch.object(
                contratos_cadastro,
                "ler_contratos_continuos",
                return_value=_contratos(),
            ),
        ):
            return migrar_cadastros_nativos(
                self.origem_bolsas,
                self.origem_contratos,
                2026,
                diretorio_bolsas=self.destino_bolsas,
                diretorio_contratos=self.destino_contratos,
                aplicar=aplicar,
            )

    def test_simulacao_e_padrao_do_cli(self) -> None:
        argumentos = construir_parser().parse_args([])
        self.assertFalse(argumentos.aplicar)

    def test_simulacao_reconcilia_sem_gravar_destinos(self) -> None:
        resultado = self._executar(aplicar=False)

        self.assertEqual(resultado["modo"], "simulacao")
        self.assertFalse(resultado["gravado"])
        self.assertEqual(resultado["bolsas"]["registros"], 2)
        self.assertEqual(resultado["bolsas"]["valores_mensais_excepcionais"], 1)
        self.assertEqual(resultado["contratos"]["registros"], 1)
        self.assertFalse((self.destino_bolsas / "2026").exists())
        self.assertFalse((self.destino_contratos / "2026").exists())

    def test_aplicacao_promove_os_dois_cadastros_reconciliados(self) -> None:
        resultado = self._executar(aplicar=True)

        self.assertTrue(resultado["gravado"])
        self.assertEqual(len(list((self.destino_bolsas / "2026").glob("*.json"))), 2)
        self.assertEqual(len(list((self.destino_contratos / "2026").glob("*.json"))), 1)
        self.assertEqual(self.origem_bolsas.read_bytes(), b"bolsas-integra")
        self.assertEqual(self.origem_contratos.read_bytes(), b"contratos-integra")

    def test_aplicacao_recusa_exercicio_existente_sem_alterar_arquivos(self) -> None:
        self._executar(aplicar=True)
        arquivos_antes = {
            caminho: caminho.read_bytes()
            for caminho in self.destino_bolsas.parent.rglob("*.json")
        }

        with self.assertRaises(ErroMigracaoCadastros):
            self._executar(aplicar=True)

        arquivos_depois = {
            caminho: caminho.read_bytes()
            for caminho in self.destino_bolsas.parent.rglob("*.json")
        }
        self.assertEqual(arquivos_depois, arquivos_antes)

    def test_divergencia_financeira_bloqueia_promocao(self) -> None:
        divergente = _bolsas()
        divergente.loc[0, "valor_anual"] = 999999.0

        with self.assertRaisesRegex(ErroMigracaoCadastros, "valor anual"):
            self._executar(aplicar=True, bolsas_para_validacao=divergente)

        self.assertFalse((self.destino_bolsas / "2026").exists())
        self.assertFalse((self.destino_contratos / "2026").exists())


if __name__ == "__main__":
    unittest.main()
