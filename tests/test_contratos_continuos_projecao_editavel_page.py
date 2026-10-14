"""Edição da Projeção pela execução na página Contratos Contínuos (14/10/2026).

Ajustes, cadastro e preferências ficam em `tmp_path` (nada é gravado em `data/`). Mesmo ambiente e mesma limitação de
`tests/test_contratos_continuos_gov_page.py` (bases reais; testes pulados sem o manifesto atual).
"""

from __future__ import annotations

import pytest

import src.projecao_ajustes as projecao_ajustes
from src import preferencias_ui
from tests._apptest import aquecer_pagina
from tests.test_contratos_continuos_gov_page import FIXTURE, MANIFESTO_EXECUCAO, PAGINA, _abrir, _ambiente

pytestmark = pytest.mark.skipif(
    not (FIXTURE.exists() and MANIFESTO_EXECUCAO.exists()),
    reason="Fixture do Contratos.gov ou manifesto atual da Execução Mensal ausente",
)

ROTULO_BASE = "Base da necessidade de empenho"
ROTULO_EXPANSOR = "Editar a projeção pela execução"
NE = "2026NE000522"  # contrato 13/2026 — PRIME CONSULTORIA (REGISTROS da página de referência)


@pytest.fixture(scope="module", autouse=True)
def _aquecer():
    aquecer_pagina(PAGINA)


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch, com_fotografia=False)
    monkeypatch.setattr(preferencias_ui, "DIRETORIO_PADRAO", tmp_path / "preferencias")
    monkeypatch.setattr(projecao_ajustes, "DIRETORIO_AJUSTES", tmp_path / "ajustes")
    return tmp_path / "ajustes" / "2026"


def _em_modo_projecao():
    app = _abrir()
    radio = next((r for r in app.radio if r.label == ROTULO_BASE), None)
    if radio is None:
        pytest.skip("Liquidação por Competência indisponível neste ambiente: o seletor não aparece")
    radio.set_value("Projeção pela execução").run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def _selecionar_ne(app, ne=NE):
    """O seletor usa `format_func`: as opções exibidas são os rótulos, mas `select`/`value` trabalham com a NE."""

    seletor = next(s for s in app.selectbox if s.label == "NE")
    assert any(o.startswith(ne) for o in seletor.options)
    if seletor.value != ne:  # já é a NE em tela: nada a selecionar
        seletor.select(ne).run()
        assert not app.exception, [e.value for e in app.exception]


def _campo(app, mes: str):
    return next(t for t in app.text_input if t.label == f"Esperado de {mes}")


def _botao(app, rotulo: str):
    return next(b for b in app.button if b.label == rotulo)


def _html(app) -> str:
    return " ".join(m.value for m in app.markdown)


def _celulas_ajustadas(app) -> int:
    """Células da matriz com ✎ (a legenda também cita o símbolo, por isso conta só as de tabela)."""

    return _html(app).count(" ✎</td>")


def _eventos(pasta) -> list:
    return sorted(pasta.glob("*.json")) if pasta.exists() else []


def test_bloco_aparece_so_no_modo_projecao_pela_execucao(ambiente):
    app = _abrir()
    assert ROTULO_EXPANSOR not in [e.label for e in app.expander]
    app = _em_modo_projecao()
    assert ROTULO_EXPANSOR in [e.label for e in app.expander]


def test_seletor_traz_o_titulo_do_contrato(ambiente):
    app = _em_modo_projecao()
    opcoes = next(s for s in app.selectbox if s.label == "NE").options
    assert any(o.startswith(NE) and "Contrato 13/2026" in o and "PRIME CONSULTORIA" in o for o in opcoes)


def test_gravar_marca_a_matriz_e_cria_um_evento(ambiente):
    app = _em_modo_projecao()
    _selecionar_ne(app)
    assert _celulas_ajustadas(app) == 0
    _campo(app, "Dez").set_value("12.345,67")
    _botao(app, "Gravar ajustes desta NE").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(_eventos(ambiente)) == 1
    assert _celulas_ajustadas(app) == 1


def test_gravar_sem_mudanca_nao_cria_evento(ambiente):
    app = _em_modo_projecao()
    _selecionar_ne(app)
    _botao(app, "Gravar ajustes desta NE").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert _eventos(ambiente) == []


def test_valor_invalido_mostra_erro_e_nao_grava(ambiente):
    app = _em_modo_projecao()
    _selecionar_ne(app)
    _campo(app, "Dez").set_value("abc")
    _botao(app, "Gravar ajustes desta NE").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("Dez" in e.value for e in app.error)
    assert _eventos(ambiente) == []


def test_refazer_ne_remove_a_marca_e_o_log_continua(ambiente):
    app = _em_modo_projecao()
    _selecionar_ne(app)
    _campo(app, "Dez").set_value("12345,67")
    _botao(app, "Gravar ajustes desta NE").click().run()
    assert _celulas_ajustadas(app) == 1
    assert _botao(app, "Refazer esta NE pela metodologia").disabled  # sem confirmar
    next(c for c in app.checkbox if c.label.startswith("Confirmo refazer esta NE")).check().run()
    _botao(app, "Refazer esta NE pela metodologia").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert _celulas_ajustadas(app) == 0
    assert len(_eventos(ambiente)) == 2  # ajustar + refazer_ne: nada é apagado


def test_refazer_todas_exige_confirmacao_e_limpa_o_exercicio(ambiente):
    app = _em_modo_projecao()
    _selecionar_ne(app)
    _campo(app, "Dez").set_value("12345,67")
    _botao(app, "Gravar ajustes desta NE").click().run()
    assert _botao(app, "Refazer todas do exercício").disabled  # sem confirmar
    next(c for c in app.checkbox if c.label.startswith("Confirmo refazer TODAS")).check().run()
    _botao(app, "Refazer todas do exercício").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert _celulas_ajustadas(app) == 0
    assert len(_eventos(ambiente)) == 2


def test_log_corrompido_avisa_usa_a_metodologia_e_nao_sobrescreve(ambiente):
    ambiente.mkdir(parents=True)
    ruim = ambiente / "0000_corrompido.json"
    ruim.write_text("{ quebrado", encoding="utf-8")
    app = _em_modo_projecao()
    assert any("Ajustes da projeção ilegíveis" in w.value for w in app.warning)
    assert any("Não foi possível ler os ajustes gravados" in e.value for e in app.error)
    assert ruim.read_text(encoding="utf-8") == "{ quebrado"
    assert len(_eventos(ambiente)) == 1


def test_ajuste_superado_aparece_na_tela_sem_abrir_o_expansor(ambiente):
    # ajuste gravado para março: com a extração atual o mês já está fechado → "superado" (vale o realizado)
    projecao_ajustes.registrar_ajustes(exercicio=2026, ne_curta=NE, valores={3: 1000.0}, extracao="abcd1234")
    app = _em_modo_projecao()
    assert any("Ajuste superado" in w.value and NE in w.value for w in app.warning)
    assert len(_eventos(ambiente)) == 1  # nada foi apagado nem gravado por cima
