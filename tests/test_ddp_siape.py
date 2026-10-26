"""Testes de `src.ddp_siape` (DDP do SIAPE × empenhos da folha, 27/10/2026).

A leitura usa fixtures congeladas em `tests/fixtures/` — `ddp_siape_{serv,pens}_2026-09.pdf`
e `cred_banc_siape_{serv,pens}_2026-09.pdf` —, versões REDUZIDAS das DDPs e Créditos
Bancários DEFINITIVOS de set/2026 da UFRPE (UPAG 260): mesmas páginas, cabeçalhos, seções,
agregados, naturezas detalhadas e totais, sem as linhas de rubrica/consignatária e com o
nome do usuário do SIAPE trocado por "XXXXXXXXXXXX". Nenhum dado pessoal. Os valores
esperados são os do confronto feito à mão com os PDFs originais (DDP set/2026 × Liquidada de
set/2026), que reproduziu centavo a centavo a liquidação da maioria das naturezas. Não
sobrescreva estas fixtures automaticamente (mesma regra das demais — ver AGENTS.md).

O reforço por empenho é testado com uma base mensal sintética, pequena o bastante para
conferir cada número à mão.
"""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

import pandas as pd
import pymupdf

from src.ddp_siape import (
    CRITERIO_ELEMENTO, CRITERIO_REPARTIDO, CRITERIO_SEM_EMPENHO, CRITERIO_SOMADO, CRITERIO_UNICO,
    OPERACAO_REFORCO, OPERACAO_REMANEJAR, RESERVA_DDP, RESERVA_PROJECAO, SEM_EMPENHO, TIPO_CREDITO, TIPO_DDP,
    conciliacao_sem_ddp, conferencia, confronto_liquidado, ddp_por_natureza, ler_relatorio, plano_operacoes,
    quadro_reforco, quadro_sem_ddp, reserva_projetada, separar_competencias, validar_conjunto, variacao_por_natureza,
)
from src.despesas_pessoal import GRUPO_RPPS
from src.tesouro_execucao_mensal import _DIMENSOES_EXTRA_BLOCO

FIXTURES = Path("tests/fixtures")
ARQUIVOS_SET = ("ddp_siape_serv_2026-09.pdf", "ddp_siape_pens_2026-09.pdf",
                "cred_banc_siape_serv_2026-09.pdf", "cred_banc_siape_pens_2026-09.pdf")


def _relatorios_set():
    return [ler_relatorio((FIXTURES / nome).read_bytes(), nome) for nome in ARQUIVOS_SET]


def _pdf(linhas: list[str]) -> bytes:
    documento = pymupdf.open()
    pagina = documento.new_page()
    for i, linha in enumerate(linhas):
        pagina.insert_text((20, 30 + 9 * i), linha, fontname="cour", fontsize=7)
    return documento.tobytes()


