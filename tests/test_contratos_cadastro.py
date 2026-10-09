"""Testes das tabelas derivadas do cadastro de contratos (src/contratos_cadastro.py).

Usam a fixture congelada `tests/fixtures/contratosgov_2026-10-08.json` (fotografia da UG
153165 no formato da spec §5, reduzida a 6 contratos reais; CPFs e nomes de pessoa física
trocados por "000.000.001-91" / "PESSOA FÍSICA FICTÍCIA"). Nenhum teste acessa a rede.

IMPORTANTE: não sobrescreva a fixture automaticamente ao refazer a consulta (AGENTS.md):
os valores abaixo foram conferidos à mão contra ela.

Valores esperados (referência `date(2026, 10, 8)`):

    id      numero       fornecedor (documento)     vigência               valor global   termos  NEs  situação
    1004328 00013/2026   05340639000130 (PJ)        2026-09-10..2027-09-10     830.906,44    1      2   vigente (337 dias)
    18940   00021/2017   10729661000106 (PJ)        2017-05-29..2027-05-28  10.354.305,17    6     14   vigente (232 dias)
    118872  00029/2021   07674744000130 (PJ)        2021-10-18..2026-10-17      93.307,80    5      5   vigente (9 dias)
    220038  00021/2023   00000000191    (PF fict.)  2023-10-03..2027-10-03           0,00    4      0   vigente (360 dias)
    7925    00018/2014   00000000191    (PF fict.)  2014-06-01..2025-05-31      42.822,36   11     12   encerrado (-495 dias)
    71912   00011/2017   19827805000131 (PJ)        2017-02-15..2017-06-14      78.838,32    1      1   inativo (lista de inativos)

Totais: 6 contratos (5 na lista de ativos, 1 na de inativos), 28 termos, 34 NEs; vigentes = 4;
vencem em até 90 dias = 1 (118872); valor global dos vigentes
830.906,44 + 10.354.305,17 + 93.307,80 + 0,00 = 11.278.519,41.

Particularidades da fonte cobertas: `situacao` da API é "Ativo" também para 7925 (encerrado há
mais de um ano) — a vigência vem das datas; 220038 é vigente com valor global 0,00 (zero, não
nulo) e 5 parcelas; os termos trazem `novo_valor_global` "0,00" na maioria (zero preservado) e
10.354.305,17 só no apostilamento 00004/2026 do 00021/2017 (id 1362652); `retroativo` vem como
"Sim"/"Não" e alguns termos têm só `retroativo_mesref_de` = "04" (período incompleto → nulo);
`qualificacao_termo` vem como lista de {codigo, descricao} (vira texto "desc1; desc2");
000.000.001-91 é o CPF fictício que substituiu os CPFs reais de 220038 e 7925.
"""

from __future__ import annotations

import copy
import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.contratos_cadastro import (
    SITUACOES,
    ErroDadoContratosGov,
    data_iso,
    montar_contratos,
    montar_empenhos,
    montar_termos,
    resumo,
    situacao_vigencia,
    valor_brl,
)

FIXTURE = Path(__file__).parent / "fixtures" / "contratosgov_2026-10-08.json"
REF = date(2026, 10, 8)


def carregar() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _item_minimo(**extra) -> dict:
    item = {
        "id": 1,
        "numero": "00001/2026",
        "tipo": "Contrato",
        "fornecedor": {"tipo": "JURIDICA", "cnpj_cpf_idgener": "00.000.000/0001-00", "nome": "X"},
        "vigencia_inicio": "2026-01-01",
        "vigencia_fim": "2026-12-31",
        "valor_global": "10,00",
    }
    item.update(extra)
    return item


def _foto_minima(ativos=(), inativos=()) -> dict:
    ids = [str(x["id"]) for x in (*ativos, *inativos)]
    return {
        "versao_formato": 1,
        "consultado_em": "2026-10-08T09:42:00",
        "ug": "153165",
        "lista_ativos": list(ativos),
        "lista_inativos": list(inativos),
        "detalhes": {
            i: {"historico": [], "empenhos": [], "consultado_em": "2026-10-08T09:42:00", "origem": "consulta"}
            for i in ids
        },
    }


