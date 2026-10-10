"""
TEDs do TransfereGov (`src/teds_transferegov.py`): consulta paginada e filtrada para a UFRPE, normalização
(códigos como texto, valores exatos, nulo ≠ zero), sincronização idempotente com JSON bruto guardado,
reversão de lote e indícios de NE por célula. Nenhum teste usa a rede: a API é simulada em memória.
"""

from __future__ import annotations

import copy
import json
import unittest
import urllib.error
from decimal import Decimal
from unittest import mock

from src import teds_transferegov as tg
from src.teds_reversao import reverter_lote
from src.teds_schema import conectar


def _api_base() -> dict[str, list[dict]]:
    """Recorte da API com dados no formato real (levantamento de 08/10/2026)."""

    return {
        "plano_acao": [
            {"id_plano_acao": 4180, "id_programa": 3900, "sigla_unidade_responsavel_execucao": "UFRPE",
             "unidade_responsavel_execucao": "Universidade Federal Rural de Pernambuco",
             "sigla_unidade_descentralizada": "UFRPE", "vl_total_plano_acao": 6197510,
             "dt_inicio_vigencia": "2025-05-26", "dt_fim_vigencia": "2026-06-30",
             "tx_objeto_plano_acao": "Formação dos Agentes em Economia Popular e Solidária",
             "tx_situacao_plano_acao": "APROVADO", "sq_instrumento": "975286", "aa_instrumento": 2025},
            {"id_plano_acao": 1445, "id_programa": 1248, "sigla_unidade_responsavel_execucao": "UFRPE",
             "unidade_responsavel_execucao": "Universidade Federal Rural de Pernambuco",
             "vl_total_plano_acao": 250000, "dt_inicio_vigencia": "2024-02-15", "dt_fim_vigencia": "2026-02-14",
             "tx_objeto_plano_acao": "Plano ainda sem termo", "tx_situacao_plano_acao": "ENVIADO_ANALISE",
             "sq_instrumento": None, "aa_instrumento": None},
            {"id_plano_acao": 9999, "id_programa": 1, "sigla_unidade_responsavel_execucao": "UFPE",
             "vl_total_plano_acao": 1, "tx_situacao_plano_acao": "APROVADO"},
        ],
        "programa": [
            {"id_programa": 3900, "tx_codigo_programa": "00122520250001", "tx_nome_programa": "Programa SENAES",
             "sigla_unidade_descentralizadora": "SENAES", "unidade_descentralizadora": "Secretaria Nacional de Economia Solidária"},
            {"id_programa": 1248, "tx_codigo_programa": "37201320240002", "tx_nome_programa": "Programa IPHAN",
             "sigla_unidade_descentralizadora": "IPHAN", "unidade_descentralizadora": "IPHAN"},
        ],
        "termo_execucao": [
            {"id_termo": 777, "id_plano_acao": 4180, "tx_situacao_termo": "EM_EXECUCAO",
             "tx_num_processo_sei": "00000.000001/2025-01", "dt_assinatura_termo": "2025-05-20T10:00:00",
             "tx_numero_ns_termo": "2025NS000010", "dt_efetivacao_termo": None},
        ],
        "nota_credito": [
            {"id_nota": 5001, "id_plano_acao": 4180, "tx_numero_nota": "2025NC800002", "tx_minuta_nota": "2025MNC00001",
             "dt_emissao_nota": "2025-06-01T09:00:00.123", "cd_ug_emitente_nota": "180073", "cd_gestao_emitente_nota": "00001",
             "cd_ug_favorecida_nota": "153165", "cd_gestao_favorecida_nota": "15239", "tx_situacao_nota": "ENVIADA",
             "tx_observacao_nota": "ATENDER DESPESAS COM O TED 975286"},
            # NC para a UFRPE ligada a plano de outra executora: entra pela UG favorecida.
            {"id_nota": 5002, "id_plano_acao": 9999, "tx_numero_nota": "2025NC800009", "dt_emissao_nota": "2025-07-01",
             "cd_ug_emitente_nota": "180073", "cd_gestao_emitente_nota": "00001", "cd_ug_favorecida_nota": "153165",
             "tx_situacao_nota": "ENVIADA"},
            # NC de outra UG, fora do recorte.
            {"id_nota": 5003, "id_plano_acao": 9999, "tx_numero_nota": "2025NC800010",
             "cd_ug_favorecida_nota": "150000", "tx_situacao_nota": "ENVIADA"},
        ],
        "evento": [
            {"id_nota": 5001, "cd_evento": "300300", "cd_ptres_evento": "235739", "cd_fonte_recurso_evento": "1000A002TQ",
             "cd_plano_interno_evento": "25P27SENAES", "codigo_natureza": "339039", "vl_evento": Decimal("1998940.00"),
             "cd_ug_responsavel_evento": "180073", "descricao_natureza": "OUTROS SERV.TERC", "nome_esfera_orcamentaria": "Orçamento Fiscal"},
            {"id_nota": 5001, "cd_evento": "300302", "cd_ptres_evento": "235739", "cd_fonte_recurso_evento": "1000A002TQ",
             "cd_plano_interno_evento": "25P27SENAES", "codigo_natureza": "339039", "vl_evento": 500},
            {"id_nota": 5001, "cd_evento": "300302", "cd_ptres_evento": "235739", "cd_fonte_recurso_evento": "1000A002TQ",
             "cd_plano_interno_evento": "25P27SENAES", "codigo_natureza": "339039", "vl_evento": 500},
            {"id_nota": 5002, "cd_evento": "300300", "cd_ptres_evento": "251010", "cd_fonte_recurso_evento": "0172024307",
             "cd_plano_interno_evento": None, "codigo_natureza": "445039", "vl_evento": None},
            {"id_nota": 5003, "cd_evento": "300300", "cd_ptres_evento": "1", "cd_fonte_recurso_evento": "1",
             "codigo_natureza": "339039", "vl_evento": 1},
        ],
        "programacao_financeira": [
            {"id_programacao": 965, "id_plano_acao": 4180, "tp_pf_tipo_programacao": "T", "tx_numero_programacao": "2025PF000082",
             "tx_minuta_programacao": "2025MPF001001", "tx_situacao_programacao": "ENVIADA", "ug_emitente_programacao": "180073",
             "ug_favorecida_programacao": "153165", "dh_recebimento_programacao": "2025-06-10T14:42:24.31373"},
        ],
        "trf": [
            {"id_programacao": 965, "cd_vinculacao_trf": 400, "cd_fonte_recurso_trf": "0180209300",
             "cd_categoria_gasto_trf": "C", "vl_valor_trf": 714647, "cd_situacao_contabil_trf": "TRF003"},
        ],
    }


