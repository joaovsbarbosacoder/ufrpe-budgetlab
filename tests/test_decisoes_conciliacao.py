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

import src.decisoes_conciliacao as dc_mod
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


class NotaEscolhidaNoAmbiguoTests(unittest.TestCase):
    """Sem poder corrigir no Contratos.gov, o usuário indica QUAL nota é a cancelada; o sistema só registra a escolha."""

    ESCOLHA = [("2798", NE_B, 1250.0)]

    def test_ambiguo_confirmado_exige_a_nota_escolhida(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ErroDecisao):
                _registrar(Path(tmp), classe="ambiguo", decisao="confirmada")  # sem escolha: continua recusado
            self.assertEqual(list(Path(tmp).glob("*.json")), [])
            _registrar(Path(tmp), classe="ambiguo", decisao="confirmada", notas_desconsideradas=self.ESCOLHA)
            d = reconstruir_decisoes(carregar_eventos(Path(tmp)))[("23/2025", 202601)]
            self.assertEqual(d.decisao, "confirmada")
            self.assertEqual(d.notas_desconsideradas, (("2798", NE_B, 1250.0),))

    def test_nota_escolhida_so_vale_no_ambiguo_confirmado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for extra in ({"classe": "deslocamento"}, {"classe": "ambiguo", "decisao": "rejeitada"}):
                with self.assertRaises(ErroDecisao):
                    _registrar(Path(tmp), notas_desconsideradas=self.ESCOLHA, **extra)

    def test_sem_escolha_a_decisao_vem_com_tupla_vazia(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _registrar(Path(tmp))
            self.assertEqual(reconstruir_decisoes(carregar_eventos(Path(tmp)))[("23/2025", 202601)].notas_desconsideradas, ())

    def test_evento_antigo_sem_o_campo_continua_legivel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evento = _registrar(Path(tmp))
            arquivo = next(Path(tmp).glob("*.json"))
            bruto = json.loads(arquivo.read_text(encoding="utf-8"))
            bruto.pop("notas_desconsideradas", None)
            arquivo.write_text(json.dumps(bruto), encoding="utf-8")
            self.assertEqual(reconstruir_decisoes(carregar_eventos(Path(tmp)))[("23/2025", 202601)].id, evento["id"])


class CallbackDaTelaTests(unittest.TestCase):
    """O seletor de nota cancelada da tela vira `notas_desconsideradas` — sem Streamlit, com session_state simulado."""

    def _mes_ambiguo(self):
        from src.conciliacao_competencia_gov import ItemNota, MesConciliado, ajustar_mes
        itens = [ItemNota(NE_B, 1310.24, "2783", False, False, None), ItemNota(NE_B, 1250.0, "2783", False, False, None),
                 ItemNota(NE_B, 1250.0, "2798", False, False, None)]
        mes = MesConciliado(2026, 5, 3810.24, {NE_B: 2560.24}, 2560.24, itens)
        return mes, ajustar_mes(mes)

    def test_alternativas_do_mes_ambiguo(self) -> None:
        from src.ui_conciliacao_competencia import _alternativas_do_mes
        mes, ajuste = self._mes_ambiguo()
        self.assertEqual(ajuste.situacao, "ambiguo")
        (ne, combos), = _alternativas_do_mes(mes, ajuste)
        self.assertEqual(ne, NE_B)
        self.assertEqual(sorted(combos), [(("2783", NE_B, 1250.0),), (("2798", NE_B, 1250.0),)])
        self.assertEqual(_alternativas_do_mes(mes, None), [])

    def test_confirmar_grava_a_nota_escolhida_e_rejeitar_nao_grava_escolha(self) -> None:
        from unittest import mock
        import src.ui_conciliacao_competencia as ui
        mes, ajuste = self._mes_ambiguo()
        alternativas = [c for _ne, c in ui._alternativas_do_mes(mes, ajuste)]
        ordenadas = sorted(alternativas[0])  # a ordem das combinações não importa: escolho a da nota 2798 pelo índice
        indice_2798 = alternativas[0].index((("2798", NE_B, 1250.0),))
        with tempfile.TemporaryDirectory() as tmp:
            estado = {"p_resp": "Maria", "p_just": "Nota 2798 é repetição da 2783.", "p_alt_0": indice_2798}
            falso = mock.Mock(session_state=estado)
            with mock.patch.object(ui, "st", falso), mock.patch.object(dc_mod, "DIRETORIO_DECISOES", Path(tmp)):
                ui._cb_registrar("p", "23/2025", 202605, "ambiguo", "sig", "confirmada", alternativas)
                self.assertEqual(estado["p_msg"], "")
                d = reconstruir_decisoes(carregar_eventos(Path(tmp)))[("23/2025", 202605)]
                self.assertEqual(d.notas_desconsideradas, (("2798", NE_B, 1250.0),))
                ui._cb_registrar("p", "23/2025", 202605, "ambiguo", "sig", "rejeitada", alternativas)
                d = reconstruir_decisoes(carregar_eventos(Path(tmp)))[("23/2025", 202605)]
                self.assertEqual((d.decisao, d.notas_desconsideradas), ("rejeitada", ()))
        self.assertEqual(len(ordenadas), 2)


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


class ConsolidadaAjustadaPorDecisaoTests(unittest.TestCase):
    """Decisão confirmada com nota indicada: o valor das notas na visão consolidada desconta a nota cancelada."""

    def setUp(self) -> None:
        self.faturas = pd.DataFrame([
            _nota("1", "A", 1310.24, NE_B, 2026, 1), _nota("2", "B", 1250.0, NE_B, 2026, 1), _nota("3", "C", 1250.0, NE_B, 2026, 1),
        ])
        self.relatorio = pd.DataFrame([(NE_B, 202601, 2560.24)], columns=["ne_curta", "ano_mes", "valor"])
        self.contratos = [("23/2025", "1", NE_B)]

    def _linha(self, decisoes=None):
        return consolidar_exercicio(self.contratos, self.faturas, _empenhos(), self.relatorio, 2026, decisoes)[0]

    def _decidir(self, tmp, **extra):
        assinatura = self._linha()["meses"][0]["assinatura"]
        _registrar(Path(tmp), classe="ambiguo", assinatura=assinatura, **extra)
        return reconstruir_decisoes(carregar_eventos(Path(tmp)))

    def test_sem_decisao_o_mes_e_ambiguo_e_as_notas_ficam_brutas(self) -> None:
        mes = self._linha()["meses"][0]
        self.assertEqual((mes["classe"], mes["notas"], mes["notas_ajustadas"]), ("ambiguo", 3810.24, None))

    def test_confirmado_com_nota_indicada_desconta_so_o_valor_da_nota_escolhida(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            decisoes = self._decidir(tmp, decisao="confirmada", notas_desconsideradas=[("C", NE_B, 1250.0)])
            linha = self._linha(decisoes)
            mes = linha["meses"][0]
            self.assertEqual((mes["classe"], mes["notas"], mes["notas_ajustadas"]), ("confirmada", 3810.24, 2560.24))
            self.assertEqual(linha["total_notas"], 3810.24)         # bruto continua acessível
            self.assertEqual(linha["total_notas_ajustado"], 2560.24)  # e o ajustado fecha com o relatório

    def test_rejeitada_nao_ajusta_nada(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mes = self._linha(self._decidir(tmp, decisao="rejeitada"))["meses"][0]
            self.assertEqual((mes["classe"], mes["notas_ajustadas"]), ("rejeitada", None))

    def test_html_mostra_o_valor_ajustado_com_marca(self) -> None:
        from src.ui_conciliacao_competencia import html_consolidada
        with tempfile.TemporaryDirectory() as tmp:
            decisoes = self._decidir(tmp, decisao="confirmada", notas_desconsideradas=[("C", NE_B, 1250.0)])
            html = html_consolidada([{**self._linha(decisoes), "ano": 2026}])
            self.assertIn("ajustado por decisão", html)
        html_sem = html_consolidada([{**self._linha(), "ano": 2026}])
        self.assertNotIn("ajustado por decisão", html_sem)


class MarcaVisualDaDecisaoTests(unittest.TestCase):
    """O mês decidido muda no layout: confirmada vira "conciliado por decisão"; rejeitada mantém a diferença e avisa."""

    def _mes(self):
        from src.conciliacao_competencia_gov import MesConciliado
        return MesConciliado(2026, 1, 11240.24, {NE_B: 2560.24}, 2560.24, [])

    def _decisao(self, decisao):
        from src.decisoes_conciliacao import Decisao
        return Decisao("id1", "23/2025", 202601, "deslocamento", "sig", decisao, "Conferido com o SIAFI.", "Maria", "2026-10-12T09:30:15.123456")

    def test_sem_decisao_nada_muda(self) -> None:
        from src.ui_conciliacao_competencia import html_mes
        html = html_mes(self._mes())
        self.assertIn("diferença", html)
        self.assertNotIn("conciliado por decisão", html)
        self.assertNotIn("cmp-conf", html)

    def test_confirmada_troca_a_diferenca_e_mostra_quem_decidiu(self) -> None:
        from src.ui_conciliacao_competencia import html_mes
        html = html_mes(self._mes(), decisao=self._decisao("confirmada"))
        self.assertIn("conciliado por decisão", html)
        self.assertNotIn('class="cmp-dif"', html)
        self.assertIn("cmp-conf", html)
        self.assertIn("Maria", html)
        self.assertIn("2026-10-12 09:30", html)
        self.assertIn("Conferido com o SIAFI.", html)

    def test_ambiguo_confirmado_risca_a_nota_escolhida_e_diz_quem_escolheu(self) -> None:
        from src.conciliacao_competencia_gov import ItemNota, MesConciliado
        from src.decisoes_conciliacao import Decisao
        from src.ui_conciliacao_competencia import html_mes
        itens = [ItemNota(NE_B, 1310.24, "2783", False, False, None), ItemNota(NE_B, 1250.0, "2783", False, False, None),
                 ItemNota(NE_B, 1250.0, "2798", False, False, None)]
        mes = MesConciliado(2026, 5, 3810.24, {NE_B: 2560.24}, 2560.24, itens)
        d = Decisao("i", "23/2025", 202605, "ambiguo", "sig", "confirmada", "Nota 2798 é repetição.", "Maria",
                    "2026-10-12T10:00:00", (("2798", NE_B, 1250.0),))
        html = html_mes(mes, decisao=d)
        self.assertIn("desconsiderando 1 nota(s) por decisão", html)
        self.assertIn("cmp-risco", html)
        self.assertEqual(html.count("cmp-risco"), 1)  # só a nota 2798; a 2783 de mesmo valor NÃO é riscada
        self.assertNotIn('class="cmp-dif"', html)

    def test_rejeitada_mantem_a_diferenca_e_avisa(self) -> None:
        from src.ui_conciliacao_competencia import html_mes
        html = html_mes(self._mes(), decisao=self._decisao("rejeitada"))
        self.assertIn('class="cmp-dif"', html)
        self.assertNotIn("conciliado por decisão", html)
        self.assertIn("cmp-rej", html)
        self.assertIn("rejeitada", html)


if __name__ == "__main__":
    unittest.main()
