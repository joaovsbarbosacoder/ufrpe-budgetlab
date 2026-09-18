"""
Testes dos leitores SIMEC (`src/teds_importacao_simec.py`) com os números do caso descrito
no briefing: TED 17352 (SIAFI 1ABDKU) e TED 17454 (SIAFI 1ABDKQ), e os documentos PF com
operação negativa citados explicitamente (regra do sinal de operação).

As classes acima de `RealHeaders...` reproduzem os NOMES DE COLUNA descritos no briefing
original — mantidos como contrato retrocompatível (os `_MAPA_*` do módulo testado guardam
ambos os conjuntos de alias). As classes `RealHeaders...` para baixo usam os cabeçalhos
CONFIRMADOS contra a extração real do SIMEC (exercício 2026, 4 arquivos: Execução
Orçamentário/Financeiro, DOC NC, DOC NE, DOC PF) e cobrem os achados dessa extração: TED/UG
como `float` do pandas, sufixo monetário `(R$)`, NC sem UG emitente, NC com várias linhas por
documento, e os dois formatos de operação (`( + )`/`( - )` no NC, `(+)`/`(-)` no PF).
"""

from __future__ import annotations

import unittest
from decimal import Decimal

import pandas as pd

from src.teds_importacao_simec import (
    AVISO_UG_EMITENTE_NC_AUSENTE,
    STATUS_RELACIONAMENTO_OK,
    STATUS_RELACIONAMENTO_PARCIAL,
    ler_doc_ne_simec,
    ler_doc_nc_simec,
    ler_doc_pf_simec,
    ler_execucao_anual_simec,
)
from src.teds_normalizacao import chave_empenho, chave_ted


class LerExecucaoAnualSimecTests(unittest.TestCase):
    def test_ted_17352_e_17454(self):
        df = pd.DataFrame(
            [
                {
                    "Ano de emissão": 2026,
                    "Descrição do Termo": "Termo de Execução Descentralizada 17352",
                    "Estado Atual": "Em execução",
                    "Início da Vigência": "01/01/2026",
                    "Fim da Vigência": "31/12/2027",
                    "SIAFI": "1ABDKU",
                    "TED": "17352",
                    "UG Descentralizadora": "154046",
                    "Total NC Descentralização": "388.300,00",
                    "Total NC Devolução": "0,00",
                    "Total Descentralizado": "388.300,00",
                    "Total PF Repasse": "388.300,00",
                    "Total PF Devolução": "0,00",
                    "Total Repassado": "388.300,00",
                },
                {
                    "Ano de emissão": 2026,
                    "Descrição do Termo": "Termo de Execução Descentralizada 17454",
                    "Estado Atual": "Em execução",
                    "Início da Vigência": "01/03/2026",
                    "Fim da Vigência": "31/12/2027",
                    "SIAFI": "1ABDKQ",
                    "TED": "17454",
                    "UG Descentralizadora": "154046",
                    "Total NC Descentralização": "154.496,00",
                    "Total NC Devolução": "0,00",
                    "Total Descentralizado": "154.496,00",
                    "Total PF Repasse": "154.496,00",
                    "Total PF Devolução": "0,00",
                    "Total Repassado": "154.496,00",
                },
                # Linha de rodapé: sem TED/SIAFI, deve ser rejeitada, não contabilizada.
                {
                    "Ano de emissão": None,
                    "Descrição do Termo": "Total geral",
                    "Estado Atual": None,
                    "Início da Vigência": None,
                    "Fim da Vigência": None,
                    "SIAFI": None,
                    "TED": None,
                    "UG Descentralizadora": None,
                    "Total NC Descentralização": "542.796,00",
                    "Total NC Devolução": "0,00",
                    "Total Descentralizado": "542.796,00",
                    "Total PF Repasse": "542.796,00",
                    "Total PF Devolução": "0,00",
                    "Total Repassado": "542.796,00",
                },
            ]
        )

        resultado = ler_execucao_anual_simec(df)

        self.assertEqual(len(resultado.registros), 2)
        self.assertEqual(len(resultado.rejeitadas), 1)
        self.assertIn("rodapé", resultado.rejeitadas[0].motivo)

        por_chave = {r["chave_ted"]: r for r in resultado.registros}
        r17352 = por_chave[chave_ted("17352", "1ABDKU")]
        self.assertEqual(r17352["total_descentralizado"], Decimal("388300.00"))
        self.assertEqual(r17352["total_pf_repasse"], Decimal("388300.00"))
        self.assertEqual(r17352["ano_emissao"], 2026)

        r17454 = por_chave[chave_ted("17454", "1ABDKQ")]
        self.assertEqual(r17454["total_descentralizado"], Decimal("154496.00"))