class TestLeituraDaFixtureDeSetembro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.relatorios = _relatorios_set()

    def test_identifica_tipo_publico_e_competencia(self):
        lidos = {(r.tipo, r.publico) for r in self.relatorios}
        self.assertEqual(lidos, {(TIPO_DDP, "SERVIDOR"), (TIPO_DDP, "PENSIONISTA"),
                                 (TIPO_CREDITO, "SERVIDOR"), (TIPO_CREDITO, "PENSIONISTA")})
        for r in self.relatorios:
            self.assertEqual((r.competencia, r.mes_pagamento, r.folha), (202609, 202610, "FOLHA NORMAL"))
            self.assertEqual(r.data_geracao, date(2026, 9, 21))
        self.assertEqual(validar_conjunto(self.relatorios), [])

    def test_conferencia_fecha_com_o_credito_bancario(self):
        tabela = conferencia(self.relatorios).set_index("publico")
        self.assertEqual(tabela.loc["SERVIDOR", "bruto"], 49974499.63)
        self.assertEqual(tabela.loc["SERVIDOR", "desconto"], 17609157.60)
        self.assertEqual(tabela.loc["SERVIDOR", "liquido"], 32365342.03)
        self.assertEqual(tabela.loc["SERVIDOR", "credito_bancario"], 32365342.03)
        self.assertEqual(tabela.loc["PENSIONISTA", "liquido"], 3947434.97)
        self.assertEqual(tabela.loc["PENSIONISTA", "credito_bancario"], 3947434.97)
        for coluna in ("dif_bruto_menos_desconto", "dif_naturezas_bruto", "dif_desconto", "dif_credito"):
            self.assertEqual(tabela[coluna].abs().max(), 0.0, coluna)

    def test_sem_credito_bancario_a_diferenca_e_nula_nao_zero(self):
        so_ddp = [r for r in self.relatorios if r.tipo == TIPO_DDP]
        tabela = conferencia(so_ddp)
        self.assertTrue(tabela["credito_bancario"].isna().all())
        self.assertTrue(tabela["dif_credito"].isna().all())

    def test_naturezas_reproduzem_o_confronto_de_setembro(self):
        nat = ddp_por_natureza(self.relatorios)
        self.assertEqual(round(nat["liquido"].sum(), 2), 54867853.53)
        por = nat.set_index(["natureza_detalhada", "publico"])["liquido"]
        self.assertEqual(por[("31901101", "SERVIDOR")], 16753889.62)
        self.assertEqual(por[("31901131", "SERVIDOR")], 15162405.86)
        self.assertEqual(por[("33904601", "SERVIDOR")], 2495694.43)
        self.assertEqual(por[("33909308", "SERVIDOR")], 318275.28)
        self.assertEqual(por[("33909308", "PENSIONISTA")], 15618.38)
        # pensões: 4.635.589,70 na seção (1) − 6.682,99 a anular
        linha = nat.set_index(["natureza_detalhada", "publico"]).loc[("31900301", "PENSIONISTA")]
        self.assertEqual((linha["despesa"], linha["anular"], linha["liquido"]), (4635589.70, 6682.99, 4628906.71))

    def test_codigo_da_ddp_vira_natureza_detalhada_como_texto(self):
        nat = ddp_por_natureza(self.relatorios)
        self.assertTrue(nat["natureza_detalhada"].map(lambda c: isinstance(c, str) and len(c) == 8).all())
        self.assertIn("31909203", set(nat["natureza_detalhada"]))  # 3.3190.92.03, zero do meio preservado


class TestValidacoesDaLeitura(unittest.TestCase):
    def test_arquivo_que_nao_e_pdf(self):
        with self.assertRaisesRegex(ValueError, "não foi possível ler"):
            ler_relatorio(b"isto nao e um pdf", "x.pdf")

    def test_pdf_que_nao_e_do_siape(self):
        with self.assertRaisesRegex(ValueError, "não é uma DDP"):
            ler_relatorio(_pdf(["RELATORIO QUALQUER", "TOTAL 1,00"]), "outro.pdf")

    def test_ddp_sem_totais_nao_vira_zero(self):
        linhas = [
            " __ SIAPE,GERENCIAL,GRFINANC,GRCOFINDDP ( DEMONS. DESPESA C/ PESSOAL-DDP )_____",
            " ORGAO SOLICITADO: 26248 UFRPE                          MES/ANO SOLIC: SET2026",
            "       *** DDP FOLHA NORMAL - NIVEL UNIDADE PAGADORA - SERVIDOR ***",
            "                       *** DESPESAS CORRENTES ( 1 ) ***",
            " 3.3190.11.01 VENCIMENTO E SALARIOS                              10,00",
        ]
        with self.assertRaisesRegex(ValueError, "sem os totais bruto, desconto, liquido"):
            ler_relatorio(_pdf(linhas), "ddp.pdf")

    def test_conjunto_com_duas_tres_competencias_ou_repetido(self):
        relatorios = _relatorios_set()
        ddp_serv = relatorios[0]
        copia = lambda **kw: type(ddp_serv)(**{**ddp_serv.__dict__, **kw})
        self.assertEqual(validar_conjunto(relatorios + [copia(competencia=202610, nome="out.pdf")]), [])
        erros = validar_conjunto(relatorios + [copia(competencia=202610, nome="out.pdf"),
                                               copia(competencia=202611, nome="nov.pdf")])
        self.assertTrue(any("no máximo duas competências" in e for e in erros))
        erros = validar_conjunto(relatorios + [copia(nome="repetida.pdf")])
        self.assertEqual(erros, ["DDP de servidor (folha normal) de 09/2026 enviado duas vezes: "
                                 "ddp_siape_serv_2026-09.pdf e repetida.pdf."])
        self.assertEqual(validar_conjunto([r for r in relatorios if r.tipo == TIPO_CREDITO]),
                         ["Nenhuma DDP de 09/2026 entre os PDFs enviados (só Crédito Bancário)."])
        # só o crédito bancário do mês anterior: falta a DDP dele
        cred_out = [type(r)(**{**r.__dict__, "competencia": 202610}) for r in relatorios if r.tipo == TIPO_CREDITO]
        self.assertEqual(validar_conjunto(relatorios + cred_out),
                         ["Nenhuma DDP de 10/2026 entre os PDFs enviados (só Crédito Bancário)."])


