"""Testes de src/prazos_orcamentarios.py — cadastro manual de prazos, persistência em disco
e classificação de alerta por antecedência própria de cada prazo. Usa um diretório temporário
(`tempfile`) a cada teste, nunca `data/prazos_orcamentarios/` real.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.prazos_orcamentarios import (
    DIAS_ANTECEDENCIA_PADRAO,
    PRIORIDADE_PADRAO,
    TIPO_PADRAO,
    ErroPrazoOrcamentario,
    atualizar,
    carregar_prazos,
    excluir,
    novo_prazo,
    prazos_com_criticidade,
    salvar,
)


class TestNovoPrazo(unittest.TestCase):
    def test_monta_registro_com_id_e_concluido_falso(self):
        prazo = novo_prazo("Prestação de contas", date(2026, 12, 1), "Obs", "Fulano", 45)
        self.assertTrue(prazo["id"])
        self.assertEqual(prazo["titulo"], "Prestação de contas")
        self.assertEqual(prazo["data_prazo"], "2026-12-01")
        self.assertEqual(prazo["descricao"], "Obs")
        self.assertEqual(prazo["responsavel"], "Fulano")
        self.assertEqual(prazo["dias_antecedencia"], 45)
        self.assertFalse(prazo["concluido"])

    def test_antecedencia_usa_padrao_quando_nao_informada(self):
        prazo = novo_prazo("Prazo A", date(2026, 12, 1))
        self.assertEqual(prazo["dias_antecedencia"], DIAS_ANTECEDENCIA_PADRAO)

    def test_tipo_categoria_prioridade_usam_padrao_quando_nao_informados(self):
        prazo = novo_prazo("Prazo A", date(2026, 12, 1))
        self.assertEqual(prazo["tipo"], TIPO_PADRAO)
        self.assertEqual(prazo["categoria"], "")
        self.assertEqual(prazo["prioridade"], PRIORIDADE_PADRAO)

    def test_tipo_categoria_prioridade_sao_gravados(self):
        prazo = novo_prazo(
            "Prazo A", date(2026, 12, 1), tipo="Calendário anual",
            categoria="SIAFI", prioridade="Essencial",
        )
        self.assertEqual(prazo["tipo"], "Calendário anual")
        self.assertEqual(prazo["categoria"], "SIAFI")
        self.assertEqual(prazo["prioridade"], "Essencial")

    def test_tipo_invalido_e_rejeitado(self):
        with self.assertRaises(ErroPrazoOrcamentario):
            novo_prazo("Prazo A", date(2026, 12, 1), tipo="Outro Tipo")

    def test_prioridade_invalida_e_rejeitada(self):
        with self.assertRaises(ErroPrazoOrcamentario):
            novo_prazo("Prazo A", date(2026, 12, 1), prioridade="Urgentíssimo")

    def test_titulo_vazio_e_rejeitado(self):
        with self.assertRaises(ErroPrazoOrcamentario):
            novo_prazo("   ", date(2026, 12, 1))

    def test_data_invalida_e_rejeitada(self):
        with self.assertRaises(ErroPrazoOrcamentario):
            novo_prazo("Título", "2026-12-01")  # type: ignore[arg-type]

    def test_antecedencia_negativa_e_rejeitada(self):
        with self.assertRaises(ErroPrazoOrcamentario):
            novo_prazo("Título", date(2026, 12, 1), dias_antecedencia=-1)

    def test_antecedencia_nao_inteira_e_rejeitada(self):
        with self.assertRaises(ErroPrazoOrcamentario):
            novo_prazo("Título", date(2026, 12, 1), dias_antecedencia=30.5)  # type: ignore[arg-type]
        with self.assertRaises(ErroPrazoOrcamentario):
            novo_prazo("Título", date(2026, 12, 1), dias_antecedencia=True)  # type: ignore[arg-type]

    def test_dois_prazos_tem_ids_diferentes(self):
        a = novo_prazo("Prazo A", date(2026, 12, 1))
        b = novo_prazo("Prazo A", date(2026, 12, 1))
        self.assertNotEqual(a["id"], b["id"])


class TestPersistencia(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.diretorio = Path(self._tmp.name)

    def test_salvar_e_carregar_round_trip(self):
        prazo = novo_prazo("Prazo A", date(2026, 12, 1))
        salvar(prazo, self.diretorio)
        carregados = carregar_prazos(self.diretorio)
        self.assertEqual(len(carregados), 1)
        self.assertEqual(carregados[0]["id"], prazo["id"])

    def test_salvar_nao_sobrescreve_id_existente(self):
        prazo = novo_prazo("Prazo A", date(2026, 12, 1))
        salvar(prazo, self.diretorio)
        with self.assertRaises(FileExistsError):
            salvar(prazo, self.diretorio)

    def test_carregar_diretorio_inexistente_devolve_lista_vazia(self):
        self.assertEqual(carregar_prazos(self.diretorio / "nao_existe"), [])

    def test_atualizar_exige_registro_ja_gravado(self):
        prazo = novo_prazo("Prazo A", date(2026, 12, 1))
        with self.assertRaises(FileNotFoundError):
            atualizar(prazo, self.diretorio)

    def test_atualizar_sobrescreve_e_atualiza_timestamp(self):
        prazo = novo_prazo("Prazo A", date(2026, 12, 1))
        salvar(prazo, self.diretorio)
        editado = {**prazo, "concluido": True, "dias_antecedencia": 90}
        atualizar(editado, self.diretorio)
        carregados = carregar_prazos(self.diretorio)
        self.assertTrue(carregados[0]["concluido"])
        self.assertEqual(carregados[0]["dias_antecedencia"], 90)
        self.assertGreaterEqual(carregados[0]["atualizado_em"], prazo["atualizado_em"])

    def test_excluir_remove_o_arquivo(self):
        prazo = novo_prazo("Prazo A", date(2026, 12, 1))
        caminho = salvar(prazo, self.diretorio)
        self.assertTrue(caminho.exists())
        excluir(prazo["id"], self.diretorio)
        self.assertFalse(caminho.exists())
        self.assertEqual(carregar_prazos(self.diretorio), [])

    def test_excluir_id_inexistente_nao_lanca_erro(self):
        excluir("00000000-0000-0000-0000-000000000000", self.diretorio)

    def test_identificador_invalido_e_rejeitado(self):
        with self.assertRaises(ErroPrazoOrcamentario):
            excluir("../fuga", self.diretorio)

    def test_arquivo_gravado_e_json_valido_no_disco(self):
        prazo = novo_prazo("Prazo A", date(2026, 12, 1))
        caminho = salvar(prazo, self.diretorio)
        conteudo = json.loads(caminho.read_text(encoding="utf-8"))
        self.assertEqual(conteudo["titulo"], "Prazo A")


class TestPrazosComCriticidade(unittest.TestCase):
    HOJE = date(2026, 9, 3)

    def test_lista_vazia_devolve_dataframe_vazio_com_colunas(self):
        resultado = prazos_com_criticidade([], hoje=self.HOJE)
        self.assertTrue(resultado.empty)
        self.assertIn("criticidade", resultado.columns)

    def test_vencido_independe_da_antecedencia(self):
        prazo = novo_prazo("Vencido", date(2026, 8, 1), dias_antecedencia=5)
        resultado = prazos_com_criticidade([prazo], hoje=self.HOJE)
        self.assertEqual(resultado.iloc[0]["criticidade"], "Atrasado")

    def test_mesmos_dias_para_vencer_com_antecedencias_diferentes(self):
        # ambos vencem em 40 dias (13/10/2026) a partir de 03/09/2026
        curta = novo_prazo("Antecedencia curta", date(2026, 10, 13), dias_antecedencia=10)
        longa = novo_prazo("Antecedencia longa", date(2026, 10, 13), dias_antecedencia=60)
        resultado = prazos_com_criticidade([curta, longa], hoje=self.HOJE)
        por_titulo = resultado.set_index("titulo")["criticidade"]
        self.assertEqual(por_titulo["Antecedencia curta"], "Em dia")
        self.assertEqual(por_titulo["Antecedencia longa"], "Vencendo")

    def test_dentro_da_antecedencia_e_vencendo(self):
        prazo = novo_prazo("Alerta", date(2026, 9, 20), dias_antecedencia=30)  # 17 dias
        resultado = prazos_com_criticidade([prazo], hoje=self.HOJE)
        self.assertEqual(resultado.iloc[0]["criticidade"], "Vencendo")

    def test_fora_da_antecedencia_e_em_dia(self):
        prazo = novo_prazo("Tranquilo", date(2027, 3, 1), dias_antecedencia=30)
        resultado = prazos_com_criticidade([prazo], hoje=self.HOJE)
        self.assertEqual(resultado.iloc[0]["criticidade"], "Em dia")

    def test_concluido_sobrepoe_criticidade_mesmo_se_vencido(self):
        prazo = novo_prazo("Feito", date(2026, 1, 1))
        prazo["concluido"] = True
        resultado = prazos_com_criticidade([prazo], hoje=self.HOJE)
        self.assertEqual(resultado.iloc[0]["criticidade"], "Concluído")

    def test_registro_antigo_sem_dias_antecedencia_usa_padrao(self):
        # simula um prazo gravado antes deste campo existir
        prazo = novo_prazo("Prazo A", date(2026, 9, 20))
        del prazo["dias_antecedencia"]
        resultado = prazos_com_criticidade([prazo], hoje=self.HOJE)
        self.assertEqual(resultado.iloc[0]["dias_antecedencia"], DIAS_ANTECEDENCIA_PADRAO)

    def test_registro_antigo_sem_tipo_categoria_prioridade_usa_padrao(self):
        # simula um prazo gravado antes do layout "Gerenciamento de Prazos" (10/09/2026)
        prazo = novo_prazo("Prazo A", date(2026, 9, 20))
        del prazo["tipo"], prazo["categoria"], prazo["prioridade"]
        resultado = prazos_com_criticidade([prazo], hoje=self.HOJE)
        self.assertEqual(resultado.iloc[0]["tipo"], TIPO_PADRAO)
        self.assertEqual(resultado.iloc[0]["categoria"], "")
        self.assertEqual(resultado.iloc[0]["prioridade"], PRIORIDADE_PADRAO)

    def test_ordena_nao_concluidos_primeiro_por_urgencia(self):
        vencido = novo_prazo("Vencido", date(2026, 8, 1))
        no_prazo = novo_prazo("No prazo", date(2027, 3, 1))
        concluido = novo_prazo("Concluido", date(2026, 8, 1))
        concluido["concluido"] = True
        resultado = prazos_com_criticidade([no_prazo, concluido, vencido], hoje=self.HOJE)
        self.assertEqual(list(resultado["titulo"]), ["Vencido", "No prazo", "Concluido"])


if __name__ == "__main__":
    unittest.main()
