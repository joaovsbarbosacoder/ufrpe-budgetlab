"""Edição manual dos planos de referência (PDI/PLS) e sua trilha de auditoria."""

from __future__ import annotations

import unittest

from src.captacao import planos, schema
from src.captacao.planos import ErroCarga

CAB_PDI = ("Código do objetivo", "Dimensão / eixo do PDI", "Descrição do objetivo")
CAB_PLS = ("Eixo temático", "Objetivo", "Código da meta", "Descrição da meta")


class EdicaoBase(unittest.TestCase):
    def setUp(self):
        self.conexao = schema.conectar(":memory:")
        planos.carregar_pdi(
            self.conexao, planos.validar_linhas_pdi([CAB_PDI, ("OE-01", "Sociedade", "Texto um"), ("OE-02", "Sociedade", "Texto dois")]), "PDI 2021-2030"
        )
        planos.carregar_pls(
            self.conexao, planos.validar_linhas_pls([CAB_PLS, (None, None, "D01", "Diretriz um"), (None, None, "D02", "Diretriz dois")]), "PLS 2025-2027"
        )
        self.pdi_id = self.conexao.execute("SELECT id FROM objetivo_pdi WHERE codigo = 'OE-01'").fetchone()[0]
        self.pls_id = self.conexao.execute("SELECT id FROM meta_pls WHERE codigo = 'D01'").fetchone()[0]

    def linha(self, tabela, item_id):
        return self.conexao.execute(f"SELECT * FROM {tabela} WHERE id = ?", (item_id,)).fetchone()

    def historico(self, tipo, item_id):
        return [(h["acao"], h["campo"], h["antes"], h["depois"], h["usuario"]) for h in planos.historico_item(self.conexao, tipo, item_id)]