def _ddp_pdf(mes: str, publico: str, naturezas: list[tuple[str, str, float]], anular: float = 0.0) -> bytes:
    """DDP mínima no layout do SIAPE; `naturezas` = (código x.xxxx.xx.xx, descrição, valor) da seção (1)."""
    bruto = sum(v for _, _, v in naturezas)
    fmt = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    linhas = [
        " __ SIAPE,GERENCIAL,GRFINANC,GRCOFINDDP ( DEMONS. DESPESA C/ PESSOAL-DDP )_____",
        f" DATA: 26{mes}2026    HORA: 07:31:54    USUARIO: XXXXXXXXXXXX             PRODUCAO",
        f" ORGAO SOLICITADO: 26248 UFRPE                          MES/ANO SOLIC: {mes}2026",
        f"       *** DDP FOLHA NORMAL - NIVEL UNIDADE PAGADORA - {publico} ***",
        "                       *** DESPESAS CORRENTES ( 1 ) ***",
        f" 3.3000       DESPESAS CORRENTES                    {fmt(bruto):>20}",
    ] + [f" {c} {d:<40} {fmt(v):>14}" for c, d, v in naturezas] + [
        "                             *** TOTAIS ( 5 ) ***",
        f"              99997 BRUTO                         {fmt(bruto):>20}",
        f"              99998 DESCONTO                      {fmt(anular):>20}",
        f"              99999 LIQUIDO                       {fmt(bruto - anular):>20}",
    ]
    return _pdf(linhas)


