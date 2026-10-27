"""Testes de `src.ddp_realizado` (DDP como realizado provisório do mês, 27/10/2026).

Base mensal sintética de pessoal (jan–set/2026) com Ativo, Inativo e RPPS; a DDP de outubro é
montada como PDF mínimo no layout do SIAPE (`tests.test_ddp_siape._ddp_pdf`). Prioridade testada:
liquidação > DDP > projeção."""
from __future__ import annotations

import unittest

import pandas as pd

from src.ddp_realizado import ORIGEM_DDP, ORIGEM_PROJECAO, aplicar_ddp
from src.ddp_siape import ler_relatorio
from src.despesas_pessoal import grade_mensal, ultimo_mes_fechado
from tests.test_ddp_siape import _ddp_pdf

UG = "UNIVERSIDADE TESTE"
ANUAL_VAZIA = pd.DataFrame({c: pd.Series(dtype="object") for c in (
    "ano", "acao_cod", "natureza_despesa_cod", "natureza_despesa_desc", "natureza_detalhada_cod", "natureza_detalhada_desc",
    "empenhada", "tipo_linha")})

#: (ação, natureza de despesa, natureza detalhada, NE, favorecido, valor mensal)
ITENS = [
    ("20TP", "319011", "31901101", "NE1", UG, 1000.0),
    ("20TP", "319011", "31901107", "NE1", UG, 100.0),      # fora da DDP: segue a projeção
    ("0181", "319001", "31900101", "NE2", UG, 500.0),
    ("0181", "319003", "31900301", "NE4", UG, 40.0),
    ("09HB", "319113", "31911303", "NE3", "FUNDO RPPS", 270.0),  # patronal: fora da DDP e da folha
]


def _linha(acao, nd, det, ne, favorecido, ano_mes, liquidada, tipo="item_execucao"):
    return {
        "ano": ano_mes // 100, "ano_mes": ano_mes, "mes": ano_mes % 100, "tipo_linha": tipo, "acao_cod": acao,
        "natureza_despesa_cod": nd, "natureza_despesa_desc": f"NAT {nd}", "natureza_detalhada_cod": det,
        "natureza_detalhada_desc": f"DET {det}", "ne_ccor": f"153165152392026{ne}", "ne_favorecido": favorecido,
        "ug_executora_desc": UG, "liquidada": liquidada, "paga": liquidada, "empenhada": 0.0, "po_cod": "0000",
        "iduso_cod": "0", "ne_item_cod": "-9", "arquivo_origem": "base.xlsx", "aba_origem": "aba", "linha_origem": 1,
    }


def _base(outubro: dict[str, float] | None = None, setembro_fator: float = 1.0) -> pd.DataFrame:
    """jan–ago e set (× `setembro_fator`) em dia; outubro com as liquidações pedidas (natureza → valor)."""
    linhas = []
    for mes in range(1, 10):
        fator = setembro_fator if mes == 9 else 1.0
        linhas += [_linha(a, nd, det, ne, fav, 202600 + mes, v * fator) for a, nd, det, ne, fav, v in ITENS]
    for acao, nd, det, ne, fav, _ in ITENS:
        if outubro and det in outubro:
            linhas.append(_linha(acao, nd, det, ne, fav, 202610, outubro[det]))
    return pd.DataFrame(linhas)


def _ddp(servidor_so=False, rubricas=None):
    serv = ler_relatorio(_ddp_pdf("OUT", "SERVIDOR", [
        ("3.3190.11.01", "VENCIMENTO E SALARIOS", 1100.0), ("3.3190.01.01", "PROVENTOS", 600.0),
        ("3.3190.92.11", "EXERC ANTERIOR ATIVO", 70.0)], rubricas=rubricas), "serv.pdf")
    pens = ler_relatorio(_ddp_pdf("OUT", "PENSIONISTA", [("3.3190.03.01", "PENSOES CIVIS", 55.0)]), "pens.pdf")
    return [serv] if servidor_so else [serv, pens]


def _total(mensal, natureza, ano_mes=202610):
    linhas = mensal.loc[(mensal["natureza_detalhada_cod"] == natureza) & (mensal["ano_mes"] == ano_mes)
                        & (mensal["tipo_linha"] == "item_execucao")]
    return round(float(linhas["liquidada"].sum()), 2)


