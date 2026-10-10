"""Acompanhamento de emendas (10/2026): tramitação (status + histórico), objeto e destinatário.

Nenhum teste escreve em `data/`: o diretório de eventos é sempre temporário. Os eventos são imutáveis; corrigir é
acrescentar um evento (cancelar um status, redefinir o complemento).
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from src.acompanhamento_emendas import (
    STATUS_OUTRO,
    STATUS_SUGERIDOS,
    ErroAcompanhamento,
    cancelar_status,
    carregar_eventos,
    complemento_vigente,
    definir_complemento,
    historico_complemento,
    orfaos,
    reconstruir_tramitacao,
    registrar_status,
    status_atual,
)

HOJE = date(2026, 10, 10)
E1 = (2026, "6", "E1")
E2 = (2026, "6", "E2")
H1 = (2025, "6", "H1")  # exercício histórico: o acompanhamento vale para qualquer exercício
VALIDAS = {E1, E2, H1}
MOTIVO = "Registrado por engano, a data estava errada."


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "acompanhamento"

    def status(self, chave=E1, status="Em análise técnica", data=date(2026, 8, 12), **extra) -> dict:
        parametros = dict(
            chave=chave, status=status, status_outro=None, data_status=data, observacao=None, responsavel="Maria",
            chaves_validas=VALIDAS, hoje=HOJE, diretorio=self.dir,
        )
        parametros.update(extra)
        return registrar_status(**parametros)

    def complemento(self, chave=E1, objeto="Aquisição de equipamentos", destinatario="Pró-Reitoria", **extra) -> dict:
        parametros = dict(
            chave=chave, objeto=objeto, destinatario=destinatario, responsavel="Maria", motivo=None,
            chaves_validas=VALIDAS, diretorio=self.dir,
        )
        parametros.update(extra)
        return definir_complemento(**parametros)


class TestRegistrarStatus(_Base):
    def test_status_da_lista_e_outro_com_texto(self) -> None:
        self.assertEqual(self.status()["status"], "Em análise técnica")
        self.assertIn("Impedimento técnico", STATUS_SUGERIDOS)
        with self.assertRaises(ErroAcompanhamento):  # "Outro" sem texto
            self.status(status=STATUS_OUTRO)
        with self.assertRaises(ErroAcompanhamento):  # texto curto demais (mín. 3)
            self.status(status=STATUS_OUTRO, status_outro="ab")
        with self.assertRaises(ErroAcompanhamento):  # texto longo demais (máx. 80)
            self.status(status=STATUS_OUTRO, status_outro="x" * 81)
        with self.assertRaises(ErroAcompanhamento):  # fora da lista, sem ser "Outro"
            self.status(status="Inventado")
        evento = self.status(status=STATUS_OUTRO, status_outro="  Aguardando parecer jurídico  ")
        self.assertEqual(evento["status_outro"], "Aguardando parecer jurídico")
        tramitacao = reconstruir_tramitacao(carregar_eventos(self.dir))
        self.assertIn("Aguardando parecer jurídico", set(tramitacao["status"]))  # o texto digitado é o status mostrado

    def test_status_outro_e_ignorado_quando_o_status_e_da_lista(self) -> None:
        self.assertIsNone(self.status(status_outro="texto solto")["status_outro"])

    def test_data_futura_recusada_e_retroativa_aceita(self) -> None:
        with self.assertRaises(ErroAcompanhamento):
            self.status(data=date(2026, 10, 11))
        self.assertEqual(self.status(data=date(2026, 10, 10))["data_status"], "2026-10-10")  # hoje vale
        self.assertEqual(self.status(data=date(2026, 8, 12))["data_status"], "2026-08-12")
        self.assertEqual(self.status(data="2026-07-01")["data_status"], "2026-07-01")  # texto ISO aceito
        for invalida in ("amanhã", "", None, "2026-13-40"):
            with self.subTest(data=invalida), self.assertRaises(ErroAcompanhamento):
                self.status(data=invalida)

    def test_responsavel_obrigatorio_e_observacao_limitada(self) -> None:
        for responsavel in ("", "   ", None):
            with self.subTest(responsavel=responsavel), self.assertRaises(ErroAcompanhamento):
                self.status(responsavel=responsavel)
        with self.assertRaises(ErroAcompanhamento):
            self.status(observacao="x" * 501)
        self.assertIsNone(self.status(observacao="   ")["observacao"])
        self.assertEqual(self.status(observacao=" ok ")["observacao"], "ok")

    def test_chave_inexistente_recusada_e_historico_aceito(self) -> None:
        with self.assertRaises(ErroAcompanhamento):
            self.status(chave=(2026, "6", "NAO"))
        with self.assertRaises(ErroAcompanhamento):
            self.status(chave=(2026, "9", "E1"))  # RP fora de 6/7/8
        self.assertEqual(self.status(chave=H1)["ano"], 2025)  # exercício < 2026 é permitido aqui

    def test_nada_e_gravado_quando_a_validacao_falha(self) -> None:
        with self.assertRaises(ErroAcompanhamento):
            self.status(responsavel="")
        self.assertFalse(self.dir.exists() and list(self.dir.glob("*.json")))


class TestStatusAtualEHistorico(_Base):
    def test_status_atual_e_o_de_maior_data(self) -> None:
        self.status(status="Em análise técnica", data=date(2026, 8, 12))
        self.status(status="Proposta aceita", data=date(2026, 9, 1))
        tramitacao = reconstruir_tramitacao(carregar_eventos(self.dir))
        self.assertEqual(list(tramitacao["status"]), ["Em análise técnica", "Proposta aceita"])  # cronológico
        atual = status_atual(tramitacao)
        self.assertEqual(len(atual), 1)
        self.assertEqual(atual.iloc[0]["status"], "Proposta aceita")
        self.assertEqual(atual.iloc[0]["data_status"], date(2026, 9, 1))
        self.assertEqual(atual.iloc[0]["responsavel"], "Maria")

    def test_status_registrado_depois_com_data_anterior_nao_vira_o_atual(self) -> None:
        self.status(status="Proposta aceita", data=date(2026, 9, 1))
        self.status(status="Recebida pela UFRPE", data=date(2026, 8, 1))  # lançado depois, mas é mais antigo
        atual = status_atual(reconstruir_tramitacao(carregar_eventos(self.dir)))
        self.assertEqual(atual.iloc[0]["status"], "Proposta aceita")

    def test_empate_de_data_vale_o_registrado_por_ultimo(self) -> None:
        self.status(status="Empenhada", data=date(2026, 9, 1))
        time.sleep(0.01)
        self.status(status="Liquidada", data=date(2026, 9, 1))
        atual = status_atual(reconstruir_tramitacao(carregar_eventos(self.dir)))
        self.assertEqual(atual.iloc[0]["status"], "Liquidada")

    def test_uma_linha_por_emenda_no_status_atual(self) -> None:
        self.status(chave=E1)
        self.status(chave=E2, status="Indicada")
        atual = status_atual(reconstruir_tramitacao(carregar_eventos(self.dir)))
        self.assertEqual(sorted(atual["emenda_numero"]), ["E1", "E2"])

    def test_sem_eventos_devolve_tabelas_vazias_com_colunas(self) -> None:
        tramitacao = reconstruir_tramitacao([])
        self.assertTrue(tramitacao.empty)
        for coluna in ("status", "data_status", "responsavel", "cancelado"):
            self.assertIn(coluna, tramitacao.columns)
        self.assertTrue(status_atual(tramitacao).empty)


class TestCancelarStatus(_Base):
    def test_cancelar_mantem_o_original_e_remove_do_status_atual(self) -> None:
        primeiro = self.status(status="Em análise técnica", data=date(2026, 8, 12))
        segundo = self.status(status="Proposta aceita", data=date(2026, 9, 1))
        original = (self.dir / f"{segundo['evento_id']}.json").read_text(encoding="utf-8")
        cancelamento = cancelar_status(evento_id=segundo["evento_id"], motivo=MOTIVO, responsavel="João", diretorio=self.dir)
        self.assertEqual(cancelamento["acao"], "cancelar_status")
        self.assertEqual(len(list(self.dir.glob("*.json"))), 3)
        self.assertEqual((self.dir / f"{segundo['evento_id']}.json").read_text(encoding="utf-8"), original)  # intacto
        tramitacao = reconstruir_tramitacao(carregar_eventos(self.dir))
        cancelado = tramitacao[tramitacao["evento_id"] == segundo["evento_id"]].iloc[0]
        self.assertTrue(cancelado["cancelado"])
        self.assertEqual((cancelado["cancelado_por"], cancelado["cancelado_motivo"]), ("João", MOTIVO))
        self.assertEqual(len(tramitacao), 2)  # o cancelado continua no histórico
        self.assertEqual(status_atual(tramitacao).iloc[0]["evento_id"], primeiro["evento_id"])

    def test_cancelar_todos_deixa_a_emenda_sem_status_atual(self) -> None:
        evento = self.status()
        cancelar_status(evento_id=evento["evento_id"], motivo=MOTIVO, responsavel="J", diretorio=self.dir)
        self.assertTrue(status_atual(reconstruir_tramitacao(carregar_eventos(self.dir))).empty)

    def test_cancelar_duas_vezes_id_inexistente_e_motivo_curto_levantam_erro(self) -> None:
        evento = self.status()
        with self.assertRaises(ErroAcompanhamento):
            cancelar_status(evento_id=evento["evento_id"], motivo="curto", responsavel="J", diretorio=self.dir)
        with self.assertRaises(ErroAcompanhamento):
            cancelar_status(evento_id=evento["evento_id"], motivo=MOTIVO, responsavel=" ", diretorio=self.dir)
        cancelar_status(evento_id=evento["evento_id"], motivo=MOTIVO, responsavel="J", diretorio=self.dir)
        with self.assertRaises(ErroAcompanhamento):
            cancelar_status(evento_id=evento["evento_id"], motivo=MOTIVO, responsavel="J", diretorio=self.dir)
        with self.assertRaises(ErroAcompanhamento):
            cancelar_status(evento_id="nao-existe", motivo=MOTIVO, responsavel="J", diretorio=self.dir)

    def test_nao_e_possivel_cancelar_um_evento_de_complemento(self) -> None:
        complemento = self.complemento()
        with self.assertRaises(ErroAcompanhamento):
            cancelar_status(evento_id=complemento["evento_id"], motivo=MOTIVO, responsavel="J", diretorio=self.dir)


class TestComplemento(_Base):
    def test_define_atualiza_e_registra_o_historico(self) -> None:
        self.complemento()
        time.sleep(0.01)
        self.complemento(objeto="Aquisição de equipamentos de laboratório", motivo="Detalhamento do objeto.")
        eventos = carregar_eventos(self.dir)
        vigente = complemento_vigente(eventos)
        self.assertEqual(len(vigente), 1)
        linha = vigente.iloc[0]
        self.assertEqual(linha["objeto"], "Aquisição de equipamentos de laboratório")
        self.assertEqual(linha["destinatario"], "Pró-Reitoria")  # retrato completo: o destinatário se manteve
        historico = historico_complemento(eventos, E1)
        self.assertEqual(len(historico), 2)
        ultimo = historico.iloc[-1]
        self.assertEqual(ultimo["objeto_anterior"], "Aquisição de equipamentos")
        self.assertEqual(ultimo["objeto"], "Aquisição de equipamentos de laboratório")
        self.assertEqual(ultimo["motivo"], "Detalhamento do objeto.")
        self.assertTrue(pd.isna(historico.iloc[0]["objeto_anterior"]))  # o primeiro não tem anterior

    def test_vazio_vira_nulo_nunca_texto_vazio(self) -> None:
        evento = self.complemento(objeto="   ", destinatario="Pró-Reitoria")
        self.assertIsNone(evento["objeto"])
        with self.assertRaises(ErroAcompanhamento):  # tudo vazio e sem nada anterior: não há o que registrar
            self.complemento(chave=E2, objeto="  ", destinatario="")
        evento2 = self.complemento(chave=E2, objeto="Só o objeto", destinatario=None)
        self.assertIsNone(evento2["destinatario"])
        vigente = complemento_vigente(carregar_eventos(self.dir)).set_index("emenda_numero")
        self.assertTrue(pd.isna(vigente.loc["E1", "objeto"]))
        self.assertEqual(vigente.loc["E2", "objeto"], "Só o objeto")

    def test_limites_de_tamanho_e_responsavel(self) -> None:
        with self.assertRaises(ErroAcompanhamento):
            self.complemento(objeto="x" * 501)
        with self.assertRaises(ErroAcompanhamento):
            self.complemento(destinatario="x" * 201)
        self.assertEqual(len(self.complemento(objeto="x" * 500, destinatario="y" * 200)["objeto"]), 500)
        with self.assertRaises(ErroAcompanhamento):
            self.complemento(chave=E2, responsavel="")

    def test_sem_alteracao_e_recusada_e_chave_inexistente_tambem(self) -> None:
        self.complemento()
        with self.assertRaises(ErroAcompanhamento):
            self.complemento()  # igual ao vigente: nada mudou
        with self.assertRaises(ErroAcompanhamento):
            self.complemento(chave=(2026, "6", "NAO"))

    def test_limpar_um_campo_e_uma_alteracao_valida(self) -> None:
        self.complemento()
        time.sleep(0.01)
        self.complemento(destinatario=None)
        vigente = complemento_vigente(carregar_eventos(self.dir)).iloc[0]
        self.assertEqual(vigente["objeto"], "Aquisição de equipamentos")
        self.assertTrue(pd.isna(vigente["destinatario"]))


class TestOrfaosEIntegridade(_Base):
    def test_orfaos_listados_quando_a_chave_some(self) -> None:
        self.status(chave=H1)
        self.complemento(chave=H1)
        self.status(chave=E1)
        eventos = carregar_eventos(self.dir)
        sem_h1 = orfaos(eventos, {E1, E2})
        self.assertEqual({o["emenda_numero"] for o in sem_h1}, {"H1"})
        self.assertEqual(len(sem_h1), 2)  # status e complemento: nada é descartado
        self.assertEqual(orfaos(eventos, VALIDAS), [])

    def test_arquivo_ilegivel_ou_incompleto_levanta_erro_nunca_vira_sem_historico(self) -> None:
        evento = self.status()
        caminho = self.dir / f"{evento['evento_id']}.json"
        original = json.loads(caminho.read_text(encoding="utf-8"))

        caminho.write_text("{ isto nao e json", encoding="utf-8")
        with self.assertRaises(ErroAcompanhamento):
            carregar_eventos(self.dir)
        for campo, valor in (("acao", "inventada"), ("versao_schema", 99), ("responsavel", ""), ("data_status", "xx"), ("status", "Inventado")):
            with self.subTest(campo=campo):
                caminho.write_text(json.dumps({**original, campo: valor}), encoding="utf-8")
                with self.assertRaises(ErroAcompanhamento):
                    carregar_eventos(self.dir)
        caminho.write_text(json.dumps({k: v for k, v in original.items() if k != "data_status"}), encoding="utf-8")
        with self.assertRaises(ErroAcompanhamento):
            carregar_eventos(self.dir)

    def test_cancelamento_de_evento_que_nao_existe_no_log_e_incoerencia(self) -> None:
        evento = self.status()
        cancelar_status(evento_id=evento["evento_id"], motivo=MOTIVO, responsavel="J", diretorio=self.dir)
        (self.dir / f"{evento['evento_id']}.json").unlink()
        with self.assertRaises(ErroAcompanhamento):
            carregar_eventos(self.dir)

    def test_sem_diretorio_devolve_lista_vazia(self) -> None:
        self.assertEqual(carregar_eventos(self.dir), [])


if __name__ == "__main__":
    unittest.main()