class ValorBrlTest(unittest.TestCase):
    def test_valor_brl(self):
        casos = {
            "830.906,44": Decimal("830906.44"),
            "500,00": Decimal("500.00"),
            "-1.234,56": Decimal("-1234.56"),
            "0,00": Decimal("0.00"),
        }
        for texto, esperado in casos.items():
            r = valor_brl(texto, contrato_id="1", endpoint="/x", campo="valor_global")
            self.assertEqual(r, esperado)
            self.assertIsNotNone(r)
        self.assertIsNone(valor_brl(None, contrato_id="1", endpoint="/x", campo="c"))
        self.assertIsNone(valor_brl("", contrato_id="1", endpoint="/x", campo="c"))

    def test_valor_invalido_cita_contrato_endpoint_e_campo(self):
        for ruim in ("1.2x3,00", "1234.56", "12,5", 12.5):
            with self.assertRaises(ErroDadoContratosGov) as ctx:
                valor_brl(ruim, contrato_id="777", endpoint="/api/contrato/777/historico", campo="valor_global")
            msg = str(ctx.exception)
            self.assertIn("777", msg)
            self.assertIn("valor_global", msg)
            self.assertIn("/api/contrato/777/historico", msg)


class DataIsoTest(unittest.TestCase):
    def test_data_iso(self):
        self.assertEqual(data_iso("2026-09-10", contrato_id="1", endpoint="/x", campo="c"), date(2026, 9, 10))
        self.assertIsNone(data_iso(None, contrato_id="1", endpoint="/x", campo="c"))
        self.assertIsNone(data_iso("", contrato_id="1", endpoint="/x", campo="c"))

    def test_data_invalida_e_erro(self):
        for ruim in ("10/09/2026", "2026-13-01", "2026-9-1"):
            with self.assertRaises(ErroDadoContratosGov) as ctx:
                data_iso(ruim, contrato_id="55", endpoint="/api/x", campo="vigencia_fim")
            self.assertIn("55", str(ctx.exception))
            self.assertIn("vigencia_fim", str(ctx.exception))


class SituacaoVigenciaTest(unittest.TestCase):
    def test_situacao_vigencia(self):
        d = date
        self.assertEqual(situacao_vigencia(d(2026, 1, 1), d(2026, 12, 31), False, REF), "vigente")
        self.assertEqual(situacao_vigencia(REF, d(2026, 12, 31), False, REF), "vigente")
        self.assertEqual(situacao_vigencia(d(2026, 1, 1), REF, False, REF), "vigente")
        self.assertEqual(situacao_vigencia(d(2026, 10, 9), d(2027, 1, 1), False, REF), "a_iniciar")
        self.assertEqual(situacao_vigencia(d(2020, 1, 1), d(2026, 10, 7), False, REF), "encerrado")
        self.assertEqual(situacao_vigencia(d(2026, 1, 1), d(2026, 12, 31), True, REF), "inativo")
        self.assertEqual(situacao_vigencia(None, d(2026, 12, 31), False, REF), "sem_vigencia")
        self.assertEqual(situacao_vigencia(d(2026, 1, 1), None, False, REF), "sem_vigencia")
        self.assertEqual(situacao_vigencia(None, None, True, REF), "inativo")

    def test_situacoes_constante(self):
        self.assertEqual(SITUACOES, ("vigente", "a_iniciar", "encerrado", "inativo", "sem_vigencia"))


class TabelasDaFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.foto = carregar()
        cls.contratos = montar_contratos(cls.foto, REF)
        cls.termos = montar_termos(cls.foto)
        cls.empenhos = montar_empenhos(cls.foto)

    def linha(self, contrato_id):
        sel = self.contratos[self.contratos["contrato_id"] == contrato_id]
        self.assertEqual(len(sel), 1)
        return sel.iloc[0]

    def test_contrato_vigente_00013_2026(self):
        r = self.linha("1004328")
        self.assertEqual(r["numero"], "00013/2026")
        self.assertEqual(r["ano_contrato"], 2026)
        self.assertEqual(r["fornecedor_documento"], "05340639000130")
        self.assertEqual(r["valor_global"], Decimal("830906.44"))
        self.assertEqual(r["situacao_vigencia"], "vigente")
        self.assertEqual(r["dias_para_vencer"], 337)
        self.assertEqual(r["qtd_empenhos"], 2)
        self.assertEqual(r["qtd_termos"], 1)
        self.assertIs(r["inativo_api"], False)
        self.assertEqual(r["situacao_api"], "Ativo")
        self.assertEqual(r["detalhe_origem"], "consulta")
        self.assertEqual(r["detalhe_consultado_em"], "2026-10-08T09:42:00")
        self.assertEqual(r["vigencia_fim"], date(2027, 9, 10))

    def test_todas_as_situacoes_e_contagens(self):
        esperado = {
            "1004328": ("vigente", 1, 2),
            "18940": ("vigente", 6, 14),
            "118872": ("vigente", 5, 5),
            "220038": ("vigente", 4, 0),
            "7925": ("encerrado", 11, 12),
            "71912": ("inativo", 1, 1),
        }
        self.assertEqual(len(self.contratos), 6)
        for cid, (sit, nt, ne) in esperado.items():
            r = self.linha(cid)
            self.assertEqual((r["situacao_vigencia"], r["qtd_termos"], r["qtd_empenhos"]), (sit, nt, ne), cid)
        self.assertEqual(len(self.termos), 28)
        self.assertEqual(len(self.empenhos), 34)
        self.assertEqual(self.linha("7925")["dias_para_vencer"], -495)
        self.assertEqual(self.linha("18940")["dias_para_vencer"], 232)
        self.assertEqual(self.linha("118872")["dias_para_vencer"], 9)

    def test_zero_e_diferente_de_nulo(self):
        r = self.linha("220038")
        self.assertIsNotNone(r["valor_global"])
        self.assertEqual(r["valor_global"], Decimal("0.00"))
        self.assertEqual(r["num_parcelas"], 5)

    def test_monetarias_sao_decimal_em_object(self):
        for col in ("valor_inicial", "valor_global", "valor_parcela", "valor_acumulado"):
            self.assertEqual(self.contratos[col].dtype, object, col)
        self.assertEqual(self.empenhos["empenhado"].dtype, object)
        self.assertEqual(self.termos["novo_valor_global"].dtype, object)

    def test_empenhos_reconstroem_ne_completa(self):
        e = self.empenhos[self.empenhos["contrato_id"] == "1004328"]
        self.assertEqual(len(e), 2)
        linha = e[e["ne_ccor"] == "153165152392026NE000522"]
        self.assertEqual(len(linha), 1)
        r = linha.iloc[0]
        self.assertEqual(r["ne"], "2026NE000522")
        self.assertEqual(r["ug"], "153165")
        self.assertEqual(r["gestao"], "15239")
        self.assertEqual(r["empenhado"], Decimal("63702.83"))
        self.assertEqual(r["pago"], Decimal("0.00"))
        self.assertEqual(r["data_emissao"], date(2026, 9, 2))

    def test_termos_do_00021_2017(self):
        t = self.termos[self.termos["contrato_id"] == "18940"]
        self.assertEqual(len(t), 6)
        self.assertEqual(list(t["data_assinatura"]), sorted(t["data_assinatura"]))
        self.assertEqual(t.iloc[0]["tipo"], "Contrato")
        self.assertEqual(list(t["termo_id"]), ["67405", "67415", "290939", "382950", "788966", "1362652"])
        apost = t[t["tipo"] == "Termo de Apostilamento"]
        self.assertEqual(len(apost), 1)
        self.assertEqual(apost.iloc[0]["novo_valor_global"], Decimal("10354305.17"))
        # zero preservado nos demais termos (não vira nulo)
        self.assertEqual(t.iloc[0]["novo_valor_global"], Decimal("0.00"))

    def test_retroativo_periodo_so_com_quatro_campos(self):
        # fixture só tem retroativo_mesref_de = "04" isolado: período incompleto → nulo
        self.assertTrue(self.termos["retroativo_periodo"].isna().all())
        self.assertTrue(self.termos["retroativo"].map(lambda v: v is False).all())
        self.assertEqual(self.termos["retroativo_valor"].dropna().iloc[0], Decimal("0.00"))

    def test_inativo_e_pessoa_fisica(self):
        self.assertEqual(self.linha("71912")["situacao_vigencia"], "inativo")
        self.assertIs(self.linha("71912")["inativo_api"], True)
        self.assertEqual(self.linha("71912")["situacao_api"], "Inativo")
        pf = self.linha("7925")
        self.assertEqual(pf["fornecedor_documento"], "00000000191")
        self.assertEqual(pf["fornecedor_tipo"], "FISICA")
        self.assertEqual(pf["fornecedor_nome"], "PESSOA FÍSICA FICTÍCIA")

    def test_resumo_confere_com_anotacao_manual(self):
        r = resumo(self.contratos)
        self.assertEqual(r["total"], 6)
        self.assertEqual(r["ativos_api"], 5)
        self.assertEqual(r["inativos_api"], 1)
        self.assertEqual(r["vigentes"], 4)
        self.assertEqual(r["vencem_90"], 1)
        self.assertEqual(r["valor_global_vigentes"], Decimal("11278519.41"))
        self.assertIsInstance(r["valor_global_vigentes"], Decimal)

    def test_referencia_muda_a_situacao(self):
        c = montar_contratos(self.foto, date(2026, 10, 18))  # 118872 venceu em 17/10
        self.assertEqual(c[c["contrato_id"] == "118872"].iloc[0]["situacao_vigencia"], "encerrado")
        c = montar_contratos(self.foto, date(2026, 9, 1))  # 1004328 só começa em 10/09
        self.assertEqual(c[c["contrato_id"] == "1004328"].iloc[0]["situacao_vigencia"], "a_iniciar")

    def test_fotografia_nao_e_alterada(self):
        antes = copy.deepcopy(self.foto)
        montar_contratos(self.foto, REF)
        montar_termos(self.foto)
        montar_empenhos(self.foto)
        self.assertEqual(self.foto, antes)


