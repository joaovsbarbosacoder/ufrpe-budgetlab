"""Teste de página do Resultado Orçamentário (08/10/2026).

Usa as bases reais já importadas (Dotação Anual, Execução Mensal, cadastros de Contratos Contínuos e de
Bolsas e Auxílios, Liquidação por Competência), como `tests/test_cadastros_layout_page.py` — pulado se a
Dotação ou a Execução Mensal não tiverem sido importadas. A persistência da página (seleção de células e
despesas manuais) vai para `tmp_path`, via monkeypatch de `DIRETORIO_PADRAO`: o teste nunca grava em
`data/resultado_orcamentario/`. A regra da conta tem testes próprios (`tests/test_resultado_orcamentario.py`);
aqui só se confere que a tela abre, grava a seleção e inclui uma despesa manual.

Limitação de `AppTest`: não há elemento de teste para `st.data_editor`. A marcação da 1ª linha é feita
escrevendo o estado de edição do widget em `session_state` (o mesmo dicionário que o navegador envia) na
mesma execução do clique em "Salvar seleção".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import resultado_orcamentario_cadastro as cadastro
from tests._apptest import TEMPO_LIMITE_APPTEST, aquecer_pagina

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGINA = PROJECT_ROOT / "app_pages" / "resultado_orcamentario.py"
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
    # 1ª carga lê as bases reais (lenta a frio): aquece uma vez, fora dos testes cronometrados
    if PAGINA.exists():
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


def _textos(app: AppTest) -> str:
    blocos = [*app.markdown, *app.caption, *app.info, *app.warning, *app.error, *app.success]
    return "\n".join(str(bloco.value) for bloco in blocos)


def _exercicio(app: AppTest) -> int:
    return int(app.selectbox(key="ro_exercicio").value)


def test_pagina_abre_sem_excecao(diretorio: Path) -> None:
    app = _abrir()
    assert not app.exception
    assert any(titulo.value == "Resultado Orçamentário" for titulo in app.title)


def test_sem_selecao_mostra_mensagem(diretorio: Path) -> None:
    app = _abrir()
    assert "Nenhuma célula selecionada" in _textos(app)


def test_salvar_selecao_grava_arquivo(diretorio: Path) -> None:
    app = _abrir()
    exercicio = _exercicio(app)
    app.session_state[f"ro_celulas_{exercicio}"] = {
        "edited_rows": {0: {"Selecionar": True}},
        "added_rows": [],
        "deleted_rows": [],
    }
    app.button(key="ro_salvar_selecao").click().run()
    assert not app.exception, [e.value for e in app.exception]

    arquivo = diretorio / str(exercicio) / "celulas.json"
    assert arquivo.exists()
    assert len(json.loads(arquivo.read_text(encoding="utf-8"))["celulas"]) == 1


def test_incluir_despesa_manual(diretorio: Path) -> None:
    app = _abrir()
    exercicio = _exercicio(app)
    app.text_input(key="ro_despesa_descricao").input("Teste")
    app.number_input(key="ro_despesa_valor").set_value(100.0)
    app.button(key="FormSubmitter:ro_nova_despesa-Incluir").click().run()
    assert not app.exception, [e.value for e in app.exception]

    arquivo = diretorio / str(exercicio) / "despesas_manuais.json"
    assert arquivo.exists()
    despesas = json.loads(arquivo.read_text(encoding="utf-8"))["despesas"]
    assert len(despesas) == 1
    assert despesas[0]["descricao"] == "Teste"
    assert despesas[0]["valor"] == 100.0

    # lista em linhas, com Editar/Excluir por despesa (layout do protótipo, 08/10/2026)
    assert any(bloco.value == "Teste" for bloco in app.markdown)
    assert app.button(key=f"ro_editar_{despesas[0]['id']}") is not None
    assert app.button(key=f"ro_excluir_{despesas[0]['id']}") is not None


def test_menu_tem_pagina(diretorio: Path) -> None:
    texto = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    assert '"app_pages/resultado_orcamentario.py"' in texto
    assert 'title="Resultado Orçamentário"' in texto

    # mesmo padrão de `tests/test_home_page.py`: abre o app pelo menu e troca para a página
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=TEMPO_LIMITE_APPTEST)
    app.run()
    app.switch_page("app_pages/resultado_orcamentario.py")
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    assert any(titulo.value == "Resultado Orçamentário" for titulo in app.title)
