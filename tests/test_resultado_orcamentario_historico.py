"""Testes do histórico do Resultado Orçamentário (fotografia por dia + variação por componente).

Valores calculados à mão. Resultado = Dotação − Empenhado − Necessidade.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.resultado_orcamentario_cadastro import ArquivoCorrompido
from src.resultado_orcamentario_historico import (
    Fotografia,
    carregar_historico,
    comparar,
    fotografar,
    mudancas,
    mudou,
    registrar,
    chave_celula,
    rotulo_celula,
    tabela_celulas,
    tabela_historico,
    tabela_mudanca,
    virada_de_situacao,
)


@dataclass
class _Res:
    dotacao: float | None
    empenhado: dict
    empenhado_total: float | None
    necessidade: dict
    resultado: float | None
    incompleto: bool = False


def _res(dotacao=1000.0, contratos=300.0, bolsas=100.0, nec_contratos=200.0, nec_bolsas=50.0, outras=0.0):
    empenhado = {"Contratos Contínuos": contratos, "Bolsas e Auxílios": bolsas}
    necessidade = {
        "Contratos Contínuos": nec_contratos, "Bolsas e Auxílios": nec_bolsas, "Outras despesas previstas": outras,
    }
    total = None if None in empenhado.values() else sum(empenhado.values())
    nec = None if None in necessidade.values() else sum(necessidade.values())
    resultado = None if dotacao is None or total is None or nec is None else dotacao - total - nec
    return _Res(dotacao, empenhado, total, necessidade, resultado, incompleto=resultado is None)


def _foto(dia: str, **kwargs) -> Fotografia:
    return fotografar(_res(**kwargs), 2026, 5, hoje=date.fromisoformat(dia), dotacao_sha="d1", execucao_sha="e1")


class TestPersistencia(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_sem_pasta_historico_vazio(self):
        self.assertEqual(carregar_historico(2026, self.dir), [])

    def test_grava_e_le_preservando_nulo(self):
        self.assertTrue(registrar(_foto("2026-10-13", nec_bolsas=None), self.dir))
        lida = carregar_historico(2026, self.dir)[0]
        self.assertIsNone(lida.necessidade["Bolsas e Auxílios"])  # nulo não vira zero
        self.assertIsNone(lida.resultado)
        self.assertTrue(lida.incompleto)
        self.assertEqual(lida.dotacao, 1000.0)
        self.assertTrue(lida.registrado_em)

    def test_um_arquivo_por_dia_e_ordem_cronologica(self):
        registrar(_foto("2026-10-14", dotacao=1100.0), self.dir)
        registrar(_foto("2026-10-13"), self.dir)
        self.assertEqual([f.data for f in carregar_historico(2026, self.dir)], ["2026-10-13", "2026-10-14"])

    def test_mesmo_conteudo_no_mesmo_dia_nao_regrava(self):
        self.assertTrue(registrar(_foto("2026-10-13"), self.dir))
        caminho = self.dir / "2026" / "historico" / "2026-10-13.json"
        antes = caminho.read_text(encoding="utf-8")
        self.assertFalse(registrar(_foto("2026-10-13"), self.dir))
        self.assertEqual(caminho.read_text(encoding="utf-8"), antes)

    def test_mudanca_no_mesmo_dia_substitui_a_fotografia(self):
        registrar(_foto("2026-10-13"), self.dir)
        self.assertTrue(registrar(_foto("2026-10-13", contratos=350.0), self.dir))
        historico = carregar_historico(2026, self.dir)
        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0].empenhado["Contratos Contínuos"], 350.0)

    def test_arquivo_corrompido_levanta_e_nao_e_sobrescrito(self):
        pasta = self.dir / "2026" / "historico"
        pasta.mkdir(parents=True)
        (pasta / "2026-10-13.json").write_text("{quebrado", encoding="utf-8")
        with self.assertRaises(ArquivoCorrompido):
            carregar_historico(2026, self.dir)
        with self.assertRaises(ArquivoCorrompido):
            registrar(_foto("2026-10-13"), self.dir)
        self.assertEqual((pasta / "2026-10-13.json").read_text(encoding="utf-8"), "{quebrado")

    def test_formato_inesperado_e_corrompido(self):
        pasta = self.dir / "2026" / "historico"
        pasta.mkdir(parents=True)
        (pasta / "2026-10-13.json").write_text(json.dumps({"data": "2026-10-13"}), encoding="utf-8")
        with self.assertRaises(ArquivoCorrompido):
            carregar_historico(2026, self.dir)

    def test_exercicios_separados(self):
        registrar(_foto("2026-10-13"), self.dir)
        self.assertEqual(carregar_historico(2025, self.dir), [])


class TestVariacao(unittest.TestCase):
    def test_variacao_e_efeito_no_resultado_por_componente(self):
        # antes: 1000 − 400 − 250 = 350 ; depois: 1100 − (350+100) − (180+50) = 420
        antes = _foto("2026-10-13")
        depois = _foto("2026-10-14", dotacao=1100.0, contratos=350.0, nec_contratos=180.0)
        m = comparar(antes, depois)
        por = {(v.grupo, v.componente): v for v in m.variacoes}
        self.assertEqual(antes.resultado, 350.0)
        self.assertEqual(depois.resultado, 420.0)
        self.assertEqual(m.variacao_resultado, 70.0)
        dot = por[("Dotação", "Dotação atualizada")]
        self.assertEqual((dot.variacao, dot.efeito), (100.0, 100.0))  # dotação maior melhora o resultado
        emp = por[("Empenhado", "Contratos Contínuos")]
        self.assertEqual((emp.variacao, emp.efeito), (50.0, -50.0))  # empenhar mais piora
        nec = por[("Necessidade", "Contratos Contínuos")]
        self.assertEqual((nec.variacao, nec.efeito), (-20.0, 20.0))  # necessidade menor melhora
        # os efeitos explicam exatamente a variação do resultado
        self.assertAlmostEqual(sum(v.efeito for v in m.variacoes if v.efeito is not None), m.variacao_resultado)

    def test_componente_nulo_gera_variacao_nula_nunca_zero(self):
        m = comparar(_foto("2026-10-13"), _foto("2026-10-14", nec_bolsas=None))
        v = {(x.grupo, x.componente): x for x in m.variacoes}[("Necessidade", "Bolsas e Auxílios")]
        self.assertEqual((v.anterior, v.atual), (50.0, None))
        self.assertIsNone(v.variacao)
        self.assertIsNone(v.efeito)
        self.assertTrue(mudou(v))  # deixar de ser calculável é mudança
        self.assertIsNone(m.variacao_resultado)  # resultado ficou indisponível

    def test_sem_mudanca_nada_marcado_como_mudou(self):
        m = comparar(_foto("2026-10-13"), _foto("2026-10-14"))
        self.assertFalse(any(mudou(v) for v in m.variacoes))
        self.assertEqual(m.variacao_resultado, 0.0)

    def test_zero_e_nulo_sao_diferentes(self):
        m = comparar(_foto("2026-10-13", outras=0.0), _foto("2026-10-14", outras=None))
        v = {(x.grupo, x.componente): x for x in m.variacoes}[("Necessidade", "Outras despesas previstas")]
        self.assertEqual(v.anterior, 0.0)
        self.assertIsNone(v.atual)
        self.assertTrue(mudou(v))

    def test_componente_so_em_uma_ponta_entra_como_nulo(self):
        antes = _foto("2026-10-13")
        depois = _foto("2026-10-14")
        depois.empenhado["Material de Consumo (elemento 30)"] = 10.0
        v = {(x.grupo, x.componente): x for x in comparar(antes, depois).variacoes}[
            ("Empenhado", "Material de Consumo (elemento 30)")
        ]
        self.assertIsNone(v.anterior)
        self.assertIsNone(v.variacao)

    def test_mudancas_consecutivas_da_mais_recente_para_a_mais_antiga(self):
        fotos = [_foto("2026-10-13"), _foto("2026-10-15", contratos=310.0), _foto("2026-10-14", dotacao=1100.0)]
        pares = [(m.anterior.data, m.atual.data) for m in mudancas(fotos)]
        self.assertEqual(pares, [("2026-10-14", "2026-10-15"), ("2026-10-13", "2026-10-14")])

    def test_menos_de_duas_fotografias_nao_tem_mudanca(self):
        self.assertEqual(mudancas([]), [])
        self.assertEqual(mudancas([_foto("2026-10-13")]), [])


class TestTabelas(unittest.TestCase):
    def test_tabela_historico_mais_recente_primeiro_com_variacao(self):
        fotos = [_foto("2026-10-13"), _foto("2026-10-14", dotacao=1100.0), _foto("2026-10-15", nec_bolsas=None)]
        t = tabela_historico(fotos)
        self.assertEqual(list(t["Dia"]), ["2026-10-15", "2026-10-14", "2026-10-13"])
        self.assertEqual(list(t["Situação"]), ["Incompleto", "Superávit", "Superávit"])
        self.assertEqual(t.loc[2, "Resultado"], 350.0)
        self.assertTrue(t["Variação"].isna().iloc[2])  # primeira fotografia: sem anterior
        self.assertEqual(t.loc[1, "Variação"], 100.0)
        self.assertTrue(t["Variação"].isna().iloc[0])  # resultado nulo: variação nula, não zero

    def test_situacao_deficit_e_equilibrio(self):
        t = tabela_historico([_foto("2026-10-13", dotacao=400.0), _foto("2026-10-14", dotacao=650.0)])
        self.assertEqual(list(t["Situação"]), ["Equilíbrio", "Déficit"])

    def test_tabela_mudanca_so_o_que_mudou(self):
        m = comparar(_foto("2026-10-13"), _foto("2026-10-14", contratos=350.0))
        t = tabela_mudanca(m)
        self.assertEqual(list(t["Componente"]), ["Contratos Contínuos"])
        self.assertEqual(list(t["Grupo"]), ["Empenhado"])
        self.assertEqual(t.loc[0, "Efeito no resultado"], -50.0)
        self.assertGreater(len(tabela_mudanca(m, apenas_que_mudaram=False)), 1)

    def test_historico_vazio_gera_tabela_vazia_com_colunas(self):
        self.assertTrue(tabela_historico([]).empty)
        self.assertIn("Resultado", tabela_historico([]).columns)


class TestViradaDeSituacao(unittest.TestCase):
    # resultado = dotação − 400 (empenhado) − 250 (necessidade): 1000 → 350 (Superávit), 650 → 0 (Equilíbrio),
    # 600 → −50 (Déficit)
    def test_cada_transicao(self):
        sup, eq, defi = _foto("2026-10-13"), _foto("2026-10-14", dotacao=650.0), _foto("2026-10-15", dotacao=600.0)
        inc = _foto("2026-10-16", nec_bolsas=None)
        self.assertEqual(virada_de_situacao(sup, eq), "Superávit → Equilíbrio")
        self.assertEqual(virada_de_situacao(eq, defi), "Equilíbrio → Déficit")
        self.assertEqual(virada_de_situacao(sup, defi), "Superávit → Déficit")
        self.assertEqual(virada_de_situacao(defi, sup), "Déficit → Superávit")
        self.assertEqual(virada_de_situacao(defi, inc), "Déficit → Incompleto")
        self.assertEqual(virada_de_situacao(inc, sup), "Incompleto → Superávit")

    def test_sem_mudanca_e_primeira_fotografia_nao_marcam(self):
        a, b = _foto("2026-10-13"), _foto("2026-10-14", dotacao=1100.0)  # ambas Superávit
        self.assertIsNone(virada_de_situacao(a, b))
        self.assertIsNone(virada_de_situacao(None, a))

    def test_coluna_na_tabela_do_historico(self):
        t = tabela_historico([_foto("2026-10-13"), _foto("2026-10-14", dotacao=600.0), _foto("2026-10-15", dotacao=700.0)])
        self.assertEqual(list(t["Dia"]), ["2026-10-15", "2026-10-14", "2026-10-13"])
        self.assertEqual(t.loc[0, "Mudança de situação"], "Déficit → Superávit")
        self.assertEqual(t.loc[1, "Mudança de situação"], "Superávit → Déficit")
        self.assertTrue(t["Mudança de situação"].isna().iloc[2])  # primeira fotografia
        self.assertEqual(list(t["Situação"]), ["Superávit", "Déficit", "Superávit"])  # valores não mudam


def _foto_celulas(dia: str, celulas: dict | None, **kwargs) -> Fotografia:
    base = _foto(dia, **kwargs)
    return fotografar(
        _res(**kwargs), 2026, 5, hoje=date.fromisoformat(dia), dotacao_sha=base.dotacao_sha,
        execucao_sha=base.execucao_sha, dotacao_por_celula=celulas,
    )


C1 = chave_celula(("0", "1", "0181", "169886", "0000", "1", "1056000000"))
C2 = chave_celula(("0", "2", "20RK", "169150", "0000", "3", "1000000000"))
C3 = chave_celula(("0", "1", "4002", "1", None, "3", "1000000000"))


class TestDotacaoPorCelula(unittest.TestCase):
    def test_chave_preserva_zeros_a_esquerda_e_nulo_vira_vazio(self):
        self.assertEqual(C1, "0|1|0181|169886|0000|1|1056000000")
        self.assertEqual(rotulo_celula(C3), "0 / 1 / 4002 / 1 / — / 3 / 1000000000")

    def test_celulas_que_moveram_a_dotacao_ordenadas_e_somam_a_variacao(self):
        # dotação: 1000 -> 1130 ; C1 +100 (alterada), C2 sai (-50), C3 entra (+80) => +130
        antes = _foto_celulas("2026-10-13", {C1: 600.0, C2: 50.0, "x": 350.0}, dotacao=1000.0)
        depois = _foto_celulas("2026-10-14", {C1: 700.0, C3: 80.0, "x": 350.0}, dotacao=1130.0)
        m = comparar(antes, depois)
        por = {v.chave: v for v in m.celulas}
        self.assertEqual(list(por), [C1, C3, C2])  # maior efeito absoluto primeiro
        self.assertEqual((por[C1].motivo, por[C1].efeito), ("dotação alterada", 100.0))
        self.assertEqual((por[C3].motivo, por[C3].antes, por[C3].depois), ("célula marcada", None, 80.0))
        self.assertEqual((por[C2].motivo, por[C2].efeito, por[C2].depois), ("célula desmarcada", -50.0, None))
        self.assertNotIn("x", por)  # célula sem mudança não aparece
        self.assertAlmostEqual(sum(v.efeito for v in m.celulas), depois.dotacao - antes.dotacao)

    def test_dotacao_nula_em_uma_ponta_nao_vira_zero(self):
        m = comparar(_foto_celulas("2026-10-13", {C1: 600.0}), _foto_celulas("2026-10-14", {C1: None}))
        v = m.celulas[0]
        self.assertEqual((v.motivo, v.antes, v.depois), ("dotação nula", 600.0, None))
        self.assertIsNone(v.efeito)

    def test_nula_nas_duas_pontas_nao_e_mudanca(self):
        m = comparar(_foto_celulas("2026-10-13", {C1: None}), _foto_celulas("2026-10-14", {C1: None}))
        self.assertEqual(m.celulas, [])

    def test_fotografia_sem_detalhe_deixa_celulas_indisponiveis(self):
        m = comparar(_foto("2026-10-13"), _foto_celulas("2026-10-14", {C1: 1.0}))
        self.assertIsNone(m.celulas)
        self.assertIsNone(tabela_celulas(m))

    def test_tabela_celulas(self):
        m = comparar(_foto_celulas("2026-10-13", {C1: 600.0}), _foto_celulas("2026-10-14", {C1: 700.0}))
        t = tabela_celulas(m)
        self.assertEqual(list(t["Efeito na dotação"]), [100.0])
        self.assertEqual(t.loc[0, "Célula"], rotulo_celula(C1))

    def test_persiste_e_le_o_detalhe_por_celula(self):
        with tempfile.TemporaryDirectory() as tmp:
            registrar(_foto_celulas("2026-10-13", {C1: 600.0, C2: None}), Path(tmp))
            lida = carregar_historico(2026, Path(tmp))[0]
            self.assertEqual(lida.dotacao_por_celula, {C1: 600.0, C2: None})

    def test_fotografia_antiga_sem_o_campo_continua_legivel(self):
        with tempfile.TemporaryDirectory() as tmp:
            registrar(_foto("2026-10-13"), Path(tmp))
            caminho = Path(tmp) / "2026" / "historico" / "2026-10-13.json"
            dado = json.loads(caminho.read_text(encoding="utf-8"))
            dado.pop("dotacao_por_celula")
            caminho.write_text(json.dumps(dado), encoding="utf-8")
            self.assertIsNone(carregar_historico(2026, Path(tmp))[0].dotacao_por_celula)

    def test_mudanca_so_no_detalhe_por_celula_regrava_o_dia(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(registrar(_foto_celulas("2026-10-13", {C1: 600.0}), Path(tmp)))
            self.assertFalse(registrar(_foto_celulas("2026-10-13", {C1: 600.0}), Path(tmp)))
            self.assertTrue(registrar(_foto_celulas("2026-10-13", {C1: 650.0}), Path(tmp)))
            # primeira fotografia com o detalhe passa a valer no mesmo dia (antes não tinha)
            self.assertTrue(registrar(_foto("2026-10-14"), Path(tmp)))
            self.assertTrue(registrar(_foto_celulas("2026-10-14", {C1: 1.0}), Path(tmp)))


if __name__ == "__main__":
    unittest.main()
