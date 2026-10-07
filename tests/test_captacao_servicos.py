"""Schema e serviços da Captação de Demandas (banco SQLite em memória)."""

from __future__ import annotations

import sqlite3
import unittest
from datetime import date

from src.captacao import regras, schema, servicos
from src.captacao.regras import ErroRegra

HOJE = date(2026, 10, 1)


def _conexao_com_ciclo(fase="ABERTO"):
    conexao = schema.conectar(":memory:")
    conexao.execute("INSERT INTO unidade (id, ugr_codigo, nome) VALUES (1, '158001', 'Depto. A')")
    conexao.execute("INSERT INTO unidade (id, ugr_codigo, nome) VALUES (2, '158002', 'Depto. B')")
    conexao.execute("INSERT INTO objetivo_pdi (id, codigo, descricao, versao_pdi) VALUES (1, 'O1', 'Obj', 'v1')")
    conexao.execute("INSERT INTO meta_pls (id, codigo, descricao, versao_pls) VALUES (1, '1.1', 'Meta', 'v1')")
    conexao.execute(
        "INSERT INTO ciclo (id, exercicio, fase, abertura, encerramento, prazo_validacao, criado_em)"
        " VALUES (1, 2027, ?, '2026-09-01', '2026-10-31', '2026-11-07', '2026-08-01T00:00:00+00:00')",
        (fase,),
    )
    conexao.commit()
    return conexao


def _dados(**ajustes):
    dados = {
        "tipo": "EQUIPAMENTO_PERMANENTE",
        "descricao": "Balança eletrônica",
        "quantidade": 2,
        "unidade_fornecimento": "Unidade",
        "valor_unitario": "24000.00",
        "prioridade": "ESSENCIAL",
        "objetivos_pdi": [1],
        "metas_pls": [1],
        "contribuicao": "Apoia a meta.",
        "justificativa": "x" * 200,
    }
    dados.update(ajustes)
    return dados


