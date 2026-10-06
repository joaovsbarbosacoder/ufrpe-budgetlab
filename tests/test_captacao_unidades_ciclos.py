"""Cadastro de unidades e do ciclo de captação (criação, edição, fases, prorrogação, auditoria)."""

from __future__ import annotations

import json
import unittest
from datetime import date

from src.captacao import auditoria, ciclos, planos, regras, schema, servicos, unidades
from src.captacao.auditoria import ErroCadastro

HOJE = date(2026, 10, 1)
CAB_PDI = ("Código do objetivo", "Dimensão / eixo do PDI", "Descrição do objetivo")
CAB_PLS = ("Eixo temático", "Objetivo", "Código da meta", "Descrição da meta")


def _historico(conexao, tabela, item_id):
    return [(h["acao"], h["campo"], h["antes"], h["depois"], h["usuario"]) for h in auditoria.historico(conexao, tabela, item_id)]


def _dados_ciclo(**ajustes):
    dados = {
        "abertura": date(2026, 9, 1),
        "encerramento": date(2026, 10, 31),
        "prazo_validacao": date(2026, 11, 7),
        "devolutiva_prevista": date(2026, 12, 15),
    }
    dados.update(ajustes)
    return dados


class Base(unittest.TestCase):
    def setUp(self):
        self.conexao = schema.conectar(":memory:")


class UnidadesTests(Base):
    def test_cria_unidade_preservando_zeros_e_grava_historico(self):
        unidade_id = unidades.criar_unidade(self.conexao, {"ugr_codigo": " 0158001 ", "nome": " Depto. A ", "sigla": "DA"}, "Maria")
        linha = self.conexao.execute("SELECT * FROM unidade WHERE id = ?", (unidade_id,)).fetchone()
        self.assertEqual((linha["ugr_codigo"], linha["nome"], linha["sigla"], linha["ativa"]), ("0158001", "Depto. A", "DA", 1))
        self.assertEqual(_historico(self.conexao, "unidade", unidade_id), [("CRIAR", "ugr_codigo", None, "0158001", "Maria")])

    def test_codigo_e_nome_obrigatorios_e_codigo_unico(self):
        unidades.criar_unidade(self.conexao, {"ugr_codigo": "A1", "nome": "Uma"}, "Maria")
        for dados, trecho in [({"ugr_codigo": "", "nome": "x"}, "código"), ({"ugr_codigo": "B", "nome": " "}, "nome"), ({"ugr_codigo": "A1", "nome": "Outra"}, "Já existe")]:
            with self.subTest(dados=dados):
                with self.assertRaises(ErroCadastro) as contexto:
                    unidades.criar_unidade(self.conexao, dados, "Maria")
                self.assertIn(trecho, " ".join(contexto.exception.erros))
        self.assertEqual(self.conexao.execute("SELECT COUNT(*) FROM unidade").fetchone()[0], 1)

    def test_edita_mantendo_o_id_e_registra_antes_e_depois(self):
        unidade_id = unidades.criar_unidade(self.conexao, {"ugr_codigo": "A1", "nome": "Antigo"}, "Maria")
        campos = unidades.editar_unidade(self.conexao, unidade_id, {"ugr_codigo": "A1", "nome": "Novo", "sigla": "N"}, "João")
        self.assertEqual(sorted(campos), ["nome", "sigla"])
        self.assertIn(("EDITAR", "nome", "Antigo", "Novo", "João"), _historico(self.conexao, "unidade", unidade_id))
        self.assertEqual(unidades.editar_unidade(self.conexao, unidade_id, {"ugr_codigo": "A1", "nome": "Novo", "sigla": "N"}, "João"), [])

    def test_editar_para_codigo_de_outra_unidade_e_recusado(self):
        unidades.criar_unidade(self.conexao, {"ugr_codigo": "A1", "nome": "Uma"}, "Maria")
        segunda = unidades.criar_unidade(self.conexao, {"ugr_codigo": "A2", "nome": "Duas"}, "Maria")
        with self.assertRaises(ErroCadastro):
            unidades.editar_unidade(self.conexao, segunda, {"ugr_codigo": "A1", "nome": "Duas"}, "Maria")
        self.assertEqual(self.conexao.execute("SELECT ugr_codigo FROM unidade WHERE id = ?", (segunda,)).fetchone()[0], "A2")

    def test_desativa_e_reativa_sem_excluir(self):
        unidade_id = unidades.criar_unidade(self.conexao, {"ugr_codigo": "A1", "nome": "Uma"}, "Maria")
        self.assertTrue(unidades.alterar_ativa(self.conexao, unidade_id, False, "Maria"))
        self.assertFalse(unidades.alterar_ativa(self.conexao, unidade_id, False, "Maria"))
        self.assertEqual(unidades.listar_unidades(self.conexao, apenas_ativas=True), [])
        self.assertEqual(len(unidades.listar_unidades(self.conexao)), 1)
        unidades.alterar_ativa(self.conexao, unidade_id, True, "Maria")
        self.assertEqual([h[0] for h in _historico(self.conexao, "unidade", unidade_id)], ["CRIAR", "DESATIVAR", "ATIVAR"])

    def test_responsavel_obrigatorio(self):
        with self.assertRaises(ErroCadastro):
            unidades.criar_unidade(self.conexao, {"ugr_codigo": "A1", "nome": "Uma"}, " ")
        self.assertEqual(self.conexao.execute("SELECT COUNT(*) FROM unidade").fetchone()[0], 0)


