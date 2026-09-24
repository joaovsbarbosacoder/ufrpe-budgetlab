"""
Testes da conciliação da célula orçamentária NC × NE (`src/teds_celula_orcamentaria.py`).

Os layouts das duas bases de NC do Tesouro Gerencial reproduzem os arquivos reais (24/09/2026): cabeçalho de
3 linhas, colunas de descrição sem título, apóstrofo inicial em códigos ("'-8") e, em 2026, células ORIGEM e
DESTINO. Os valores são fictícios. O caso de referência é o do briefing: NE 2025NE000706 do TED 12112
(transferência 1AAMVG) com natureza 339032, ausente das NCs (que trazem 339014, 339030, 339033, 339036, 339039
e 339040).
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd

from src.teds_alertas import Alerta
from src.teds_celula_orcamentaria import (
    ESTADO_BASE_INCOMPLETA,
    ESTADO_CORRESPONDENTE,
    ESTADO_DIVERGENCIA,
    TIPO_NE_CELULA_DIVERGE_NC,
    CelulaNcTg,
    CelulaNe,
    NcSimec,
    VinculoNe,
    carregar_conciliacao_celulas,
    conciliar_celulas,
    gerar_alertas_celula,
    ler_nc_tg_2026,
    ler_nc_tg_historica,
    montar_ne_celulas,
    resultados_para_tabela,
    sincronizar_alertas_celula_orcamentaria,
)
from src.teds_lotes import (
    importar_doc_nc,
    importar_doc_ne,
    importar_nc_tg_2026,
    importar_nc_tg_historica,
    sincronizar_execucao_tg,
)
from src.teds_normalizacao import ColunaObrigatoriaAusente, chave_empenho, chave_ted
from src.teds_reversao import reverter_lote
from src.teds_schema import conectar

NAN = np.nan
TED = chave_ted("12112", "1AAMVG")
CE = chave_empenho("153165", "15239", "2025NE000706")

_ROTULOS_HIST = [
    "Unidade Orçamentária", NAN, "Ano Lançamento", "NC - Ano Emissão", "NC - Dia Emissão", "NC", "NC - Transferência",
    "NC - Operação (Tipo)", "NC - Descrição", "NC - Tipo Descentralização", "Documento", "Autor Emendas Orçamento", NAN,
    "Resultado Lei", NAN, "Natureza Despesa", NAN, "PTRES", "PI", NAN, "Fonte Recursos Detalhada", NAN,
    "Item Informação", NAN, 17,
]
_ROTULOS_2026 = [
    "Emitente - Órgão", NAN, "Emitente - UG", NAN, "NC", "Favorecido Doc.", NAN, "NC Célula - Esfera Orçamentária", NAN,
    "NC Célula - Fonte Recurso Det.", NAN, "NC Célula - Natureza Despesa", NAN, "NC Célula - Plano Interno", NAN,
    "NC Célula - PTRES", "NC Célula - Tipo", "NC Item - RO Operação", "NC - Transferência", "NC - Tipo Descentralização",
    "NC - Descrição", "Doc - Observação", "Item Informação", 17,
]


def _bruto_hist(linhas):
    """linhas = (nc, transferência, natureza, ptres, pi, fonte, saldo)."""

    cab0 = _ROTULOS_HIST
    cab1 = [NAN] * 25
    cab2 = [NAN] * 25
    cab2[22], cab2[24] = "NC - UG Responsável", "Saldo - Moeda Origem (Item Informação)"
    dados = []
    for nc, transf, natureza, ptres, pi, fonte, saldo in linhas:
        linha = [NAN] * 25
        linha[5], linha[6], linha[15], linha[17], linha[18], linha[20], linha[24] = nc, transf, natureza, ptres, pi, fonte, saldo
        dados.append(linha)
    return pd.DataFrame([cab0, cab1, cab2] + dados, dtype=object)


def _bruto_2026(linhas):
    """linhas = (nc, transferência, natureza, ptres, pi, fonte, tipo, valor_celula)."""

    cab0 = _ROTULOS_2026
    cab1 = [NAN] * 24
    cab2 = [NAN] * 24
    cab2[22], cab2[23] = "NC Célula - Valor", "Saldo - Moeda Origem (Item Informação)"
    dados = []
    for nc, transf, natureza, ptres, pi, fonte, tipo, valor in linhas:
        linha = [NAN] * 24
        linha[4], linha[18], linha[11], linha[15], linha[13], linha[9], linha[16], linha[22] = (
            nc, transf, natureza, ptres, pi, fonte, tipo, valor,
        )
        dados.append(linha)
    return pd.DataFrame([cab0, cab1, cab2] + dados, dtype=object)


def _como_header0(bruto):
    """Como `pd.read_excel(caminho)` entrega: a linha 1 do cabeçalho vira o nome das colunas."""

    nomes = [v if not pd.isna(v) else f"Unnamed: {i}" for i, v in enumerate(bruto.iloc[0])]
    return pd.DataFrame(bruto.iloc[1:].values.tolist(), columns=nomes)


NC_A = "154003152792025NC000408"
NC_B = "152734000012025NC000408"  # mesmo ano e número, OUTRA UG e outra transferência


class LeitorHistoricoTests(unittest.TestCase):
    def _linhas(self):
        return [
            (NC_A, "1AAMVG", "339014", "230551", "MCC62G22EDN", "1000A00238", 100.0),
            (NC_A, "1AAMVG", "339014", "230551", "MCC62G22EDN", "1000A00238", 50.5),  # mesma célula: agrega
            (NC_A, "1AAMVG", "339030", "230551", "MCC62G22EDN", "1000A00238", 10.0),
            (NC_B, "'-8", "000012", "0100", "0PI", "0FONTE", 5.0),
        ]

    def test_le_os_dois_layouts_com_o_mesmo_resultado(self):
        bruto = _bruto_hist(self._linhas())
        a = ler_nc_tg_historica(bruto)
        b = ler_nc_tg_historica(_como_header0(bruto))
        self.assertEqual(a.registros, b.registros)
        self.assertEqual(len(a.registros), 3)

    def test_agrega_linhas_iguais_e_guarda_as_linhas_de_origem_e_a_soma_direta(self):
        (r,) = [x for x in ler_nc_tg_historica(_bruto_hist(self._linhas())).registros if x["natureza"] == "339014"]
        self.assertEqual(r["quantidade_linhas"], 2)
        self.assertEqual(r["linhas_origem"], [4, 5])  # linhas da planilha (1 = 1ª linha do cabeçalho)
        self.assertEqual(r["valor"], Decimal("150.50"))
        self.assertEqual(r["metrica_valor"], "saldo_moeda_origem")
        self.assertEqual((r["sufixo_nc"], r["ug_emitente"], r["ano_emissao"]), ("2025NC000408", "154003", 2025))
        self.assertEqual(r["tipo_celula"], "")

    def test_apostrofo_inicial_sai_e_zeros_a_esquerda_ficam(self):
        registros = ler_nc_tg_historica(_bruto_hist(self._linhas())).registros
        (b,) = [x for x in registros if x["nc_completa"] == NC_B]
        self.assertEqual(b["transferencia"], "-8")
        self.assertEqual((b["natureza"], b["ptres"]), ("000012", "0100"))

    def test_nc_fora_do_formato_e_rejeitada_com_motivo_e_nao_entra(self):
        leitura = ler_nc_tg_historica(_bruto_hist(self._linhas() + [("700014", "1AAMVG", "339014", "1", "P", "F", 1.0)]))
        self.assertEqual(len(leitura.rejeitadas), 1)
        self.assertIn("fora do formato", leitura.rejeitadas[0].motivo)
        self.assertEqual(leitura.linhas_lidas, 5)
        self.assertEqual(len(leitura.registros), 3)

    def test_coluna_obrigatoria_ausente_rejeita_o_arquivo(self):
        bruto = _bruto_hist(self._linhas())
        bruto.iloc[0, 17] = "Outra coisa"  # some o rótulo PTRES
        with self.assertRaises(ColunaObrigatoriaAusente) as erro:
            ler_nc_tg_historica(bruto)
        self.assertIn("ptres", erro.exception.campos_faltando)

    def test_arquivo_vazio(self):
        with self.assertRaises(ColunaObrigatoriaAusente):
            ler_nc_tg_historica(pd.DataFrame())


class Leitor2026Tests(unittest.TestCase):
    def _linhas(self):
        return [
            ("373001372012026NC000363", "1AAZUV", "339014", "235422", "D210T000203", "1052000231", "ORIGEM", 1675.0),
            ("373001372012026NC000363", "1AAZUV", "339014", "235422", "D210T000203", "1052000231", "DESTINO", 1675.0),
        ]

    def test_guarda_origem_e_destino_sem_somar_entre_elas(self):
        leitura = ler_nc_tg_2026(_bruto_2026(self._linhas()))
        self.assertEqual(sorted(r["tipo_celula"] for r in leitura.registros), ["DESTINO", "ORIGEM"])
        for r in leitura.registros:
            self.assertEqual(r["valor"], Decimal("1675.00"))  # cada célula com o próprio valor: nunca 3350
            self.assertEqual(r["metrica_valor"], "nc_celula_valor")

    def test_layout_header0(self):
        bruto = _bruto_2026(self._linhas())
        self.assertEqual(ler_nc_tg_2026(bruto).registros, ler_nc_tg_2026(_como_header0(bruto)).registros)

    def test_relatorio_historico_nao_serve_como_2026(self):
        with self.assertRaises(ColunaObrigatoriaAusente):
            ler_nc_tg_2026(_bruto_hist([(NC_A, "1AAMVG", "339014", "1", "P", "F", 1.0)]))


class CelulasDaNeTests(unittest.TestCase):
    def _df(self, linhas):
        return pd.DataFrame(
            linhas, columns=["ne_ccor", "linha_origem", "ptres", "fonte_recursos_detalhada_cod", "natureza_despesa_cod", "pi_cod"]
        )

    def test_celulas_distintas_por_ne_com_as_linhas_de_origem(self):
        ccor = "153165152392025NE000706"
        df = self._df([
            (ccor, 10, 230551, "1000A00238", "339032", "MCC62G22EDN"),
            (ccor, 10, 230551, "1000A00238", "339032", "MCC62G22EDN"),  # mesma linha × mês: não duplica
            (ccor, 11, 230551, "1000A00238", "339032", "MCC62G22EDN"),
            (ccor, 12, 230551, "1000A00238", "339030", "MCC62G22EDN"),
        ])
        resultado = montar_ne_celulas(df)
        self.assertEqual(len(resultado.registros), 2)
        (r,) = [x for x in resultado.registros if x["natureza"] == "339032"]
        self.assertEqual((r["numero_ne"], r["ug_emitente"], r["ptres"]), ("2025NE000706", "153165", "230551"))
        self.assertEqual(r["linhas_origem"], [10, 11])

    def test_ne_fora_do_formato_e_rejeitada(self):
        resultado = montar_ne_celulas(self._df([("xyz", 5, 1, "F", "339030", "P")]))
        self.assertEqual(resultado.registros, [])
        self.assertEqual(len(resultado.rejeitadas), 1)

    def test_sem_as_colunas_de_celula_devolve_vazio_e_nao_falha(self):
        self.assertEqual(montar_ne_celulas(pd.DataFrame({"ne_ccor": ["x"]})).registros, [])
        self.assertEqual(montar_ne_celulas(pd.DataFrame()).registros, [])


def _tg(nc, transf, natureza, ptres="230551", pi="MCC62G22EDN", fonte="1000A00238", tipo="", linhas=(4,)):
    return CelulaNcTg(nc, nc[-12:], nc[:6], int(nc[-12:-8]), transf, tipo, (ptres, fonte, natureza, pi), tuple(linhas))


def _vinculo(ne="2025NE000706", status="ok", chave=TED, ted="12112", siafi="1AAMVG"):
    return VinculoNe(chave, ted, siafi, chave_empenho("153165", "15239", ne), ne, status)


def _ne(ne="2025NE000706", natureza="339032", ptres="230551", pi="MCC62G22EDN", fonte="1000A00238", linhas=(20,)):
    return CelulaNe(ne, (ptres, fonte, natureza, pi), tuple(linhas))


def _nc(numero="2025NC000408", siafi="1AAMVG", ug=None, chave=TED):
    return NcSimec(chave, numero, siafi, ug)


class ConciliacaoTests(unittest.TestCase):
    def _um(self, *args, **kw):
        resultados = conciliar_celulas(*args, **kw)
        self.assertEqual(len(resultados), 1, resultados)
        return resultados[0]

    def test_correspondente_quando_algum_conjunto_de_nc_tem_os_quatro_campos(self):
        r = self._um([_nc()], [_tg(NC_A, "1AAMVG", "339032"), _tg(NC_A, "1AAMVG", "339030")], [_vinculo()], [_ne()])
        self.assertEqual(r.situacao, ESTADO_CORRESPONDENTE)
        self.assertEqual(r.ncs_consideradas, ("2025NC000408",))
        self.assertEqual(r.campos_divergentes, ())

    def test_caso_de_referencia_natureza_ausente_nas_ncs(self):
        naturezas = ["339014", "339030", "339033", "339036", "339039", "339040"]
        r = self._um([_nc()], [_tg(NC_A, "1AAMVG", n) for n in naturezas], [_vinculo()], [_ne(natureza="339032")])
        self.assertEqual(r.situacao, ESTADO_DIVERGENCIA)
        self.assertEqual(r.campos_divergentes, ("natureza",))
        self.assertEqual(r.valores_nas_ncs["natureza"], tuple(naturezas))
        self.assertNotIn("339032", r.valores_nas_ncs["natureza"])
        self.assertIn("natureza da despesa", r.motivo)
        self.assertEqual(r.celula_ne, ("230551", "1000A00238", "339032", "MCC62G22EDN"))

    def test_varios_campos_divergentes_e_a_celula_de_nc_mais_parecida(self):
        r = self._um([_nc()], [_tg(NC_A, "1AAMVG", "339014")], [_vinculo()], [_ne(natureza="339032", ptres="999999")])
        self.assertEqual(r.campos_divergentes, ("ptres", "natureza"))

    def test_o_sufixo_sozinho_nao_liga_a_nc_desambigua_pela_transferencia(self):
        # NC_B tem o mesmo ano e número, mas é de outra UG e outra transferência: não pode ser considerada.
        tg = [_tg(NC_A, "1AAMVG", "339032"), _tg(NC_B, "1ZZZZZ", "339999")]
        r = self._um([_nc()], tg, [_vinculo()], [_ne(natureza="339032")])
        self.assertEqual(r.situacao, ESTADO_CORRESPONDENTE)
        self.assertNotIn(("230551", "1000A00238", "339999", "MCC62G22EDN"), r.celulas_nc)

    def test_ug_emitente_do_simec_desambigua_quando_informada(self):
        tg = [_tg(NC_A, "1AAMVG", "339030"), _tg(NC_B, "1AAMVG", "339032")]  # mesma transferência, UGs diferentes
        r = self._um([_nc(ug="152734")], tg, [_vinculo()], [_ne(natureza="339032")])
        self.assertEqual(r.situacao, ESTADO_CORRESPONDENTE)
        r2 = self._um([_nc(ug="154003")], tg, [_vinculo()], [_ne(natureza="339032")])
        self.assertEqual(r2.situacao, ESTADO_DIVERGENCIA)

    def test_em_2026_so_a_celula_destino_conta(self):
        nc = "373001372012026NC000363"
        tg = [_tg(nc, "1AAMVG", "339020", tipo="ORIGEM"), _tg(nc, "1AAMVG", "339014", tipo="DESTINO")]
        ne = _ne(ne="2026NE000001", natureza="339020")
        r = self._um([_nc("2026NC000363")], tg, [_vinculo("2026NE000001")], [ne])
        self.assertEqual(r.situacao, ESTADO_DIVERGENCIA)  # 339020 só existe na ORIGEM
        self.assertEqual(r.celulas_nc, (("230551", "1000A00238", "339014", "MCC62G22EDN"),))

    def test_so_as_ncs_do_mesmo_exercicio_da_ne(self):
        tg = [_tg("154003152792024NC000408", "1AAMVG", "339032")]
        r = self._um([_nc("2024NC000408")], tg, [_vinculo("2025NE000706")], [_ne()])
        self.assertEqual(r.situacao, ESTADO_BASE_INCOMPLETA)
        self.assertIn("não tem NC do exercício 2025", r.motivo)

    def test_base_incompleta_quando_a_nc_nao_esta_no_tg(self):
        r = self._um([_nc()], [], [_vinculo()], [_ne()])
        self.assertEqual(r.situacao, ESTADO_BASE_INCOMPLETA)
        self.assertEqual(r.ncs_nao_identificadas, 1)
        self.assertIn("localizada no Tesouro", r.motivo)

    def test_nc_abreviada_nunca_casa_e_nao_vira_divergencia(self):
        r = self._um([_nc("700014")], [_tg(NC_A, "1AAMVG", "339032")], [_vinculo()], [_ne()])
        self.assertEqual(r.situacao, ESTADO_BASE_INCOMPLETA)
        self.assertIn("número abreviado", r.motivo)

    def test_divergencia_com_nc_abreviada_no_ted_marca_comparacao_possivelmente_incompleta(self):
        r = self._um(
            [_nc(), _nc("700014")], [_tg(NC_A, "1AAMVG", "339030")], [_vinculo()], [_ne(natureza="339032")]
        )
        self.assertEqual(r.situacao, ESTADO_DIVERGENCIA)
        self.assertTrue(r.comparacao_pode_estar_incompleta)

    def test_ne_sem_celula_na_base(self):
        r = self._um([_nc()], [_tg(NC_A, "1AAMVG", "339032")], [_vinculo()], [])
        self.assertEqual(r.situacao, ESTADO_BASE_INCOMPLETA)
        self.assertIsNone(r.celula_ne)

    def test_ne_com_duas_celulas_cada_uma_e_avaliada(self):
        tg = [_tg(NC_A, "1AAMVG", "339032")]
        resultados = conciliar_celulas([_nc()], tg, [_vinculo()], [_ne(natureza="339032"), _ne(natureza="339039")])
        self.assertEqual(sorted(r.situacao for r in resultados), sorted([ESTADO_CORRESPONDENTE, ESTADO_DIVERGENCIA]))

    def test_coincidencia_de_celula_nao_cria_vinculo(self):
        # Há NE com a mesma célula e NC do TED, mas SEM vínculo TED × NE: nada é comparado.
        self.assertEqual(conciliar_celulas([_nc()], [_tg(NC_A, "1AAMVG", "339032")], [], [_ne()]), [])

    def test_vinculo_pendente_entra_com_o_status_visivel(self):
        r = self._um([_nc()], [_tg(NC_A, "1AAMVG", "339032")], [_vinculo(status="pendente")], [_ne()])
        self.assertEqual(r.status_vinculo, "pendente")

    def test_codigos_sao_comparados_como_texto_zeros_a_esquerda_contam(self):
        r = self._um([_nc()], [_tg(NC_A, "1AAMVG", "000012", ptres="0100")], [_vinculo()], [_ne(natureza="12", ptres="100")])
        self.assertEqual(r.situacao, ESTADO_DIVERGENCIA)
        self.assertEqual(r.campos_divergentes, ("ptres", "natureza"))


class AlertasETabelaTests(unittest.TestCase):
    def _divergente(self, abreviada=False):
        ncs = [_nc()] + ([_nc("700014")] if abreviada else [])
        naturezas = ["339014", "339030", "339033", "339036", "339039", "339040"]
        return conciliar_celulas(ncs, [_tg(NC_A, "1AAMVG", n) for n in naturezas], [_vinculo()], [_ne()])

    def test_so_divergencia_gera_alerta_e_o_texto_e_de_conferencia(self):
        (alerta,) = gerar_alertas_celula(self._divergente())
        self.assertIsInstance(alerta, Alerta)
        self.assertEqual((alerta.tipo, alerta.gravidade, alerta.chave_ted), (TIPO_NE_CELULA_DIVERGE_NC, "alta", TED))
        self.assertEqual(alerta.documento, f"{TED}|{CE}")
        for esperado in ("2025NE000706", "12112", "1AAMVG", "339032", "339014, 339030, 339033, 339036, 339039, 339040",
                         "2025NC000408", "não é conclusão de uso indevido"):
            self.assertIn(esperado, alerta.descricao)

    def test_alerta_avisa_quando_a_comparacao_pode_estar_incompleta(self):
        (alerta,) = gerar_alertas_celula(self._divergente(abreviada=True))
        self.assertIn("pode estar incompleta", alerta.descricao)

    def test_correspondente_e_base_incompleta_nao_geram_alerta(self):
        ok = conciliar_celulas([_nc()], [_tg(NC_A, "1AAMVG", "339032")], [_vinculo()], [_ne()])
        incompleto = conciliar_celulas([_nc()], [], [_vinculo()], [_ne()])
        self.assertEqual(gerar_alertas_celula(ok + incompleto), [])

    def test_uma_ne_com_duas_celulas_divergentes_gera_um_alerta_so(self):
        resultados = conciliar_celulas(
            [_nc()], [_tg(NC_A, "1AAMVG", "339014")], [_vinculo()], [_ne(natureza="339032"), _ne(natureza="339039")]
        )
        self.assertEqual(len(gerar_alertas_celula(resultados)), 1)

    def test_tabela_mostra_os_codigos_comparados_as_ncs_e_o_motivo(self):
        tabela = resultados_para_tabela(self._divergente())
        (linha,) = tabela.to_dict("records")
        self.assertEqual(linha["Situação"], ESTADO_DIVERGENCIA)
        self.assertEqual(linha["Célula da NE (PTRES | fonte | natureza | PI)"], "230551 | 1000A00238 | 339032 | MCC62G22EDN")
        self.assertEqual(linha["Campos divergentes"], "natureza da despesa")
        self.assertIn("339040", linha["Valores nas NCs para o campo divergente"])
        self.assertEqual(linha["NCs consideradas"], "2025NC000408")
        self.assertEqual(linha["Linhas de origem (NC)"], "4")
        self.assertEqual(linha["Linhas de origem (NE)"], "20")


def _df_ne_simec():
    return pd.DataFrame([{
        "Gestão Emitente - NE": "15239", "UG Executora Emitente - NE": "153165", "Descrição do Termo": "Termo",
        "Estado Atual": "Termo em Execução", "Início da Vigência": "01/01/2025", "Fim da Vigência": "31/12/2027",
        "UG Descentralizadora": "154046", "Número do Empenho": "2025NE000706", "SIAFI": "1AAMVG", "TED": "12112",
        "Valor da NE": "4.997,80",
    }])


def _df_nc_simec(numeros):
    base = {
        "Data de Emissão da NC": "10/02/2025", "Operação": "( + )", "UG Emitente - NC": "154003",
        "Descrição do Termo": "Termo", "Estado Atual": "Termo em Execução", "Fim da Vigência": "31/12/2027",
        "Início da Vigência": "01/01/2025", "SIAFI": "1AAMVG", "TED": "12112", "UG Descentralizadora": "153165",
        "Valor Total NC": 100.0,
    }
    return pd.DataFrame([{**base, "Número da NC": n} for n in numeros])


def _execucao_mensal(natureza):
    return pd.DataFrame(
        [("153165152392025NE000706", 10, 230551, "1000A00238", natureza, "MCC62G22EDN")],
        columns=["ne_ccor", "linha_origem", "ptres", "fonte_recursos_detalhada_cod", "natureza_despesa_cod", "pi_cod"],
    )


class IntegracaoComBancoTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def _sincronizar_tg(self, natureza="339032"):
        vazio = SimpleNamespace(registros=[], rejeitadas=[])
        with mock.patch("src.teds_lotes.montar_execucao_tg", return_value=vazio):
            return sincronizar_execucao_tg(self.conn, _execucao_mensal(natureza), f"sha-{natureza}", "mensal.xlsx")

    def _importar_tudo(self, natureza_ne="339032"):
        importar_doc_ne(self.conn, _df_ne_simec(), "ne.xlsx", b"ne")
        importar_doc_nc(self.conn, _df_nc_simec(["2025NC000408"]), "nc.xlsx", b"nc")
        bruto = _bruto_hist([(NC_A, "1AAMVG", n, "230551", "MCC62G22EDN", "1000A00238", 10.0) for n in ("339014", "339030")])
        importar_nc_tg_historica(self.conn, _como_header0(bruto), "destaques.xlsx", b"destaques")
        self._sincronizar_tg(natureza_ne)

    def _alertas(self):
        return self.conn.execute(
            "SELECT gravidade, documento, status FROM alerta WHERE tipo = ?", (TIPO_NE_CELULA_DIVERGE_NC,)
        ).fetchall()

    def test_importa_concilia_e_gera_o_alerta_uma_unica_vez(self):
        self._importar_tudo()
        (r,) = carregar_conciliacao_celulas(self.conn)
        self.assertEqual((r.situacao, r.campos_divergentes), (ESTADO_DIVERGENCIA, ("natureza",)))
        self.assertEqual(self._alertas(), [("alta", f"{TED}|{CE}", "aberto")])
        self.assertEqual(sincronizar_alertas_celula_orcamentaria(self.conn), [])  # sem duplicar

    def test_sem_celulas_de_nc_ou_de_ne_nao_ha_o_que_comparar_e_nenhum_alerta(self):
        importar_doc_ne(self.conn, _df_ne_simec(), "ne.xlsx", b"ne")
        self.assertEqual(sincronizar_alertas_celula_orcamentaria(self.conn), [])
        (r,) = carregar_conciliacao_celulas(self.conn)
        self.assertEqual(r.situacao, ESTADO_BASE_INCOMPLETA)

    def test_correspondente_nao_gera_alerta(self):
        self._importar_tudo(natureza_ne="339014")
        (r,) = carregar_conciliacao_celulas(self.conn)
        self.assertEqual(r.situacao, ESTADO_CORRESPONDENTE)
        self.assertEqual(self._alertas(), [])

    def test_reimportar_o_mesmo_arquivo_de_nc_e_no_op(self):
        bruto = _bruto_hist([(NC_A, "1AAMVG", "339014", "230551", "MCC62G22EDN", "1000A00238", 10.0)])
        df = _como_header0(bruto)
        primeiro = importar_nc_tg_historica(self.conn, df, "d.xlsx", b"d")
        segundo = importar_nc_tg_historica(self.conn, df, "d.xlsx", b"d")
        self.assertTrue(segundo.ja_importado)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM nc_celula").fetchone()[0], 1)
        self.assertEqual(primeiro.import_batch_id, segundo.import_batch_id)

    def test_uma_extracao_nova_atualiza_a_celula_e_a_reversao_devolve_a_anterior(self):
        antigo = _como_header0(_bruto_hist([(NC_A, "1AAMVG", "339014", "230551", "MCC62G22EDN", "1000A00238", 10.0)]))
        novo = _como_header0(_bruto_hist([(NC_A, "1AAMVG", "339014", "230551", "MCC62G22EDN", "1000A00238", 99.0)]))
        importar_nc_tg_historica(self.conn, antigo, "d1.xlsx", b"d1")
        lote2 = importar_nc_tg_historica(self.conn, novo, "d2.xlsx", b"d2").import_batch_id
        self.assertEqual(self.conn.execute("SELECT valor FROM nc_celula").fetchone()[0], "99.00")
        reverter_lote(self.conn, lote2, responsavel="Ana", motivo="arquivo errado")
        self.assertEqual(self.conn.execute("SELECT valor FROM nc_celula").fetchone()[0], "10.00")

    def test_lote_de_nc_2026_e_importado_com_origem_e_destino(self):
        bruto = _bruto_2026([
            ("373001372012026NC000363", "1AAMVG", "339014", "235422", "P", "F", "ORIGEM", 10.0),
            ("373001372012026NC000363", "1AAMVG", "339014", "235422", "P", "F", "DESTINO", 10.0),
        ])
        importar_nc_tg_2026(self.conn, _como_header0(bruto), "nc2026.xlsx", b"nc26")
        tipos = sorted(t for (t,) in self.conn.execute("SELECT tipo_celula FROM nc_celula"))
        self.assertEqual(tipos, ["DESTINO", "ORIGEM"])


if __name__ == "__main__":
    unittest.main()