class LerDocNeSimecTests(unittest.TestCase):
    def test_ne_2026ne000422_aparece_em_dois_teds(self):
        linha_base = {
            "Gestão Emitente - NE": "15239",
            "UG Executora Emitente - NE": "153165",
            "Descrição do Termo": "Termo de Execução Descentralizada",
            "Estado Atual": "Em execução",
            "Início da Vigência": "01/01/2026",
            "Fim da Vigência": "31/12/2027",
            "UG Descentralizadora": "154046",
        }
        df = pd.DataFrame(
            [
                {**linha_base, "Número do Empenho": "2026NE000422", "SIAFI": "1ABDKU", "TED": "17352", "Valor da NE": "388.300,00"},
                {**linha_base, "Número do Empenho": "2026NE000427", "SIAFI": "1ABDKQ", "TED": "17454", "Valor da NE": "154.496,00"},
                {**linha_base, "Número do Empenho": "2026NE000422", "SIAFI": "1ABDKQ", "TED": "17454", "Valor da NE": "388.300,00"},
            ]
        )

        resultado = ler_doc_ne_simec(df)
        self.assertEqual(len(resultado.registros), 3)
        self.assertEqual(len(resultado.rejeitadas), 0)

        chave_422 = chave_empenho("153165", "15239", "2026NE000422")
        ocorrencias_422 = [r for r in resultado.registros if r["chave_empenho"] == chave_422]
        self.assertEqual(len(ocorrencias_422), 2)
        self.assertEqual({r["chave_ted"] for r in ocorrencias_422}, {
            chave_ted("17352", "1ABDKU"),
            chave_ted("17454", "1ABDKQ"),
        })
        for r in ocorrencias_422:
            self.assertEqual(r["valor_ne"], Decimal("388300.00"))

    def test_ne_sem_ug_ou_gestao_e_rejeitada(self):
        df = pd.DataFrame(
            [
                {
                    "Gestão Emitente - NE": None,
                    "Número do Empenho": "2026NE000999",
                    "UG Executora Emitente - NE": "153165",
                    "SIAFI": "1ABDKU",
                    "TED": "17352",
                    "Valor da NE": "1.000,00",
                }
            ]
        )
        resultado = ler_doc_ne_simec(df)
        self.assertEqual(len(resultado.registros), 0)
        self.assertEqual(len(resultado.rejeitadas), 1)
        self.assertIn("gestão", resultado.rejeitadas[0].motivo)


class LerDocNcSimecTests(unittest.TestCase):
    def test_nc_de_descentralizacao_ted_17352(self):
        df = pd.DataFrame(
            [
                {
                    "Operação": "(+)",
                    "UG emitente da NC": "154046",
                    "Número da NC": "2026NC000101",
                    "Número da transferência SIAFI": "1ABDKU",
                    "Valor total da NC": "353.000,00",
                    "Data de emissão da NC": "10/02/2026",
                    "TED": "17352",
                },
                {
                    "Operação": "(+)",
                    "UG emitente da NC": "154046",
                    "Número da NC": "2026NC000102",
                    "Número da transferência SIAFI": "1ABDKU",
                    "Valor total da NC": "35.300,00",
                    "Data de emissão da NC": "10/02/2026",
                    "TED": "17352",
                },
            ]
        )
        resultado = ler_doc_nc_simec(df)
        self.assertEqual(len(resultado.registros), 2)
        total = sum((r["valor_assinado"] for r in resultado.registros), Decimal("0"))
        self.assertEqual(total, Decimal("388300.00"))

    def test_operacao_negativa_de_devolucao(self):
        df = pd.DataFrame(
            [
                {
                    "Operação": "(-)",
                    "UG emitente da NC": "154046",
                    "Número da NC": "2026NC000200",
                    "Número da transferência SIAFI": "1ABDKX",
                    "Valor total da NC": "1.000,00",
                    "Data de emissão da NC": "10/02/2026",
                    "TED": "20000",
                }
            ]
        )
        resultado = ler_doc_nc_simec(df)
        self.assertEqual(resultado.registros[0]["valor_assinado"], Decimal("-1000.00"))
        self.assertEqual(resultado.registros[0]["valor_original"], Decimal("1000.00"))