class CriarEditarCicloTests(Base):
    def test_cria_ciclo_em_rascunho_com_datas_e_historico(self):
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(), "Maria")
        linha = self.conexao.execute("SELECT * FROM ciclo WHERE id = ?", (ciclo_id,)).fetchone()
        self.assertEqual((linha["exercicio"], linha["fase"], linha["abertura"], linha["devolutiva_prevista"]), (2027, "RASCUNHO", "2026-09-01", "2026-12-15"))
        self.assertEqual(linha["somente_leitura_apos"], 1)
        self.assertEqual(linha["permite_rascunho_antecipado"], 0)
        self.assertEqual(ciclos.avisos_do_ciclo(linha), ciclos.avisos_padrao())
        self.assertEqual(_historico(self.conexao, "ciclo", ciclo_id), [("CRIAR", "exercicio", None, "2027", "Maria")])

    def test_um_ciclo_por_exercicio_e_exercicio_valido(self):
        ciclos.criar_ciclo(self.conexao, 2027, {}, "Maria")
        with self.assertRaises(ErroCadastro):
            ciclos.criar_ciclo(self.conexao, 2027, {}, "Maria")
        for invalido in (1999, 2101, "2027", None, True):
            with self.subTest(exercicio=invalido):
                with self.assertRaises(ErroCadastro):
                    ciclos.criar_ciclo(self.conexao, invalido, {}, "Maria")

    def test_ordem_das_datas_e_validada_so_entre_as_informadas(self):
        with self.assertRaises(ErroCadastro) as contexto:
            ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(encerramento=date(2026, 8, 1)), "Maria")
        self.assertIn("abertura do registro não pode ser depois de encerramento do registro", contexto.exception.erros[0])
        with self.assertRaises(ErroCadastro):
            ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(prazo_validacao=date(2026, 10, 1)), "Maria")
        # datas ausentes no meio não impedem a checagem das vizinhas presentes
        ciclos.criar_ciclo(self.conexao, 2027, {"abertura": "2026-09-01", "devolutiva_prevista": "2026-12-15"}, "Maria")
        with self.assertRaises(ErroCadastro):
            ciclos.criar_ciclo(self.conexao, 2028, {"abertura": "2026-09-01", "devolutiva_prevista": "2026-08-15"}, "Maria")

    def test_data_invalida_e_recusada_e_texto_iso_e_aceito(self):
        with self.assertRaises(ErroCadastro):
            ciclos.criar_ciclo(self.conexao, 2027, {"abertura": "31/02/2026"}, "Maria")
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, {"abertura": "2026-09-01"}, "Maria")
        self.assertEqual(self.conexao.execute("SELECT abertura FROM ciclo WHERE id = ?", (ciclo_id,)).fetchone()[0], "2026-09-01")

    def test_versoes_dos_planos_precisam_estar_carregadas(self):
        with self.assertRaises(ErroCadastro) as contexto:
            ciclos.criar_ciclo(self.conexao, 2027, {"versao_pdi": "PDI X"}, "Maria")
        self.assertIn("Planos de Referência", contexto.exception.erros[0])
        planos.carregar_pdi(self.conexao, planos.validar_linhas_pdi([CAB_PDI, ("O1", "x", "Um")]), "PDI X")
        planos.carregar_pls(self.conexao, planos.validar_linhas_pls([CAB_PLS, (None, None, "D1", "Um")]), "PLS Y")
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, {"versao_pdi": "PDI X", "versao_pls": "PLS Y"}, "Maria")
        linha = self.conexao.execute("SELECT versao_pdi, versao_pls FROM ciclo WHERE id = ?", (ciclo_id,)).fetchone()
        self.assertEqual((linha["versao_pdi"], linha["versao_pls"]), ("PDI X", "PLS Y"))

    def test_edita_ciclo_em_preparacao_e_grava_antes_e_depois(self):
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(), "Maria")
        campos = ciclos.editar_ciclo(
            self.conexao, ciclo_id, _dados_ciclo(encerramento=date(2026, 11, 5), mensagem_abertura="Olá", avisos={"abertura": True}), "João", HOJE
        )
        self.assertEqual(sorted(campos), ["avisos_json", "encerramento", "mensagem_abertura"])
        self.assertIn(("EDITAR", "encerramento", "2026-10-31", "2026-11-05", "João"), _historico(self.conexao, "ciclo", ciclo_id))
        linha = self.conexao.execute("SELECT * FROM ciclo WHERE id = ?", (ciclo_id,)).fetchone()
        self.assertTrue(ciclos.avisos_do_ciclo(linha)["abertura"])
        self.assertEqual(ciclos.editar_ciclo(self.conexao, ciclo_id, _dados_ciclo(encerramento=date(2026, 11, 5), mensagem_abertura="Olá", avisos={"abertura": True}), "João", HOJE), [])

    def test_ciclo_aberto_trava_a_abertura_mas_deixa_ajustar_encerramento(self):
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(), "Maria")
        ciclos.agendar_ciclo(self.conexao, ciclo_id, "Maria")
        with self.assertRaises(ErroCadastro) as contexto:
            ciclos.editar_ciclo(self.conexao, ciclo_id, _dados_ciclo(abertura=date(2026, 9, 5)), "Maria", HOJE)  # 01/10: já aberto pela data
        self.assertIn("abertura do registro", contexto.exception.erros[0])
        ciclos.editar_ciclo(self.conexao, ciclo_id, _dados_ciclo(encerramento=date(2026, 11, 5)), "Maria", HOJE)

    def test_ciclo_encerrado_trava_abertura_e_encerramento_mas_nao_prazos_posteriores(self):
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(), "Maria")
        ciclos.agendar_ciclo(self.conexao, ciclo_id, "Maria")
        depois = date(2026, 11, 3)  # passou o encerramento: encerrado pela data
        with self.assertRaises(ErroCadastro):
            ciclos.editar_ciclo(self.conexao, ciclo_id, _dados_ciclo(encerramento=date(2026, 11, 20)), "Maria", depois)
        ciclos.editar_ciclo(self.conexao, ciclo_id, _dados_ciclo(prazo_validacao=date(2026, 11, 12)), "Maria", depois)

    def test_exercicio_nunca_muda_e_ciclo_inexistente_e_erro(self):
        with self.assertRaises(ErroCadastro):
            ciclos.editar_ciclo(self.conexao, 999, {}, "Maria", HOJE)

    def test_responsavel_obrigatorio_em_todas_as_acoes(self):
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(), "Maria")
        for acao in (
            lambda: ciclos.criar_ciclo(self.conexao, 2028, {}, ""),
            lambda: ciclos.editar_ciclo(self.conexao, ciclo_id, {}, " ", HOJE),
            lambda: ciclos.agendar_ciclo(self.conexao, ciclo_id, None),
            lambda: ciclos.abrir_agora(self.conexao, ciclo_id, "", HOJE),
            lambda: ciclos.encerrar_agora(self.conexao, ciclo_id, "", HOJE),
        ):
            with self.assertRaises(ErroCadastro):
                acao()