class ErrosDeFormatoTest(unittest.TestCase):
    def test_mesmo_id_em_ativos_e_inativos_e_erro(self):
        foto = _foto_minima(ativos=[_item_minimo(id=5)], inativos=[_item_minimo(id=5)])
        with self.assertRaises(ErroDadoContratosGov) as ctx:
            montar_contratos(foto, REF)
        self.assertIn("5", str(ctx.exception))

    def test_campo_obrigatorio_ausente_e_erro(self):
        item = _item_minimo(id=9)
        del item["vigencia_fim"]
        with self.assertRaises(ErroDadoContratosGov) as ctx:
            montar_contratos(_foto_minima(ativos=[item]), REF)
        self.assertIn("vigencia_fim", str(ctx.exception))
        self.assertIn("9", str(ctx.exception))

    def test_valor_null_e_aceito(self):
        item = _item_minimo(id=9, vigencia_fim=None, valor_global=None)
        c = montar_contratos(_foto_minima(ativos=[item]), REF)
        r = c.iloc[0]
        self.assertTrue(pd.isna(r["valor_global"]))
        self.assertEqual(r["situacao_vigencia"], "sem_vigencia")
        self.assertTrue(pd.isna(r["dias_para_vencer"]))

    def test_numero_fora_do_padrao_tem_ano_nulo(self):
        c = montar_contratos(_foto_minima(ativos=[_item_minimo(id=3, numero="ABC-12")]), REF)
        r = c.iloc[0]
        self.assertTrue(pd.isna(r["ano_contrato"]))
        self.assertEqual(r["numero"], "ABC-12")

    def test_valor_invalido_na_lista_cita_contrato_e_campo(self):
        with self.assertRaises(ErroDadoContratosGov) as ctx:
            montar_contratos(_foto_minima(ativos=[_item_minimo(id=4, valor_global="1234.56")]), REF)
        self.assertIn("4", str(ctx.exception))
        self.assertIn("valor_global", str(ctx.exception))

    def test_detalhe_ausente_e_erro(self):
        foto = _foto_minima(ativos=[_item_minimo(id=6)])
        del foto["detalhes"]["6"]
        with self.assertRaises(ErroDadoContratosGov):
            montar_contratos(foto, REF)

    def test_empenho_sem_gestao_e_erro_e_codigos_sao_texto(self):
        foto = _foto_minima(ativos=[_item_minimo(id=7)])
        emp = {"id": 1, "numero": "2026NE000001", "unidade_gestora": "153165", "gestao": "00001"}
        foto["detalhes"]["7"]["empenhos"] = [emp]
        e = montar_empenhos(foto)
        self.assertEqual(e.iloc[0]["ne_ccor"], "153165" + "00001" + "2026NE000001")
        self.assertEqual(e.iloc[0]["gestao"], "00001")
        self.assertTrue(pd.isna(e.iloc[0]["empenhado"]))
        del emp["gestao"]
        with self.assertRaises(ErroDadoContratosGov) as ctx:
            montar_empenhos(foto)
        self.assertIn("gestao", str(ctx.exception))

    def test_termo_sem_data_assinatura_e_erro(self):
        foto = _foto_minima(ativos=[_item_minimo(id=8)])
        foto["detalhes"]["8"]["historico"] = [{"id": 1, "tipo": "Contrato"}]
        with self.assertRaises(ErroDadoContratosGov) as ctx:
            montar_termos(foto)
        self.assertIn("data_assinatura", str(ctx.exception))

    def test_tabelas_vazias_mantem_colunas(self):
        foto = _foto_minima(ativos=[_item_minimo(id=2)])
        self.assertEqual(len(montar_termos(foto)), 0)
        self.assertIn("termo_id", montar_termos(foto).columns)
        self.assertIn("ne_ccor", montar_empenhos(foto).columns)

    def test_qualificacao_termo_lista_vira_texto(self):
        foto = _foto_minima(ativos=[_item_minimo(id=2)])
        foto["detalhes"]["2"]["historico"] = [
            {"id": 1, "tipo": "Termo Aditivo", "data_assinatura": "2026-02-01",
             "qualificacao_termo": [{"codigo": 2, "descricao": "VIGÊNCIA"}, {"codigo": 1, "descricao": "ACRÉSCIMO"}]},
            {"id": 2, "tipo": "Contrato", "data_assinatura": "2026-01-01", "qualificacao_termo": None},
            {"id": 3, "tipo": "Contrato", "data_assinatura": "2026-01-02", "qualificacao_termo": [{"codigo": 1}]},
        ]
        with self.assertRaises(ErroDadoContratosGov) as ctx:
            montar_termos(foto)
        self.assertIn("qualificacao_termo", str(ctx.exception))
        del foto["detalhes"]["2"]["historico"][2]
        t = montar_termos(foto)
        self.assertTrue(pd.isna(t.iloc[0]["qualificacao_termo"]))
        self.assertEqual(t.iloc[1]["qualificacao_termo"], "VIGÊNCIA; ACRÉSCIMO")

    def test_retroativo_periodo_completo(self):
        foto = _foto_minima(ativos=[_item_minimo(id=2)])
        foto["detalhes"]["2"]["historico"] = [{
            "id": 10, "tipo": "Termo Aditivo", "data_assinatura": "2026-02-01", "retroativo": "Sim",
            "retroativo_mesref_de": "03", "retroativo_anoref_de": 2025,
            "retroativo_mesref_ate": "01", "retroativo_anoref_ate": "2026",
        }]
        t = montar_termos(foto).iloc[0]
        self.assertEqual(t["retroativo_periodo"], "03/2025–01/2026")
        self.assertIs(t["retroativo"], True)


if __name__ == "__main__":
    unittest.main()
