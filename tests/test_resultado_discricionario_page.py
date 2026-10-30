"""Teste de página de "Discricionário por Plano" (29/10/2026).

Usa as bases reais já importadas (Dotação Anual, Execução Mensal, cadastros de Contratos e Bolsas, Liquidação por Competência), como
`tests/test_resultado_orcamentario_page.py` — pulado se a Dotação ou a Execução Mensal não tiverem sido importadas. A página só lê:
o cadastro de despesas e receitas vai para `tmp_path` por monkeypatch de `DIRETORIO_PADRAO`, e o teste confere que nada é gravado.
A conta dos quadros tem testes próprios (`tests/test_resultado_orcamentario_planos.py`, `tests/test_ui_resultado_planos.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import resultado_orcamentario_cadastro as cadastro
from tests._apptest import TEMPO_LIMITE_APPTEST, aquecer_pagina

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGINA = PROJECT_ROOT / "app_pages" / "resultado_discricionario.py"
MANIFESTOS = (
    PROJECT_ROOT / "data" / "manifestos" / "dotacao_anual_atual.json",
    PROJECT_ROOT / "data" / "manifestos" / "execucao_mensal_atual.json",
)

pytestmark = pytest.mark.skipif(
    not all(caminho.exists() for caminho in MANIFESTOS),
    reason="Dotação Anual ou Execução Mensal não importadas neste ambiente.",
)


@pytest.fixture(scope="module", autouse=True)
def _aquecer() -> None:
    aquecer_pagina(str(PAGINA))


@pytest.fixture
def diretorio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cadastro, "DIRETORIO_PADRAO", tmp_path)
    return tmp_path


def _abrir() -> AppTest:
    app = AppTest.from_file(str(PAGINA), default_timeout=TEMPO_LIMITE_APPTEST)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def _html(app: AppTest) -> str:
    return "".join(str(e.proto.body) for e in app.get("html"))


def test_pagina_abre_com_os_quadros_por_plano_e_fecha_com_o_resultado(diretorio: Path) -> None:
    app = _abrir()
    html = _html(app)
    assert 'class="rp"' in html and html.count('<article class="card"') >= 1
    assert "Dotação discricionária" in html and "PO " in html
    assert "A soma dos quadros confere com o resultado do discricionário" in html
    assert "Resultado Primário 2" in " ".join(str(c.value) for c in app.caption)


def test_pagina_nao_grava_nada(diretorio: Path) -> None:
    _abrir()
    assert list(diretorio.rglob("*")) == []


def test_pagina_oferece_a_escolha_do_exercicio(diretorio: Path) -> None:
    app = _abrir()
    exercicios = app.selectbox(key="rd_exercicio").options
    assert len(exercicios) >= 1 and any("2026" in str(o) for o in exercicios)


def test_menu_tem_a_pagina() -> None:
    texto = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    assert '"app_pages/resultado_discricionario.py"' in texto and 'title="Discricionário por Plano"' in texto


def test_filtros_por_acao_e_situacao_recortam_os_quadros(diretorio: Path) -> None:
    # 30/10/2026: filtros só de exibição — com recorte, aviso "Filtrado" e sem a conferência com o resultado
    app = _abrir()
    cartoes = _html(app).count('<article class="card"')
    acao = app.multiselect(key="rd_f_acao")
    assert len(acao.options) >= 1 and app.multiselect(key="rd_f_situacao").options
    acao.set_value([acao.options[0].split(" — ")[0]]).run()  # options traz o rótulo; o valor é o código da Ação
    assert not app.exception
    html = _html(app)
    assert "Filtrado:" in html and f"de {cartoes} Planos" in html
    assert "A soma dos quadros confere" not in html
    assert html.count('<article class="card"') <= cartoes
    # Planos oferecidos passam a ser só os da Ação escolhida
    assert len(app.multiselect(key="rd_f_plano").options) == html.count('<article class="card"')
    acao.set_value([]).run()
    assert "A soma dos quadros confere" in _html(app)
