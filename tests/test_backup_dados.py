"""Testes de src/backup_dados.py e da página app_pages/backup_dados.py.

Tudo em diretório temporário: nenhum teste lê ou grava em `data/` real.
"""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from src import backup_dados
from src.backup_dados import ErroBackup, analisar_backup, gerar_backup, restaurar_backup
from tests._apptest import TEMPO_LIMITE_APPTEST

PAGINA = Path(__file__).resolve().parents[1] / "app_pages" / "backup_dados.py"
AGORA = datetime(2026, 10, 1, 10, 30, 0)


def _escrever(base: Path, relativo: str, conteudo: bytes | str) -> Path:
    caminho = base / relativo
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo if isinstance(conteudo, bytes) else conteudo.encode("utf-8"))
    return caminho


def _arvore(base: Path) -> dict[str, bytes]:
    return {
        p.relative_to(base).as_posix(): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()
    }


def _popular(base: Path) -> None:
    _escrever(base, "raw/Planilha Ação.xlsx", b"\x00xlsx\xffbytes")
    _escrever(base, "raw/_backup/Planilha__substituida-2026-09-11.xlsx", b"antiga")
    _escrever(base, "manifestos/dotacao_anual_atual.json", '{"codigo": "0012"}')
    _escrever(base, "demandas/abc.json", '{"valor": null, "zero": 0, "neg": -1.5}')
    _escrever(base, "limite_empenho/fracao_liberada.json", '{"fracao": 0.5}')
    _escrever(base, "google_agenda/historico_sincronizacao.jsonl", "{}\n")
    _escrever(base, "google_agenda/credentials.json", '{"installed": {"client_secret": "x"}}')
    _escrever(base, "google_agenda/token.json", '{"refresh_token": "SEGREDO"}')
    _escrever(base, "raw/.gitkeep", b"")
    _escrever(base, "bolsas_auxilios/.gitkeep", b"")


