"""
Testes da reversão de lote (`src/teds_reversao.py`, briefing seção 6.4).

Cenário central (o mesmo explicado ao usuário): o lote 1 importa um valor, o lote 2 sobrescreve
esse valor, e reverter o lote 2 tem de devolver o valor do lote 1 — o que só é possível porque
um gatilho guarda a versão anterior antes de cada sobrescrita.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.teds_alertas import TIPO_EMPENHO_MULTIPLOS_TEDS
from src.teds_auditoria import ENTIDADE_IMPORT_BATCH, historico_auditoria
from src.teds_lotes import importar_doc_ne, importar_doc_pf
from src.teds_normalizacao import chave_empenho, chave_ted, texto_para_valor
from src.teds_reversao import ReversaoNaoPermitida, lotes_reversiveis, reverter_lote
from src.teds_schema import TABELAS_VERSIONADAS, conectar

TED_17352 = chave_ted("17352", "1ABDKU")
TED_17454 = chave_ted("17454", "1ABDKQ")
NE_427 = chave_empenho("153165", "15239", "2026NE000427")

_BASE_NE = {
    "Gestão Emitente - NE": "15239",
    "UG Executora Emitente - NE": "153165",
    "Descrição do Termo": "Termo",
    "Estado Atual": "Termo em Execução",
    "Início da Vigência": "01/01/2026",
    "Fim da Vigência": "31/12/2027",
    "UG Descentralizadora": "154046",
}


def _df_ne(valor_427: str, extras: tuple[tuple[str, str, str, str], ...] = ()) -> pd.DataFrame:
    """NE 427 (TED 17454) com o valor dado; `extras` = (NE, SIAFI, TED, valor) de linhas a mais."""

    linhas = [{**_BASE_NE, "Número do Empenho": "2026NE000427", "SIAFI": "1ABDKQ", "TED": "17454", "Valor da NE": valor_427}]
    for numero, siafi, ted, valor in extras:
        linhas.append({**_BASE_NE, "Número do Empenho": numero, "SIAFI": siafi, "TED": ted, "Valor da NE": valor})
    return pd.DataFrame(linhas)


def _df_pf(valor: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "Data de Emissão Doc. PF": "10/02/2026", "Número Doc. PF": "2026PF000001", "Operação": "(+)",
        "UG Emitente - PF": "154046", "Descrição do Termo": "Termo", "Estado Atual": "Termo em Execução",
        "Início da Vigência": "01/01/2026", "Fim da Vigência": "31/12/2027", "SIAFI": "1ABDKQ",
        "TED": "17454", "UG Descentralizadora": "154046", "Valor Doc. PF (R$)": valor,
    }])


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def valor_427(self) -> Decimal:
        (texto,) = self.conn.execute(
            "SELECT valor_ne FROM vinculo_ne WHERE chave_empenho = ?", (NE_427,)
        ).fetchone()
        return texto_para_valor(texto)

    def lote_do_vinculo(self, chave_empenho_: str = NE_427) -> int:
        return self.conn.execute(
            "SELECT import_batch_id FROM vinculo_ne WHERE chave_empenho = ?", (chave_empenho_,)
        ).fetchone()[0]

    def importar(self, valor: str, conteudo: bytes, extras=()) -> int:
        return importar_doc_ne(self.conn, _df_ne(valor, extras), "ne.xlsx", conteudo).import_batch_id

    def reverter(self, lote: int, **kw):
        return reverter_lote(self.conn, lote, responsavel="Ana", motivo="arquivo errado", **kw)


class SobrescritaRestauradaTests(Base):
    def test_reverter_o_lote_que_sobrescreveu_devolve_o_valor_do_lote_anterior(self):
        lote1 = self.importar("100,00", b"v1")
        lote2 = self.importar("160,00", b"v2")
        self.assertEqual(self.valor_427(), Decimal("160.00"))
        self.assertEqual(self.lote_do_vinculo(), lote2)

        resultado = self.reverter(lote2)

        self.assertEqual(self.valor_427(), Decimal("100.00"))
        self.assertEqual(self.lote_do_vinculo(), lote1)  # volta a apontar para o lote de origem
        self.assertEqual(resultado.restauradas["vinculo_ne"], 1)
        self.assertEqual(resultado.total_removidas, 0)

    def test_a_versao_revertida_fica_guardada_e_nada_e_descartado(self):
        self.importar("100,00", b"v1")
        lote2 = self.importar("160,00", b"v2")
        self.reverter(lote2)
        acao, conteudo = self.conn.execute(
            "SELECT acao, conteudo FROM linha_revertida WHERE import_batch_id = ? AND tabela = 'vinculo_ne'",
            (lote2,),
        ).fetchone()
        self.assertEqual(acao, "voltou_a_versao_anterior")
        self.assertIn("160", conteudo)  # o valor revertido continua consultável

    def test_lote_que_so_criou_linhas_as_remove_das_tabelas_de_trabalho_mas_arquiva(self):
        lote1 = self.importar("100,00", b"v1")
        resultado = self.reverter(lote1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM vinculo_ne").fetchone()[0], 0)
        self.assertEqual(resultado.removidas["vinculo_ne"], 1)
        self.assertEqual(resultado.removidas["ted"], 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM linha_revertida WHERE import_batch_id = ? AND acao = 'removida'", (lote1,)
            ).fetchone()[0],
            2,
        )

    def test_so_as_linhas_do_lote_sao_tocadas(self):
        lote1 = self.importar("100,00", b"v1")
        lote2 = self.importar("160,00", b"v2", extras=(("2026NE000999", "1ABDKU", "17352", "50,00"),))
        self.reverter(lote2)
        # A NE 999 só existia no lote 2: sai. A NE 427 volta ao lote 1. O TED 17352 só existia no lote 2.
        empenhos = {c for (c,) in self.conn.execute("SELECT chave_empenho FROM vinculo_ne")}
        self.assertEqual(empenhos, {NE_427})
        self.assertEqual(self.lote_do_vinculo(), lote1)
        teds = {c for (c,) in self.conn.execute("SELECT chave_ted FROM ted")}
        self.assertEqual(teds, {TED_17454})

    def test_reverter_um_lote_de_um_tipo_nao_toca_nas_linhas_de_outro(self):
        lote_ne = self.importar("100,00", b"ne")
        lote_pf = importar_doc_pf(self.conn, _df_pf("1.000,00"), "pf.xlsx", b"pf").import_batch_id
        self.reverter(lote_ne)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documento_pf").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT status FROM import_batch WHERE id = ?", (lote_pf,)).fetchone()[0], "ok")


class ReversaoForaDeOrdemTests(Base):
    def setUp(self):
        super().setUp()
        self.lote1 = self.importar("100,00", b"v1")
        self.lote2 = self.importar("200,00", b"v2")
        self.lote3 = self.importar("300,00", b"v3")

    def test_reverter_o_do_meio_nao_altera_o_valor_mais_novo(self):
        self.reverter(self.lote2)
        self.assertEqual(self.valor_427(), Decimal("300.00"))
        self.assertEqual(self.lote_do_vinculo(), self.lote3)

    def test_depois_de_reverter_o_do_meio_reverter_o_ultimo_pula_a_versao_do_lote_revertido(self):
        self.reverter(self.lote2)
        self.reverter(self.lote3)
        self.assertEqual(self.valor_427(), Decimal("100.00"))  # 200 é do lote 2 (revertido): pulado
        self.assertEqual(self.lote_do_vinculo(), self.lote1)

    def test_reverter_do_mais_novo_para_o_mais_antigo_desce_um_degrau_por_vez(self):
        self.reverter(self.lote3)
        self.assertEqual(self.valor_427(), Decimal("200.00"))
        self.reverter(self.lote2)
        self.assertEqual(self.valor_427(), Decimal("100.00"))
        self.reverter(self.lote1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM vinculo_ne").fetchone()[0], 0)

    def test_lote_revertido_deixa_de_ser_oferecido(self):
        self.reverter(self.lote3)
        self.assertEqual([l[0] for l in lotes_reversiveis(self.conn)], [self.lote2, self.lote1])


class HistoricoDeVersoesTests(Base):
    def test_sobrescrita_por_lote_diferente_guarda_a_versao_anterior(self):
        lote1 = self.importar("100,00", b"v1")
        lote2 = self.importar("160,00", b"v2")
        origem, sobrescritor, conteudo = self.conn.execute(
            "SELECT import_batch_id_origem, import_batch_id_sobrescritor, conteudo FROM historico_linha "
            "WHERE tabela = 'vinculo_ne'"
        ).fetchone()
        self.assertEqual((origem, sobrescritor), (lote1, lote2))
        self.assertIn("100", conteudo)

    def test_atualizar_no_mesmo_lote_nao_gera_versao(self):
        self.importar("100,00", b"v1", extras=(("2026NE000998", "1ABDKQ", "17454", "1,00"),))
        # `ted` é regravado várias vezes dentro do mesmo lote (uma vez por NE): sem histórico.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM historico_linha").fetchone()[0], 0)

    def test_historico_e_append_only(self):
        self.importar("100,00", b"v1")
        self.importar("160,00", b"v2")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("DELETE FROM historico_linha")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE historico_linha SET tabela = 'x'")

    def test_arquivo_de_linhas_revertidas_e_append_only(self):
        lote1 = self.importar("100,00", b"v1")
        self.reverter(lote1)
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("DELETE FROM linha_revertida")

    def test_a_propria_restauracao_nao_cria_versao_espuria(self):
        self.importar("100,00", b"v1")
        lote2 = self.importar("160,00", b"v2")
        antes = self.conn.execute("SELECT COUNT(*) FROM historico_linha").fetchone()[0]
        self.reverter(lote2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM historico_linha").fetchone()[0], antes)
        self.assertEqual(self.conn.execute("SELECT pausado FROM versionamento_controle").fetchone()[0], 0)

    def test_listas_de_colunas_batem_com_o_esquema_real(self):
        for tabela, (chave, colunas) in TABELAS_VERSIONADAS.items():
            reais = [linha[1] for linha in self.conn.execute(f"PRAGMA table_info({tabela})")]
            self.assertEqual(list(colunas), reais, tabela)
            self.assertTrue(set(chave) <= set(colunas), tabela)


class StatusAuditoriaEAlertasTests(Base):
    def test_lote_revertido_guarda_quem_quando_e_por_que(self):
        lote = self.importar("100,00", b"v1")
        self.reverter(lote)
        status, em, por, motivo = self.conn.execute(
            "SELECT status, revertido_em, revertido_por, motivo_reversao FROM import_batch WHERE id = ?", (lote,)
        ).fetchone()
        self.assertEqual((status, por, motivo), ("revertido", "Ana", "arquivo errado"))
        self.assertTrue(em)

    def test_a_reversao_entra_na_trilha_de_auditoria(self):
        self.importar("100,00", b"v1")
        lote2 = self.importar("160,00", b"v2")
        self.reverter(lote2, origem="teste")
        (registro,) = historico_auditoria(self.conn, ENTIDADE_IMPORT_BATCH, lote2)
        self.assertEqual(registro.acao, "lote_revertido")
        self.assertEqual(registro.usuario, "Ana")
        self.assertEqual(registro.origem, "teste")
        self.assertEqual(registro.valor_anterior, {"status": "ok"})
        self.assertEqual(registro.valor_novo["status"], "revertido")
        self.assertEqual(registro.valor_novo["linhas_restauradas_para_versao_anterior"], {"ted": 1, "vinculo_ne": 1})

    def test_o_mesmo_arquivo_pode_ser_importado_de_novo_como_lote_novo(self):
        lote = self.importar("100,00", b"v1")
        self.reverter(lote)
        outro = self.importar("100,00", b"v1")
        self.assertNotEqual(outro, lote)
        self.assertEqual(self.valor_427(), Decimal("100.00"))

    def test_alerta_criado_pelo_lote_revertido_nao_e_fechado_sozinho(self):
        extras = (("2026NE000427", "1ABDKU", "17352", "100,00"),)  # mesma NE em dois TEDs
        lote = self.importar("100,00", b"v1", extras=extras)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM alerta WHERE tipo = ? AND status = 'aberto'", (TIPO_EMPENHO_MULTIPLOS_TEDS,)).fetchone()[0],
            1,
        )
        self.reverter(lote)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM alerta WHERE tipo = ? AND status = 'aberto'", (TIPO_EMPENHO_MULTIPLOS_TEDS,)).fetchone()[0],
            1,
        )


class RecusasTests(Base):
    def setUp(self):
        super().setUp()
        self.lote = self.importar("100,00", b"v1")

    def _recusa(self, lote, **kw):
        kw = {"responsavel": "Ana", "motivo": "x", **kw}
        with self.assertRaises(ReversaoNaoPermitida) as contexto:
            reverter_lote(self.conn, lote, **kw)
        return str(contexto.exception)

    def test_exige_responsavel_e_motivo(self):
        self.assertIn("responsável", self._recusa(self.lote, responsavel="  "))
        self.assertIn("motivo", self._recusa(self.lote, motivo=""))

    def test_lote_inexistente(self):
        self.assertIn("não encontrado", self._recusa(999))

    def test_lote_ja_revertido(self):
        self.reverter(self.lote)
        self.assertIn("já foi revertido", self._recusa(self.lote))

    def test_lote_anterior_ao_historico_de_versoes_e_recusado_e_nada_muda(self):
        self.conn.execute("UPDATE import_batch SET versionado = NULL")
        self.conn.commit()
        self.assertIn("anterior ao histórico de versões", self._recusa(self.lote))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM vinculo_ne").fetchone()[0], 1)
        self.assertEqual(lotes_reversiveis(self.conn), [])

    def test_recusa_nao_deixa_auditoria_nem_muda_o_status(self):
        self._recusa(self.lote, responsavel="")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT status FROM import_batch WHERE id = ?", (self.lote,)).fetchone()[0], "ok")


class AtomicidadeTests(Base):
    def test_falha_no_meio_desfaz_tudo(self):
        self.importar("100,00", b"v1")
        lote2 = self.importar("160,00", b"v2")
        # Sabota a gravação da auditoria (último passo, depois de mexer nas linhas e no status).
        self.conn.execute("ALTER TABLE auditoria RENAME TO auditoria_quebrada")
        self.conn.commit()

        with self.assertRaises(sqlite3.DatabaseError):
            self.reverter(lote2)

        self.assertEqual(self.valor_427(), Decimal("160.00"))  # linha não voltou
        self.assertEqual(self.lote_do_vinculo(), lote2)
        self.assertEqual(self.conn.execute("SELECT status FROM import_batch WHERE id = ?", (lote2,)).fetchone()[0], "ok")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM linha_revertida").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT pausado FROM versionamento_controle").fetchone()[0], 0)


class MigracaoTests(unittest.TestCase):
    def test_banco_antigo_ganha_o_versionamento_e_seus_lotes_ficam_nao_reversiveis(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teds.db"
            antigo = sqlite3.connect(caminho)
            antigo.executescript(
                """
                CREATE TABLE import_batch (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, tipo_relatorio TEXT NOT NULL, nome_arquivo TEXT NOT NULL,
                    hash_arquivo TEXT NOT NULL, data_importacao TEXT NOT NULL,
                    quantidade_registros INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, mensagem_erro TEXT
                );
                INSERT INTO import_batch (tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, quantidade_registros, status)
                VALUES ('simec_doc_ne', 'velho.xlsx', 'h', '2026-01-01T00:00:00', 3, 'ok');
                """
            )
            antigo.commit()
            antigo.close()

            conn = conectar(caminho)
            try:
                colunas = {linha[1] for linha in conn.execute("PRAGMA table_info(import_batch)")}
                self.assertTrue({"versionado", "revertido_em", "revertido_por", "motivo_reversao"} <= colunas)
                self.assertIsNone(conn.execute("SELECT versionado FROM import_batch").fetchone()[0])
                self.assertEqual(lotes_reversiveis(conn), [])
                with self.assertRaises(ReversaoNaoPermitida):
                    reverter_lote(conn, 1, responsavel="Ana", motivo="x")
                conectar(caminho).close()  # idempotente
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM import_batch").fetchone()[0], 1)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