class SchemaTests(unittest.TestCase):
    def test_todas_as_tabelas_do_modelo_sao_criadas(self):
        conexao = schema.conectar(":memory:")
        nomes = {linha["name"] for linha in conexao.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue(set(schema.TABELAS) <= nomes)
        self.assertEqual(conexao.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_conectar_e_idempotente_em_arquivo(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "sub" / "captacao.db"
            primeira = schema.conectar(caminho)
            primeira.execute("INSERT INTO unidade (ugr_codigo, nome) VALUES ('X', 'Unidade X')")
            primeira.commit()
            primeira.close()
            segunda = schema.conectar(caminho)
            self.assertEqual(segunda.execute("SELECT COUNT(*) FROM unidade").fetchone()[0], 1)
            segunda.close()

    def test_unicidade_de_ugr_e_de_vinculos(self):
        conexao = _conexao_com_ciclo()
        with self.assertRaises(sqlite3.IntegrityError):
            conexao.execute("INSERT INTO unidade (ugr_codigo, nome) VALUES ('158001', 'Duplicada')")
        with self.assertRaises(sqlite3.IntegrityError):
            conexao.execute("INSERT INTO ciclo (exercicio, criado_em) VALUES (2027, 'x')")

    def test_codigo_ugr_preserva_zeros_a_esquerda(self):
        conexao = schema.conectar(":memory:")
        conexao.execute("INSERT INTO unidade (ugr_codigo, nome) VALUES ('0158001', 'Com zero')")
        self.assertEqual(conexao.execute("SELECT ugr_codigo FROM unidade").fetchone()[0], "0158001")

    def test_prorrogacao_exige_motivo_e_e_unica_por_unidade(self):
        conexao = _conexao_com_ciclo()
        with self.assertRaises(sqlite3.IntegrityError):
            conexao.execute(
                "INSERT INTO prorrogacao (ciclo_id, unidade_id, novo_prazo, motivo, concedida_em)"
                " VALUES (1, 1, '2026-11-07', '  ', 'x')"
            )
        conexao.execute(
            "INSERT INTO prorrogacao (ciclo_id, unidade_id, novo_prazo, motivo, concedida_em)"
            " VALUES (1, 1, '2026-11-07', 'Troca de chefia', 'x')"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            conexao.execute(
                "INSERT INTO prorrogacao (ciclo_id, unidade_id, novo_prazo, motivo, concedida_em)"
                " VALUES (1, 1, '2026-11-09', 'Outra', 'x')"
            )


class CriarRascunhoTests(unittest.TestCase):
    def test_cria_rascunho_com_total_e_natureza_calculados_no_servidor(self):
        conexao = _conexao_com_ciclo()
        # valor_total e natureza vindos do cliente são ignorados (RN-03)
        demanda_id = servicos.criar_rascunho(
            conexao, 1, 1, "rep", _dados(valor_total="1.00", natureza_sugerida="CUSTEIO"), HOJE
        )
        linha = conexao.execute("SELECT * FROM demanda WHERE id = ?", (demanda_id,)).fetchone()
        self.assertEqual(linha["valor_total"], "48000.00")
        self.assertEqual(linha["natureza_sugerida"], "CAPITAL")
        self.assertEqual(linha["situacao"], "RASCUNHO")
        self.assertEqual(linha["origem"], "MANUAL")
        historico = conexao.execute("SELECT de, para FROM historico_situacao WHERE demanda_id = ?", (demanda_id,)).fetchall()
        self.assertEqual([(h["de"], h["para"]) for h in historico], [(None, "RASCUNHO")])

    def test_rascunho_incompleto_e_aceito_e_total_fica_nulo_nao_zero(self):
        conexao = _conexao_com_ciclo()
        demanda_id = servicos.criar_rascunho(conexao, 1, 1, "rep", {"descricao": "Só a descrição"}, HOJE)
        linha = conexao.execute("SELECT * FROM demanda WHERE id = ?", (demanda_id,)).fetchone()
        self.assertIsNone(linha["valor_total"])
        self.assertIsNone(linha["natureza_sugerida"])
        self.assertIsNone(linha["quantidade"])

    def test_rn05_recusa_ciclo_nao_aberto_e_fora_do_prazo(self):
        for fase, hoje in [("ENCERRADO", HOJE), ("ABERTO", date(2026, 11, 1)), ("RASCUNHO", HOJE)]:
            with self.subTest(fase=fase, hoje=hoje):
                conexao = _conexao_com_ciclo(fase)
                with self.assertRaises(ErroRegra):
                    servicos.criar_rascunho(conexao, 1, 1, "rep", _dados(), hoje)
                self.assertEqual(conexao.execute("SELECT COUNT(*) FROM demanda").fetchone()[0], 0)

    def test_rn05_prorrogacao_vale_so_para_a_unidade_prorrogada(self):
        conexao = _conexao_com_ciclo()
        conexao.execute(
            "INSERT INTO prorrogacao (ciclo_id, unidade_id, novo_prazo, motivo, concedida_em)"
            " VALUES (1, 1, '2026-11-07', 'Motivo', 'x')"
        )
        conexao.commit()
        depois = date(2026, 11, 3)
        self.assertGreater(servicos.criar_rascunho(conexao, 1, 1, "rep", _dados(), depois), 0)
        with self.assertRaises(ErroRegra):
            servicos.criar_rascunho(conexao, 1, 2, "rep", _dados(), depois)


class EnviarDemandaTests(unittest.TestCase):
    def test_envio_valido_muda_situacao_e_grava_historico(self):
        conexao = _conexao_com_ciclo()
        demanda_id = servicos.criar_rascunho(conexao, 1, 1, "rep", _dados(), HOJE)
        servicos.enviar_demanda(conexao, demanda_id, "rep", HOJE)
        linha = conexao.execute("SELECT * FROM demanda WHERE id = ?", (demanda_id,)).fetchone()
        self.assertEqual(linha["situacao"], "ENVIADA")
        self.assertIsNotNone(linha["enviada_em"])
        historico = conexao.execute(
            "SELECT de, para, usuario FROM historico_situacao WHERE demanda_id = ? ORDER BY id", (demanda_id,)
        ).fetchall()
        self.assertEqual([(h["de"], h["para"], h["usuario"]) for h in historico], [(None, "RASCUNHO", "rep"), ("RASCUNHO", "ENVIADA", "rep")])

    def test_rn08_envio_incompleto_lista_pendencias_e_nao_grava_nada(self):
        conexao = _conexao_com_ciclo()
        demanda_id = servicos.criar_rascunho(
            conexao, 1, 1, "rep", _dados(objetivos_pdi=[], metas_pls=[], justificativa="curta"), HOJE
        )
        with self.assertRaises(ErroRegra) as contexto:
            servicos.enviar_demanda(conexao, demanda_id, "rep", HOJE)
        self.assertIn("Pelo menos um objetivo do PDI", contexto.exception.pendencias)
        self.assertIn("Pelo menos uma meta do PLS", contexto.exception.pendencias)
        self.assertIn("Justificativa com pelo menos 200 caracteres", contexto.exception.pendencias)
        linha = conexao.execute("SELECT situacao, enviada_em FROM demanda WHERE id = ?", (demanda_id,)).fetchone()
        self.assertEqual((linha["situacao"], linha["enviada_em"]), ("RASCUNHO", None))
        self.assertEqual(conexao.execute("SELECT COUNT(*) FROM historico_situacao").fetchone()[0], 1)

    def test_rn01_excecao_envia_sem_meta_pls_quando_a_unidade_pede_analise(self):
        conexao = _conexao_com_ciclo()
        demanda_id = servicos.criar_rascunho(
            conexao, 1, 1, "rep", _dados(metas_pls=[], solicita_analise_vinculo=1), HOJE
        )
        servicos.enviar_demanda(conexao, demanda_id, "rep", HOJE)
        self.assertEqual(
            conexao.execute("SELECT situacao FROM demanda WHERE id = ?", (demanda_id,)).fetchone()[0], "ENVIADA"
        )

    def test_rn03_total_e_recalculado_no_envio_mesmo_se_o_gravado_estiver_adulterado(self):
        conexao = _conexao_com_ciclo()
        demanda_id = servicos.criar_rascunho(conexao, 1, 1, "rep", _dados(), HOJE)
        conexao.execute("UPDATE demanda SET valor_total = '1.00' WHERE id = ?", (demanda_id,))
        conexao.commit()
        servicos.enviar_demanda(conexao, demanda_id, "rep", HOJE)
        self.assertEqual(
            conexao.execute("SELECT valor_total FROM demanda WHERE id = ?", (demanda_id,)).fetchone()[0], "48000.00"
        )

    def test_rn05_envio_apos_o_prazo_e_recusado(self):
        conexao = _conexao_com_ciclo()
        demanda_id = servicos.criar_rascunho(conexao, 1, 1, "rep", _dados(), HOJE)
        with self.assertRaises(ErroRegra):
            servicos.enviar_demanda(conexao, demanda_id, "rep", date(2026, 11, 1))
        self.assertEqual(
            conexao.execute("SELECT situacao FROM demanda WHERE id = ?", (demanda_id,)).fetchone()[0], "RASCUNHO"
        )

    def test_rn06_devolvida_reenvia_apos_encerramento_ate_o_prazo_de_validacao(self):
        conexao = _conexao_com_ciclo()
        demanda_id = servicos.criar_rascunho(conexao, 1, 1, "rep", _dados(), HOJE)
        conexao.execute("UPDATE demanda SET devolvida = 1 WHERE id = ?", (demanda_id,))
        conexao.execute("UPDATE ciclo SET fase = 'ENCERRADO' WHERE id = 1")
        conexao.commit()
        with self.assertRaises(ErroRegra):
            servicos.enviar_demanda(conexao, demanda_id, "rep", date(2026, 11, 8))
        servicos.enviar_demanda(conexao, demanda_id, "rep", date(2026, 11, 3))
        self.assertEqual(
            conexao.execute("SELECT situacao FROM demanda WHERE id = ?", (demanda_id,)).fetchone()[0], "ENVIADA"
        )

    def test_nao_reenvia_demanda_ja_enviada_nem_inexistente(self):
        conexao = _conexao_com_ciclo()
        demanda_id = servicos.criar_rascunho(conexao, 1, 1, "rep", _dados(), HOJE)
        servicos.enviar_demanda(conexao, demanda_id, "rep", HOJE)
        with self.assertRaises(ErroRegra):
            servicos.enviar_demanda(conexao, demanda_id, "rep", HOJE)
        with self.assertRaises(ErroRegra):
            servicos.enviar_demanda(conexao, 999, "rep", HOJE)

    def test_nao_envia_demanda_excluida(self):
        conexao = _conexao_com_ciclo()
        demanda_id = servicos.criar_rascunho(conexao, 1, 1, "rep", _dados(), HOJE)
        conexao.execute("UPDATE demanda SET excluida_em = 'x' WHERE id = ?", (demanda_id,))
        conexao.commit()
        with self.assertRaises(ErroRegra):
            servicos.enviar_demanda(conexao, demanda_id, "rep", HOJE)


class MudarSituacaoTests(unittest.TestCase):
    def test_transicao_invalida_e_recusada_sem_gravar(self):
        conexao = _conexao_com_ciclo()
        demanda_id = servicos.criar_rascunho(conexao, 1, 1, "rep", _dados(), HOJE)
        with self.assertRaises(ErroRegra):
            servicos._mudar_situacao(conexao, demanda_id, regras.SITUACAO_VALIDADA_PROPLAD, "x")
        self.assertEqual(
            conexao.execute("SELECT situacao FROM demanda WHERE id = ?", (demanda_id,)).fetchone()[0], "RASCUNHO"
        )

    def test_devolucao_volta_a_rascunho_com_indicador_e_comentario(self):
        conexao = _conexao_com_ciclo()
        demanda_id = servicos.criar_rascunho(conexao, 1, 1, "rep", _dados(), HOJE)
        servicos.enviar_demanda(conexao, demanda_id, "rep", HOJE)
        servicos._mudar_situacao(conexao, demanda_id, regras.SITUACAO_RASCUNHO, "chefia", "Ajustar valor", devolvida=True)
        conexao.commit()
        linha = conexao.execute("SELECT situacao, devolvida FROM demanda WHERE id = ?", (demanda_id,)).fetchone()
        self.assertEqual((linha["situacao"], linha["devolvida"]), ("RASCUNHO", 1))
        ultimo = conexao.execute(
            "SELECT de, para, comentario FROM historico_situacao WHERE demanda_id = ? ORDER BY id DESC LIMIT 1",
            (demanda_id,),
        ).fetchone()
        self.assertEqual((ultimo["de"], ultimo["para"], ultimo["comentario"]), ("ENVIADA", "RASCUNHO", "Ajustar valor"))


if __name__ == "__main__":
    unittest.main()