class LerDocPfSimecTests(unittest.TestCase):
    def test_documentos_negativos_do_briefing(self):
        # Os três documentos PF negativos citados explicitamente no briefing.
        df = pd.DataFrame(
            [
                {
                    "Data de Emissão Doc. PF": "15/03/2023",
                    "Número Doc. PF": "2023PF000185",
                    "Operação": "(-)",
                    "UG Emitente - PF": "154046",
                    "SIAFI": "SIAFI-12112",
                    "TED": "12112",
                    "Valor Doc. PF": "261,50",
                },
                {
                    "Data de Emissão Doc. PF": "10/01/2024",
                    "Número Doc. PF": "2024PF000016",
                    "Operação": "(-)",
                    "UG Emitente - PF": "154046",
                    "SIAFI": "SIAFI-12112",
                    "TED": "12112",
                    "Valor Doc. PF": "19.902,91",
                },
                {
                    "Data de Emissão Doc. PF": "05/02/2024",
                    "Número Doc. PF": "2024PF000002",
                    "Operação": "(-)",
                    "UG Emitente - PF": "154046",
                    "SIAFI": "SIAFI-12172",
                    "TED": "12172",
                    "Valor Doc. PF": "1.970,61",
                },
            ]
        )
        resultado = ler_doc_pf_simec(df)
        self.assertEqual(len(resultado.registros), 3)
        valores = {r["numero_pf"]: r["valor_assinado"] for r in resultado.registros}
        self.assertEqual(valores["2023PF000185"], Decimal("-261.50"))
        self.assertEqual(valores["2024PF000016"], Decimal("-19902.91"))
        self.assertEqual(valores["2024PF000002"], Decimal("-1970.61"))

    def test_valor_liquido_com_positivos_e_negativos(self):
        df = pd.DataFrame(
            [
                {
                    "Número Doc. PF": "2026PF000001",
                    "Operação": "(+)",
                    "UG Emitente - PF": "154046",
                    "SIAFI": "1ABDKU",
                    "TED": "17352",
                    "Valor Doc. PF": "388.300,00",
                },
                {
                    "Número Doc. PF": "2026PF000002",
                    "Operação": "(-)",
                    "UG Emitente - PF": "154046",
                    "SIAFI": "1ABDKU",
                    "TED": "17352",
                    "Valor Doc. PF": "300,00",
                },
            ]
        )
        resultado = ler_doc_pf_simec(df)
        liquido = sum((r["valor_assinado"] for r in resultado.registros), Decimal("0"))
        self.assertEqual(liquido, Decimal("388000.00"))

    def test_numero_pf_ausente_e_rejeitado(self):
        df = pd.DataFrame(
            [
                {
                    "Número Doc. PF": None,
                    "Operação": "(+)",
                    "UG Emitente - PF": None,
                    "SIAFI": None,
                    "TED": None,
                    "Valor Doc. PF": "7.434.334,46",
                }
            ]
        )
        resultado = ler_doc_pf_simec(df)
        self.assertEqual(len(resultado.registros), 0)
        self.assertEqual(len(resultado.rejeitadas), 1)


