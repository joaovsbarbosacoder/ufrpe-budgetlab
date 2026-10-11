"""Testes da linha do tempo das vigências DENTRO do cadastro de cada contrato (11/10/2026).

Pedido do usuário: a linha do tempo fica na janela de cada contrato — na página Contratos (Contratos.gov) e na janela
"Editar contrato" de Contratos Contínuos —, não numa seção separada. Ambientes reaproveitados dos testes das duas
páginas (cadastro/fotografia em `tmp_path`, data de referência 08/10/2026). Somente leitura.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.linha_tempo_vigencias import LinhaDoTempo, Segmento
from src.ui_linha_tempo_vigencias import html_bloco_contrato
from tests import test_contratos_page as pagina_contratos
from tests.test_contratos_continuos_gov_page import (
    FIXTURE,
    MANIFESTO_EXECUCAO,
    PAGINA,
    _abrir,
    _ambiente,
    _botao,
    _html,
    aquecer_pagina,
)


def _blocos(app) -> str:
    return " ".join(m.value for m in app.markdown if 'class="ltv-bloco"' in m.value)


def test_bloco_escapa_textos_e_lista_os_periodos() -> None:
    linha = LinhaDoTempo(
        contrato="01/2026", fornecedor="C&C <LTDA>", ligado=True, fim_gov=date(2027, 1, 1), fim_cadastro=date(2027, 2, 1),
        situacao="Vigente", tom="ok", segmentos=[Segmento(date(2026, 1, 1), date(2027, 1, 1), "TA <1>", "ta")],
    )
    html = html_bloco_contrato(linha, date(2026, 10, 11))
    assert "TA &lt;1&gt;" in html
    assert "<li>TA &lt;1&gt;: 01/01/2026 a 01/01/2027</li>" in html
    assert "≠ cadastro 01/02/2027" in html
    assert 'class="ltv-hoje c-hoje"' in html


@pytest.mark.skipif(
    not (FIXTURE.exists() and MANIFESTO_EXECUCAO.exists()),
    reason="Fixture do Contratos.gov ou manifesto atual da Execução Mensal ausente",
)
class TestContratosContinuos:
    @pytest.fixture(scope="class", autouse=True)
    def _aquecer(self):
        aquecer_pagina(PAGINA)

    def test_pagina_nao_tem_secao_separada(self, tmp_path, monkeypatch) -> None:
        _ambiente(tmp_path, monkeypatch, com_fotografia=True)
        app = _abrir()
        assert not any("Linha do tempo das vigências" in e.label for e in app.expander)
        assert _blocos(app) == ""

    def test_janela_de_edicao_mostra_a_linha_do_tempo_do_contrato(self, tmp_path, monkeypatch) -> None:
        registros = _ambiente(tmp_path, monkeypatch, com_fotografia=True)
        app = _abrir()
        _botao(app, "cc_editar_", registros[1]["id"]).click()  # 29/2021: contrato + 4 termos aditivos de vigência
        app.run()
        assert not app.exception, [e.value for e in app.exception]
        bloco = _blocos(app)
        assert bloco.count('class="ltv-bloco"') == 1
        assert bloco.count('class="ltv-seg ') >= 2
        assert "≠ cadastro" in bloco  # 29/2021: vigência do cadastro diverge da do gov
        assert "Contratos.gov" in _html(app)


@pytest.mark.skipif(not pagina_contratos.FIXTURE.exists(), reason="Fixture do Contratos.gov ausente")
def test_detalhe_da_pagina_contratos_mostra_a_linha_do_tempo(tmp_path, monkeypatch) -> None:
    dirs = pagina_contratos.dirs.__wrapped__(tmp_path, monkeypatch)
    pagina_contratos._gravar_fixture(dirs)
    cid = next(c for c, d in pagina_contratos._fixture()["detalhes"].items() if d["historico"])
    app = pagina_contratos._app()
    pagina_contratos._aba(app, "Todos")
    [b for b in app.button if b.key == f"ctg_detalhe_{cid}"][0].click().run()
    assert not app.exception, [e.value for e in app.exception]
    bloco = _blocos(app)
    assert bloco.count('class="ltv-bloco"') == 1
    assert 'class="ltv-seg c-contrato' in bloco
    assert "Linha do tempo das vigências" in " ".join(m.value for m in app.markdown)