class EditarItemTests(EdicaoBase):
    def test_edita_descricao_e_grava_antes_e_depois_com_usuario(self):
        campos = planos.editar_item(self.conexao, "pdi", self.pdi_id, {"codigo": "OE-01", "dimensao": "Sociedade", "descricao": "Texto novo"}, "Maria")
        self.assertEqual(campos, ["descricao"])
        self.assertEqual(self.linha("objetivo_pdi", self.pdi_id)["descricao"], "Texto novo")
        self.assertIn(("EDITAR", "descricao", "Texto um", "Texto novo", "Maria"), self.historico("pdi", self.pdi_id))

    def test_meta_pls_aceita_eixo_e_objetivo_inicialmente_vazios(self):
        campos = planos.editar_item(
            self.conexao, "pls", self.pls_id, {"codigo": "D01", "eixo": "Meio ambiente", "objetivo": "Preservar", "descricao": "Diretriz um"}, "Maria"
        )
        self.assertEqual(sorted(campos), ["eixo", "objetivo"])
        linha = self.linha("meta_pls", self.pls_id)
        self.assertEqual((linha["eixo"], linha["objetivo"]), ("Meio ambiente", "Preservar"))
        self.assertIn(("EDITAR", "eixo", None, "Meio ambiente", "Maria"), self.historico("pls", self.pls_id))

    def test_limpar_campo_opcional_grava_nulo_e_historico(self):
        planos.editar_item(self.conexao, "pdi", self.pdi_id, {"codigo": "OE-01", "dimensao": "  ", "descricao": "Texto um"}, "Maria")
        self.assertIsNone(self.linha("objetivo_pdi", self.pdi_id)["dimensao"])
        self.assertIn(("EDITAR", "dimensao", "Sociedade", None, "Maria"), self.historico("pdi", self.pdi_id))

    def test_alterar_codigo_mantem_o_id_e_os_vinculos(self):
        self.conexao.execute("INSERT INTO unidade (id, ugr_codigo, nome) VALUES (1, '1', 'U')")
        self.conexao.execute("INSERT INTO ciclo (id, exercicio, criado_em) VALUES (1, 2027, 'x')")
        self.conexao.execute("INSERT INTO demanda (id, ciclo_id, unidade_id, criada_em, atualizada_em) VALUES (1, 1, 1, 'x', 'x')")
        self.conexao.execute("INSERT INTO demanda_objetivo_pdi VALUES (1, ?)", (self.pdi_id,))
        self.conexao.commit()
        planos.editar_item(self.conexao, "pdi", self.pdi_id, {"codigo": "OE-99", "dimensao": "Sociedade", "descricao": "Texto um"}, "Maria")
        self.assertEqual(self.linha("objetivo_pdi", self.pdi_id)["codigo"], "OE-99")
        self.assertEqual(self.conexao.execute("SELECT objetivo_id FROM demanda_objetivo_pdi").fetchone()[0], self.pdi_id)

    def test_codigo_repetido_na_mesma_versao_e_recusado_sem_gravar(self):
        with self.assertRaises(ErroCarga) as contexto:
            planos.editar_item(self.conexao, "pdi", self.pdi_id, {"codigo": "OE-02", "dimensao": "Sociedade", "descricao": "Texto um"}, "Maria")
        self.assertIn("Já existe o código", contexto.exception.erros[0])
        self.assertEqual(self.linha("objetivo_pdi", self.pdi_id)["codigo"], "OE-01")
        self.assertEqual(self.historico("pdi", self.pdi_id), [("CRIAR", "codigo", None, "OE-01", None)])

    def test_mesmo_codigo_em_outra_versao_e_permitido(self):
        planos.criar_item(self.conexao, "pdi", "PDI 2031", {"codigo": "OE-01", "descricao": "Outra versão"}, "Maria")
        planos.editar_item(self.conexao, "pdi", self.pdi_id, {"codigo": "OE-01", "dimensao": "Sociedade", "descricao": "Texto um editado"}, "Maria")

    def test_codigo_e_descricao_obrigatorios_e_marcador_recusado(self):
        for dados, trecho in [
            ({"codigo": "", "descricao": "x"}, "Informe o código"),
            ({"codigo": "OE-01", "descricao": "  "}, "Informe a descrição"),
            ({"codigo": "[código]", "descricao": "x"}, "marcador"),
        ]:
            with self.subTest(dados=dados):
                with self.assertRaises(ErroCarga) as contexto:
                    planos.editar_item(self.conexao, "pdi", self.pdi_id, dados, "Maria")
                self.assertTrue(any(trecho in e for e in contexto.exception.erros))
        self.assertEqual(self.linha("objetivo_pdi", self.pdi_id)["descricao"], "Texto um")

    def test_codigo_preserva_zeros_a_esquerda_e_caixa(self):
        planos.editar_item(self.conexao, "pls", self.pls_id, {"codigo": "007a", "descricao": "Diretriz um"}, "Maria")
        self.assertEqual(self.linha("meta_pls", self.pls_id)["codigo"], "007a")

    def test_sem_mudanca_nao_grava_historico(self):
        campos = planos.editar_item(self.conexao, "pdi", self.pdi_id, {"codigo": "OE-01", "dimensao": "Sociedade", "descricao": "Texto um"}, "Maria")
        self.assertEqual(campos, [])
        self.assertEqual(len(self.historico("pdi", self.pdi_id)), 1)

    def test_usuario_e_obrigatorio_e_item_inexistente_e_erro(self):
        with self.assertRaises(ErroCarga):
            planos.editar_item(self.conexao, "pdi", self.pdi_id, {"codigo": "OE-01", "descricao": "Novo"}, "  ")
        with self.assertRaises(ErroCarga):
            planos.editar_item(self.conexao, "pdi", 9999, {"codigo": "X", "descricao": "Novo"}, "Maria")
        self.assertEqual(self.linha("objetivo_pdi", self.pdi_id)["descricao"], "Texto um")

    def test_tipo_desconhecido_e_erro_de_programacao(self):
        with self.assertRaises(ValueError):
            planos.editar_item(self.conexao, "outro", 1, {}, "Maria")