class RealHeadersExecucaoAnualTests(unittest.TestCase):
    """Cabeçalhos e tipos confirmados na extração real (exercício 2026): a coluna de TED/UG
    chega como `float` e só 3 das 6 colunas de valor têm o sufixo `(R$)`."""

    def test_cabecalhos_reais_com_sufixo_monetario_parcial(self):
        df = pd.DataFrame(
            [
                {
                    "Ano de emissão": 2026.0,
                    "Descrição do Termo": "Curso de Especialização em Tecnologias Digitais",
                    "Estado Atual": "Termo em Execução",
                    "Fim da Vigência": "31/07/2026",
                    "Início da Vigência": "09/12/2024",
                    "SIAFI": "1AAVEH",
                    "TED": 14142.0,
                    "UG Descentralizadora": 153173.0,
                    "Total NC Descentralização (R$)": 1210680.0,
                    "Total NC Devolução (R$)": 0.0,
                    "Total Descentralizado (R$)": 1210680.0,
                    "Total PF Repasse": 0.0,
                    "Total PF Devolução": 0.0,
                    "Total Repassado": 0.0,
                }
            ]
        )
        resultado = ler_execucao_anual_simec(df)
        self.assertEqual(len(resultado.rejeitadas), 0)
        registro = resultado.registros[0]
        self.assertEqual(registro["ted"], "14142")
        self.assertEqual(registro["codigo_siafi"], "1AAVEH")
        self.assertEqual(registro["ug_descentralizadora"], "153173")
        self.assertEqual(registro["total_descentralizado"], Decimal("1210680.00"))
        self.assertIsInstance(registro["total_descentralizado"], Decimal)

    def test_rodape_com_apenas_totais_e_excluido(self):
        df = pd.DataFrame(
            [
                {
                    "Ano de emissão": 2026.0,
                    "Descrição do Termo": "Termo qualquer",
                    "Estado Atual": "Termo em Execução",
                    "Fim da Vigência": "31/07/2026",
                    "Início da Vigência": "09/12/2024",
                    "SIAFI": "1AAVEH",
                    "TED": 14142.0,
                    "UG Descentralizadora": 153173.0,
                    "Total NC Descentralização (R$)": 1210680.0,
                    "Total NC Devolução (R$)": 0.0,
                    "Total Descentralizado (R$)": 1210680.0,
                    "Total PF Repasse": 0.0,
                    "Total PF Devolução": 0.0,
                    "Total Repassado": 0.0,
                },
                {
                    "Ano de emissão": None,
                    "Descrição do Termo": None,
                    "Estado Atual": None,
                    "Fim da Vigência": None,
                    "Início da Vigência": None,
                    "SIAFI": None,
                    "TED": None,
                    "UG Descentralizadora": None,
                    "Total NC Descentralização (R$)": 57619026.14,
                    "Total NC Devolução (R$)": 5219366.74,
                    "Total Descentralizado (R$)": 52399659.4,
                    "Total PF Repasse": 26592595.72,
                    "Total PF Devolução": 1087532.94,
                    "Total Repassado": 25505062.78,
                },
            ]
        )
        resultado = ler_execucao_anual_simec(df)
        self.assertEqual(len(resultado.registros), 1)
        self.assertEqual(len(resultado.rejeitadas), 1)


class RealHeadersDocNeTests(unittest.TestCase):
    def test_cabecalhos_reais_e_codigos_float_sem_ponto_zero(self):
        df = pd.DataFrame(
            [
                {
                    "Gestão Emitente - NE": 15239.0,
                    "Número do Empenho": "2024NE000338",
                    "UG Executora Emitente - NE": 153165.0,
                    "Descrição do Termo": "Financiamento dos Cursos no Âmbito do Sistema UAB.",
                    "Estado Atual": "Aguardando Prestação de Contas (RCO)",
                    "Fim da Vigência": "30/12/2025",
                    "Início da Vigência": "02/08/2021",
                    "SIAFI": "1AAEZQ",
                    "TED": 10328.0,
                    "UG Descentralizadora": 150304.0,
                    "Valor da NE": 43989.84,
                }
            ]
        )
        resultado = ler_doc_ne_simec(df)
        self.assertEqual(len(resultado.rejeitadas), 0)
        registro = resultado.registros[0]
        self.assertEqual(registro["ted"], "10328")
        self.assertEqual(registro["ug_emitente"], "153165")
        self.assertEqual(registro["gestao_emitente"], "15239")
        self.assertEqual(registro["chave_ted"], chave_ted("10328", "1AAEZQ"))
        self.assertEqual(registro["chave_empenho"], chave_empenho("153165", "15239", "2024NE000338"))
        self.assertIsInstance(registro["valor_ne"], Decimal)


