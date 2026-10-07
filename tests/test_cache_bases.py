"""Cache em Parquet das bases lidas (`src/cache_bases.py`): desligado por padrão, chave pelo conteúdo
do arquivo e pelos argumentos, só grava o que volta idêntico, e falha do cache nunca impede a leitura."""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

from src import cache_bases
from src.liquidacao_competencia import ler_liquidacao_competencia

FIXTURES = Path(__file__).parent / "fixtures"
TEM_PYARROW = importlib.util.find_spec("pyarrow") is not None

CHAMADAS: list[str] = []


@cache_bases.em_cache
def _leitor_teste(caminho, fator: int = 1) -> pd.DataFrame:
    CHAMADAS.append(str(caminho))
    texto = Path(caminho).read_text(encoding="utf-8")
    return pd.DataFrame(
        {
            "codigo": pd.array(["0012", "A1"], dtype="string"),  # zero à esquerda e alfanumérico
            "valor": pd.array([float(len(texto)) * fator, None], dtype="Float64"),  # nulo ≠ zero
        }
    )


@cache_bases.em_cache
def _leitor_com_nome(caminho) -> pd.DataFrame:
    CHAMADAS.append(str(caminho))
    return pd.DataFrame({"arquivo_origem": pd.array([Path(caminho).name], dtype="string")})


@cache_bases.em_cache
def _leitor_tipo_misto(caminho) -> pd.DataFrame:
    CHAMADAS.append("misto")
    return pd.DataFrame({"x": [1, "a", None]}, dtype=object)  # o Parquet não devolve idêntico


@unittest.skipUnless(TEM_PYARROW, "pyarrow não instalado")
class TestCacheBases(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())
        self.cache = self.pasta / "cache"
        self.arquivo = self.pasta / "base.txt"
        self.arquivo.write_text("abc", encoding="utf-8")
        CHAMADAS.clear()

    def tearDown(self):
        cache_bases.desativar()
        shutil.rmtree(self.pasta, ignore_errors=True)

    def test_desligado_por_padrao(self):
        cache_bases.desativar()
        _leitor_teste(self.arquivo)
        _leitor_teste(self.arquivo)
        self.assertEqual(len(CHAMADAS), 2)
        self.assertFalse(self.cache.exists())

    def test_segunda_leitura_vem_do_cache_identica(self):
        self.assertTrue(cache_bases.ativar(self.cache))
        primeira = _leitor_teste(self.arquivo)
        segunda = _leitor_teste(self.arquivo)
        self.assertEqual(len(CHAMADAS), 1)
        assert_frame_equal(primeira, segunda, check_dtype=True, check_exact=True)
        self.assertEqual(segunda["codigo"].tolist(), ["0012", "A1"])
        self.assertTrue(pd.isna(segunda["valor"].iloc[1]))

    def test_conteudo_e_argumentos_mudam_a_chave(self):
        cache_bases.ativar(self.cache)
        _leitor_teste(self.arquivo)
        self.arquivo.write_text("abcd", encoding="utf-8")  # mesmo nome, conteúdo novo
        self.assertEqual(_leitor_teste(self.arquivo)["valor"].iloc[0], 4.0)
        self.assertEqual(_leitor_teste(self.arquivo, fator=2)["valor"].iloc[0], 8.0)
        self.assertEqual(len(CHAMADAS), 3)

    def test_mesmo_conteudo_com_outro_nome_nao_reaproveita_a_copia(self):
        # o leitor grava o nome do arquivo (`arquivo_origem`): dois arquivos com os mesmos bytes e nomes
        # diferentes não podem compartilhar a cópia — senão a rastreabilidade aponta o arquivo errado
        cache_bases.ativar(self.cache)
        copia = self.pasta / "outro_nome.txt"
        copia.write_bytes(self.arquivo.read_bytes())
        _leitor_com_nome(self.arquivo)
        self.assertEqual(_leitor_com_nome(copia)["arquivo_origem"].tolist(), ["outro_nome.txt"])
        self.assertEqual(_leitor_com_nome(self.arquivo)["arquivo_origem"].tolist(), ["base.txt"])
        self.assertEqual(len(CHAMADAS), 2)

    def test_tipo_que_nao_volta_identico_nao_e_gravado(self):
        cache_bases.ativar(self.cache)
        _leitor_tipo_misto(self.arquivo)
        _leitor_tipo_misto(self.arquivo)
        self.assertEqual(CHAMADAS, ["misto", "misto"])
        self.assertEqual(list(self.cache.glob("*.parquet")), [])
        self.assertEqual(list(self.cache.glob("*.tmp")), [])

    def test_copia_corrompida_e_relida_da_planilha(self):
        cache_bases.ativar(self.cache)
        _leitor_teste(self.arquivo)
        for copia in self.cache.glob("*.parquet"):
            copia.write_bytes(b"lixo")
        resultado = _leitor_teste(self.arquivo)
        self.assertEqual(len(CHAMADAS), 2)
        self.assertEqual(resultado["valor"].iloc[0], 3.0)

    def test_leitor_real(self):
        cache_bases.ativar(self.cache)
        arquivo = FIXTURES / "liquidacao_competencia_2026-09-11.xlsx"
        direto = ler_liquidacao_competencia.sem_cache(arquivo)
        ler_liquidacao_competencia(arquivo)
        do_cache = ler_liquidacao_competencia(arquivo)
        self.assertEqual(len(list(self.cache.glob("ler_liquidacao_competencia_*.parquet"))), 1)
        assert_frame_equal(direto, do_cache, check_dtype=True, check_exact=True)


if __name__ == "__main__":
    unittest.main()
