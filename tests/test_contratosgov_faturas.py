"""Testes dos instrumentos de cobrança (faturas) do Contratos.gov.br (11/10/2026).

Endpoint `/api/contrato/{id}/faturas`. Amostra no formato real da API (conferido em 11/10/2026 nos contratos 326557,
118872, 157257 e 533524), com CNPJ fictício. Sem rede: cliente simulado.
"""

from __future__ import annotations

import copy
import unittest
from datetime import date, datetime
from decimal import Decimal

from src.contratos_cadastro import ErroDadoContratosGov, contratos_com_faturas, montar_faturas
from src.contratosgov_extracao import consultar


def _fatura(**extra) -> dict:
    base = {
        "id": 2245958, "contrato_id": 326557, "tipolistafatura_id": "PRESTAÇÃO DE SERVIÇOS",
        "tipo_instrumento_cobranca": "Nota Fiscal Eletrônica", "numero": "68715", "numero_serie": None,
        "fornecedor_contrato": "00.000.000/0001-00", "emissao": "2026-08-20", "prazo": "2026-09-04",
        "vencimento": "2026-09-04", "valor": "33.498,24", "juros": "0,00", "multa": "0,00", "glosa": "1.000,00",
        "valorliquido": "32.498,24", "data_liquidacao": "2026-09-03", "nota_cancelada": "Não", "processo": "23082.023225/2026-14",
        "repactuacao": "Não", "situacao": "Siafi Apropriado",
        "dados_empenho": [{"id_empenho": 15382317, "numero_empenho": "2026NE000510", "valor_empenho": "33.498,24"}],
        "dados_referencia": [{"mesref": "05", "anoref": "2026", "valorref": "33.498,24"}],
    }
    base.update(extra)
    return base


def _fotografia(faturas: list | None) -> dict:
    item = {
        "id": 326557, "numero": "00035/2024", "tipo": "Contrato", "fornecedor": {"tipo": "JURIDICA", "cnpj_cpf_idgener": "00.000.000/0001-00", "nome": "X"},
        "vigencia_inicio": "2024-10-16", "vigencia_fim": "2026-06-16", "valor_global": "1,00",
    }
    detalhe = {"historico": [], "empenhos": [], "consultado_em": "2026-10-11T08:00:00", "origem": "consulta"}
    if faturas is not None:
        detalhe["faturas"] = faturas
    return {"versao_formato": 1, "consultado_em": "2026-10-11T08:00:00", "ug": "153165",
            "lista_ativos": [item], "lista_inativos": [], "detalhes": {"326557": detalhe}}


class MontarFaturasTests(unittest.TestCase):
    def test_converte_valores_datas_nes_e_competencias(self) -> None:
        tabela = montar_faturas(_fotografia([_fatura()]))
        self.assertEqual(len(tabela), 1)
        linha = tabela.iloc[0]
        self.assertEqual(linha["contrato_id"], "326557")
        self.assertEqual(linha["numero"], "68715")
        self.assertEqual(linha["valor"], Decimal("33498.24"))
        self.assertEqual(linha["glosa"], Decimal("1000.00"))
        self.assertEqual(linha["valor_liquido"], Decimal("32498.24"))
        self.assertEqual(linha["data_liquidacao"], date(2026, 9, 3))
        self.assertEqual(linha["nes"], ("2026NE000510",))
        self.assertEqual(linha["referencias"], ((2026, 5, Decimal("33498.24")),))
        self.assertIs(linha["cancelada"], False)
        self.assertIs(linha["repactuacao"], False)
        self.assertEqual(linha["situacao"], "Siafi Apropriado")

    def test_zero_e_nulo_sao_distintos(self) -> None:
        linha = montar_faturas(_fotografia([_fatura(glosa=None, juros="0,00")])).iloc[0]
        self.assertIsNone(linha["glosa"])
        self.assertEqual(linha["juros"], Decimal("0"))

    def test_sim_nao_invalido_e_erro_explicito(self) -> None:
        with self.assertRaises(ErroDadoContratosGov):
            montar_faturas(_fotografia([_fatura(nota_cancelada="talvez")]))

    def test_fatura_sem_id_e_erro_explicito(self) -> None:
        sem_id = _fatura()
        del sem_id["id"]
        with self.assertRaises(ErroDadoContratosGov):
            montar_faturas(_fotografia([sem_id]))

    def test_fotografia_antiga_sem_faturas_nao_e_lista_vazia(self) -> None:
        self.assertTrue(montar_faturas(_fotografia(None)).empty)
        self.assertEqual(contratos_com_faturas(_fotografia(None)), set())  # não consultado
        self.assertEqual(contratos_com_faturas(_fotografia([])), {"326557"})  # consultado, sem notas


