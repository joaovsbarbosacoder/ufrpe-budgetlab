"""Testes de `src/conciliacao_competencia_gov.py` — relatório de competência × notas do Contratos.gov (11/10/2026).

Valores calculados à mão. Sem rede nem leitura de arquivo.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

import pandas as pd

from src.conciliacao_competencia_gov import (
    conciliar_exercicio,
    empenhos_do_contrato,
    exercicios_disponiveis,
    CLASSES,
    Causa,
    ajustar_mes,
    causas_do_mes,
    classificar_mes,
    totais_por_ne,
    construir_contexto,
    filtrar_mes,
    itens_das_notas,
    naturezas_20rk,
    nes_do_mes,
    padrao_do_mes,
)

DEA = "339092 - DESPESAS DE EXERCICIOS ANTERIORES"
SERV = "339037 - LOCACAO DE MAO-DE-OBRA"


def _empenhos() -> pd.DataFrame:
    return pd.DataFrame({
        "contrato_id": ["1", "1", "1", "2"],
        "ne": ["2026NE000001", "2026NE000002", "2026NE000003", "2026NE000009"],
        "plano_interno": ["M20RKG01SCN - GESTAO", "M20RKG01SCN - GESTAO", "L20RLP01SCN - TI", "M20RKG01SCN - X"],
        "natureza_despesa": [SERV, DEA, SERV, SERV],
    })


def _nota(fid, numero, valor, empenhos, referencias, liquidacao=date(2026, 9, 3)) -> dict:
    return {
        "fatura_id": fid, "numero": numero, "valor": Decimal(str(valor)), "data_liquidacao": liquidacao,
        "empenhos": tuple((ne, None, Decimal(str(v))) for ne, v in empenhos),
        "referencias": tuple((a, m, Decimal(str(v))) for a, m, v in referencias),
    }


def _faturas(*notas) -> pd.DataFrame:
    return pd.DataFrame(list(notas))


def _relatorio(*linhas) -> pd.DataFrame:
    return pd.DataFrame(linhas, columns=["ne_curta", "ano_mes", "valor"])


class NaturezasTests(unittest.TestCase):
    def test_so_nes_da_20rk_do_contrato(self) -> None:
        self.assertEqual(
            naturezas_20rk(_empenhos(), "1"), {"2026NE000001": SERV, "2026NE000002": DEA},
        )  # 2026NE000003 é de outro plano interno; 2026NE000009 é de outro contrato

    def test_ne_do_cadastro_entra_mesmo_sem_par_no_gov(self) -> None:
        resultado = naturezas_20rk(_empenhos(), "1", ne_cadastro="2026NE000777", natureza_cadastro=None)
        self.assertIn("2026NE000777", resultado)
        self.assertIsNone(resultado["2026NE000777"])
        self.assertEqual(naturezas_20rk(None, None, "2026NE000777"), {"2026NE000777": None})


class ItensTests(unittest.TestCase):
    def setUp(self) -> None:
        self.nat = {"2026NE000001": SERV, "2026NE000002": DEA}

    def test_nota_simples_vai_para_a_competencia_de_referencia(self) -> None:
        itens, fora = itens_das_notas(_faturas(_nota("1", "100", 1000, [("2026NE000001", 1000)], [(2026, 5, 1000)])), self.nat)
        self.assertEqual((fora, len(itens)), (0, 1))
        self.assertEqual(itens.iloc[0][["ne", "ano", "mes", "valor", "rateada"]].tolist(), ["2026NE000001", 2026, 5, 1000.0, False])

    def test_nota_nao_liquidada_ou_de_ne_fora_do_recorte_nao_entra(self) -> None:
        sem_liquidacao = _nota("1", "100", 1000, [("2026NE000001", 1000)], [(2026, 5, 1000)], liquidacao=None)
        de_outra_acao = _nota("2", "200", 500, [("2026NE000003", 500)], [(2026, 5, 500)])
        itens, fora = itens_das_notas(_faturas(sem_liquidacao, de_outra_acao), self.nat)
        self.assertTrue(itens.empty)
        self.assertEqual(fora, 1)  # a não liquidada nem conta; a de outra ação é contada à parte

    def test_uma_ne_varias_competencias_usa_o_valor_de_cada_competencia(self) -> None:
        nota = _nota("1", "100", 3000, [("2026NE000001", 3000)], [(2026, 3, 1000), (2026, 4, 2000)])
        itens, _ = itens_das_notas(_faturas(nota), self.nat)
        self.assertEqual(sorted(itens["valor"]), [1000.0, 2000.0])
        self.assertFalse(itens["rateada"].any())

    def test_varias_nes_e_varias_competencias_rateia_proporcional_e_marca(self) -> None:
        nota = _nota("1", "100", 3000, [("2026NE000001", 2000), ("2026NE000002", 1000)], [(2026, 3, 1000), (2026, 4, 2000)])
        itens, _ = itens_das_notas(_faturas(nota), self.nat)
        mar = itens[(itens["ne"] == "2026NE000001") & (itens["mes"] == 3)].iloc[0]["valor"]
        self.assertAlmostEqual(mar, 2000 * 1000 / 3000)
        self.assertAlmostEqual(itens["valor"].sum(), 3000.0)
        self.assertTrue(itens["rateada"].all())

    def test_nota_duplicada_e_sinalizada_e_nao_soma(self) -> None:
        a = _nota("1", "100", 1000, [("2026NE000002", 1000)], [(2025, 6, 1000)])
        b = _nota("2", "100", 1000, [("2026NE000002", 1000)], [(2025, 6, 1000)])
        itens, _ = itens_das_notas(_faturas(a, b), self.nat)
        self.assertEqual(itens["duplicada"].tolist(), [False, True])
        mes = conciliar_exercicio(2025, None, itens, self.nat)[5]
        self.assertAlmostEqual(mes.notas, 1000.0)  # a duplicada não soma
        self.assertEqual(len(mes.itens), 2)  # mas aparece, sinalizada


class FiltroPorMesTests(unittest.TestCase):
    """Contrato pago por várias ações: em cada mês, quais NEs ficam em evidência."""

    def setUp(self) -> None:
        self.empenhos = empenhos_do_contrato(_empenhos(), "1")  # 2026NE000001 (20RK), 000002 (20RK/DEA), 000003 (20RL)
        self.nat = {ne: i.natureza for ne, i in self.empenhos.items()}
        notas = _faturas(
            _nota("1", "100", 1000, [("2026NE000001", 1000)], [(2026, 3, 1000)]),
            _nota("2", "200", 300, [("2026NE000003", 300)], [(2026, 3, 300)]),
        )
        self.itens, _ = itens_das_notas(notas, self.nat)
        self.relatorio = _relatorio(("2026NE000001", 202603, 1000.0), ("2026NE000003", 202603, 300.0))
        self.marco = conciliar_exercicio(2026, self.relatorio, self.itens, self.nat)[2]

    def test_empenhos_trazem_acao_e_elemento_de_todas_as_nes_do_contrato(self) -> None:
        self.assertEqual(set(self.empenhos), {"2026NE000001", "2026NE000002", "2026NE000003"})
        self.assertEqual([self.empenhos[n].acao for n in sorted(self.empenhos)], ["20RK", "20RK", "L20RLP01SCN"])
        self.assertEqual(self.empenhos["2026NE000002"].elemento, "92")
        self.assertFalse(self.empenhos["2026NE000003"].da_20rk)

    def test_padrao_do_mes_e_a_20rk_ou_todas_se_nao_houver(self) -> None:
        self.assertEqual(nes_do_mes(self.marco), ["2026NE000001", "2026NE000003"])
        self.assertEqual(padrao_do_mes(self.marco, self.empenhos), ["2026NE000001"])
        so_outra = filtrar_mes(self.marco, ["2026NE000003"])
        self.assertEqual(padrao_do_mes(so_outra, self.empenhos), ["2026NE000003"])  # sem 20RK: todas as presentes

    def test_filtro_recalcula_os_dois_lados_e_mostra_o_que_ficou_fora(self) -> None:
        visto = filtrar_mes(self.marco, ["2026NE000001"])
        self.assertEqual((visto.relatorio, visto.notas, visto.situacao), (1000.0, 1000.0, "batem"))
        self.assertEqual(visto.nes_fora, ("2026NE000003",))
        self.assertEqual((visto.fora_do_filtro_relatorio, visto.fora_do_filtro_notas), (300.0, 300.0))
        todas = filtrar_mes(self.marco, ["2026NE000001", "2026NE000003"])
        self.assertEqual((todas.relatorio, todas.notas, todas.nes_fora), (1300.0, 1300.0, ()))

    def test_selecao_vazia_deixa_tudo_fora_e_sem_registro(self) -> None:
        vazio = filtrar_mes(self.marco, [])
        self.assertEqual((vazio.relatorio, vazio.notas, vazio.situacao), (None, None, "sem_registro"))
        self.assertEqual(vazio.fora_do_filtro_relatorio, 1300.0)

    def test_filtro_nao_conta_duplicada_como_fora(self) -> None:
        notas = _faturas(
            _nota("1", "100", 500, [("2026NE000003", 500)], [(2026, 3, 500)]),
            _nota("2", "100", 500, [("2026NE000003", 500)], [(2026, 3, 500)]),
        )
        itens, _ = itens_das_notas(notas, self.nat)
        mes = conciliar_exercicio(2026, None, itens, self.nat)[2]
        self.assertEqual(filtrar_mes(mes, ["2026NE000001"]).fora_do_filtro_notas, 500.0)  # a duplicada não soma


class ConciliacaoDeDuplicidadesTests(unittest.TestCase):
    """Notas canceladas/substituídas sem aviso no gov: as notas somam MAIS que o relatório."""

    NE = "2026NE000001"

    def _mes(self, notas: list[tuple[str, float]], relatorio: float | None):
        nat = {self.NE: SERV}
        faturas = _faturas(*[
            _nota(str(i), numero, valor, [(self.NE, valor)], [(2026, 3, valor)]) for i, (numero, valor) in enumerate(notas)
        ])
        itens, _ = itens_das_notas(faturas, nat)
        rel = None if relatorio is None else _relatorio((self.NE, 202603, relatorio))
        return conciliar_exercicio(2026, rel, itens, nat)[2]

    def test_combinacao_unica_fecha_o_relatorio_e_sugere_o_cancelamento(self) -> None:
        # modelo real: nota 2600000000005 duas vezes (valores diferentes); o relatório só tem a primeira
        mes = self._mes([("A", 921050.28), ("B", 925624.81)], 921050.28)
        ajuste = ajustar_mes(mes)
        self.assertEqual(ajuste.situacao, "batem_ajustado")
        self.assertEqual([mes.itens[i].nota for i in ajuste.retiradas], ["B"])
        self.assertAlmostEqual(ajuste.notas_ajustadas, 921050.28)
        self.assertAlmostEqual(mes.notas, 1846675.09)  # o valor do gov continua como veio

    def test_menor_combinacao_vence(self) -> None:
        # 463.612,62 + 463.612,61 + 35.482,05 = 962.707,28; relatório 927.225,23 → retirar só a de 35.482,05
        mes = self._mes([("3305", 463612.62), ("3305.1", 463612.61), ("3306.1", 35482.05)], 927225.23)
        ajuste = ajustar_mes(mes)
        self.assertEqual([mes.itens[i].nota for i in ajuste.retiradas], ["3306.1"])
        self.assertEqual(ajuste.situacao, "batem_ajustado")

    def test_mais_de_uma_combinacao_e_ambiguo_e_nunca_desempata(self) -> None:
        mes = self._mes([("A", 100.0), ("B", 100.0), ("C", 250.0)], 250.0)  # retirar A ou B? só uma de 100 não fecha 200…
        # excedente = 200: {A,B} é a única de 2 notas → única; teste de ambiguidade abaixo
        self.assertEqual(ajustar_mes(mes).situacao, "batem_ajustado")
        ambiguo = self._mes([("A", 100.0), ("B", 100.0), ("C", 500.0)], 500.0 + 100.0)  # excedente 100: A ou B
        ajuste = ajustar_mes(ambiguo)
        self.assertEqual(ajuste.situacao, "ambiguo")
        self.assertEqual(ajuste.retiradas, ())  # nenhuma retirada
        self.assertEqual(len(ajuste.alternativas[0][1]), 2)

    def test_sem_combinacao_nao_conclui(self) -> None:
        ajuste = ajustar_mes(self._mes([("A", 100.0), ("B", 200.0)], 50.0))
        self.assertEqual((ajuste.situacao, ajuste.retiradas, ajuste.alternativas), ("sem_ajuste", (), ()))

    def test_notas_a_menos_ou_iguais_nao_sao_cancelamento(self) -> None:
        self.assertEqual(ajustar_mes(self._mes([("A", 100.0)], 150.0)).situacao, "sem_ajuste")  # a menos
        self.assertEqual(ajustar_mes(self._mes([("A", 100.0)], 100.0)).retiradas, ())  # já bate
        self.assertEqual(ajustar_mes(self._mes([("A", 100.0)], None)).retiradas, ())  # só notas, sem relatório

    def test_mes_filtrado_so_considera_as_nes_em_evidencia(self) -> None:
        nat = {self.NE: SERV, "2026NE000002": DEA}
        faturas = _faturas(
            _nota("1", "A", 500.0, [(self.NE, 500.0)], [(2026, 3, 500.0)]),
            _nota("2", "B", 300.0, [(self.NE, 300.0)], [(2026, 3, 300.0)]),
            _nota("3", "C", 900.0, [("2026NE000002", 900.0)], [(2026, 3, 900.0)]),
        )
        itens, _ = itens_das_notas(faturas, nat)
        mes = conciliar_exercicio(2026, _relatorio((self.NE, 202603, 500.0), ("2026NE000002", 202603, 900.0)), itens, nat)[2]
        visto = filtrar_mes(mes, [self.NE])
        ajuste = ajustar_mes(visto)
        self.assertEqual([visto.itens[i].nota for i in ajuste.retiradas], ["B"])  # a NE desmarcada nem entra

    def test_nota_duplicada_ja_sinalizada_nao_e_candidata(self) -> None:
        a = _nota("1", "A", 500.0, [(self.NE, 500.0)], [(2026, 3, 500.0)])
        b = _nota("2", "A", 500.0, [(self.NE, 500.0)], [(2026, 3, 500.0)])  # duplicada: mesma nota
        itens, _ = itens_das_notas(_faturas(a, b), {self.NE: SERV})
        mes = conciliar_exercicio(2026, _relatorio((self.NE, 202603, 500.0)), itens, {self.NE: SERV})[2]
        self.assertEqual(ajustar_mes(mes).retiradas, ())  # a duplicada já não soma; nada a retirar


class CausasTests(unittest.TestCase):
    """Motor de causas: nota não liquidada e deslocamento de competência (casos modelados em dados reais)."""

    NE = "2025NE000604"

    def _contexto(self, notas, relatorio, pendentes=()):
        nat = {self.NE: SERV, "2026NE000100": SERV}
        itens, _ = itens_das_notas(_faturas(*[
            _nota(str(i), f"N{i}", v, [(ne, v)], [(a, m, v)]) for i, (ne, a, m, v) in enumerate(notas)
        ]) if notas else None, nat)
        pend, _ = itens_das_notas(_faturas(*[
            _nota(f"p{i}", f"P{i}", v, [(ne, v)], [(a, m, v)], liquidacao=None) for i, (ne, a, m, v) in enumerate(pendentes)
        ]) if pendentes else None, nat, liquidadas=False)
        rel = _relatorio(*[(ne, a * 100 + m, v) for ne, a, m, v in relatorio])
        return construir_contexto(rel, itens, pend, nat)

    def test_caso_real_deslocamento_dez_2025_jan_2026_atravessa_o_ano(self) -> None:
        # notas põem R$ 8.680 em jan/2026 (2.480 + 6.200); o relatório registrou em dez/2025
        ctx = self._contexto(
            notas=[(self.NE, 2026, 1, 2480.0), (self.NE, 2026, 1, 6200.0)],
            relatorio=[(self.NE, 2025, 12, 8680.0), ("2026NE000100", 2026, 1, 2560.24)],
        )
        jan = causas_do_mes(ctx, 2026, 1, [self.NE])
        self.assertEqual([(c.tipo, c.valor, c.par, c.sentido) for c in jan], [("deslocamento", 8680.0, 202512, "notas_aqui")])
        dez = causas_do_mes(ctx, 2025, 12, [self.NE])
        self.assertEqual([(c.tipo, c.valor, c.par, c.sentido) for c in dez], [("deslocamento", 8680.0, 202601, "relatorio_aqui")])

    def test_deslocamento_de_dois_meses(self) -> None:
        ctx = self._contexto(notas=[(self.NE, 2025, 4, 87554.09)], relatorio=[(self.NE, 2025, 2, 87554.09), (self.NE, 2025, 3, 5.0)])
        self.assertEqual(causas_do_mes(ctx, 2025, 4, [self.NE])[0].par, 202502)

    def test_valores_diferentes_nao_sao_deslocamento(self) -> None:
        ctx = self._contexto(notas=[(self.NE, 2026, 1, 8680.0)], relatorio=[(self.NE, 2025, 12, 8000.0)])
        self.assertEqual(causas_do_mes(ctx, 2026, 1, [self.NE]), [])

    def test_nota_nao_liquidada_explica_a_falta(self) -> None:
        ctx = self._contexto(
            notas=[(self.NE, 2026, 2, 100.0)], relatorio=[(self.NE, 2026, 2, 33458.77)],
            pendentes=[(self.NE, 2026, 2, 33358.77)],
        )
        causa = causas_do_mes(ctx, 2026, 2, [self.NE])[0]
        self.assertEqual((causa.tipo, causa.valor, causa.notas), ("nota_pendente", 33358.77, ("P0",)))

    def test_ne_sem_nenhuma_linha_no_relatorio_nao_se_compara(self) -> None:
        ctx = self._contexto(notas=[(self.NE, 2026, 1, 500.0)], relatorio=[("2026NE000100", 2026, 1, 10.0)])
        self.assertEqual(causas_do_mes(ctx, 2026, 1, [self.NE]), [])  # DEA: o relatório não tem competência

    def test_deslocamento_tem_prioridade_sobre_o_cancelamento(self) -> None:
        nat = {self.NE: SERV}
        itens, _ = itens_das_notas(_faturas(
            _nota("1", "A", 100.0, [(self.NE, 100.0)], [(2026, 3, 100.0)]),
            _nota("2", "B", 40.0, [(self.NE, 40.0)], [(2026, 3, 40.0)]),
        ), nat)
        rel = _relatorio((self.NE, 202603, 100.0), (self.NE, 202602, 40.0))
        ctx = construir_contexto(rel, itens, None, nat)
        mes = conciliar_exercicio(2026, rel, itens, nat)[2]
        self.assertEqual(ajustar_mes(mes).situacao, "batem_ajustado")  # sozinha, a regra sugeriria cancelar B
        causas = causas_do_mes(ctx, 2026, 3, [self.NE])
        self.assertEqual(causas[0].tipo, "deslocamento")  # mas as duas pontas mostram que B só mudou de mês
        self.assertEqual(ajustar_mes(mes, {c.ne for c in causas}).situacao, "sem_ajuste")


class ClassificarMesTests(unittest.TestCase):
    def test_cada_situacao_tem_a_sua_classe(self) -> None:
        from src.conciliacao_competencia_gov import ItemNota

        self.assertEqual(classificar_mes(MesConciliado(2026, 1, None, {}, None, []), None, []), "sem_registro")
        self.assertEqual(classificar_mes(MesConciliado(2026, 1, 10.0, {"a": 10.0}, 10.0, []), None, []), "batem")
        self.assertEqual(classificar_mes(MesConciliado(2026, 1, 10.0, {"a": 10.0}, None, []), None, []), "so_relatorio")
        so_notas = MesConciliado(2026, 1, None, {}, 10.0, [ItemNota("a", 10.0, "1", False, False, None)])
        self.assertEqual(classificar_mes(so_notas, ajustar_mes(so_notas), []), "so_notas")
        diverge = MesConciliado(2026, 1, 10.0, {"a": 10.0}, 25.0, [ItemNota("a", 25.0, "1", False, False, None)])
        self.assertEqual(classificar_mes(diverge, ajustar_mes(diverge), []), "sem_explicacao")

    def test_causa_identificada_vale_mais_que_o_cancelamento(self) -> None:
        itens = [ItemNota_("a", 100.0, "1"), ItemNota_("a", 40.0, "2")]
        mes = MesConciliado(2026, 3, 100.0, {"a": 100.0}, 140.0, itens)
        self.assertEqual(classificar_mes(mes, ajustar_mes(mes), []), "cancelamento")
        desloc = [Causa("a", "deslocamento", 40.0, 202602, "notas_aqui")]
        self.assertEqual(classificar_mes(mes, ajustar_mes(mes, {"a"}), desloc), "deslocamento")
        pend = [Causa("a", "nota_pendente", 40.0, None, None, ("9",))]
        self.assertEqual(classificar_mes(mes, None, desloc + pend), "nota_pendente")

    def test_todas_as_classes_tem_rotulo(self) -> None:
        self.assertIn("deslocamento", CLASSES)
        self.assertEqual(CLASSES["nota_pendente"], "Nota ainda não liquidada")


def ItemNota_(ne, valor, nota):
    from src.conciliacao_competencia_gov import ItemNota

    return ItemNota(ne, valor, nota, False, False, None)


class TotaisPorNeTests(unittest.TestCase):
    """Confronto de totais por NE: notas × relatório de competência × Execução Mensal (por mês de lançamento)."""

    def setUp(self) -> None:
        self.empenhos = empenhos_do_contrato(_empenhos(), "1")
        self.nat = {ne: i.natureza for ne, i in self.empenhos.items()}
        notas = _faturas(
            _nota("1", "100", 1000, [("2026NE000001", 1000)], [(2026, 1, 1000)]),
            _nota("2", "200", 500, [("2026NE000001", 500)], [(2026, 2, 500)]),
            _nota("3", "300", 700, [("2026NE000002", 700)], [(2025, 6, 700)]),
        )
        self.itens, _ = itens_das_notas(notas, self.nat)
        self.relatorio = _relatorio(("2026NE000001", 202601, 1000.0), ("2026NE000001", 202602, 500.0))
        self.execucao = pd.DataFrame({
            "ne_curta": ["2026NE000001", "2026NE000001", "2026NE000002"], "ano_mes": [202602, 202603, 202603],
            "liquidada": [1000.0, 500.0, 400.0],
        })

    def test_tres_totais_por_ne_e_diferencas(self) -> None:
        linhas = {l.ne: l for l in totais_por_ne(self.relatorio, self.itens, self.execucao, self.empenhos)}
        a = linhas["2026NE000001"]
        self.assertEqual((a.notas, a.relatorio, a.execucao), (1500.0, 1500.0, 1500.0))
        self.assertEqual((a.dif_relatorio, a.dif_notas, a.situacao), (0.0, 0.0, "batem"))
        b = linhas["2026NE000002"]  # DEA: sem linha no relatório; execução menor que as notas
        self.assertEqual((b.notas, b.relatorio, b.execucao), (700.0, None, 400.0))
        self.assertIsNone(b.dif_relatorio)  # nulo ≠ zero
        self.assertEqual((b.dif_notas, b.situacao), (300.0, "diverge_notas"))

    def test_ne_sem_execucao_e_sinalizada_e_nulo_nao_vira_zero(self) -> None:
        sem = totais_por_ne(self.relatorio, self.itens, self.execucao.iloc[0:0], self.empenhos)
        self.assertTrue(all(l.execucao is None and l.situacao == "sem_execucao" for l in sem if l.ne != "2026NE000003"))
        nada = totais_por_ne(self.relatorio, self.itens, None, self.empenhos)
        self.assertTrue(all(l.execucao is None for l in nada))

    def test_ne_sem_nenhum_dado_nao_aparece_e_ordem_por_ne(self) -> None:
        linhas = totais_por_ne(self.relatorio, self.itens, self.execucao, self.empenhos)
        self.assertEqual([l.ne for l in linhas], ["2026NE000001", "2026NE000002"])  # 2026NE000003 (20RL) sem nada

    def test_relatorio_diferente_da_execucao_e_destacado(self) -> None:
        rel = _relatorio(("2026NE000001", 202601, 1000.0))
        linha = totais_por_ne(rel, self.itens, self.execucao, self.empenhos)[0]
        self.assertEqual((linha.dif_relatorio, linha.situacao), (-500.0, "diverge_relatorio"))


class ConciliarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.nat = {"2026NE000001": SERV, "2026NE000002": DEA}
        notas = _faturas(
            _nota("1", "100", 1000, [("2026NE000001", 1000)], [(2026, 1, 1000)]),
            _nota("2", "200", 500, [("2026NE000001", 500)], [(2026, 2, 500)]),
            _nota("3", "300", 800, [("2026NE000002", 800)], [(2025, 6, 800)]),
        )
        self.itens, _ = itens_das_notas(notas, self.nat)
        self.relatorio = _relatorio(
            ("2026NE000001", 202601, 1000.0), ("2026NE000001", 202602, 400.0), ("2026NE000001", 202603, 700.0),
            ("2026NE999999", 202601, 99999.0),  # NE de outro contrato: fora
        )

    def test_batem_divergem_so_relatorio_so_notas_e_sem_registro(self) -> None:
        meses = conciliar_exercicio(2026, self.relatorio, self.itens, self.nat)
        self.assertEqual([m.situacao for m in meses[:4]], ["batem", "divergem", "so_relatorio", "sem_registro"])
        self.assertAlmostEqual(meses[1].diferenca, 100.0)  # notas 500 − relatório 400
        self.assertIsNone(meses[2].notas)
        self.assertIsNone(meses[3].relatorio)
        self.assertEqual(meses[0].relatorio, 1000.0)  # a NE de outro contrato não entra

    def test_so_notas_traz_o_elemento_de_despesa_do_empenho(self) -> None:
        junho = conciliar_exercicio(2025, self.relatorio, self.itens, self.nat)[5]
        self.assertEqual(junho.situacao, "so_notas")
        self.assertIsNone(junho.relatorio)
        self.assertEqual(junho.itens[0].elemento, "92")
        self.assertEqual(junho.itens[0].natureza, DEA)

    def test_ne_sem_natureza_conhecida_tem_elemento_nulo(self) -> None:
        nat = {"2026NE000001": None}
        itens, _ = itens_das_notas(_faturas(_nota("1", "1", 10, [("2026NE000001", 10)], [(2026, 1, 10)])), nat)
        self.assertIsNone(conciliar_exercicio(2026, None, itens, nat)[0].itens[0].elemento)

    def test_sem_relatorio_nem_notas_todos_sem_registro(self) -> None:
        meses = conciliar_exercicio(2026, None, pd.DataFrame(columns=["ne", "ano", "mes", "valor", "nota", "fatura_id", "rateada", "duplicada"]), self.nat)
        self.assertEqual({m.situacao for m in meses}, {"sem_registro"})

    def test_exercicios_disponiveis(self) -> None:
        self.assertEqual(exercicios_disponiveis(self.relatorio, self.itens, self.nat), [2026, 2025])


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------------------ tela (janela "Editar contrato")

import json  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

import src.contratos_continuos_cadastro as cadastro  # noqa: E402
from src import contratosgov_extracao  # noqa: E402
from src.conciliacao_competencia_gov import MesConciliado  # noqa: E402
from src.contratosgov_extracao import calcular_delta, gravar  # noqa: E402
from src.ui_conciliacao_competencia import html_mes  # noqa: E402
from tests import test_contratos_continuos_gov_page as pagina  # noqa: E402


class HtmlMesTests(unittest.TestCase):
    def test_so_nota_evidencia_o_elemento_e_avisa_sem_registro_no_relatorio(self) -> None:
        from src.conciliacao_competencia_gov import ItemNota

        mes = MesConciliado(2025, 6, None, {}, 800.0, [ItemNota("2026NE000002", 800.0, "300", False, False, DEA)])
        html = html_mes(mes)
        self.assertIn("sem registro", html)  # relatório
        self.assertIn("sem registro no relatório de competência", html)
        self.assertIn("elemento 92", html)
        self.assertIn("jun/2025", html)

    def test_so_relatorio_avisa_sem_registro_nas_notas(self) -> None:
        html = html_mes(MesConciliado(2026, 3, 700.0, {"2026NE000001": 700.0}, None, []))
        self.assertIn("2026NE000001", html)
        self.assertEqual(html.count("sem registro"), 1)  # só a linha das notas

    def test_batem_e_divergem_mostram_os_dois_valores(self) -> None:
        batem = html_mes(MesConciliado(2026, 1, 1000.0, {"a": 1000.0}, 1000.0, []))
        self.assertIn("✓ batem", batem)
        diverge = html_mes(MesConciliado(2026, 2, 400.0, {"a": 400.0}, 500.0, []))
        self.assertIn("diferença", diverge)

    def test_html_da_sugestao_de_cancelamento(self) -> None:
        from src.conciliacao_competencia_gov import ItemNota

        itens = [ItemNota("NE1", 100.0, "A", False, False, None), ItemNota("NE1", 40.0, "B", False, False, None)]
        mes = MesConciliado(2026, 3, 100.0, {"NE1": 100.0}, 140.0, itens)
        html = html_mes(mes, None, ajustar_mes(mes))
        self.assertIn("batem, desconsiderando 1 nota(s)", html)
        self.assertIn("provável cancelamento não informado no Contratos.gov", html)
        self.assertIn("cmp-risco", html)  # a nota sugerida aparece riscada, não some
        self.assertIn("sugerida como cancelada", html)

    def test_html_ambiguo_lista_as_alternativas_sem_escolher(self) -> None:
        from src.conciliacao_competencia_gov import ItemNota

        itens = [ItemNota("NE1", 100.0, "A", False, False, None), ItemNota("NE1", 100.0, "B", False, False, None),
                 ItemNota("NE1", 500.0, "C", False, False, None)]
        mes = MesConciliado(2026, 3, 600.0, {"NE1": 600.0}, 700.0, itens)
        html = html_mes(mes, None, ajustar_mes(mes))
        self.assertIn("poderia ser nota A (", html)
        self.assertIn(" ou nota B (", html)
        self.assertIn("O sistema não escolhe", html)
        self.assertNotIn("cmp-risco", html)

    def test_html_das_causas(self) -> None:
        from src.conciliacao_competencia_gov import Causa

        mes = MesConciliado(2026, 1, None, {}, 8680.0, [])
        html = html_mes(mes, None, None, [Causa("NE1", "deslocamento", 8680.0, 202512, "notas_aqui")])
        self.assertIn("deslocamento de competência", html)
        self.assertIn("as notas põem", html)
        self.assertIn("dez/2025", html)
        pend = html_mes(mes, None, None, [Causa("NE1", "nota_pendente", 100.0, None, None, ("P1",))])
        self.assertIn("nota ainda não liquidada", pend)
        self.assertIn("nota P1", pend)

    def test_matriz_consolidada(self) -> None:
        from src.ui_conciliacao_competencia import _compacto, html_consolidada

        meses = [{"mes": m, "relatorio": None, "notas": None, "classe": "sem_registro", "acao": ""} for m in range(1, 13)]
        meses[0] = {"mes": 1, "relatorio": 2560.24, "notas": 2560.24, "classe": "batem", "acao": ""}
        meses[1] = {"mes": 2, "relatorio": None, "notas": 8680.0, "classe": "so_notas", "acao": ""}
        html = html_consolidada([{"contrato": "A&B", "ano": 2026, "meses": meses, "total_relatorio": 2560.24, "total_notas": 11240.24}])
        self.assertIn("A&amp;B", html)  # texto escapado
        self.assertIn("k-batem", html)
        self.assertIn("<i>8,7 mil</i>", html)  # só nota: itálico
        self.assertIn("Total (relatório)", html)
        self.assertEqual((_compacto(None), _compacto(2560.24), _compacto(1_234_000.0), _compacto(0.0)), ("—", "2,6 mil", "1,2 mi", "0"))

    def test_aviso_de_fora_do_filtro(self) -> None:
        mes = filtrar_mes(
            MesConciliado(2026, 3, 1300.0, {"A": 1000.0, "B": 300.0}, None, []), ["A"],
        )
        html = html_mes(mes)
        self.assertIn("1 NE(s) fora do filtro", html)
        self.assertIn("relatório", html)
        self.assertIn("(B)", html)

    def test_duplicidade_rateio_e_texto_escapado(self) -> None:
        from src.conciliacao_competencia_gov import ItemNota

        itens = [ItemNota("NE<1>", 10.0, "A&B", True, True, None)]
        html = html_mes(MesConciliado(2026, 1, None, {}, 10.0, itens))  # sem relatório: o elemento é evidenciado
        self.assertIn("possível duplicidade", html)
        self.assertIn("rateio estimado", html)
        self.assertIn("NE&lt;1&gt;", html)
        self.assertIn("A&amp;B", html)
        self.assertIn("elemento não identificado", html)


def _fixture_com_notas() -> dict:
    nova = json.loads(pagina.FIXTURE.read_text(encoding="utf-8"))
    for detalhe in nova["detalhes"].values():
        detalhe["faturas"] = []
    # 13/2026 (id 1004328): NE 2026NE000522 no plano interno da 20RK
    nova["detalhes"]["1004328"]["faturas"] = [{
        "id": 1, "contrato_id": 1004328, "numero": "100", "valor": "1.000,00", "glosa": "0,00", "valorliquido": "1.000,00",
        "emissao": "2026-05-10", "data_liquidacao": "2026-06-05", "situacao": "Siafi Apropriado",
        "dados_empenho": [{"numero_empenho": "2026NE000522", "valor_empenho": "1.000,00"}],
        "dados_referencia": [{"mesref": "05", "anoref": "2026", "valorref": "1.000,00"}],
    }]
    return nova


@pytest.mark.skipif(
    not (pagina.FIXTURE.exists() and pagina.MANIFESTO_EXECUCAO.exists()),
    reason="Fixture do Contratos.gov ou manifesto atual da Execução Mensal ausente",
)
def test_janela_editar_mostra_o_seletor_de_exercicio_e_os_meses(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cadastro, "DIRETORIO_PADRAO", tmp_path / "continuos")
    manifestos, fotografias = tmp_path / "manifestos", tmp_path / "fotografias"
    monkeypatch.setattr(contratosgov_extracao, "DIRETORIO_MANIFESTOS", manifestos)
    monkeypatch.setattr(contratosgov_extracao, "DIRETORIO_FOTOGRAFIAS", fotografias)
    nova = _fixture_com_notas()
    gravar(nova, calcular_delta(None, nova), importado_em=datetime(2026, 10, 8, 9, 45), referencia=date(2026, 10, 8),
           dir_manifestos=manifestos, dir_fotografias=fotografias)
    registros = [cadastro.novo_contrato(**r) for r in pagina.REGISTROS]
    for registro in registros:
        cadastro.salvar_contrato(2026, registro)
    app = pagina._abrir()
    pagina._botao(app, "cc_editar_", registros[0]["id"]).click()
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    assert next(s for s in app.selectbox if s.label == "Exercício")  # seletor de exercício
    html = " ".join(m.value for m in app.markdown if 'class="cmp-mes"' in m.value)
    assert html.count('class="cmp-mes"') == 12  # os 12 meses do exercício
    assert any(m.label.startswith("NEs em evidência") for m in app.multiselect)  # filtro de NEs dentro do mês
    assert "Pendências do exercício" in " ".join(m.value for m in app.markdown)  # painel de pendências
    assert any(c.label.startswith("Mostrar só os meses com pendência") for c in app.checkbox)
    assert any(e.label.startswith("Totais por NE × Execução Mensal") for e in app.expander)  # confronto com a Execução Mensal
    assert any(e.label.startswith("Conciliação por competência — todos os contratos") for e in app.expander)  # visão consolidada
    assert any(b.label == "Calcular a visão consolidada" for b in app.button)