_CAMPO_ID = {
    "plano_acao": "id_plano_acao", "programa": "id_programa", "termo_execucao": "id_termo",
    "nota_credito": "id_nota", "evento": "id_nota", "programacao_financeira": "id_programacao", "trf": "id_programacao",
}


class ApiFalsa:
    """Imita a API PostgREST: filtros `eq.`/`in.(...)`, `limit` e `offset`. Registra as chamadas."""

    def __init__(self, tabelas: dict[str, list[dict]]):
        self.tabelas = tabelas
        self.chamadas: list[tuple[str, dict[str, str]]] = []

    def __call__(self, tabela: str, parametros: dict[str, str]) -> list[dict]:
        self.chamadas.append((tabela, dict(parametros)))
        linhas = self.tabelas.get(tabela, [])
        for campo, filtro in parametros.items():
            if campo in ("order", "limit", "offset"):
                continue
            if filtro.startswith("eq."):
                alvo = filtro[3:]
                linhas = [l for l in linhas if str(l.get(campo)) == alvo]
            elif filtro.startswith("in.("):
                alvos = set(filtro[4:-1].split(","))
                linhas = [l for l in linhas if str(l.get(campo)) in alvos]
            else:
                raise AssertionError(f"filtro não suportado: {campo}={filtro}")
        linhas = sorted(linhas, key=lambda l: json.dumps(l, sort_keys=True, default=str))
        inicio = int(parametros["offset"])
        return copy.deepcopy(linhas[inicio:inicio + int(parametros["limit"])])


def _extracao(tabelas=None, consultado_em="2026-10-08T12:00:00+00:00") -> tg.ExtracaoTransfereGov:
    extracao = tg.baixar_extracao(ApiFalsa(tabelas or _api_base()))
    return tg.ExtracaoTransfereGov(extracao.tabelas, consultado_em)


