"""Decisão registrada sobre divergência de dotação de Emendas (10/2026).

Nenhum teste escreve em `data/`: o diretório de eventos é sempre um diretório temporário. O caso do usuário
é o da emenda `E1`: relatório R$ 300.000,00 × Dotação Anual R$ 600.000,00 no mesmo PTRES (única emenda dele).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.ajustes_dotacao_emendas import (
    DECISOES,
    ErroAjusteDotacao,
    carregar_eventos,
    desfazer_decisao,
    ptres_com_uma_emenda,
    reconstruir_decisoes,
    registrar_decisao,
)

JUSTIFICATIVA = "Dotação ampliada conforme a Dotação Anual de 2026."


def _vinculos() -> pd.DataFrame:
    """Vínculos (emenda × PTRES) como saem de `vincular_execucao_emendas(..., dotacao=...)`."""

    linhas = [
        # E1/P1: o caso real — relatório 300 mil, Dotação Anual 600 mil, PTRES só dela
        {"ano": 2026, "resultado_primario_cod": "6", "emenda_numero": "E1", "ptres": "P1",
         "dotacao_atualizada": 300000.0, "dotacao_anual_ptres": 600000.0},
        {"ano": 2026, "resultado_primario_cod": "6", "emenda_numero": "E2", "ptres": "P2",
         "dotacao_atualizada": 100000.0, "dotacao_anual_ptres": 100000.0},
        # P3 é compartilhado por duas emendas (a Dotação Anual é do PTRES inteiro)
        {"ano": 2026, "resultado_primario_cod": "6", "emenda_numero": "E3", "ptres": "P3",
         "dotacao_atualizada": 200000.0, "dotacao_anual_ptres": 500000.0},
        {"ano": 2026, "resultado_primario_cod": "6", "emenda_numero": "E4", "ptres": "P3",
         "dotacao_atualizada": 300000.0, "dotacao_anual_ptres": 500000.0},
        # histórico: sem política de decisão
        {"ano": 2025, "resultado_primario_cod": "6", "emenda_numero": "H1", "ptres": "PH",
         "dotacao_atualizada": 50000.0, "dotacao_anual_ptres": pd.NA},
    ]
    return pd.DataFrame(linhas).astype({"dotacao_anual_ptres": "Float64"})


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "ajustes"
        self.vinculos = _vinculos()

    def registrar(self, emenda="E1", ptres="P1", decisao="adotar_dotacao_anual", valor=None, **extra):
        parametros = dict(
            vinculos=self.vinculos, ano=2026, resultado_primario_cod="6", emenda_numero=emenda, ptres=ptres,
            decisao=decisao, valor_informado=valor, justificativa=JUSTIFICATIVA, responsavel="Maria",
            diretorio=self.dir,
        )
        parametros.update(extra)
        return registrar_decisao(**parametros)


class TestRegistrarDecisao(_Base):
    def test_adotar_dotacao_anual_grava_evento_com_os_valores_da_decisao(self) -> None:
        evento = self.registrar()
        self.assertEqual(evento["valor_relatorio"], 300000.0)
        self.assertEqual(evento["valor_dotacao_anual"], 600000.0)
        self.assertEqual(evento["valor_efetivo"], 600000.0)
        arquivos = list(self.dir.glob("*.json"))
        self.assertEqual([a.stem for a in arquivos], [evento["evento_id"]])
        decisoes = reconstruir_decisoes(carregar_eventos(self.dir))
        self.assertEqual(len(decisoes), 1)
        self.assertFalse(decisoes[0]["desfeita"])
        self.assertEqual(decisoes[0]["responsavel"], "Maria")

    def test_manter_relatorio_tem_valor_efetivo_igual_ao_do_relatorio(self) -> None:
        evento = self.registrar(decisao="manter_relatorio")
        self.assertEqual(evento["valor_efetivo"], 300000.0)

    def test_valor_informado_aceita_zero_e_recusa_vazio_e_negativo(self) -> None:
        self.assertEqual(self.registrar(decisao="valor_informado", valor=0.0)["valor_efetivo"], 0.0)
        for invalido in (None, -1.0, float("nan")):
            with self.subTest(valor=invalido), self.assertRaises(ErroAjusteDotacao):
                self.registrar(emenda="E2", ptres="P2", decisao="valor_informado", valor=invalido)

    def test_recusa_exercicio_anterior_a_2026(self) -> None:
        with self.assertRaises(ErroAjusteDotacao):
            self.registrar(emenda="H1", ptres="PH", ano=2025, decisao="manter_relatorio")

    def test_recusa_chave_inexistente_e_decisao_invalida(self) -> None:
        with self.assertRaises(ErroAjusteDotacao):
            self.registrar(emenda="NAO", ptres="NAO")
        with self.assertRaises(ErroAjusteDotacao):
            self.registrar(decisao="inventada")
        self.assertEqual(set(DECISOES), {"adotar_dotacao_anual", "manter_relatorio", "valor_informado"})

    def test_adotar_recusada_quando_o_ptres_tem_mais_de_uma_emenda(self) -> None:
        with self.assertRaises(ErroAjusteDotacao):
            self.registrar(emenda="E3", ptres="P3", decisao="adotar_dotacao_anual")

    def test_manter_e_valor_informado_continuam_permitidos_no_ptres_compartilhado(self) -> None:
        self.assertEqual(self.registrar(emenda="E3", ptres="P3", decisao="manter_relatorio")["valor_efetivo"], 200000.0)
        self.assertEqual(
            self.registrar(emenda="E4", ptres="P3", decisao="valor_informado", valor=250000.0)["valor_efetivo"], 250000.0
        )

    def test_recusa_justificativa_curta_e_responsavel_vazio(self) -> None:
        for justificativa in ("curta", "   ", "", None):
            with self.subTest(justificativa=justificativa), self.assertRaises(ErroAjusteDotacao):
                self.registrar(justificativa=justificativa)
        for responsavel in ("", "   ", None):
            with self.subTest(responsavel=responsavel), self.assertRaises(ErroAjusteDotacao):
                self.registrar(responsavel=responsavel)
        self.assertFalse(self.dir.exists() and list(self.dir.glob("*.json")))  # nada foi gravado

    def test_adotar_exige_dotacao_anual_conhecida(self) -> None:
        sem_anual = self.vinculos.copy()
        sem_anual["dotacao_anual_ptres"] = pd.array([pd.NA] * len(sem_anual), dtype="Float64")
        with self.assertRaises(ErroAjusteDotacao):
            self.registrar(vinculos=sem_anual)

    def test_uma_decisao_ativa_por_chave(self) -> None:
        self.registrar()
        with self.assertRaises(ErroAjusteDotacao):
            self.registrar(decisao="manter_relatorio")

    def test_valor_original_vem_de_dotacao_relatorio_quando_a_coluna_existe(self) -> None:
        efetivos = self.vinculos.copy()
        efetivos["dotacao_relatorio"] = efetivos["dotacao_atualizada"]
        efetivos.loc[efetivos["emenda_numero"] == "E1", "dotacao_atualizada"] = 600000.0  # já com uma decisão aplicada
        evento = self.registrar(vinculos=efetivos, decisao="manter_relatorio")
        self.assertEqual(evento["valor_relatorio"], 300000.0)


class TestDesfazerDecisao(_Base):
    def test_desfazer_acrescenta_evento_e_nao_apaga_o_original(self) -> None:
        evento = self.registrar()
        original = (self.dir / f"{evento['evento_id']}.json").read_text(encoding="utf-8")
        desfazer = desfazer_decisao(
            decisao_id=evento["decisao_id"], justificativa="Lançamento equivocado, voltando ao relatório.",
            responsavel="João", diretorio=self.dir,
        )
        self.assertEqual(len(list(self.dir.glob("*.json"))), 2)
        self.assertEqual((self.dir / f"{evento['evento_id']}.json").read_text(encoding="utf-8"), original)
        decisao = reconstruir_decisoes(carregar_eventos(self.dir))[0]
        self.assertTrue(decisao["desfeita"])
        self.assertEqual(decisao["desfeita_por"], "João")
        self.assertIn("equivocado", decisao["desfeita_motivo"])
        self.assertEqual(desfazer["acao"], "desfazer")

    def test_depois_de_desfazer_pode_decidir_de_novo(self) -> None:
        evento = self.registrar()
        desfazer_decisao(decisao_id=evento["decisao_id"], justificativa=JUSTIFICATIVA, responsavel="J", diretorio=self.dir)
        self.registrar(decisao="manter_relatorio")
        ativas = [d for d in reconstruir_decisoes(carregar_eventos(self.dir)) if not d["desfeita"]]
        self.assertEqual([d["decisao"] for d in ativas], ["manter_relatorio"])

    def test_desfazer_duas_vezes_e_id_inexistente_levantam_erro(self) -> None:
        evento = self.registrar()
        desfazer_decisao(decisao_id=evento["decisao_id"], justificativa=JUSTIFICATIVA, responsavel="J", diretorio=self.dir)
        with self.assertRaises(ErroAjusteDotacao):
            desfazer_decisao(decisao_id=evento["decisao_id"], justificativa=JUSTIFICATIVA, responsavel="J", diretorio=self.dir)
        with self.assertRaises(ErroAjusteDotacao):
            desfazer_decisao(decisao_id="nao-existe", justificativa=JUSTIFICATIVA, responsavel="J", diretorio=self.dir)

    def test_desfazer_exige_justificativa_e_responsavel(self) -> None:
        evento = self.registrar()
        with self.assertRaises(ErroAjusteDotacao):
            desfazer_decisao(decisao_id=evento["decisao_id"], justificativa="curta", responsavel="J", diretorio=self.dir)
        with self.assertRaises(ErroAjusteDotacao):
            desfazer_decisao(decisao_id=evento["decisao_id"], justificativa=JUSTIFICATIVA, responsavel=" ", diretorio=self.dir)


class TestCarregarEventos(_Base):
    def test_sem_diretorio_devolve_lista_vazia(self) -> None:
        self.assertEqual(carregar_eventos(self.dir), [])

    def test_arquivo_ilegivel_ou_incompleto_levanta_erro_nunca_vira_sem_decisoes(self) -> None:
        evento = self.registrar()
        caminho = self.dir / f"{evento['evento_id']}.json"
        original = json.loads(caminho.read_text(encoding="utf-8"))

        caminho.write_text("{ isto nao e json", encoding="utf-8")
        with self.assertRaises(ErroAjusteDotacao):
            carregar_eventos(self.dir)

        for campo, valor in (("decisao", "inventada"), ("versao_schema", 99), ("responsavel", "")):
            quebrado = {**original, campo: valor}
            caminho.write_text(json.dumps(quebrado), encoding="utf-8")
            with self.subTest(campo=campo), self.assertRaises(ErroAjusteDotacao):
                carregar_eventos(self.dir)

        faltando = {k: v for k, v in original.items() if k != "valor_efetivo"}
        caminho.write_text(json.dumps(faltando), encoding="utf-8")
        with self.assertRaises(ErroAjusteDotacao):
            carregar_eventos(self.dir)

    def test_desfazer_de_decisao_desconhecida_no_log_e_incoerencia(self) -> None:
        evento = self.registrar()
        desfazer = desfazer_decisao(decisao_id=evento["decisao_id"], justificativa=JUSTIFICATIVA, responsavel="J", diretorio=self.dir)
        (self.dir / f"{evento['evento_id']}.json").unlink()  # histórico incoerente: desfazer sem a decisão
        with self.assertRaises(ErroAjusteDotacao):
            carregar_eventos(self.dir)
        self.assertTrue((self.dir / f"{desfazer['evento_id']}.json").exists())


class TestPtresComUmaEmenda(_Base):
    def test_ptres_com_uma_emenda(self) -> None:
        self.assertTrue(ptres_com_uma_emenda(self.vinculos, 2026, "6", "P1"))
        self.assertFalse(ptres_com_uma_emenda(self.vinculos, 2026, "6", "P3"))
        self.assertFalse(ptres_com_uma_emenda(self.vinculos, 2026, "6", "NAO"))  # inexistente


if __name__ == "__main__":
    unittest.main()