class FasesTests(Base):
    def test_agendar_exige_abertura_e_encerramento_e_so_vale_em_rascunho(self):
        sem_datas = ciclos.criar_ciclo(self.conexao, 2027, {"abertura": "2026-09-01"}, "Maria")
        with self.assertRaises(ErroCadastro) as contexto:
            ciclos.agendar_ciclo(self.conexao, sem_datas, "Maria")
        self.assertIn("encerramento do registro", contexto.exception.erros[0])
        completo = ciclos.criar_ciclo(self.conexao, 2028, _dados_ciclo(), "Maria")
        ciclos.agendar_ciclo(self.conexao, completo, "Maria")
        self.assertEqual(self.conexao.execute("SELECT fase FROM ciclo WHERE id = ?", (completo,)).fetchone()[0], "AGENDADO")
        self.assertIn(("FASE", "fase", "RASCUNHO", "AGENDADO", "Maria"), _historico(self.conexao, "ciclo", completo))
        with self.assertRaises(ErroCadastro):
            ciclos.agendar_ciclo(self.conexao, completo, "Maria")

    def test_fase_efetiva_segue_a_data_sem_gravar(self):
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(), "Maria")
        ciclos.agendar_ciclo(self.conexao, ciclo_id, "Maria")
        ciclo = self.conexao.execute("SELECT * FROM ciclo WHERE id = ?", (ciclo_id,)).fetchone()
        self.assertEqual(ciclos.fase_efetiva(ciclo, date(2026, 8, 20)), "AGENDADO")
        self.assertEqual(ciclos.fase_efetiva(ciclo, date(2026, 9, 1)), "ABERTO")
        self.assertEqual(ciclos.fase_efetiva(ciclo, date(2026, 11, 1)), "ENCERRADO")
        self.assertEqual(self.conexao.execute("SELECT fase FROM ciclo WHERE id = ?", (ciclo_id,)).fetchone()[0], "AGENDADO")

    def test_abrir_agora_antecipa_a_abertura_para_hoje_e_registra(self):
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(abertura=date(2026, 10, 15)), "Maria")
        ciclos.agendar_ciclo(self.conexao, ciclo_id, "Maria")
        ciclos.abrir_agora(self.conexao, ciclo_id, "Maria", HOJE)
        linha = self.conexao.execute("SELECT fase, abertura FROM ciclo WHERE id = ?", (ciclo_id,)).fetchone()
        self.assertEqual((linha["fase"], linha["abertura"]), ("ABERTO", "2026-10-01"))
        historico = _historico(self.conexao, "ciclo", ciclo_id)
        self.assertIn(("EDITAR", "abertura", "2026-10-15", "2026-10-01", "Maria"), historico)
        self.assertIn(("FASE", "fase", "AGENDADO", "ABERTO", "Maria"), historico)

    def test_abrir_agora_libera_o_registro_de_demandas_pela_regra_RN05(self):
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(abertura=date(2026, 10, 15)), "Maria")
        self.conexao.execute("INSERT INTO unidade (id, ugr_codigo, nome) VALUES (1, '1', 'U')")
        self.conexao.commit()
        with self.assertRaises(regras.ErroRegra):
            servicos.criar_rascunho(self.conexao, ciclo_id, 1, "rep", {"descricao": "x"}, HOJE)
        ciclos.abrir_agora(self.conexao, ciclo_id, "Maria", HOJE)
        self.assertGreater(servicos.criar_rascunho(self.conexao, ciclo_id, 1, "rep", {"descricao": "x"}, HOJE), 0)

    def test_abrir_agora_exige_encerramento_futuro_e_so_vale_antes_da_abertura(self):
        sem_encerramento = ciclos.criar_ciclo(self.conexao, 2027, {}, "Maria")
        with self.assertRaises(ErroCadastro):
            ciclos.abrir_agora(self.conexao, sem_encerramento, "Maria", HOJE)
        vencido = ciclos.criar_ciclo(self.conexao, 2028, _dados_ciclo(encerramento=date(2026, 9, 30)), "Maria")
        with self.assertRaises(ErroCadastro):
            ciclos.abrir_agora(self.conexao, vencido, "Maria", HOJE)
        aberto = ciclos.criar_ciclo(self.conexao, 2029, _dados_ciclo(), "Maria")
        ciclos.abrir_agora(self.conexao, aberto, "Maria", HOJE)
        with self.assertRaises(ErroCadastro):
            ciclos.abrir_agora(self.conexao, aberto, "Maria", HOJE)

    def test_encerrar_agora_bloqueia_o_registro_mesmo_dentro_do_prazo(self):
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(), "Maria")
        self.conexao.execute("INSERT INTO unidade (id, ugr_codigo, nome) VALUES (1, '1', 'U')")
        self.conexao.commit()
        ciclos.abrir_agora(self.conexao, ciclo_id, "Maria", HOJE)
        ciclos.encerrar_agora(self.conexao, ciclo_id, "Maria", HOJE)
        self.assertIn(("FASE", "fase", "ABERTO", "ENCERRADO", "Maria"), _historico(self.conexao, "ciclo", ciclo_id))
        with self.assertRaises(regras.ErroRegra):
            servicos.criar_rascunho(self.conexao, ciclo_id, 1, "rep", {"descricao": "x"}, HOJE)
        with self.assertRaises(ErroCadastro):
            ciclos.encerrar_agora(self.conexao, ciclo_id, "Maria", HOJE)

    def test_encerrar_so_ciclo_aberto(self):
        em_preparo = ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(), "Maria")
        with self.assertRaises(ErroCadastro):
            ciclos.encerrar_agora(self.conexao, em_preparo, "Maria", HOJE)
        futuro = ciclos.criar_ciclo(self.conexao, 2028, _dados_ciclo(abertura=date(2026, 12, 1), encerramento=date(2026, 12, 31), prazo_validacao=date(2027, 1, 10), devolutiva_prevista=date(2027, 2, 1)), "Maria")
        ciclos.agendar_ciclo(self.conexao, futuro, "Maria")
        with self.assertRaises(ErroCadastro):
            ciclos.encerrar_agora(self.conexao, futuro, "Maria", HOJE)


