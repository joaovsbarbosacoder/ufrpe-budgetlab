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
    anulacao: dict | None = None


def _res(dotacao=1000.0, contratos=300.0, bolsas=100.0, nec_contratos=200.0, nec_bolsas=50.0, outras=0.0, anulacao=None):
    empenhado = {"Contratos Contínuos": contratos, "Bolsas e Auxílios": bolsas}
    necessidade = {
        "Contratos Contínuos": nec_contratos, "Bolsas e Auxílios": nec_bolsas, "Outras despesas previstas": outras,
    }
    total = None if None in empenhado.values() else sum(empenhado.values())
    nec = None if None in necessidade.values() else sum(necessidade.values())
    receita = sum((anulacao or {}).values())
    resultado = None if dotacao is None or total is None or nec is None else dotacao - total - nec + receita
    return _Res(dotacao, empenhado, total, necessidade, resultado, incompleto=resultado is None, anulacao=anulacao)


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


class TestAnulacaoSugerida(unittest.TestCase):
    """15/10/2026: a anulação sugerida (receita) entra na fórmula e no que levou à alteração."""

    def test_grava_le_e_compara_a_anulacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            foto = fotografar(
                _res(anulacao={"Contratos Contínuos": 80.0, "Bolsas e Auxílios": 0.0}), 2026, 5,
                hoje=date(2026, 10, 15), dotacao_sha="d1", execucao_sha="e1",
            )
            self.assertTrue(registrar(foto, Path(tmp)))
            lida = carregar_historico(2026, Path(tmp))[0]
            self.assertEqual(lida.anulacao, {"Contratos Contínuos": 80.0, "Bolsas e Auxílios": 0.0})
            self.assertFalse(registrar(foto, Path(tmp)))  # mesmo conteúdo: não regrava

    def test_variacao_da_anulacao_move_o_resultado_com_sinal_positivo(self):
        antes = fotografar(_res(anulacao={"Contratos Contínuos": 80.0, "Bolsas e Auxílios": 0.0}), 2026, 5,
                           hoje=date(2026, 10, 14), dotacao_sha="d1", execucao_sha="e1")
        depois = fotografar(_res(anulacao={"Contratos Contínuos": 130.0, "Bolsas e Auxílios": 10.0}), 2026, 5,
                            hoje=date(2026, 10, 15), dotacao_sha="d1", execucao_sha="e1")
        mudanca = comparar(antes, depois)
        itens = {(v.grupo, v.componente): v for v in mudanca.variacoes}
        contratos = itens[("Anulação sugerida", "Contratos Contínuos")]
        self.assertEqual((contratos.anterior, contratos.atual, contratos.variacao, contratos.efeito), (80.0, 130.0, 50.0, 50.0))
        self.assertEqual(itens[("Anulação sugerida", "Bolsas e Auxílios")].efeito, 10.0)
        self.assertEqual(mudanca.variacao_resultado, 60.0)  # 50 + 10: os demais componentes não mudaram

    def test_fotografia_antiga_sem_anulacao_vale_zero_na_comparacao(self):
        antiga = fotografar(_res(), 2026, 5, hoje=date(2026, 10, 14), dotacao_sha="d1", execucao_sha="e1")
        antiga = Fotografia(**{**antiga.__dict__, "anulacao": None})
        nova = fotografar(_res(anulacao={"Contratos Contínuos": 70.0, "Bolsas e Auxílios": 0.0}), 2026, 5,
                          hoje=date(2026, 10, 15), dotacao_sha="d1", execucao_sha="e1")
        mudanca = comparar(antiga, nova)
        item = next(v for v in mudanca.variacoes if v.grupo == "Anulação sugerida" and v.componente == "Contratos Contínuos")
        self.assertEqual((item.anterior, item.atual, item.efeito), (0.0, 70.0, 70.0))
        self.assertEqual(mudanca.variacao_resultado, 70.0)

    def test_arquivo_antigo_sem_a_chave_continua_legivel(self):
        with tempfile.TemporaryDirectory() as tmp:
            foto = fotografar(_res(), 2026, 5, hoje=date(2026, 10, 13), dotacao_sha="d1", execucao_sha="e1")
            registrar(foto, Path(tmp))
            caminho = next(Path(tmp).rglob("2026-10-13.json"))
            dado = json.loads(caminho.read_text(encoding="utf-8"))
            dado.pop("anulacao")
            caminho.write_text(json.dumps(dado), encoding="utf-8")
            self.assertIsNone(carregar_historico(2026, Path(tmp))[0].anulacao)



