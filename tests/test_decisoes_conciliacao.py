"""Testes de `src/decisoes_conciliacao.py` — confirmar ou rejeitar sugestões de conciliação (11/10/2026).

Persistência em pasta temporária. Padrão dos eventos de `src/ajustes_dotacao_emendas.py`: um arquivo por ação,
imutável, desfazer acrescenta um evento novo.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.decisoes_conciliacao import (
    ErroDecisao,
    aplicar_decisao,
    assinatura_mes,
    carregar_eventos,
    desfazer_decisao,
    reconstruir_decisoes,
    registrar_decisao,
)
from src.pendencias_conciliacao import calcular_pendencias, consolidar_exercicio

NE_A, NE_B = "2025NE000604", "2026NE000100"


def _registrar(diretorio, **extra):
    base = dict(
        contrato="23/2025", ano_mes=202601, classe="deslocamento", assinatura="sig1", decisao="confirmada",
        justificativa="Competência trocada no gov; conferido com o SIAFI.", responsavel="Maria", diretorio=diretorio,
    )
    base.update(extra)
    return registrar_decisao(**base)


class RegistroTests(unittest.TestCase):
    def test_registra_um_arquivo_por_decisao_e_reconstroi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evento = _registrar(Path(tmp))
            self.assertEqual(len(list(Path(tmp).glob("*.json"))), 1)
            decisoes = reconstruir_decisoes(carregar_eventos(Path(tmp)))
            d = decisoes[("23/2025", 202601)]
            self.assertEqual((d.decisao, d.assinatura, d.responsavel, d.id), ("confirmada", "sig1", "Maria", evento["id"]))

    def test_justificativa_curta_responsavel_vazio_e_decisao_invalida_sao_recusados(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for extra in ({"justificativa": "curta"}, {"responsavel": "  "}, {"decisao": "talvez"}, {"classe": "batem"}):
                with self.assertRaises(ErroDecisao):
                    _registrar(Path(tmp), **extra)
            self.assertEqual(list(Path(tmp).glob("*.json")), [])  # nada gravado

    def test_ambiguo_so_pode_ser_rejeitado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ErroDecisao):
                _registrar(Path(tmp), classe="ambiguo", decisao="confirmada")  # qual nota? o sistema não escolhe
            _registrar(Path(tmp), classe="ambiguo", decisao="rejeitada")

    def test_nova_decisao_substitui_a_anterior_e_o_historico_fica(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _registrar(Path(tmp), decisao="rejeitada")
            _registrar(Path(tmp), decisao="confirmada")
            self.assertEqual(len(carregar_eventos(Path(tmp))), 2)
            self.assertEqual(reconstruir_decisoes(carregar_eventos(Path(tmp)))[("23/2025", 202601)].decisao, "confirmada")

    def test_desfazer_acrescenta_evento_e_remove_o_efeito(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evento = _registrar(Path(tmp))
            desfazer_decisao(decisao_id=evento["id"], motivo="Registrada por engano.", responsavel="João", diretorio=Path(tmp))
            self.assertEqual(len(carregar_eventos(Path(tmp))), 2)  # o original continua
            self.assertEqual(reconstruir_decisoes(carregar_eventos(Path(tmp))), {})
            with self.assertRaises(ErroDecisao):
                desfazer_decisao(decisao_id="inexistente", motivo="Registrada por engano.", responsavel="João", diretorio=Path(tmp))

    def test_arquivo_ilegivel_levanta_erro_e_nao_e_ignorado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "quebrado.json").write_text("{ nao e json", encoding="utf-8")
            with self.assertRaises(ErroDecisao):
                carregar_eventos(Path(tmp))

    def test_sem_pasta_nao_ha_eventos(self) -> None:
        self.assertEqual(carregar_eventos(Path(tempfile.gettempdir()) / "pasta-que-nao-existe-xyz"), [])


class AplicacaoTests(unittest.TestCase):
    def test_assinatura_muda_quando_os_dados_mudam(self) -> None:
        a = assinatura_mes("deslocamento", ["NE1"], ["A", "B"], 100.0, 50.0)
        self.assertEqual(a, assinatura_mes("deslocamento", ["NE1"], ["B", "A"], 100.0, 50.0))  # ordem não importa
        self.assertNotEqual(a, assinatura_mes("deslocamento", ["NE1"], ["A", "B"], 120.0, 50.0))
        self.assertNotEqual(a, assinatura_mes("cancelamento", ["NE1"], ["A", "B"], 100.0, 50.0))
        self.assertNotEqual(a, assinatura_mes("deslocamento", ["NE1"], ["A", "B"], None, 50.0))  # nulo ≠ valor

    def test_confirmada_resolve_rejeitada_continua_pendente_e_obsoleta_e_ignorada(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _registrar(Path(tmp), decisao="confirmada", assinatura="sigA")
            d = reconstruir_decisoes(carregar_eventos(Path(tmp)))[("23/2025", 202601)]
            self.assertEqual(aplicar_decisao("deslocamento", d, "sigA"), "confirmada")
            self.assertEqual(aplicar_decisao("deslocamento", d, "sigDIFERENTE"), "deslocamento")  # dado mudou: decisão obsoleta
            self.assertEqual(aplicar_decisao("batem", d, "sigA"), "batem")  # só sugestões recebem decisão
            _registrar(Path(tmp), decisao="rejeitada", assinatura="sigA")
            r = reconstruir_decisoes(carregar_eventos(Path(tmp)))[("23/2025", 202601)]
            self.assertEqual(aplicar_decisao("deslocamento", r, "sigA"), "rejeitada")
            self.assertEqual(aplicar_decisao("sem_explicacao", None, "x"), "sem_explicacao")


def _nota(fid, numero, valor, ne, ano, mes) -> dict:
    return {
        "contrato_id": "1", "fatura_id": fid, "numero": numero, "valor": Decimal(str(valor)), "data_liquidacao": date(2026, 2, 1),
        "empenhos": ((ne, None, Decimal(str(valor))),), "referencias": ((ano, mes, Decimal(str(valor))),),
    }


def _empenhos() -> pd.DataFrame:
    return pd.DataFrame({
        "contrato_id": ["1", "1"], "ne": [NE_A, NE_B], "plano_interno": ["M20RKG01SCN - X", "M20RKG01SCN - X"],
        "natureza_despesa": ["339037 - X", "339037 - X"],
    })


class EfeitoNasVisoesTests(unittest.TestCase):
    """A decisão confirmada tira o mês das pendências (alerta, relatório, matriz); a rejeitada mantém."""

    def setUp(self) -> None:
        self.faturas = pd.DataFrame([_nota("1", "A", 8680.0, NE_A, 2026, 1)])
        self.relatorio = pd.DataFrame(
            [(NE_A, 202512, 8680.0), (NE_B, 202601, 2560.24)], columns=["ne_curta", "ano_mes", "valor"]
        )
        self.contratos = [("23/2025", "1", NE_B)]

    def _assinatura_jan(self) -> str:
        meses = consolidar_exercicio(self.contratos, self.faturas, _empenhos(), self.relatorio, 2026)[0]["meses"]
        return meses[0]["assinatura"]

    def test_sem_decisao_e_pendencia(self) -> None:
        self.assertIn((202601, "deslocamento"), calcular_pendencias(self.contratos, self.faturas, _empenhos(), self.relatorio)["23/2025"])

    def test_confirmada_remove_o_mes_das_pendencias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _registrar(Path(tmp), assinatura=self._assinatura_jan())
            decisoes = reconstruir_decisoes(carregar_eventos(Path(tmp)))
            pend = calcular_pendencias(self.contratos, self.faturas, _empenhos(), self.relatorio, decisoes)["23/2025"]
            self.assertNotIn((202601, "deslocamento"), pend)
            self.assertNotIn((202601, "confirmada"), pend)  # resolvida
            linha = consolidar_exercicio(self.contratos, self.faturas, _empenhos(), self.relatorio, 2026, decisoes)[0]
            self.assertEqual(linha["meses"][0]["classe"], "confirmada")

    def test_rejeitada_continua_pendente_com_a_classe_rejeitada(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _registrar(Path(tmp), decisao="rejeitada", assinatura=self._assinatura_jan())
            decisoes = reconstruir_decisoes(carregar_eventos(Path(tmp)))
            pend = calcular_pendencias(self.contratos, self.faturas, _empenhos(), self.relatorio, decisoes)["23/2025"]
            self.assertIn((202601, "rejeitada"), pend)

    def test_decisao_obsoleta_e_ignorada(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _registrar(Path(tmp), assinatura="assinatura-de-outros-dados")
            decisoes = reconstruir_decisoes(carregar_eventos(Path(tmp)))
            pend = calcular_pendencias(self.contratos, self.faturas, _empenhos(), self.relatorio, decisoes)["23/2025"]
            self.assertIn((202601, "deslocamento"), pend)


if __name__ == "__main__":
    unittest.main()
