"""Edição da Projeção pela execução na página Bolsas e Auxílios (15/10/2026).

Cadastro, ajustes e preferências ficam em `tmp_path` (nada é gravado em `data/`). Usa as bases reais, como
`tests/test_contratos_continuos_projecao_editavel_page.py`; sem o cadastro de Bolsas ou o manifesto atual, os testes são pulados.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import src.bolsas_auxilios_cadastro as cadastro
import src.projecao_ajustes as projecao_ajustes
from src.ui_projecao_execucao import ler_valor_brl
from tests._apptest import TEMPO_LIMITE_APPTEST, aquecer_pagina

PAGINA = str(Path(__file__).resolve().parents[1] / "app_pages" / "bolsas_auxilios.py")
CADASTRO_REAL = Path("data/bolsas_auxilios")
MANIFESTO_EXECUCAO = Path("data/manifestos/execucao_mensal_atual.json")
ROTULO_EXPANSOR = "Editar a projeção pela execução"

pytestmark = pytest.mark.skipif(
    not (CADASTRO_REAL.exists() and any(CADASTRO_REAL.glob("2026/*.json")) and MANIFESTO_EXECUCAO.exists()),
    reason="Cadastro de Bolsas e Auxílios de 2026 ou manifesto atual da Execução Mensal ausente",
)


@pytest.fixture(scope="module", autouse=True)
def _aquecer():
    aquecer_pagina(PAGINA)


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    shutil.copytree(CADASTRO_REAL, tmp_path / "bolsas")
    monkeypatch.setattr(cadastro, "DIRETORIO_PADRAO", tmp_path / "bolsas")
    monkeypatch.setattr(projecao_ajustes, "DIRETORIO_AJUSTES_BOLSAS", tmp_path / "ajustes_bolsas")
    monkeypatch.setattr(projecao_ajustes, "DIRETORIO_AJUSTES", tmp_path / "ajustes_contratos")
    return tmp_path / "ajustes_bolsas" / "2026"


def _abrir() -> AppTest:
    app = AppTest.from_file(PAGINA, default_timeout=TEMPO_LIMITE_APPTEST).run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def _campo(app, rotulo_inicio: str, mes: str):
    return next(t for t in app.text_input if t.label == f"{rotulo_inicio} {mes}")


def _botao(app, rotulo: str):
    return next(b for b in app.button if b.label == rotulo)


def _html(app) -> str:
    return " ".join(m.value for m in app.markdown)


def _eventos(pasta) -> list:
    return sorted(pasta.glob("*.json")) if pasta.exists() else []


def _ne_com_bolsa(app) -> str:
    """Primeira NE do seletor cujo formulário tem o campo de quantidade de bolsas (valor único de bolsa)."""

    seletor = next(s for s in app.selectbox if s.label == "NE")
    for ne in [rotulo.split(" — ")[0] for rotulo in seletor.options]:  # rótulo: `<NE> — <programa> — Processo <nº>`
        if seletor.value != ne:
            seletor.select(ne).run()
        if any(t.label.startswith("Bolsas de ") for t in app.text_input):
            return ne
    pytest.fail("nenhuma NE de Bolsas com valor único de bolsa neste cadastro")


def test_bloco_aparece_com_processo_e_programa(ambiente):
    app = _abrir()
    assert ROTULO_EXPANSOR in [e.label for e in app.expander]
    opcoes = next(s for s in app.selectbox if s.label == "NE").options
    assert any("Processo" in o for o in opcoes)
    assert "<th>Processo</th>" in _html(app)


def test_valor_e_quantidade_se_vinculam_nos_dois_sentidos(ambiente):
    app = _abrir()
    _ne_com_bolsa(app)
    qtd, valor = _campo(app, "Bolsas de", "Dez"), _campo(app, "Esperado de", "Dez")
    qtd.set_value("2").run()
    v2 = ler_valor_brl(_campo(app, "Esperado de", "Dez").value)
    assert v2 and v2 > 0
    _campo(app, "Bolsas de", "Dez").set_value("3").run()
    v3 = ler_valor_brl(_campo(app, "Esperado de", "Dez").value)
    assert v3 == pytest.approx(v2 * 1.5, abs=0.02)  # 3 bolsas = 1,5 × o valor de 2 bolsas
    _campo(app, "Esperado de", "Dez").set_value(f"{v2:.2f}".replace(".", ",")).run()
    assert _campo(app, "Bolsas de", "Dez").value == "2"  # o caminho inverso: valor → quantidade


def test_gravar_grava_o_valor_em_reais_na_pasta_de_bolsas(ambiente, tmp_path):
    app = _abrir()
    _ne_com_bolsa(app)
    _campo(app, "Bolsas de", "Dez").set_value("2").run()
    esperado = ler_valor_brl(_campo(app, "Esperado de", "Dez").value)
    _botao(app, "Gravar ajustes desta NE").click().run()
    assert not app.exception, [e.value for e in app.exception]
    arquivos = _eventos(ambiente)
    assert len(arquivos) == 1
    assert not (tmp_path / "ajustes_contratos").exists()  # Contratos não é tocado
    import json
    evento = json.loads(arquivos[0].read_text(encoding="utf-8"))
    assert evento["valores"]["12"] == pytest.approx(esperado)
    assert " ✎</td>" in _html(app)


def test_valor_nao_multiplo_avisa_mas_vale(ambiente):
    app = _abrir()
    _ne_com_bolsa(app)
    _campo(app, "Bolsas de", "Dez").set_value("2,5").run()  # meia bolsa: não é número inteiro
    assert any("2,5 bolsas" in c.value and "não é número inteiro de bolsas" in c.value for c in app.caption)
    _botao(app, "Gravar ajustes desta NE").click().run()
    assert len(_eventos(ambiente)) == 1  # aviso, não recusa


def test_diferenca_de_centavos_nao_gera_aviso(ambiente):
    app = _abrir()
    _ne_com_bolsa(app)
    _campo(app, "Bolsas de", "Dez").set_value("2").run()
    base = ler_valor_brl(_campo(app, "Esperado de", "Dez").value)
    _campo(app, "Esperado de", "Dez").set_value(f"{base + 0.01:.2f}".replace(".", ",")).run()
    assert not any("não é número inteiro de bolsas" in c.value for c in app.caption)


def test_refazer_todas_de_bolsas_nao_apaga_ajustes_de_contratos(ambiente, tmp_path):
    projecao_ajustes.registrar_ajustes(
        exercicio=2026, ne_curta="2026NE000001", valores={12: 10.0}, extracao="x", diretorio=tmp_path / "ajustes_contratos",
    )
    app = _abrir()
    _ne_com_bolsa(app)
    _campo(app, "Bolsas de", "Dez").set_value("2").run()
    _botao(app, "Gravar ajustes desta NE").click().run()
    next(c for c in app.checkbox if c.label.startswith("Confirmo refazer TODAS")).check().run()
    _botao(app, "Refazer todas do exercício").click().run()
    assert projecao_ajustes.ajustes_vigentes(2026, tmp_path / "ajustes_bolsas") == {}
    assert projecao_ajustes.ajustes_vigentes(2026, tmp_path / "ajustes_contratos") == {"2026NE000001": {12: 10.0}}


def test_log_corrompido_de_bolsas_avisa_e_nao_sobrescreve(ambiente):
    ambiente.mkdir(parents=True)
    ruim = ambiente / "0000_corrompido.json"
    ruim.write_text("{ quebrado", encoding="utf-8")
    app = _abrir()
    assert any("Ajustes da projeção ilegíveis" in w.value for w in app.warning)
    assert any("Não foi possível ler os ajustes gravados" in e.value for e in app.error)
    assert ruim.read_text(encoding="utf-8") == "{ quebrado"