class BaixarExtracaoTests(unittest.TestCase):
    def test_filtra_a_ufrpe_e_inclui_nc_e_pf_pela_ug_favorecida(self):
        extracao = _extracao()
        self.assertEqual({p["id_plano_acao"] for p in extracao.tabelas["plano_acao"]}, {4180, 1445})
        self.assertEqual({n["id_nota"] for n in extracao.tabelas["nota_credito"]}, {5001, 5002})
        self.assertEqual({e["id_nota"] for e in extracao.tabelas["evento"]}, {5001, 5002})
        self.assertEqual(len(extracao.tabelas["evento"]), 4)
        self.assertEqual([p["id_programacao"] for p in extracao.tabelas["programacao_financeira"]], [965])

    def test_pagina_ate_a_ultima_pagina_incompleta(self):
        api = ApiFalsa(_api_base())
        with mock.patch.object(tg, "TAMANHO_PAGINA", 2):
            extracao = tg.baixar_extracao(api)
        self.assertEqual(len(extracao.tabelas["evento"]), 4)
        offsets_evento = [p["offset"] for t, p in api.chamadas if t == "evento"]
        self.assertEqual(offsets_evento, ["0", "2", "4"])
        self.assertTrue(all("order" in p for _, p in api.chamadas))

    def test_falha_de_rede_vira_erro_de_consulta(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("sem rede")):
            with self.assertRaises(tg.ErroConsultaTransfereGov):
                tg.buscar_pagina_http("plano_acao", {"limit": "1", "offset": "0"})


class MontarRegistrosTests(unittest.TestCase):
    def setUp(self):
        self.leitura = tg.montar_registros(_extracao())

    def test_ted_com_termo_e_concedente(self):
        ted = next(t for t in self.leitura.teds if t["id_plano_acao"] == "4180")
        self.assertEqual(ted["instrumento"], "975286/2025")
        self.assertEqual(ted["sigla_concedente"], "SENAES")
        self.assertEqual(ted["codigo_programa"], "00122520250001")
        self.assertEqual(ted["situacao_termo"], "EM_EXECUCAO")
        self.assertEqual(ted["data_assinatura"], "2025-05-20")
        self.assertIsNone(ted["data_efetivacao"])
        self.assertEqual(ted["valor_plano"], "6197510.00")

    def test_plano_sem_termo_fica_sem_instrumento(self):
        ted = next(t for t in self.leitura.teds if t["id_plano_acao"] == "1445")
        self.assertIsNone(ted["instrumento"])
        self.assertIsNone(ted["situacao_termo"])

    def test_codigos_preservam_zeros_e_valores_sao_exatos(self):
        nota = next(n for n in self.leitura.notas if n["id_nota"] == "5001")
        self.assertEqual(nota["gestao_emitente"], "00001")
        self.assertEqual(nota["data_emissao"], "2025-06-01")
        evento_nulo = next(e for e in self.leitura.eventos if e["id_nota"] == "5002")
        self.assertEqual(evento_nulo["fonte_detalhada"], "0172024307")
        self.assertIsNone(evento_nulo["valor"])  # nulo continua nulo, não vira zero
        self.assertIsNone(evento_nulo["pi"])
        self.assertIn("1998940.00", {e["valor"] for e in self.leitura.eventos})
        self.assertEqual(self.leitura.trfs[0]["vinculacao"], "400")
        self.assertEqual(self.leitura.trfs[0]["situacao_contabil"], "TRF003")

    def test_eventos_identicos_continuam_sendo_dois(self):
        estornos = [e for e in self.leitura.eventos if e["cd_evento"] == "300302"]
        self.assertEqual(len(estornos), 2)
        self.assertEqual(len({e["chave_evento"] for e in estornos}), 2)

    def test_valor_com_mais_de_duas_casas_nao_e_arredondado(self):
        self.assertEqual(tg._valor(Decimal("10.005")), "10.005")
        self.assertEqual(tg._valor(0), "0.00")

    def test_linha_sem_identificador_e_rejeitada_com_motivo(self):
        tabelas = _extracao().tabelas
        tabelas["nota_credito"].append({"id_nota": None, "tx_numero_nota": "2025NC000001"})
        leitura = tg.montar_registros(tg.ExtracaoTransfereGov(tabelas, "x"))
        self.assertEqual([r.motivo for r in leitura.rejeitadas], ["NC sem id_nota"])


class SincronizarTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def _valor_evento(self, cd_evento="300300", id_nota="5001"):
        return self.conn.execute(
            "SELECT valor FROM tg_nc_evento WHERE id_nota = ? AND cd_evento = ?", (id_nota, cd_evento)
        ).fetchone()[0]

    def test_grava_lote_sem_somas_e_guarda_o_json_bruto(self):
        resultado = tg.sincronizar_transferegov(self.conn, _extracao())
        self.assertFalse(resultado.ja_importado)
        contagens = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("tg_ted", "tg_nota_credito", "tg_nc_evento", "tg_programacao_financeira", "tg_pf_trf")}
        self.assertEqual(contagens, {"tg_ted": 2, "tg_nota_credito": 2, "tg_nc_evento": 4,
                                     "tg_programacao_financeira": 1, "tg_pf_trf": 1})
        tipo, soma_bruta, soma_liquida, versionado = self.conn.execute(
            "SELECT tipo_relatorio, soma_bruta, soma_liquida, versionado FROM import_batch WHERE id = ?",
            (resultado.import_batch_id,),
        ).fetchone()
        self.assertEqual(tipo, tg.TIPO_TRANSFEREGOV)
        self.assertIsNone(soma_bruta)
        self.assertIsNone(soma_liquida)
        self.assertEqual(versionado, 1)
        consultado_em, conteudo = self.conn.execute(
            "SELECT consultado_em, conteudo FROM tg_extracao_bruta WHERE import_batch_id = ?", (resultado.import_batch_id,)
        ).fetchone()
        self.assertEqual(consultado_em, "2026-10-08T12:00:00+00:00")
        self.assertEqual(len(json.loads(conteudo)["evento"]), 4)

    def test_mesma_resposta_em_outra_ordem_e_outra_hora_e_no_op(self):
        primeiro = tg.sincronizar_transferegov(self.conn, _extracao())
        tabelas = _extracao().tabelas
        for linhas in tabelas.values():
            linhas.reverse()
        segundo = tg.sincronizar_transferegov(self.conn, tg.ExtracaoTransfereGov(tabelas, "2026-10-09T08:00:00+00:00"))
        self.assertTrue(segundo.ja_importado)
        self.assertEqual(segundo.import_batch_id, primeiro.import_batch_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM import_batch").fetchone()[0], 1)

    def test_extracao_nova_atualiza_e_pode_ser_revertida(self):
        tg.sincronizar_transferegov(self.conn, _extracao())
        api = _api_base()
        api["termo_execucao"][0]["tx_situacao_termo"] = "CUMPRIMENTO_OBJETO_INICIADO"
        api["nota_credito"].append({"id_nota": 5004, "id_plano_acao": 4180, "tx_numero_nota": "2026NC800001",
                                    "cd_ug_favorecida_nota": "153165", "tx_situacao_nota": "ENVIADA"})
        segundo = tg.sincronizar_transferegov(self.conn, _extracao(api))
        self.assertFalse(segundo.ja_importado)
        situacao = lambda: self.conn.execute("SELECT situacao_termo FROM tg_ted WHERE id_plano_acao = '4180'").fetchone()[0]
        self.assertEqual(situacao(), "CUMPRIMENTO_OBJETO_INICIADO")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tg_nota_credito").fetchone()[0], 3)

        reverter_lote(self.conn, segundo.import_batch_id, responsavel="Teste", motivo="conferência")
        self.assertEqual(situacao(), "EM_EXECUCAO")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tg_nota_credito").fetchone()[0], 2)
        self.assertEqual(self._valor_evento(), "1998940.00")

    def test_linha_que_some_da_api_nao_e_apagada(self):
        tg.sincronizar_transferegov(self.conn, _extracao())
        api = _api_base()
        api["trf"] = []
        tg.sincronizar_transferegov(self.conn, _extracao(api))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM tg_pf_trf").fetchone()[0], 1)

    def test_falha_no_meio_nao_deixa_lote_pela_metade(self):
        original = tg._upsert

        def falha_nas_ncs(conn, tabela, registros, batch_id):
            if tabela == "tg_nota_credito":
                raise RuntimeError("falha simulada")
            original(conn, tabela, registros, batch_id)

        with mock.patch.object(tg, "_upsert", falha_nas_ncs):
            with self.assertRaises(RuntimeError):
                tg.sincronizar_transferegov(self.conn, _extracao())
        for tabela in ("import_batch", "tg_extracao_bruta", "tg_ted"):
            self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0], 0, tabela)

    def test_json_bruto_e_append_only(self):
        tg.sincronizar_transferegov(self.conn, _extracao())
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM tg_extracao_bruta")

    def test_ultimo_lote(self):
        self.assertIsNone(tg.ultimo_lote_transferegov(self.conn))
        resultado = tg.sincronizar_transferegov(self.conn, _extracao())
        self.assertEqual(tg.ultimo_lote_transferegov(self.conn)[0], resultado.import_batch_id)

    def test_consultas_da_tela(self):
        tg.sincronizar_transferegov(self.conn, _extracao())
        teds = tg.carregar_teds_transferegov(self.conn)
        self.assertEqual(list(teds["id_plano_acao"]), ["4180", "1445"])  # com instrumento primeiro
        self.assertEqual(int(teds.iloc[0]["qtd_nc"]), 1)
        notas = tg.notas_do_plano(self.conn, "4180")
        self.assertEqual(len(notas[0]["eventos"]), 3)
        pfs = tg.pfs_do_plano(self.conn, "4180")
        self.assertEqual(pfs[0]["trfs"][0]["valor"], "714647.00")