class TestPrioridadeLiquidacaoDdpProjecao(unittest.TestCase):
    def test_sem_liquidacao_do_mes_usa_a_ddp_e_projeta_o_resto(self):
        base = _base(outubro={"31901101": 20.0})  # liquidação parcial de outubro (folha ainda aberta)
        self.assertEqual(ultimo_mes_fechado(base), 202609)
        res = aplicar_ddp(base, ANUAL_VAZIA, _ddp())
        self.assertTrue(res.aplicada)
        self.assertEqual(res.competencia, 202610)
        # DDP: valores do mês por natureza; a liquidação parcial (20,00) é substituída e informada
        self.assertEqual(_total(res.mensal, "31901101"), 1100.0)
        self.assertEqual(_total(res.mensal, "31900101"), 600.0)
        self.assertEqual(_total(res.mensal, "31900301"), 55.0)
        self.assertEqual(res.liquidado_parcial_substituido, 20.0)
        # natureza que a DDP não traz: projeção do painel (repete setembro); RPPS idem
        self.assertEqual(_total(res.mensal, "31901107"), 100.0)
        self.assertEqual(_total(res.mensal, "31911303"), 270.0)
        self.assertEqual(set(res.detalhe.loc[res.detalhe["natureza_detalhada"].isin(["31901107", "31911303"]), "origem"]),
                         {ORIGEM_PROJECAO})
        self.assertEqual(set(res.detalhe.loc[res.detalhe["natureza_detalhada"] == "31901101", "origem"]), {ORIGEM_DDP})
        # o mês passa a contar como fechado e a base original não foi alterada
        self.assertEqual(ultimo_mes_fechado(res.mensal), 202610)
        self.assertEqual(_total(base, "31901101"), 20.0)

    def test_natureza_da_ddp_sem_linha_modelo_e_listada_nao_descartada(self):
        res = aplicar_ddp(_base(), ANUAL_VAZIA, _ddp())
        self.assertEqual(res.sem_destino, [("31909211", 70.0)])
        self.assertEqual(res.total_ddp, 1825.0)
        self.assertEqual(res.total_no_painel, 1755.0)  # 1.825 − 70 sem destino

    def test_meses_seguintes_sao_recalculados_a_partir_da_ddp(self):
        base = _base()
        sem = grade_mensal(base, ANUAL_VAZIA, 2026, 202609).linhas.set_index("natureza_detalhada_cod")
        com = grade_mensal(aplicar_ddp(base, ANUAL_VAZIA, _ddp()).mensal, ANUAL_VAZIA, 2026, 202610).linhas.set_index("natureza_detalhada_cod")
        self.assertEqual(com.loc["31901101", "meses"][9], 1100.0)  # outubro real (DDP)
        self.assertAlmostEqual(com.loc["31901101", "meses"][10] / sem.loc["31901101", "meses"][10], 1.1)
        # natureza fora da DDP: mesma projeção de antes
        self.assertEqual(com.loc["31901107", "meses"][10], sem.loc["31901107", "meses"][10])

    def test_liquidacao_do_mes_ja_fechada_prevalece_e_a_ddp_nao_e_somada(self):
        base = _base(outubro={"31901101": 1050.0, "31901107": 100.0, "31900101": 510.0, "31900301": 41.0, "31911303": 271.0})
        self.assertEqual(ultimo_mes_fechado(base), 202610)
        res = aplicar_ddp(base, ANUAL_VAZIA, _ddp())
        self.assertFalse(res.aplicada)
        self.assertIn("prevalece", res.motivo)
        self.assertIs(res.mensal, base)
        self.assertEqual(_total(res.mensal, "31901101"), 1050.0)

    def test_mes_anterior_ainda_aberto_nao_usa_a_ddp(self):
        base = _base(setembro_fator=0.1)  # setembro muito abaixo da média: não fechou
        self.assertEqual(ultimo_mes_fechado(base), 202608)
        res = aplicar_ddp(base, ANUAL_VAZIA, _ddp())
        self.assertFalse(res.aplicada)
        self.assertIn("mês anterior", res.motivo)
        self.assertIs(res.mensal, base)

    def test_ddp_so_de_servidor_ou_sem_ddp_nao_muda_nada(self):
        base = _base()
        self.assertFalse(aplicar_ddp(base, ANUAL_VAZIA, _ddp(servidor_so=True)).aplicada)
        self.assertIn("servidor e pensionista", aplicar_ddp(base, ANUAL_VAZIA, _ddp(servidor_so=True)).motivo)
        for vazio in (None, []):
            res = aplicar_ddp(base, ANUAL_VAZIA, vazio)
            self.assertFalse(res.aplicada)
            self.assertIs(res.mensal, base)
            self.assertIsNone(res.competencia)

    def test_empenho_fora_da_folha_na_mesma_natureza_repete_o_mes_anterior(self):
        base = _base()
        extra = [_linha("0181", "319001", "31900101", "NE9", "OUTRO FAVORECIDO", 202600 + m, 30.0) for m in range(1, 10)]
        base = pd.concat([base, pd.DataFrame(extra)], ignore_index=True)
        res = aplicar_ddp(base, ANUAL_VAZIA, _ddp())
        # DDP (600) só na folha; o empenho de outro favorecido repete setembro (30)
        self.assertEqual(_total(res.mensal, "31900101"), 630.0)
        folha = res.mensal.loc[(res.mensal["natureza_detalhada_cod"] == "31900101") & (res.mensal["ano_mes"] == 202610)
                               & (res.mensal["ne_favorecido"] == UG), "liquidada"].sum()
        self.assertEqual(round(float(folha), 2), 600.0)


