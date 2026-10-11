"""Teste da tela de decisões (confirmar/rejeitar) na janela "Editar contrato" (11/10/2026).

Pasta de decisões em `tmp_path` (nada é gravado em `data/`). Ambiente do teste de conciliação: fixture do Contratos.gov
com uma nota da NE da 20RK; a Liquidação por Competência é a real, então o mês sugerido depende dela — por isso o teste
confere só a presença do formulário e a gravação pelo callback (módulo de decisões), não um mês específico.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

import src.contratos_continuos_cadastro as cadastro
from src import contratosgov_extracao, decisoes_conciliacao
from src.contratosgov_extracao import calcular_delta, gravar
from tests import test_contratos_continuos_gov_page as pagina
from tests.test_conciliacao_competencia_gov import _fixture_com_notas

pytestmark = pytest.mark.skipif(
    not (pagina.FIXTURE.exists() and pagina.MANIFESTO_EXECUCAO.exists()),
    reason="Fixture do Contratos.gov ou manifesto atual da Execução Mensal ausente",
)


def test_formulario_de_decisao_aparece_nos_meses_com_sugestao_e_grava_pelo_callback(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cadastro, "DIRETORIO_PADRAO", tmp_path / "continuos")
    manifestos, fotografias = tmp_path / "manifestos", tmp_path / "fotografias"
    monkeypatch.setattr(contratosgov_extracao, "DIRETORIO_MANIFESTOS", manifestos)
    monkeypatch.setattr(contratosgov_extracao, "DIRETORIO_FOTOGRAFIAS", fotografias)
    monkeypatch.setattr(decisoes_conciliacao, "DIRETORIO_DECISOES", tmp_path / "decisoes")
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
    # a página abriu sem decisão nenhuma; nada gravado ao abrir
    assert not (tmp_path / "decisoes").exists() or not list((tmp_path / "decisoes").glob("*.json"))