class IndiciosNETests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")
        tg.sincronizar_transferegov(self.conn, _extracao())
        celulas = [
            ("2025NE000383", "235739", "1000A002TQ", "339039", "25P27SENAES"),  # mesma célula e exercício
            ("2024NE000100", "235739", "1000A002TQ", "339039", "25P27SENAES"),  # exercício diferente
            ("2025NE000582", "251010", "0172024307", "445039", ""),             # NC de plano de outra executora
            ("2025NE000999", "235739", "1000A002TQ", "339030", "25P27SENAES"),  # natureza diferente
        ]
        self.conn.executemany(
            "INSERT INTO ne_celula (numero_ne, ptres, fonte_detalhada, natureza, pi, ug_emitente, quantidade_linhas, "
            "linhas_origem, import_batch_id) VALUES (?, ?, ?, ?, ?, '153165', 1, '[]', 99)",
            celulas,
        )
        self.conn.executemany(
            "INSERT INTO execucao_tg (numero_completo_ne, empenhado, liquidado, pago, ano_lancamento, mes_lancamento, "
            "import_batch_id, linha_origem) VALUES ('2025NE000383', ?, ?, ?, 2025, ?, 99, '{}')",
            [("1998940.00", "0.00", "0.00", 6), ("0.00", "1998940.00", "1998940.00", 7)],
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_so_mesma_celula_e_mesmo_exercicio(self):
        indicios = {i.numero_ne: i for i in tg.indicios_ne(self.conn)}
        self.assertEqual(set(indicios), {"2025NE000383", "2025NE000582"})
        principal = indicios["2025NE000383"]
        self.assertEqual(principal.instrumentos, ("975286/2025",))
        self.assertEqual(principal.numeros_nc, ("2025NC800002",))
        self.assertEqual((principal.empenhado, principal.liquidado, principal.pago),
                         (Decimal("1998940.00"), Decimal("1998940.00"), Decimal("1998940.00")))
        self.assertEqual(principal.teds_simec, ())

    def test_ne_sem_execucao_fica_sem_dado_e_nao_zero(self):
        indicio = next(i for i in tg.indicios_ne(self.conn) if i.numero_ne == "2025NE000582")
        self.assertIsNone(indicio.empenhado)
        self.assertEqual(indicio.instrumentos, ("plano 9999",))

    def test_filtra_por_plano_e_nao_cria_vinculo(self):
        self.assertEqual([i.numero_ne for i in tg.indicios_ne(self.conn, "4180")], ["2025NE000383"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM vinculo_ne").fetchone()[0], 0)

    def test_mostra_vinculo_existente_no_simec(self):
        self.conn.execute(
            "INSERT INTO vinculo_ne (chave_ted, chave_empenho, ug_emitente, gestao_emitente, numero_ne, valor_ne, "
            "import_batch_id, linha_origem) VALUES ('12112|1AAMVG', '153165|15239|2025NE000383', '153165', '15239', "
            "'2025NE000383', '1.00', 99, '{}')"
        )
        indicio = next(i for i in tg.indicios_ne(self.conn) if i.numero_ne == "2025NE000383")
        self.assertEqual(indicio.teds_simec, ("12112|1AAMVG",))


if __name__ == "__main__":
    unittest.main()