class _Cliente:
    def __init__(self, foto: dict, com_faturas: bool):
        self.foto = foto
        if com_faturas:
            self.faturas = lambda cid: copy.deepcopy(foto["detalhes"][str(cid)]["faturas"])

    def contratos_ug(self, ug):
        return copy.deepcopy(self.foto["lista_ativos"])

    def contratos_inativos_ug(self, ug):
        return []

    def historico(self, cid):
        return []

    def empenhos(self, cid):
        return []


class ConsultarTests(unittest.TestCase):
    def test_consulta_grava_as_faturas_no_detalhe(self) -> None:
        nova = consultar(_Cliente(_fotografia([_fatura()]), True), None, referencia=date(2026, 10, 11), agora=datetime(2026, 10, 11, 8))
        self.assertEqual(nova["detalhes"]["326557"]["faturas"][0]["numero"], "68715")

    def test_cliente_sem_o_endpoint_nao_inventa_lista_vazia(self) -> None:
        nova = consultar(_Cliente(_fotografia([_fatura()]), False), None, referencia=date(2026, 10, 11), agora=datetime(2026, 10, 11, 8))
        self.assertNotIn("faturas", nova["detalhes"]["326557"])


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------------------ telas (janelas de detalhe)

import json  # noqa: E402

import pytest  # noqa: E402

import src.contratos_continuos_cadastro as cadastro  # noqa: E402
from src import contratosgov_extracao  # noqa: E402
from src.contratosgov_extracao import calcular_delta, gravar  # noqa: E402
from tests import test_contratos_continuos_gov_page as pagina_continuos  # noqa: E402
from tests import test_contratos_page as pagina_contratos  # noqa: E402


def _fixture_com_faturas() -> dict:
    nova = json.loads(pagina_continuos.FIXTURE.read_text(encoding="utf-8"))
    for detalhe in nova["detalhes"].values():
        detalhe["faturas"] = []  # consultado, sem notas
    nova["detalhes"]["1004328"]["faturas"] = [  # 13/2026 no cadastro de teste (NE 2026NE000522)
        _fatura(id=1, numero="100", dados_empenho=[{"numero_empenho": "2026NE000522"}], situacao="Siafi Erro"),
        _fatura(id=2, numero="200", dados_empenho=[{"numero_empenho": "2026NE999000"}]),
    ]
    return nova


def _gravar(nova: dict, manifestos, fotografias) -> None:
    gravar(nova, calcular_delta(None, nova), importado_em=datetime(2026, 10, 8, 9, 45), referencia=date(2026, 10, 8),
           dir_manifestos=manifestos, dir_fotografias=fotografias)


@pytest.mark.skipif(not pagina_continuos.FIXTURE.exists(), reason="Fixture do Contratos.gov ausente")
def test_janela_da_pagina_contratos_lista_as_notas(tmp_path, monkeypatch) -> None:
    dirs = pagina_contratos.dirs.__wrapped__(tmp_path, monkeypatch)
    _gravar(_fixture_com_faturas(), *dirs)
    app = pagina_contratos._app()
    pagina_contratos._aba(app, "Todos")
    [b for b in app.button if b.key == "ctg_detalhe_1004328"][0].click().run()
    assert not app.exception, [e.value for e in app.exception]
    tabela = next(d.value for d in app.dataframe if {"Competência", "Nº"} <= set(d.value.columns))
    assert sorted(tabela["Nº"]) == ["100", "200"]  # na página Contratos, todas as notas do contrato
    assert any("erro no Siafi" in w.value for w in app.warning)


@pytest.mark.skipif(
    not (pagina_continuos.FIXTURE.exists() and pagina_continuos.MANIFESTO_EXECUCAO.exists()),
    reason="Fixture do Contratos.gov ou manifesto atual da Execução Mensal ausente",
)
def test_janela_de_continuos_filtra_as_notas_pela_ne_do_cadastro(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cadastro, "DIRETORIO_PADRAO", tmp_path / "continuos")
    manifestos, fotografias = tmp_path / "manifestos", tmp_path / "fotografias"
    monkeypatch.setattr(contratosgov_extracao, "DIRETORIO_MANIFESTOS", manifestos)
    monkeypatch.setattr(contratosgov_extracao, "DIRETORIO_FOTOGRAFIAS", fotografias)
    _gravar(_fixture_com_faturas(), manifestos, fotografias)
    registros = [cadastro.novo_contrato(**r) for r in pagina_continuos.REGISTROS]
    for registro in registros:
        cadastro.salvar_contrato(2026, registro)

    app = pagina_continuos._abrir()
    pagina_continuos._botao(app, "cc_editar_", registros[0]["id"]).click()
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    tabela = next(d.value for d in app.dataframe if {"Competência", "Nº"} <= set(d.value.columns))
    assert list(tabela["Nº"]) == ["100"]  # só a nota paga pela NE do cadastro
    assert any("1 de 2 nota(s)" in c.value for c in app.caption)