class RealHeadersDocNcTests(unittest.TestCase):
    """DOC NC é o relatório com mais achados na extração real: `UG Emitente - NC` ausente em
    boa parte das linhas legítimas (não confundir com rodapé) e o mesmo documento espalhado
    em várias linhas (rateio por fonte/ação)."""

    def _linha_base(self, **overrides):
        linha = {
            "Data de Emissão da NC": "02/07/2025",
            "Número da NC": "2025NC000265",
            "Operação": "( + )",
            "UG Emitente - NC": None,
            "Descrição do Termo": "Concessão PROAP 2023.",
            "Estado Atual": "Termo em Execução",
            "Fim da Vigência": "30/06/2027",
            "Início da Vigência": "29/05/2023",
            "SIAFI": "1AAMPD",
            "TED": 12172.0,
            "UG Descentralizadora": 150300.0,
            "Valor Total NC": 559338.0,
        }
        linha.update(overrides)
        return linha

    def test_cabecalhos_reais_com_ug_emitente_preenchida(self):
        df = pd.DataFrame([self._linha_base(**{"UG Emitente - NC": 152734.0})])
        resultado = ler_doc_nc_simec(df)
        self.assertEqual(len(resultado.rejeitadas), 0)
        registro = resultado.registros[0]
        self.assertEqual(registro["ug_emitente"], "152734")
        self.assertEqual(registro["ted"], "12172")
        self.assertEqual(registro["operacao"], "+")
        self.assertEqual(registro["status_relacionamento"], STATUS_RELACIONAMENTO_OK)
        self.assertEqual(registro["avisos"], [])
        self.assertIsInstance(registro["valor_original"], Decimal)

    def test_nc_sem_ug_emitente_e_importada_com_aviso_e_status_parcial(self):
        # 86 das 179 linhas reais de NC vêm sem "UG Emitente - NC" — não é rodapé, a linha
        # tem que ser importada, nunca rejeitada, e a UG Descentralizadora NUNCA substitui a
        # UG emitente ausente (são UGs diferentes sempre que as duas vêm preenchidas).
        df = pd.DataFrame([self._linha_base()])
        resultado = ler_doc_nc_simec(df)
        self.assertEqual(len(resultado.rejeitadas), 0)
        self.assertEqual(len(resultado.registros), 1)
        registro = resultado.registros[0]
        self.assertIsNone(registro["ug_emitente"])
        self.assertIn(AVISO_UG_EMITENTE_NC_AUSENTE, registro["avisos"])
        self.assertEqual(registro["status_relacionamento"], STATUS_RELACIONAMENTO_PARCIAL)

    def test_rodape_sem_numero_da_nc_e_excluido(self):
        df = pd.DataFrame(
            [
                self._linha_base(**{"UG Emitente - NC": 152734.0}),
                {
                    "Data de Emissão da NC": None,
                    "Número da NC": None,
                    "Operação": None,
                    "UG Emitente - NC": None,
                    "Descrição do Termo": None,
                    "Estado Atual": None,
                    "Fim da Vigência": None,
                    "Início da Vigência": None,
                    "SIAFI": None,
                    "TED": None,
                    "UG Descentralizadora": None,
                    "Valor Total NC": 62838392.88,
                },
            ]
        )
        resultado = ler_doc_nc_simec(df)
        self.assertEqual(len(resultado.registros), 1)
        self.assertEqual(len(resultado.rejeitadas), 1)
        self.assertIn("rodapé", resultado.rejeitadas[0].motivo)

    def test_documento_com_varias_linhas_preserva_detalhe_e_agrega(self):
        # Caso real: 2025NC000265 aparece em 6 linhas na extração de referência (rateio por
        # fonte). Aqui com 3, uma delas com UG emitente preenchida e as outras não.
        df = pd.DataFrame(
            [
                self._linha_base(**{"UG Emitente - NC": 152734.0, "Valor Total NC": 559338.0}),
                self._linha_base(**{"UG Emitente - NC": None, "Valor Total NC": 170000.0}),
                self._linha_base(**{"UG Emitente - NC": None, "Valor Total NC": 140000.0}),
            ]
        )
        resultado = ler_doc_nc_simec(df)
        self.assertEqual(len(resultado.registros), 3)  # nenhuma linha foi descartada/mesclada
        self.assertEqual(len(resultado.documentos), 1)  # mas é um único documento

        documento = resultado.documentos[0]
        self.assertEqual(documento["quantidade_linhas"], 3)
        self.assertEqual(documento["valor_original_total"], Decimal("869338.00"))
        self.assertEqual(documento["valor_assinado_total"], Decimal("869338.00"))
        self.assertEqual(documento["ug_emitente"], "152734")  # veio da única linha que a trouxe
        self.assertEqual(documento["status_relacionamento"], STATUS_RELACIONAMENTO_PARCIAL)

        chaves_documento = {r["chave_nc_documento"] for r in resultado.registros}
        self.assertEqual(len(chaves_documento), 1)
        self.assertEqual(chaves_documento.pop(), documento["chave_nc_documento"])

    def test_documentos_diferentes_nao_sao_agregados_juntos(self):
        df = pd.DataFrame(
            [
                self._linha_base(**{"Número da NC": "2025NC000265", "UG Emitente - NC": 152734.0}),
                self._linha_base(**{"Número da NC": "2025NC000266", "UG Emitente - NC": 152734.0}),
            ]
        )
        resultado = ler_doc_nc_simec(df)
        self.assertEqual(len(resultado.documentos), 2)

    def test_operacoes_com_e_sem_espacos_internos(self):
        df = pd.DataFrame(
            [
                self._linha_base(**{"Número da NC": "2025NC000001", "Operação": "( + )"}),
                self._linha_base(**{"Número da NC": "2025NC000002", "Operação": "( - )"}),
            ]
        )
        resultado = ler_doc_nc_simec(df)
        operacoes = {r["numero_nc"]: r["operacao"] for r in resultado.registros}
        self.assertEqual(operacoes["2025NC000001"], "+")
        self.assertEqual(operacoes["2025NC000002"], "-")

    def test_reimportacao_idempotente_mesma_chave_de_linha(self):
        df = pd.DataFrame([self._linha_base(**{"UG Emitente - NC": 152734.0})])
        primeira = ler_doc_nc_simec(df, identificador_lote="hash-arquivo-x")
        segunda = ler_doc_nc_simec(df, identificador_lote="hash-arquivo-x")

        self.assertEqual(primeira.registros[0]["chave_nc_linha"], segunda.registros[0]["chave_nc_linha"])
        self.assertEqual(
            primeira.registros[0]["chave_nc_documento"], segunda.registros[0]["chave_nc_documento"]
        )
        # Lote diferente (arquivo reenviado, outro hash) muda a chave de linha, mas o
        # documento continua sendo o mesmo — é o que permite agregação estável entre lotes.
        terceira = ler_doc_nc_simec(df, identificador_lote="hash-arquivo-y")
        self.assertNotEqual(primeira.registros[0]["chave_nc_linha"], terceira.registros[0]["chave_nc_linha"])
        self.assertEqual(
            primeira.registros[0]["chave_nc_documento"], terceira.registros[0]["chave_nc_documento"]
        )