class TestOutrasDespesasConsideradas(unittest.TestCase):
    """15/10/2026: o usuário pode desconsiderar as outras despesas previstas na conta; a fotografia do dia continua sendo
    gravada e guarda se elas estavam consideradas, para a série seguir interpretável."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pasta = Path(self._tmp.name)

    def _foto_flag(self, dia: str, consideradas, outras=0.0) -> Fotografia:
        return fotografar(
            _res(outras=outras), 2026, 5, hoje=date.fromisoformat(dia), dotacao_sha="d1", execucao_sha="e1",
            **({} if consideradas is None else {"outras_despesas_consideradas": consideradas}),
        )

    def test_padrao_e_considerar(self):
        self.assertIs(self._foto_flag("2026-10-10", None).outras_despesas_consideradas, True)

    def test_grava_e_le_o_estado_desconsiderado(self):
        registrar(self._foto_flag("2026-10-10", False), self.pasta)
        self.assertIs(carregar_historico(2026, self.pasta)[0].outras_despesas_consideradas, False)

    def test_fotografia_antiga_sem_o_campo_vale_como_considerada(self):
        registrar(self._foto_flag("2026-10-10", True), self.pasta)
        arquivo = next((self.pasta / "2026" / "historico").glob("*.json"))
        dado = json.loads(arquivo.read_text(encoding="utf-8"))
        dado.pop("outras_despesas_consideradas")  # arquivo gravado antes deste campo existir
        arquivo.write_text(json.dumps(dado), encoding="utf-8")
        foto = carregar_historico(2026, self.pasta)[0]
        self.assertIsNone(foto.outras_despesas_consideradas)
        self.assertEqual(tabela_historico([foto]).iloc[0]["Outras despesas"], "Consideradas")

    def test_mudar_a_escolha_no_mesmo_dia_regrava_mesmo_com_o_resto_igual(self):
        self.assertTrue(registrar(self._foto_flag("2026-10-10", True), self.pasta))
        self.assertFalse(registrar(self._foto_flag("2026-10-10", True), self.pasta))  # igual: não regrava
        self.assertTrue(registrar(self._foto_flag("2026-10-10", False), self.pasta))  # só a escolha mudou: regrava
        self.assertIs(carregar_historico(2026, self.pasta)[0].outras_despesas_consideradas, False)

    def test_none_e_true_sao_o_mesmo_conteudo(self):
        self.assertTrue(registrar(self._foto_flag("2026-10-10", None), self.pasta))
        self.assertFalse(registrar(self._foto_flag("2026-10-10", True), self.pasta))

    def test_tabela_do_historico_mostra_a_escolha_de_cada_dia(self):
        historico = [self._foto_flag("2026-10-10", True, outras=40.0), self._foto_flag("2026-10-11", False)]
        tabela = tabela_historico(historico)
        self.assertEqual(list(tabela["Dia"]), ["2026-10-11", "2026-10-10"])
        self.assertEqual(list(tabela["Outras despesas"]), ["Desconsideradas", "Consideradas"])

    def test_comparar_avisa_quando_a_escolha_mudou(self):
        antes, depois = self._foto_flag("2026-10-10", True, outras=40.0), self._foto_flag("2026-10-11", False)
        mudanca = comparar(antes, depois)
        self.assertEqual(mudanca.escolha_outras_despesas, "consideradas → desconsideradas")
        self.assertEqual(comparar(depois, antes).escolha_outras_despesas, "desconsideradas → consideradas")

    def test_sem_mudanca_de_escolha_nao_ha_aviso(self):
        a, b = self._foto_flag("2026-10-10", False), self._foto_flag("2026-10-11", False)
        self.assertIsNone(comparar(a, b).escolha_outras_despesas)
        antiga, nova = self._foto_flag("2026-10-10", None), self._foto_flag("2026-10-11", True)
        self.assertIsNone(comparar(antiga, nova).escolha_outras_despesas)  # None ≡ consideradas

    def test_a_variacao_da_necessidade_continua_calculada_com_o_efeito_no_resultado(self):
        antes, depois = self._foto_flag("2026-10-10", True, outras=40.0), self._foto_flag("2026-10-11", False, outras=0.0)
        v = next(v for v in comparar(antes, depois).variacoes if v.componente == "Outras despesas previstas")
        self.assertEqual((v.anterior, v.atual, v.variacao, v.efeito), (40.0, 0.0, -40.0, 40.0))


@dataclass
class _ResNovo:
    """Resultado no critério de 15/10/2026 (executado + projetado)."""
    dotacao: float | None
    empenhado: dict
    executado: dict
    executado_total: float | None
    projetado: dict
    resultado: float | None
    incompleto: bool = False


def _res_novo(dotacao=1000.0, exec_c=250.0, exec_b=80.0, proj_c=150.0, proj_b=40.0) -> _ResNovo:
    executado = {"Contratos Contínuos": exec_c, "Bolsas e Auxílios": exec_b}
    projetado = {"Contratos Contínuos": proj_c, "Bolsas e Auxílios": proj_b, "Outras despesas previstas": 0.0}
    total = sum(executado.values())
    return _ResNovo(
        dotacao, {"Contratos Contínuos": 300.0, "Bolsas e Auxílios": 100.0}, executado, total, projetado,
        dotacao - total - sum(projetado.values()),
    )


class TestCriterioExecutadoProjetado(unittest.TestCase):
    def _foto_novo(self, dia, **kw):
        return fotografar(_res_novo(**kw), 2026, 5, hoje=date.fromisoformat(dia), dotacao_sha="d1", execucao_sha="e1")

    def test_fotografia_nova_guarda_executado_e_projetado_com_o_criterio(self):
        foto = self._foto_novo("2026-10-15")
        self.assertEqual(foto.criterio, "executado_projetado")
        self.assertEqual(foto.empenhado["Contratos Contínuos"], 250.0)  # executado, não o empenhado de 300
        self.assertEqual(foto.empenhado_total, 330.0)
        self.assertEqual(foto.necessidade["Bolsas e Auxílios"], 40.0)
        self.assertEqual(foto.anulacao, {})
        self.assertEqual(foto.resultado, 1000 - 330 - 190)

    def test_criterio_ida_e_volta_pelo_arquivo_e_fotografia_antiga_fica_sem_criterio(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            registrar(self._foto_novo("2026-10-15"), pasta)
            registrar(_foto("2026-10-14"), pasta)
            lidas = {f.data: f for f in carregar_historico(2026, pasta)}
            self.assertEqual(lidas["2026-10-15"].criterio, "executado_projetado")
            self.assertIsNone(lidas["2026-10-14"].criterio)  # não é reescrita

    def test_mudar_so_o_criterio_regrava_a_fotografia_do_dia(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            self.assertTrue(registrar(_foto("2026-10-15", dotacao=1000.0), pasta))
            self.assertTrue(registrar(self._foto_novo("2026-10-15", exec_c=300.0, exec_b=100.0, proj_c=200.0, proj_b=50.0), pasta))
            self.assertFalse(registrar(self._foto_novo("2026-10-15", exec_c=300.0, exec_b=100.0, proj_c=200.0, proj_b=50.0), pasta))

    def test_comparar_criterios_diferentes_avisa_e_nomeia_os_grupos_pelo_critério_atual(self):
        antes, depois = _foto("2026-10-14"), self._foto_novo("2026-10-15")
        m = comparar(antes, depois)
        self.assertEqual(m.mudanca_de_criterio, "empenhado + necessidade → executado + projetado")
        self.assertIn("Executado", {v.grupo for v in m.variacoes})
        self.assertIn("Projetado a realizar", {v.grupo for v in m.variacoes})
        self.assertNotIn("Necessidade", {v.grupo for v in m.variacoes})

    def test_mesmo_criterio_nao_avisa(self):
        a, b = self._foto_novo("2026-10-15"), self._foto_novo("2026-10-16", exec_c=260.0)
        self.assertIsNone(comparar(a, b).mudanca_de_criterio)
        self.assertIsNone(comparar(_foto("2026-10-13"), _foto("2026-10-14")).mudanca_de_criterio)

    def test_tabela_do_historico_mostra_o_criterio_de_cada_dia(self):
        tabela = tabela_historico([_foto("2026-10-14"), self._foto_novo("2026-10-15")])
        self.assertEqual(list(tabela["Critério"]), ["Executado + projetado", "Empenhado + necessidade"])


class TestEscolhaItemAItem(unittest.TestCase):
    def _foto_qtd(self, dia, qtd, valor):
        res = _res_novo()
        res.outras_desconsideradas_qtd, res.outras_desconsideradas_valor = qtd, valor
        return fotografar(res, 2026, 5, hoje=date.fromisoformat(dia), dotacao_sha="d1", execucao_sha="e1")

    def test_fotografia_guarda_quantas_e_quanto_ficaram_de_fora(self):
        foto = self._foto_qtd("2026-10-15", 2, 70.0)
        self.assertEqual((foto.outras_despesas_ignoradas_qtd, foto.outras_despesas_ignoradas_valor), (2, 70.0))
        self.assertFalse(foto.outras_despesas_consideradas)  # "consideradas" = nenhuma desmarcada
        self.assertTrue(self._foto_qtd("2026-10-16", 0, 0.0).outras_despesas_consideradas)

    def test_ida_e_volta_pelo_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            registrar(self._foto_qtd("2026-10-15", 1, 40.0), Path(tmp))
            lida = carregar_historico(2026, Path(tmp))[0]
            self.assertEqual((lida.outras_despesas_ignoradas_qtd, lida.outras_despesas_ignoradas_valor), (1, 40.0))

    def test_mudar_so_a_quantidade_regrava_o_dia(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(registrar(self._foto_qtd("2026-10-15", 1, 40.0), Path(tmp)))
            self.assertFalse(registrar(self._foto_qtd("2026-10-15", 1, 40.0), Path(tmp)))
            self.assertTrue(registrar(self._foto_qtd("2026-10-15", 2, 90.0), Path(tmp)))

    def test_comparar_avisa_mudanca_parcial_e_a_tabela_mostra_a_situacao(self):
        todas, uma, duas = self._foto_qtd("2026-10-14", 0, 0.0), self._foto_qtd("2026-10-15", 1, 40.0), self._foto_qtd("2026-10-16", 2, 90.0)
        self.assertEqual(comparar(todas, uma).escolha_outras_despesas, "consideradas → 1 desconsiderada(s) (R$ 40,00)")
        self.assertEqual(
            comparar(uma, duas).escolha_outras_despesas, "1 desconsiderada(s) (R$ 40,00) → 2 desconsiderada(s) (R$ 90,00)"
        )
        self.assertIsNone(comparar(uma, self._foto_qtd("2026-10-17", 1, 40.0)).escolha_outras_despesas)
        tabela = tabela_historico([todas, uma])
        self.assertEqual(list(tabela["Outras despesas"]), ["1 desconsiderada(s) (R$ 40,00)", "Consideradas"])


if __name__ == "__main__":
    unittest.main()