class ProrrogacaoTests(Base):
    def setUp(self):
        super().setUp()
        self.unidade = unidades.criar_unidade(self.conexao, {"ugr_codigo": "A1", "nome": "Depto. A"}, "Maria")
        self.outra = unidades.criar_unidade(self.conexao, {"ugr_codigo": "A2", "nome": "Depto. B"}, "Maria")
        self.ciclo = ciclos.criar_ciclo(self.conexao, 2027, _dados_ciclo(), "Maria")
        ciclos.agendar_ciclo(self.conexao, self.ciclo, "Maria")

    def test_concede_com_motivo_e_historico(self):
        pid = ciclos.conceder_prorrogacao(self.conexao, self.ciclo, self.unidade, date(2026, 11, 7), "Troca de chefia", "Gestor")
        linha = self.conexao.execute("SELECT * FROM prorrogacao WHERE id = ?", (pid,)).fetchone()
        self.assertEqual((linha["novo_prazo"], linha["motivo"], linha["concedida_por"]), ("2026-11-07", "Troca de chefia", "Gestor"))
        self.assertIn(("PRORROGAR", "novo_prazo", None, "2026-11-07", "Gestor"), _historico(self.conexao, "prorrogacao", pid))
        self.assertEqual([p["ugr_codigo"] for p in ciclos.listar_prorrogacoes(self.conexao, self.ciclo)], ["A1"])

    def test_motivo_obrigatorio_e_prazo_depois_do_encerramento(self):
        for prazo, motivo, trecho in [
            (date(2026, 11, 7), "  ", "motivo"),
            (date(2026, 10, 31), "Motivo", "depois do encerramento"),
            (date(2026, 10, 1), "Motivo", "depois do encerramento"),
            (None, "Motivo", "novo prazo"),
            ("32/13/2026", "Motivo", "Data inválida"),
        ]:
            with self.subTest(prazo=prazo, motivo=motivo):
                with self.assertRaises(ErroCadastro) as contexto:
                    ciclos.conceder_prorrogacao(self.conexao, self.ciclo, self.unidade, prazo, motivo, "Gestor")
                self.assertIn(trecho, " ".join(contexto.exception.erros))
        self.assertEqual(self.conexao.execute("SELECT COUNT(*) FROM prorrogacao").fetchone()[0], 0)

    def test_uma_por_unidade_e_altera_a_existente_com_historico(self):
        pid = ciclos.conceder_prorrogacao(self.conexao, self.ciclo, self.unidade, date(2026, 11, 7), "Motivo 1", "Gestor")
        with self.assertRaises(ErroCadastro):
            ciclos.conceder_prorrogacao(self.conexao, self.ciclo, self.unidade, date(2026, 11, 9), "Motivo 2", "Gestor")
        campos = ciclos.alterar_prorrogacao(self.conexao, pid, date(2026, 11, 9), "Motivo 1", "Gestor")
        self.assertEqual(campos, ["novo_prazo"])
        self.assertIn(("PRORROGAR", "novo_prazo", "2026-11-07", "2026-11-09", "Gestor"), _historico(self.conexao, "prorrogacao", pid))
        self.assertEqual(ciclos.alterar_prorrogacao(self.conexao, pid, date(2026, 11, 9), "Motivo 1", "Gestor"), [])

    def test_so_enquanto_o_registro_nao_foi_encerrado_e_para_unidade_ativa(self):
        unidades.alterar_ativa(self.conexao, self.outra, False, "Maria")
        with self.assertRaises(ErroCadastro):
            ciclos.conceder_prorrogacao(self.conexao, self.ciclo, self.outra, date(2026, 11, 7), "Motivo", "Gestor")
        with self.assertRaises(ErroCadastro):
            ciclos.conceder_prorrogacao(self.conexao, self.ciclo, 999, date(2026, 11, 7), "Motivo", "Gestor")
        self.conexao.execute("UPDATE ciclo SET fase = 'ENCERRADO' WHERE id = ?", (self.ciclo,))
        self.conexao.commit()
        with self.assertRaises(ErroCadastro):
            ciclos.conceder_prorrogacao(self.conexao, self.ciclo, self.unidade, date(2026, 11, 7), "Motivo", "Gestor")

    def test_prorrogacao_vale_so_para_a_unidade_na_regra_de_registro(self):
        ciclos.conceder_prorrogacao(self.conexao, self.ciclo, self.unidade, date(2026, 11, 7), "Motivo", "Gestor")
        depois = date(2026, 11, 3)  # passou o encerramento geral
        servicos.criar_rascunho(self.conexao, self.ciclo, self.unidade, "rep", {"descricao": "ok"}, depois)
        with self.assertRaises(regras.ErroRegra):
            servicos.criar_rascunho(self.conexao, self.ciclo, self.outra, "rep", {"descricao": "x"}, depois)

    def test_responsavel_obrigatorio(self):
        with self.assertRaises(ErroCadastro):
            ciclos.conceder_prorrogacao(self.conexao, self.ciclo, self.unidade, date(2026, 11, 7), "Motivo", " ")


class AvisosTests(Base):
    def test_avisos_sao_guardados_como_json_e_lidos_de_volta(self):
        ciclo_id = ciclos.criar_ciclo(self.conexao, 2027, {"avisos": {"sete_dias": True, "dois_dias": True}}, "Maria")
        linha = self.conexao.execute("SELECT * FROM ciclo WHERE id = ?", (ciclo_id,)).fetchone()
        guardado = json.loads(linha["avisos_json"])
        self.assertEqual(set(guardado), set(ciclos.AVISOS))
        self.assertTrue(guardado["sete_dias"] and guardado["dois_dias"] and not guardado["abertura"])


if __name__ == "__main__":
    unittest.main()