class RealHeadersDocPfTests(unittest.TestCase):
    def test_cabecalhos_reais_com_sufixo_monetario_e_operacao_sem_espacos(self):
        df = pd.DataFrame(
            [
                {
                    "Data de Emissão Doc. PF": "31/12/2025",
                    "Número Doc. PF": "2025PF000137",
                    "Operação": "(-)",
                    "UG Emitente - PF": 153165.0,
                    "Descrição do Termo": "Apoio à Manutenção da UFRPE",
                    "Estado Atual": "Relatório de cumprimento do objeto em análise pela Coordenação",
                    "Fim da Vigência": "31/12/2025",
                    "Início da Vigência": "18/06/2025",
                    "SIAFI": "1AAYDF",
                    "TED": 15686.0,
                    "UG Descentralizadora": 150011.0,
                    "Valor Doc. PF (R$)": 9.76,
                }
            ]
        )
        resultado = ler_doc_pf_simec(df)
        self.assertEqual(len(resultado.rejeitadas), 0)
        registro = resultado.registros[0]
        self.assertEqual(registro["ug_emitente"], "153165")
        self.assertEqual(registro["chave_ted"], chave_ted("15686", "1AAYDF"))
        self.assertEqual(registro["operacao"], "-")
        self.assertEqual(registro["valor_assinado"], Decimal("-9.76"))
        self.assertIsInstance(registro["valor_original"], Decimal)


if __name__ == "__main__":
    unittest.main()