class TestPatronalPelaDdp(unittest.TestCase):
    """28/10/2026: o patronal do RPPS no mês da DDP é (PSS dos servidores) × 2, e a razão dos meses seguintes se calibra por ele."""
    RUBRICAS = [("98002", "CONT. PLANO SEGURIDADE SOCIAL", 100.0), ("98015", "CONT P.SEGURIDADE SOCIAL AP", 30.0)]
    PENS = [("98020", "CONT.PLANO SEG.SOCIAL- PENSION", 5.0)]

    def test_patronal_do_mes_vem_do_pss_e_nao_entra_nos_totais_da_ddp(self):
        res = aplicar_ddp(_base(), ANUAL_VAZIA, _ddp(rubricas=self.RUBRICAS))
        self.assertEqual(_total(res.mensal, "31911303"), 260.0)  # (100 + 30) × 2, e não a projeção (270)
        self.assertEqual(set(res.detalhe.loc[res.detalhe["natureza_detalhada"] == "31911303", "origem"]), {ORIGEM_DDP})
        self.assertEqual(res.patronal_pss["valor"].sum(), 130.0)
        self.assertEqual((res.total_ddp, res.total_no_painel), (1825.0, 1755.0))  # o patronal não é natureza da DDP

    def test_painel_no_mes_da_ddp_nao_reescala_o_patronal_e_calibra_a_razao(self):
        res = aplicar_ddp(_base(), ANUAL_VAZIA, _ddp(rubricas=self.RUBRICAS))
        g = grade_mensal(res.mensal, ANUAL_VAZIA, 2026, 202610)
        patronal = g.linhas.set_index("natureza_detalhada_cod").loc["31911303", "meses"]
        self.assertEqual(patronal[9], 260.0)
        self.assertTrue(g.patronal_pela_ddp)
        self.assertEqual(g.mes_razao_patronal_rpps, 10)
        self.assertAlmostEqual(g.razao_patronal_rpps, 260.0 / 1100.0)  # patronal ÷ base do Ativo (31901101) do mês

    def test_rubricas_da_ddp_de_pensionistas_entram_na_soma(self):
        servidor, pens = _ddp(rubricas=self.RUBRICAS)
        pens = ler_relatorio(_ddp_pdf("OUT", "PENSIONISTA", [("3.3190.03.01", "PENSOES CIVIS", 55.0)], rubricas=self.PENS), "pens.pdf")
        res = aplicar_ddp(_base(), ANUAL_VAZIA, [servidor, pens])
        self.assertEqual(_total(res.mensal, "31911303"), 270.0)  # (100 + 30 + 5) × 2
        self.assertEqual(set(res.patronal_pss["parte"]), {"Ativo", "Inativo", "Pensionista"})

    def test_sem_rubricas_o_patronal_segue_a_projecao(self):
        res = aplicar_ddp(_base(), ANUAL_VAZIA, _ddp())
        self.assertEqual(_total(res.mensal, "31911303"), 270.0)
        self.assertIsNone(res.patronal_pss)
        self.assertFalse(grade_mensal(res.mensal, ANUAL_VAZIA, 2026, 202610).patronal_pela_ddp)


class TestAvisoNoPainel(unittest.TestCase):
    def test_textos_do_aviso(self):
        from src.ui_ddp_siape import aviso_ddp_aplicada

        res = aplicar_ddp(_base(outubro={"31901101": 20.0}), ANUAL_VAZIA, _ddp())
        nivel, texto = aviso_ddp_aplicada(res, None, 202610)
        self.assertEqual(nivel, "warning")  # há natureza sem destino
        self.assertIn("ainda não liquidados", texto)
        self.assertIn("31909211", texto)
        self.assertIn("20,00", texto)
        self.assertIsNone(aviso_ddp_aplicada(res, None, 202609))  # outra referência: sem aviso
        self.assertEqual(aviso_ddp_aplicada(res, "arquivo ausente", 202610)[0], "error")
        sem = aplicar_ddp(_base(), ANUAL_VAZIA, None)
        self.assertIsNone(aviso_ddp_aplicada(sem, None, 202610))
        prevalece = aplicar_ddp(_base(outubro={"31901101": 1050.0, "31901107": 100.0, "31900101": 510.0,
                                               "31900301": 41.0, "31911303": 271.0}), ANUAL_VAZIA, _ddp())
        self.assertEqual(aviso_ddp_aplicada(prevalece, None, 202610)[0], "info")
        self.assertIn("prevalece", aviso_ddp_aplicada(prevalece, None, 202610)[1])


if __name__ == "__main__":
    unittest.main()
