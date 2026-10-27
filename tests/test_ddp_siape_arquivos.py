"""Testes de `src.ddp_siape_arquivos` (DDP guardada, 27/10/2026), em diretórios temporários.

Usa as fixtures reduzidas de set/2026 (`tests/fixtures/ddp_siape_*`, `cred_banc_siape_*`) e DDPs
sintéticas de out/2026 (`tests.test_ddp_siape._ddp_pdf`)."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.ddp_siape import ler_relatorio, validar_conjunto
from src.ddp_siape_arquivos import (
    ArquivoGuardadoInvalido, carregar, chave_cache, competencias_com_ddp, competencias_guardadas, guardar, historico,
    manifesto_atual, ultima_ddp_completa, validar_troca,
)
from tests.test_ddp_siape import ARQUIVOS_SET, FIXTURES, _ddp_pdf

AGORA = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _setembro():
    itens = []
    for nome in ARQUIVOS_SET:
        conteudo = (FIXTURES / nome).read_bytes()
        itens.append((ler_relatorio(conteudo, nome), conteudo))
    return itens


def _outubro(publico: str, valor: float, nome: str):
    conteudo = _ddp_pdf("OUT", publico, [("3.3190.11.01", "VENCIMENTO E SALARIOS", valor)])
    return ler_relatorio(conteudo, nome), conteudo


class TestDdpGuardada(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        raiz = Path(self._tmp.name)
        self.kw = dict(diretorio_dados_brutos=raiz / "raw", diretorio_manifestos=raiz / "manifestos")
        self.raiz = raiz

    def tearDown(self):
        self._tmp.cleanup()

    def test_guarda_pdfs_sem_alterar_e_cria_manifesto_e_ponteiro(self):
        resultado = guardar(_setembro(), agora=AGORA, **self.kw)
        self.assertEqual((resultado.versoes_novas, resultado.sem_mudanca), ([202609], []))
        manifesto = manifesto_atual(202609, self.raiz / "manifestos")
        self.assertEqual(len(manifesto["arquivos"]), 4)
        self.assertEqual(manifesto["gravado_em"], AGORA.isoformat())
        for entrada, (_, conteudo) in zip(sorted(manifesto["arquivos"], key=lambda a: a["nome_original"]),
                                           sorted(_setembro(), key=lambda par: par[0].nome)):
            guardado = (self.raiz / "raw" / entrada["arquivo"]).read_bytes()
            self.assertEqual(guardado, conteudo)  # byte a byte: o original não é alterado
        nomes = sorted(p.name for p in (self.raiz / "manifestos").iterdir())
        self.assertEqual(len(nomes), 2)  # versão datada + ponteiro "atual"
        self.assertTrue(any(n.endswith("_atual.json") for n in nomes))
        self.assertTrue(any(n.startswith("ddp_siape_202609_2026-10-27_") for n in nomes))

    def test_carregar_devolve_os_relatorios_lidos_dos_pdfs_guardados(self):
        guardar(_setembro(), agora=AGORA, **self.kw)
        relatorios = carregar(202609, **self.kw)
        self.assertEqual({(r.tipo, r.publico) for r in relatorios},
                         {("DDP", "SERVIDOR"), ("DDP", "PENSIONISTA"), ("CRED-BANC", "SERVIDOR"), ("CRED-BANC", "PENSIONISTA")})
        self.assertEqual(sum(r.totais["liquido"] for r in relatorios if r.tipo == "DDP"), 32365342.03 + 3947434.97)

    def test_reenviar_o_mesmo_pdf_nao_cria_versao(self):
        guardar(_setembro(), agora=AGORA, **self.kw)
        resultado = guardar(_setembro(), agora=AGORA, **self.kw)
        self.assertEqual((resultado.versoes_novas, resultado.sem_mudanca), ([], [202609]))
        self.assertEqual(len(historico(202609, self.raiz / "manifestos")), 1)

    def test_pdf_diferente_cria_versao_preserva_a_antiga_e_os_demais_arquivos(self):
        guardar([_outubro("SERVIDOR", 100.0, "serv.pdf"), _outubro("PENSIONISTA", 10.0, "pens.pdf")], agora=AGORA, **self.kw)
        antigo = manifesto_atual(202610, self.raiz / "manifestos")
        sha_serv_antigo = next(a["sha256"] for a in antigo["arquivos"] if a["publico"] == "SERVIDOR")
        depois = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
        resultado = guardar([_outubro("SERVIDOR", 120.0, "serv_v2.pdf")], agora=depois, **self.kw)
        self.assertEqual(resultado.versoes_novas, [202610])
        novo = manifesto_atual(202610, self.raiz / "manifestos")
        self.assertNotEqual(novo["versao"], antigo["versao"])
        self.assertEqual(len(novo["arquivos"]), 2)  # o de pensionista ficou
        self.assertEqual(next(a["nome_original"] for a in novo["arquivos"] if a["publico"] == "SERVIDOR"), "serv_v2.pdf")
        versoes = historico(202610, self.raiz / "manifestos")
        self.assertEqual([v["versao"] for v in versoes], [antigo["versao"], novo["versao"]])
        # o PDF antigo continua em disco e o painel lê o novo
        antigo_serv = next(a for a in antigo["arquivos"] if a["publico"] == "SERVIDOR")
        self.assertTrue((self.raiz / "raw" / antigo_serv["arquivo"]).exists())
        self.assertEqual(antigo_serv["sha256"], sha_serv_antigo)
        serv = next(r for r in carregar(202610, **self.kw) if r.publico == "SERVIDOR")
        self.assertEqual(serv.totais["liquido"], 120.0)

    def test_validar_troca_exige_mesmo_tipo_publico_folha_competencia_e_arquivo_diferente(self):
        serv, pens = _outubro("SERVIDOR", 100.0, "serv.pdf"), _outubro("PENSIONISTA", 10.0, "pens.pdf")
        guardar([serv, pens], agora=AGORA, **self.kw)
        entrada = next(a for a in manifesto_atual(202610, self.raiz / "manifestos")["arquivos"] if a["publico"] == "SERVIDOR")
        novo = _outubro("SERVIDOR", 120.0, "serv_v2.pdf")
        self.assertEqual(validar_troca(entrada, novo[0], novo[1]), [])
        self.assertIn("idêntico", validar_troca(entrada, serv[0], serv[1])[0])
        erro = validar_troca(entrada, pens[0], pens[1])
        self.assertEqual(len(erro), 1)
        self.assertIn("pensionista", erro[0])
        setembro = _setembro()[0]
        self.assertEqual(len(validar_troca(entrada, setembro[0], setembro[1])), 1)  # outra competência
        # trocar e guardar: nova versão, o antigo preservado
        guardar([novo], agora=AGORA, **self.kw)
        self.assertEqual(len(historico(202610, self.raiz / "manifestos")), 2)

    def test_competencias_e_ultima_ddp_completa(self):
        guardar(_setembro(), agora=AGORA, **self.kw)
        self.assertEqual(competencias_guardadas(self.raiz / "manifestos"), [202609])
        guardar([_outubro("SERVIDOR", 100.0, "serv.pdf")], agora=AGORA, **self.kw)  # outubro sem pensionista
        self.assertEqual(competencias_guardadas(self.raiz / "manifestos"), [202609, 202610])
        self.assertEqual(ultima_ddp_completa(**self.kw)[0].competencia, 202609)  # a mais recente completa
        guardar([_outubro("PENSIONISTA", 10.0, "pens.pdf")], agora=AGORA, **self.kw)
        self.assertEqual(ultima_ddp_completa(**self.kw)[0].competencia, 202610)
        self.assertEqual(competencias_com_ddp(self.raiz / "manifestos"), {202609, 202610})

    def test_sem_nada_guardado(self):
        self.assertEqual(competencias_guardadas(self.raiz / "manifestos"), [])
        self.assertIsNone(ultima_ddp_completa(**self.kw))
        self.assertEqual(carregar(202610, **self.kw), [])
        self.assertEqual(chave_cache(self.raiz / "manifestos"), ())

    def test_chave_de_cache_muda_com_versao_nova(self):
        guardar(_setembro(), agora=AGORA, **self.kw)
        antes = chave_cache(self.raiz / "manifestos")
        guardar([_outubro("SERVIDOR", 100.0, "serv.pdf")], agora=AGORA, **self.kw)
        self.assertNotEqual(chave_cache(self.raiz / "manifestos"), antes)

    def test_arquivo_ausente_ou_alterado_e_erro(self):
        guardar(_setembro(), agora=AGORA, **self.kw)
        entrada = manifesto_atual(202609, self.raiz / "manifestos")["arquivos"][0]
        caminho = self.raiz / "raw" / entrada["arquivo"]
        caminho.write_bytes(caminho.read_bytes() + b"x")
        with self.assertRaisesRegex(ArquivoGuardadoInvalido, "não confere com o hash"):
            carregar(202609, **self.kw)
        caminho.unlink()
        with self.assertRaisesRegex(ArquivoGuardadoInvalido, "ausente"):
            carregar(202609, **self.kw)

    def test_manifesto_e_json_legivel_com_hash_e_data(self):
        guardar(_setembro(), agora=AGORA, **self.kw)
        for caminho in (self.raiz / "manifestos").iterdir():
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            self.assertEqual((dados["base"], dados["competencia"]), ("ddp_siape", 202609))
            self.assertTrue(all(len(a["sha256"]) == 64 for a in dados["arquivos"]))

    def test_envio_so_de_credito_bancario_nao_e_erro_se_a_ddp_ja_esta_guardada(self):
        itens = _setembro()
        guardar(itens, agora=AGORA, **self.kw)
        so_credito = [r for r, _ in itens if r.tipo == "CRED-BANC"]
        self.assertTrue(validar_conjunto(so_credito))  # sozinho, sem DDP guardada: erro
        self.assertEqual(validar_conjunto(so_credito, competencias_com_ddp=competencias_com_ddp(self.raiz / "manifestos")), [])


if __name__ == "__main__":
    unittest.main()