class CriarItemTests(EdicaoBase):
    def test_cria_meta_com_historico(self):
        item_id = planos.criar_item(self.conexao, "pls", "PLS 2025-2027", {"codigo": "D20", "descricao": "Nova diretriz"}, "Maria")
        linha = self.linha("meta_pls", item_id)
        self.assertEqual((linha["codigo"], linha["versao_pls"], linha["ativo"]), ("D20", "PLS 2025-2027", 1))
        self.assertEqual(self.historico("pls", item_id), [("CRIAR", "codigo", None, "D20", "Maria")])

    def test_codigo_duplicado_na_versao_e_recusado(self):
        with self.assertRaises(ErroCarga):
            planos.criar_item(self.conexao, "pls", "PLS 2025-2027", {"codigo": "D01", "descricao": "Repetida"}, "Maria")
        self.assertEqual(self.conexao.execute("SELECT COUNT(*) FROM meta_pls").fetchone()[0], 2)

    def test_versao_e_usuario_obrigatorios(self):
        with self.assertRaises(ErroCarga):
            planos.criar_item(self.conexao, "pls", " ", {"codigo": "D20", "descricao": "x"}, "Maria")
        with self.assertRaises(ErroCarga):
            planos.criar_item(self.conexao, "pls", "PLS 2025-2027", {"codigo": "D20", "descricao": "x"}, None)


class AtivoETrilhaTests(EdicaoBase):
    def test_desativa_e_reativa_sem_excluir_e_registra(self):
        self.assertTrue(planos.alterar_ativo(self.conexao, "pdi", self.pdi_id, False, "Maria"))
        self.assertEqual(self.linha("objetivo_pdi", self.pdi_id)["ativo"], 0)
        self.assertTrue(planos.alterar_ativo(self.conexao, "pdi", self.pdi_id, True, "Maria"))
        self.assertEqual(self.linha("objetivo_pdi", self.pdi_id)["ativo"], 1)
        acoes = [h[0] for h in self.historico("pdi", self.pdi_id)]
        self.assertEqual(acoes, ["CRIAR", "DESATIVAR", "REATIVAR"])

    def test_repetir_o_estado_atual_nao_muda_nem_registra(self):
        self.assertFalse(planos.alterar_ativo(self.conexao, "pdi", self.pdi_id, True, "Maria"))
        self.assertEqual(len(self.historico("pdi", self.pdi_id)), 1)

    def test_item_desativado_sai_da_busca_padrao_mas_continua_no_banco(self):
        planos.alterar_ativo(self.conexao, "pls", self.pls_id, False, "Maria")
        self.assertEqual([m["codigo"] for m in planos.buscar_metas_pls(self.conexao, "")], ["D02"])
        self.assertEqual(len(planos.buscar_metas_pls(self.conexao, "", apenas_ativas=False)), 2)

    def test_recarga_sobrescreve_edicao_manual_mas_guarda_o_valor_anterior(self):
        planos.editar_item(self.conexao, "pdi", self.pdi_id, {"codigo": "OE-01", "dimensao": "Sociedade", "descricao": "Editado à mão"}, "Maria")
        resultado = planos.carregar_pdi(
            self.conexao, planos.validar_linhas_pdi([CAB_PDI, ("OE-01", "Sociedade", "Texto um"), ("OE-02", "Sociedade", "Texto dois")]), "PDI 2021-2030", usuario="Carga"
        )
        self.assertEqual(resultado.atualizados, 1)
        self.assertEqual(self.linha("objetivo_pdi", self.pdi_id)["descricao"], "Texto um")
        self.assertIn(("CARGA", "descricao", "Editado à mão", "Texto um", "Carga"), self.historico("pdi", self.pdi_id))

    def test_carga_registra_criacao_e_desativacao_no_historico(self):
        planos.carregar_pdi(self.conexao, planos.validar_linhas_pdi([CAB_PDI, ("OE-01", "Sociedade", "Texto um"), ("OE-03", "x", "Novo")]), "PDI 2021-2030")
        novo = self.conexao.execute("SELECT id FROM objetivo_pdi WHERE codigo = 'OE-03'").fetchone()[0]
        self.assertEqual([h[0] for h in self.historico("pdi", novo)], ["CRIAR"])
        removido = self.conexao.execute("SELECT id FROM objetivo_pdi WHERE codigo = 'OE-02'").fetchone()[0]
        self.assertEqual([h[0] for h in self.historico("pdi", removido)], ["CRIAR", "DESATIVAR"])

    def test_historico_e_por_item_e_por_tipo(self):
        planos.editar_item(self.conexao, "pdi", self.pdi_id, {"codigo": "OE-01", "descricao": "Outro"}, "Maria")
        self.assertEqual(len(self.historico("pls", self.pls_id)), 1)  # só o CRIAR da carga


if __name__ == "__main__":
    unittest.main()