def _zip_com(itens: dict[str, bytes], manifesto: dict | None = None) -> bytes:
    """Monta um .zip à mão (para os casos adulterados)."""

    if manifesto is None:
        import hashlib

        manifesto = {
            "formato_versao": backup_dados.FORMATO_VERSAO,
            "criado_em": AGORA.isoformat(),
            "grupos": [],
            "credenciais_incluidas": False,
            "arquivos": [
                {"caminho": c, "tamanho": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                for c, b in itens.items()
            ],
        }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for caminho, conteudo in itens.items():
            zf.writestr(caminho, conteudo)
        zf.writestr(backup_dados.NOME_MANIFESTO, json.dumps(manifesto))
    return buffer.getvalue()


class TestExportar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.origem = Path(self._tmp.name) / "origem"
        _popular(self.origem)

    def _manifesto(self, conteudo: bytes) -> dict:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as zf:
            return json.loads(zf.read(backup_dados.NOME_MANIFESTO))

    def test_manifesto_traz_tamanho_e_sha256_e_ignora_gitkeep(self):
        conteudo = gerar_backup(self.origem, agora=AGORA)
        manifesto = self._manifesto(conteudo)
        caminhos = {a["caminho"] for a in manifesto["arquivos"]}
        self.assertIn("raw/Planilha Ação.xlsx", caminhos)
        self.assertIn("raw/_backup/Planilha__substituida-2026-09-11.xlsx", caminhos)
        self.assertFalse(any(c.endswith(".gitkeep") for c in caminhos))
        self.assertEqual(manifesto["criado_em"], "2026-10-01T10:30:00")
        arquivo = next(a for a in manifesto["arquivos"] if a["caminho"] == "raw/Planilha Ação.xlsx")
        self.assertEqual(arquivo["tamanho"], len(b"\x00xlsx\xffbytes"))
        self.assertEqual(len(arquivo["sha256"]), 64)

    def test_token_nunca_entra_e_credenciais_so_com_opcao(self):
        padrao = {a["caminho"] for a in self._manifesto(gerar_backup(self.origem))["arquivos"]}
        self.assertNotIn("google_agenda/token.json", padrao)
        self.assertNotIn("google_agenda/credentials.json", padrao)
        self.assertIn("google_agenda/historico_sincronizacao.jsonl", padrao)

        com = self._manifesto(gerar_backup(self.origem, incluir_credenciais=True))
        caminhos = {a["caminho"] for a in com["arquivos"]}
        self.assertIn("google_agenda/credentials.json", caminhos)
        self.assertNotIn("google_agenda/token.json", caminhos)
        self.assertTrue(com["credenciais_incluidas"])

    def test_exportar_nao_altera_a_origem(self):
        antes = _arvore(self.origem)
        gerar_backup(self.origem, incluir_credenciais=True)
        self.assertEqual(_arvore(self.origem), antes)

    def test_selecao_de_pastas(self):
        manifesto = self._manifesto(gerar_backup(self.origem, grupos=["demandas"]))
        self.assertEqual([a["caminho"] for a in manifesto["arquivos"]], ["demandas/abc.json"])

    def test_pasta_desconhecida_e_recusada(self):
        with self.assertRaises(ErroBackup):
            gerar_backup(self.origem, grupos=["raw", "inexistente"])

    def test_origem_vazia_gera_backup_sem_arquivos(self):
        vazia = Path(self._tmp.name) / "vazia"
        self.assertEqual(self._manifesto(gerar_backup(vazia))["arquivos"], [])

    def test_sqlite_e_copiado_de_forma_consistente(self):
        banco = self.origem / "captacao" / "captacao.db"
        banco.parent.mkdir(parents=True)
        con = sqlite3.connect(banco)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE t (codigo TEXT, valor REAL)")
        con.execute("INSERT INTO t VALUES ('00123', NULL), ('B7', 0), ('C', -2.5)")
        con.commit()  # fica no -wal enquanto a conexão está aberta
        self.addCleanup(con.close)

        conteudo = gerar_backup(self.origem, grupos=["captacao"])
        caminhos = {a["caminho"] for a in self._manifesto(conteudo)["arquivos"]}
        self.assertEqual(caminhos, {"captacao/captacao.db"})  # sem -wal/-shm

        destino = Path(self._tmp.name) / "destino"
        restaurar_backup(conteudo, destino)
        restaurado = sqlite3.connect(destino / "captacao" / "captacao.db")
        self.addCleanup(restaurado.close)
        linhas = restaurado.execute("SELECT codigo, valor FROM t ORDER BY codigo").fetchall()
        self.assertEqual(linhas, [("00123", None), ("B7", 0.0), ("C", -2.5)])


class TestIdaEVolta(unittest.TestCase):
    def test_restauracao_em_diretorio_limpo_reproduz_os_arquivos_byte_a_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            origem, destino = Path(tmp) / "o", Path(tmp) / "d"
            _popular(origem)
            conteudo = gerar_backup(origem, incluir_credenciais=True)

            previa = analisar_backup(conteudo, destino)
            self.assertTrue(all(i.situacao == "novo" for i in previa.itens))

            resultado = restaurar_backup(conteudo, destino)
            esperado = {
                c: b for c, b in _arvore(origem).items()
                if not c.endswith(".gitkeep") and not c.endswith("token.json")
            }
            self.assertEqual(_arvore(destino), esperado)
            self.assertEqual(sorted(resultado.novos), sorted(esperado))
            self.assertEqual(resultado.substituidos, [])
            # códigos/valores nulo, zero e negativo preservados literalmente
            self.assertEqual(
                (destino / "demandas/abc.json").read_text(encoding="utf-8"),
                '{"valor": null, "zero": 0, "neg": -1.5}',
            )

    def test_restaurar_de_novo_so_acha_identicos(self):
        with tempfile.TemporaryDirectory() as tmp:
            origem, destino = Path(tmp) / "o", Path(tmp) / "d"
            _popular(origem)
            conteudo = gerar_backup(origem)
            restaurar_backup(conteudo, destino)
            previa = analisar_backup(conteudo, destino)
            self.assertTrue(all(i.situacao == "identico" for i in previa.itens))
            resultado = restaurar_backup(conteudo, destino, substituir=True)
            self.assertEqual((resultado.novos, resultado.substituidos), ([], []))


class TestRecusas(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.destino = Path(self._tmp.name) / "d"

    def _recusa(self, conteudo: bytes):
        with self.assertRaises(ErroBackup):
            analisar_backup(conteudo, self.destino)
        with self.assertRaises(ErroBackup):
            restaurar_backup(conteudo, self.destino, substituir=True)
        arquivos = [p for p in self.destino.rglob("*") if p.is_file()] if self.destino.exists() else []
        self.assertEqual(arquivos, [], "recusa não pode gravar nada")

    def test_nao_zip(self):
        self._recusa(b"isto nao e um zip")

    def test_zip_sem_manifesto(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("raw/a.xlsx", b"x")
        self._recusa(buffer.getvalue())

    def test_hash_divergente(self):
        bom = _zip_com({"raw/a.xlsx": b"conteudo"})
        buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(bom)) as origem, zipfile.ZipFile(buffer, "w") as saida:
            for info in origem.infolist():
                dados = origem.read(info.filename)
                saida.writestr(info.filename, b"ADULTERADO" if info.filename == "raw/a.xlsx" else dados)
        self._recusa(buffer.getvalue())

    def test_tamanho_divergente(self):
        manifesto = {
            "formato_versao": 1, "criado_em": "", "arquivos": [
                {"caminho": "raw/a.xlsx", "tamanho": 3, "sha256": "0" * 64}
            ],
        }
        self._recusa(_zip_com({"raw/a.xlsx": b"conteudo"}, manifesto))

    def test_caminhos_perigosos(self):
        for caminho in [
            "../fora.txt", "raw/../../fora.txt", "/abs/a.txt", "C:/x.txt", "raw\\a.xlsx",
            "desconhecida/a.txt", "a.txt", "raw//a.txt", "google_agenda/token.json",
        ]:
            with self.subTest(caminho=caminho):
                self._recusa(_zip_com({caminho: b"x"}))
        self.assertFalse((Path(self._tmp.name) / "fora.txt").exists())

    def test_arquivo_fora_do_manifesto(self):
        base = _zip_com({"raw/a.xlsx": b"x"})
        buffer = io.BytesIO(base)
        with zipfile.ZipFile(buffer, "a") as zf:
            zf.writestr("raw/extra.xlsx", b"intruso")
        self._recusa(buffer.getvalue())

    def test_arquivo_ausente_do_zip(self):
        manifesto = {
            "formato_versao": 1, "criado_em": "", "arquivos": [
                {"caminho": "raw/a.xlsx", "tamanho": 1, "sha256": "0" * 64}
            ],
        }
        self._recusa(_zip_com({}, manifesto))

    def test_versao_de_formato_desconhecida(self):
        self._recusa(_zip_com({"raw/a.xlsx": b"x"}, {"formato_versao": 99, "arquivos": []}))


class TestConflitos(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.origem = Path(self._tmp.name) / "o"
        self.destino = Path(self._tmp.name) / "d"
        _escrever(self.origem, "demandas/a.json", "do backup")
        _escrever(self.origem, "demandas/nova.json", "nova")
        _escrever(self.destino, "demandas/a.json", "atual local")
        self.conteudo = gerar_backup(self.origem)

    def test_previa_classifica_novo_e_diferente(self):
        previa = analisar_backup(self.conteudo, self.destino)
        self.assertEqual([i.caminho for i in previa.com_situacao("diferente")], ["demandas/a.json"])
        self.assertEqual([i.caminho for i in previa.com_situacao("novo")], ["demandas/nova.json"])

    def test_padrao_nunca_sobrescreve_em_silencio(self):
        resultado = restaurar_backup(self.conteudo, self.destino)
        self.assertEqual((self.destino / "demandas/a.json").read_text(), "atual local")
        self.assertEqual((self.destino / "demandas/nova.json").read_text(), "nova")
        self.assertEqual(resultado.mantidos_diferentes, ["demandas/a.json"])
        self.assertEqual(resultado.novos, ["demandas/nova.json"])
        self.assertFalse((self.destino / backup_dados.PASTA_COPIAS_RESTAURACAO).exists())

    def test_substituir_preserva_copia_do_atual(self):
        resultado = restaurar_backup(self.conteudo, self.destino, substituir=True, agora=AGORA)
        self.assertEqual((self.destino / "demandas/a.json").read_text(), "do backup")
        self.assertEqual(resultado.substituidos, ["demandas/a.json"])
        copia = resultado.pasta_copias / "demandas/a.json"
        self.assertEqual(copia.read_text(), "atual local")
        self.assertEqual(resultado.pasta_copias.name, "2026-10-01-10h30m00s")

    def test_falha_no_meio_desfaz_tudo(self):
        original = backup_dados.os.replace
        chamadas = {"n": 0}

        def falha_na_segunda(origem, destino):
            chamadas["n"] += 1
            if chamadas["n"] == 2:
                raise OSError("disco cheio")
            return original(origem, destino)

        with mock.patch.object(backup_dados.os, "replace", side_effect=falha_na_segunda):
            with self.assertRaises(OSError):
                restaurar_backup(self.conteudo, self.destino, substituir=True)
        self.assertEqual((self.destino / "demandas/a.json").read_text(), "atual local")
        self.assertFalse((self.destino / "demandas/nova.json").exists())
        self.assertEqual(
            [p.name for p in self.destino.iterdir() if p.name.startswith(".restauracao")], []
        )


class TestPagina(unittest.TestCase):
    def test_pagina_gera_backup_sem_excecao(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _popular(base)
            with mock.patch.object(backup_dados, "BASE_PADRAO", base):
                at = AppTest.from_file(str(PAGINA), default_timeout=TEMPO_LIMITE_APPTEST).run()
                self.assertFalse(at.exception)
                at.button[0].click().run()
                self.assertFalse(at.exception)
                self.assertTrue(any("Backup pronto" in s.value for s in at.success))
                nome, conteudo = at.session_state["backup_dados_pacote"]
                self.assertTrue(nome.endswith(".zip"))
                caminhos = {i.caminho for i in analisar_backup(conteudo, base / "x").itens}
                self.assertNotIn("google_agenda/credentials.json", caminhos)
                self.assertNotIn("google_agenda/token.json", caminhos)


class TestSenha(unittest.TestCase):
    SENHA = "senha-forte-123"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.origem = Path(self._tmp.name) / "o"
        self.destino = Path(self._tmp.name) / "d"
        _popular(self.origem)
        self.cifrado = gerar_backup(self.origem, incluir_credenciais=True, senha=self.SENHA)

    def test_pacote_cifrado_nao_expoe_conteudo_nem_nomes(self):
        self.assertTrue(backup_dados.esta_criptografado(self.cifrado))
        self.assertFalse(zipfile.is_zipfile(io.BytesIO(self.cifrado)))
        for trecho in (b"client_secret", b"Planilha", b"MANIFESTO", b"manifestos/"):
            self.assertNotIn(trecho, self.cifrado)

    def test_sem_senha_o_backup_continua_zip_comum(self):
        simples = gerar_backup(self.origem)
        self.assertFalse(backup_dados.esta_criptografado(simples))
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(simples)))

    def test_ida_e_volta_com_senha_igual_ao_sem_senha(self):
        previa = analisar_backup(self.cifrado, self.destino, self.SENHA)
        self.assertTrue(previa.credenciais_incluidas)
        restaurar_backup(self.cifrado, self.destino, senha=self.SENHA)
        esperado = {
            c: b for c, b in _arvore(self.origem).items()
            if not c.endswith((".gitkeep", "token.json"))
        }
        self.assertEqual(_arvore(self.destino), esperado)

    def test_senha_errada_ausente_ou_vazia_e_recusada_sem_gravar(self):
        for senha in ("outra-senha-123", None, ""):
            with self.subTest(senha=senha):
                with self.assertRaises(ErroBackup):
                    analisar_backup(self.cifrado, self.destino, senha)
                with self.assertRaises(ErroBackup):
                    restaurar_backup(self.cifrado, self.destino, senha=senha)
        self.assertFalse(self.destino.exists() and any(self.destino.rglob("*.*")))

    def test_pacote_cifrado_adulterado_ou_truncado_e_recusado(self):
        adulterado = bytearray(self.cifrado)
        adulterado[len(adulterado) // 2] ^= 0x01
        with self.assertRaises(ErroBackup):
            analisar_backup(bytes(adulterado), self.destino, self.SENHA)
        cabecalho_adulterado = bytearray(self.cifrado)
        cabecalho_adulterado[10] ^= 0x01  # salt
        with self.assertRaises(ErroBackup):
            analisar_backup(bytes(cabecalho_adulterado), self.destino, self.SENHA)
        with self.assertRaises(ErroBackup):
            analisar_backup(self.cifrado[:20], self.destino, self.SENHA)

    def test_senha_curta_e_recusada_na_exportacao(self):
        with self.assertRaises(ErroBackup):
            gerar_backup(self.origem, senha="curta")

    def test_cada_exportacao_usa_salt_e_nonce_novos(self):
        outro = gerar_backup(self.origem, incluir_credenciais=True, senha=self.SENHA)
        self.assertNotEqual(self.cifrado[:36], outro[:36])

    def test_senha_informada_para_zip_sem_cifra_e_ignorada(self):
        simples = gerar_backup(self.origem)
        previa = analisar_backup(simples, self.destino, "qualquer-coisa")
        self.assertTrue(previa.itens)


class TestPaginaSenha(unittest.TestCase):
    def test_pagina_gera_backup_cifrado_e_senha_divergente_bloqueia(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _popular(base)
            with mock.patch.object(backup_dados, "BASE_PADRAO", base):
                at = AppTest.from_file(str(PAGINA), default_timeout=TEMPO_LIMITE_APPTEST).run()
                at.text_input[0].set_value("senha-forte-123")
                at.text_input[1].set_value("diferente-123")
                at.run()
                self.assertFalse(at.exception)
                self.assertTrue(at.button[0].disabled)

                at.text_input[1].set_value("senha-forte-123")
                at.run()
                self.assertFalse(at.button[0].disabled)
                at.button[0].click().run()
                self.assertFalse(at.exception)
                nome, conteudo = at.session_state["backup_dados_pacote"]
                self.assertTrue(nome.endswith(".zip.enc"))
                self.assertTrue(backup_dados.esta_criptografado(conteudo))
                self.assertTrue(analisar_backup(conteudo, base / "x", "senha-forte-123").itens)


if __name__ == "__main__":
    unittest.main()