class TestVariacaoEntreCompetencias(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.setembro = _relatorios_set()
        # outubro sintético: vencimentos sobem, gratificação cai, licença-prêmio é nova; o resto não veio
        cls.outubro = [
            ler_relatorio(_ddp_pdf("OUT", "SERVIDOR", [("3.3190.11.01", "VENCIMENTO E SALARIOS", 16800000.00),
                                                        ("3.3190.11.31", "GRATIFICACAO DE EXERCICIO DE CARGO", 15000000.00)]), "serv.pdf"),
            ler_relatorio(_ddp_pdf("OUT", "PENSIONISTA", [("3.3190.03.06", "LICENCA PREMIO PENSIONISTA", 19150.48)]), "pens.pdf"),
        ]

    def test_mais_recente_e_a_do_reforco(self):
        atuais, anteriores = separar_competencias(self.setembro + self.outubro)
        self.assertEqual({r.competencia for r in atuais}, {202610})
        self.assertEqual({r.competencia for r in anteriores}, {202609})
        self.assertEqual(len(anteriores), 4)
        self.assertEqual(separar_competencias(self.setembro)[1], [])

    def test_variacao_por_natureza(self):
        variacao = variacao_por_natureza(ddp_por_natureza(self.outubro), ddp_por_natureza(self.setembro))
        v = variacao.set_index("natureza_detalhada")
        self.assertEqual((v.loc["31901101", "anterior"], v.loc["31901101", "atual"], v.loc["31901101", "variacao"]),
                         (16753889.62, 16800000.00, 46110.38))
        self.assertEqual(v.loc["31901101", "situacao"], "alta")
        self.assertEqual((v.loc["31901131", "variacao"], v.loc["31901131", "situacao"]), (-162405.86, "queda"))
        self.assertTrue(pd.isna(v.loc["31900306", "anterior"]))  # nova: anterior nulo, não zero
        self.assertEqual((v.loc["31900306", "variacao"], v.loc["31900306", "situacao"]), (19150.48, "nova"))
        self.assertTrue(pd.isna(v.loc["31900301", "atual"]))
        self.assertEqual((v.loc["31900301", "variacao"], v.loc["31900301", "situacao"]), (-4628906.71, "saiu"))
        # a soma das variações fecha com a diferença dos totais; maior variação primeiro
        self.assertEqual(round(variacao["variacao"].sum(), 2),
                         round(variacao["atual"].sum() - variacao["anterior"].sum(), 2))
        self.assertEqual(variacao["natureza_detalhada"].iloc[0], "31900101")  # proventos (~R$ 11 mi) não vieram
        # servidor + pensionista somados na mesma natureza (per capita de set/2026)
        self.assertEqual(v.loc["33909308", "anterior"], 333893.66)

    def test_conferencia_traz_as_duas_competencias(self):
        conf = conferencia(self.setembro + self.outubro)
        self.assertEqual(conf["competencia"].tolist(), [202610, 202610, 202609, 202609])
        self.assertEqual(conf.loc[conf["competencia"] == 202610, "dif_bruto_menos_desconto"].abs().max(), 0.0)


# ---------------------------------------------------------------------------
# Base mensal sintética
# ---------------------------------------------------------------------------

UG = "UNIVERSIDADE TESTE"


def _ne(n: int) -> str:
    return f"153165152392026NE{n:06d}"


def _linha(ne: int, natureza: str, tipo: str, ano_mes: int, empenhada=0.0, liquidada=0.0,
           favorecido: str = UG, acao: str = "20TP") -> dict:
    linha = {coluna: "X" for coluna in _DIMENSOES_EXTRA_BLOCO.values()}
    linha.update({
        "ano": ano_mes // 100, "ano_mes": ano_mes, "mes": ano_mes % 100, "tipo_linha": tipo, "ne_ccor": _ne(ne),
        "natureza_detalhada_cod": natureza, "subitem_cod": natureza[-2:], "acao_cod": acao,
        "ne_item_cod": "1" if tipo == "empenho" else "-9", "ne_favorecido": favorecido, "ug_executora_desc": UG,
        "empenhada": empenhada if tipo == "empenho" else 0.0, "liquidada": liquidada if tipo == "item_execucao" else 0.0,
    })
    return linha


def _item(ne, natureza, empenhado, liquidado_por_mes: dict[int, float], **kw) -> list[dict]:
    linhas = [_linha(ne, natureza, "empenho", 202601, empenhada=empenhado, **kw)]
    linhas += [_linha(ne, natureza, "item_execucao", am, liquidada=v, **kw) for am, v in liquidado_por_mes.items()]
    return linhas


def _base_sintetica() -> pd.DataFrame:
    linhas = []
    # NE 1: falta em 31901101 compensada pela sobra livre do 13º (31901143), fora da DDP
    linhas += _item(1, "31901101", 1000.0, {202608: 400.0, 202609: 300.0})            # saldo 300
    linhas += _item(1, "31901143", 5000.0, {})                                         # saldo 5000
    # NE 2 e NE 3: per capita repartido pelo liquidado de setembro (300 × 100); NE 9 é a operadora
    linhas += _item(2, "33909308", 400.0, {202609: 300.0}, acao="2004")                # saldo 100
    linhas += _item(3, "33909308", 600.0, {202609: 100.0}, acao="2004")                # saldo 500
    linhas += _item(9, "33909308", 9000.0, {202609: 900.0}, acao="2004", favorecido="OPERADORA DE SAUDE")
    # NE 4 e NE 5: mesma natureza, sem liquidado em setembro — somados
    linhas += _item(4, "31909201", 10.0, {}, acao="0181")
    linhas += _item(5, "31909201", 20.0, {}, acao="0181")
    # NE 6: pensões; a licença-prêmio (31900306) não tem item, mas o elemento 319003 só está aqui
    linhas += _item(6, "31900301", 100.0, {202609: 50.0}, acao="0181")
    # empenho de outro exercício não entra
    linhas.append({**_linha(7, "31901101", "empenho", 202509, empenhada=10**6), "ano": 2025})
    return pd.DataFrame(linhas)


def _ddp_sintetica() -> pd.DataFrame:
    linhas = [
        ("31901101", "SERVIDOR", 500.0), ("33909308", "SERVIDOR", 300.0), ("33909308", "PENSIONISTA", 100.0),
        ("31909201", "SERVIDOR", 50.0), ("31900301", "PENSIONISTA", 50.0), ("31900306", "PENSIONISTA", 19.0),
        ("31909211", "SERVIDOR", 7.0),
    ]
    return pd.DataFrame([{"natureza_detalhada": n, "publico": p, "descricao": f"DESC {n}", "despesa": v,
                          "anular": 0.0, "liquido": v} for n, p, v in linhas])


RESERVA = {"31901101": 1000.0, "31901143": 3000.0, "33909308": 99999.0, "31900301": 100.0}


class TestQuadroReforco(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.itens, cls.por_empenho = quadro_reforco(_ddp_sintetica(), _base_sintetica(), 202610, RESERVA)
        cls.item = cls.itens.set_index(["empenho", "natureza_detalhada"])
        cls.ne = cls.por_empenho.set_index("empenho")

    def test_falta_compensada_pela_sobra_livre_da_mesma_ne(self):
        self.assertEqual(self.item.loc[("NE000001", "31901101"), "falta"], 200.0)
        decimo = self.item.loc[("NE000001", "31901143")]
        self.assertEqual((decimo["ddp"], decimo["reserva"], decimo["sobra_livre"]), (0.0, 3000.0, 2000.0))
        ne = self.ne.loc["NE000001"]
        self.assertEqual((ne["falta"], ne["compensa"], ne["reforco_mes"]), (200.0, 200.0, 0.0))
        # (300 − 500 − 1000) + (5000 − 0 − 3000) = 800 ⇒ nada a reforçar até dezembro
        self.assertEqual((ne["saldo_apos_ano"], ne["reforco_ate_dezembro"]), (800.0, 0.0))

    def test_per_capita_repartido_e_reserva_pela_ddp_quando_ha_empenho_fora_da_folha(self):
        b, c = self.item.loc[("NE000002", "33909308")], self.item.loc[("NE000003", "33909308")]
        self.assertEqual((b["ddp"], c["ddp"]), (300.0, 100.0))  # 400 × 0,75 e × 0,25
        self.assertEqual((b["criterio"], b["tipo_reserva"]), (CRITERIO_REPARTIDO, RESERVA_DDP))
        self.assertEqual((b["reserva"], c["reserva"]), (600.0, 200.0))  # DDP × 2 meses restantes
        self.assertEqual((b["falta"], c["falta"], c["sobra_livre"]), (200.0, 0.0, 200.0))
        # NEs diferentes não se compensam
        self.assertEqual(self.ne.loc["NE000002", "reforco_mes"], 200.0)
        self.assertEqual(self.ne.loc["NE000002", "reforco_ate_dezembro"], 800.0)
        self.assertNotIn("NE000009", self.ne.index)  # favorecido não é a UG: fora da folha

    def test_sem_liquidado_no_mes_anterior_os_empenhos_sao_somados(self):
        linha = self.item.loc[("NE000004 + NE000005", "31909201")]
        self.assertEqual((linha["saldo"], linha["ddp"], linha["falta"], linha["criterio"]), (30.0, 50.0, 20.0, CRITERIO_SOMADO))

    def test_natureza_sem_item_vai_para_o_empenho_do_mesmo_elemento_ou_fica_sem_empenho(self):
        licenca = self.item.loc[("NE000006", "31900306")]
        self.assertEqual((licenca["saldo"], licenca["falta"], licenca["criterio"]), (0.0, 19.0, CRITERIO_ELEMENTO))
        self.assertEqual(self.ne.loc["NE000006", "reforco_mes"], 19.0)
        # 319092: dois empenhos (4 e 5) com o elemento — não escolhe
        dea = self.item.loc[(SEM_EMPENHO, "31909211")]
        self.assertEqual((dea["falta"], dea["criterio"]), (7.0, CRITERIO_SEM_EMPENHO))
        self.assertEqual(self.item.loc[("NE000006", "31900301"), "criterio"], CRITERIO_UNICO)
        self.assertEqual(self.item.loc[("NE000001", "31901101"), "tipo_reserva"], RESERVA_PROJECAO)

    def test_totais_do_mes(self):
        # 200 (NE 2) + 20 (NE 4+5) + 19 (NE 6) + 7 (sem empenho); NE 1 compensa os seus 200
        self.assertEqual(round(self.por_empenho["reforco_mes"].sum(), 2), 246.0)
        self.assertEqual(round(self.por_empenho["falta"].sum(), 2), 446.0)
        self.assertNotIn("NE000007", " ".join(self.itens["empenho"]))  # outro exercício

    def test_liquidado_ja_lancado_no_mes_aparece_e_reduz_o_saldo(self):
        base = pd.concat([_base_sintetica(), pd.DataFrame([_linha(1, "31901101", "item_execucao", 202610, liquidada=500.0)])])
        itens, _ = quadro_reforco(_ddp_sintetica(), base, 202610, RESERVA)
        linha = itens.set_index(["empenho", "natureza_detalhada"]).loc[("NE000001", "31901101")]
        self.assertEqual((linha["liquidado_no_mes"], linha["saldo"], linha["falta"]), (500.0, -200.0, 700.0))


class TestRppsPatronalSemDdp(unittest.TestCase):
    """Contribuição patronal ao RPPS: não está na DDP; o mês vem da projeção (grade)."""

    @classmethod
    def setUpClass(cls):
        rpps = _item(10, "31911303", 1000.0, {202608: 300.0, 202609: 300.0}, acao="09HB", favorecido="FUNDO RPPS")
        cls.base = pd.concat([_base_sintetica(), pd.DataFrame(rpps)], ignore_index=True)
        cls.grade = pd.DataFrame([
            {"grupo": GRUPO_RPPS, "natureza_detalhada_cod": "31911303", "natureza_detalhada_desc": "PATRONAL RPPS",
             "meses": [None] * 7 + [300.0, 300.0, 350.0, 700.0, 350.0]},
            {"grupo": "ativo", "natureza_detalhada_cod": "31901101", "natureza_detalhada_desc": "VENC", "meses": [1.0] * 12},
        ])
        cls.itens, cls.por_empenho = quadro_sem_ddp(cls.base, 202610, cls.grade, GRUPO_RPPS)

    def test_mes_da_projecao_reserva_com_13o_e_empenho_fora_da_folha(self):
        self.assertEqual(self.itens["empenho"].tolist(), ["NE000010"])  # favorecido não é a UG, entra mesmo assim
        item = self.itens.iloc[0]
        self.assertEqual((item["saldo"], item["ddp"], item["reserva"], item["tipo_reserva"]),
                         (400.0, 350.0, 1050.0, RESERVA_PROJECAO))
        ne = self.por_empenho.iloc[0]
        self.assertEqual((ne["reforco_mes"], ne["reforco_ate_dezembro"]), (0.0, 1000.0))

    def test_conciliacao_com_o_painel(self):
        c = conciliacao_sem_ddp(self.itens, self.grade, GRUPO_RPPS, 202610, 1900.0)
        self.assertEqual((c["total_ano"], c["empenhado"], c["liquidado"]), (2000.0, 1000.0, 600.0))
        self.assertEqual((c["deficit_dotacao"], c["dotacao_nao_empenhada"], c["diferenca_meses_anteriores"]),
                         (100.0, 900.0, 0.0))
        self.assertEqual(c["reforco_ate_dezembro"],
                         c["deficit_dotacao"] + c["dotacao_nao_empenhada"] + c["diferenca_meses_anteriores"])
        sem = conciliacao_sem_ddp(self.itens, self.grade, GRUPO_RPPS, 202610, None)
        self.assertIsNone(sem["deficit_dotacao"])
        self.assertIsNone(sem["dotacao_nao_empenhada"])

    def test_mes_nulo_na_grade_conta_zero_e_folha_nao_muda(self):
        grade = self.grade.copy()
        grade.at[0, "meses"] = [None] * 9 + [None, 700.0, 350.0]
        itens, _ = quadro_sem_ddp(self.base, 202610, grade, GRUPO_RPPS)
        self.assertEqual(itens.iloc[0]["ddp"], 0.0)
        # o quadro da DDP continua só com os empenhos da folha: o do RPPS não entra
        itens_ddp, _ = quadro_reforco(_ddp_sintetica(), self.base, 202610, RESERVA)
        self.assertNotIn("NE000010", set(itens_ddp["empenho"]))


class TestPlanoOperacoes(unittest.TestCase):
    def test_plano_da_base_sintetica_fecha_com_o_quadro(self):
        itens, por_empenho = quadro_reforco(_ddp_sintetica(), _base_sintetica(), 202610, RESERVA)
        plano = plano_operacoes(itens)
        remanejar = plano.loc[plano["operacao"] == OPERACAO_REMANEJAR]
        self.assertEqual(remanejar[["empenho", "item_origem", "item_destino", "valor"]].values.tolist(),
                         [["NE000001", "31901143", "31901101", 200.0]])
        novos = plano.loc[plano["operacao"] == OPERACAO_REFORCO].set_index("empenho")
        self.assertEqual(novos["valor"].to_dict(),
                         {"(sem empenho)": 7.0, "NE000002": 200.0, "NE000004 + NE000005": 20.0, "NE000006": 19.0})
        self.assertTrue(novos["item_origem"].isna().all())
        self.assertEqual(round(novos["valor"].sum(), 2), round(por_empenho["reforco_mes"].sum(), 2))

    def test_reparte_maior_falta_pela_maior_sobra_sem_passar_da_sobra_livre(self):
        itens = pd.DataFrame([
            {"empenho": "NE1", "natureza_detalhada": "A", "falta": 70.0, "sobra_livre": 0.0},
            {"empenho": "NE1", "natureza_detalhada": "B", "falta": 50.0, "sobra_livre": 0.0},
            {"empenho": "NE1", "natureza_detalhada": "C", "falta": 0.0, "sobra_livre": 60.0},
            {"empenho": "NE1", "natureza_detalhada": "D", "falta": 0.0, "sobra_livre": 40.005},
            {"empenho": "NE2", "natureza_detalhada": "A", "falta": 0.0, "sobra_livre": 999.0},  # outra NE: não ajuda
        ])
        plano = plano_operacoes(itens)
        # D tem 40,005 de sobra livre: cede 40,00, nunca 40,01
        self.assertEqual(plano.fillna({"item_origem": "—"})[["operacao", "item_origem", "item_destino", "valor"]].values.tolist(), [
            [OPERACAO_REMANEJAR, "C", "A", 60.0], [OPERACAO_REMANEJAR, "D", "A", 10.0],
            [OPERACAO_REMANEJAR, "D", "B", 30.0], [OPERACAO_REFORCO, "—", "B", 20.0],
        ])
        self.assertEqual(set(plano["empenho"]), {"NE1"})

    def test_sem_falta_plano_vazio(self):
        itens = pd.DataFrame([{"empenho": "NE1", "natureza_detalhada": "A", "falta": 0.0, "sobra_livre": 5.0}])
        self.assertTrue(plano_operacoes(itens).empty)


class TestReservaEConfronto(unittest.TestCase):
    def test_reserva_soma_meses_depois_da_ddp_e_nulo_nao_conta(self):
        grade = pd.DataFrame([
            {"natureza_detalhada_cod": "31901101", "meses": [1.0] * 9 + [10.0, 20.0, None]},
            {"natureza_detalhada_cod": "31901101", "meses": [0.0] * 11 + [5.0]},
            {"natureza_detalhada_cod": "31901143", "meses": [None] * 12},
        ])
        self.assertEqual(reserva_projetada(grade, 10), {"31901101": 25.0, "31901143": 0.0})

    def test_confronto_so_naturezas_da_ddp_e_empenhos_da_folha(self):
        base = pd.concat([_base_sintetica(), pd.DataFrame([
            _linha(1, "31901101", "item_execucao", 202610, liquidada=480.0),
            _linha(9, "33909308", "item_execucao", 202610, liquidada=900.0, favorecido="OPERADORA DE SAUDE"),
            _linha(8, "33901414", "item_execucao", 202610, liquidada=70.0),  # diária: não está na DDP
        ])])
        tabela = confronto_liquidado(_ddp_sintetica(), base, 202610).set_index("natureza_detalhada")
        self.assertNotIn("33901414", tabela.index)
        self.assertEqual(tabela.loc["31901101", "diferenca"], -20.0)
        self.assertEqual(tabela.loc["33909308", "liquidado_no_mes"], 0.0)  # a operadora não conta


class TestTabelasDaAba(unittest.TestCase):
    def test_situacao_da_conferencia(self):
        from src.ui_ddp_siape import tabela_conferencia

        relatorios = _relatorios_set()
        self.assertEqual(tabela_conferencia(conferencia(relatorios))["Situação"].tolist(), ["Confere", "Confere"])
        so_ddp = conferencia([r for r in relatorios if r.tipo == TIPO_DDP])
        self.assertEqual(tabela_conferencia(so_ddp).loc[0, "Crédito bancário"], "—")
        self.assertIn("crédito bancário não enviado", tabela_conferencia(so_ddp).loc[0, "Situação"])
        divergente = conferencia(relatorios).assign(dif_credito=[0.0, -10.0])
        self.assertEqual(tabela_conferencia(divergente).loc[1, "Situação"],
                         "Diferença — crédito bancário ≠ líquido: −R$ 10,00")

    def test_plano_e_planilha(self):
        from io import BytesIO
        from src.ui_ddp_siape import planilha_excel, tabela_plano

        itens, por_empenho = quadro_reforco(_ddp_sintetica(), _base_sintetica(), 202610, RESERVA)
        plano = plano_operacoes(itens)
        tabela = tabela_plano(plano, itens).set_index("Empenho")
        self.assertEqual(tabela.loc["NE000001", "Anular do item"], "31901143 X")  # fora da DDP: descrição da base
        self.assertEqual(tabela.loc["NE000001", "Reforçar o item"], "31901101 DESC 31901101")
        self.assertEqual(tabela.loc["NE000002", "Anular do item"], "—")
        conteudo = planilha_excel(202610, conferencia(_relatorios_set()), plano, por_empenho, itens)
        abas = pd.read_excel(BytesIO(conteudo), sheet_name=None)
        self.assertEqual(list(abas), ["Plano por item", "Por empenho", "Itens", "Conferência", "Referência"])
        self.assertEqual(round(abas["Plano por item"]["valor"].sum(), 2), 446.0)  # 200 remanejados + 246 novos


if __name__ == "__main__":
    unittest.main()
