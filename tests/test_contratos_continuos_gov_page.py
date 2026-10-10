"""Testes da página Contratos Contínuos — integração com o Contratos.gov.br (10/2026).

Cadastro nativo e fotografia do gov são trocados por `tmp_path` com `monkeypatch`
(`src.contratos_continuos_cadastro.DIRETORIO_PADRAO`, `src.contratosgov_extracao.DIRETORIO_*`), então
nenhum teste escreve em `data/`. A fotografia é a congelada `tests/fixtures/contratosgov_2026-10-08.json`
(6 contratos), gravada com `gravar(...)` como em `tests/test_contratos_page.py`; a data de referência é
fixada em 08/10/2026 pelo gancho `st.session_state["contratos_referencia"]` (o mesmo de
`app_pages/contratos.py`). As demais bases (Execução Mensal etc.) são as reais, como em
`tests/test_cadastros_layout_page.py` — por isso o teste é pulado sem o manifesto atual.

Limitação do `AppTest` (ver `tests/test_cadastros_layout_page.py`): só a PRIMEIRA execução de um
`@st.dialog` — a que reage ao clique que o abre — é alcançável; os testes de janela conferem o conteúdo ao
abrir, nunca interagem dentro dela, e nenhum clica em "Salvar".
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import src.contratos_continuos_cadastro as cadastro
from src import contratosgov_extracao
from src.contratosgov_extracao import calcular_delta, gravar
from tests._apptest import TEMPO_LIMITE_APPTEST, aquecer_pagina

PAGINA = str(Path(__file__).resolve().parents[1] / "app_pages" / "contratos_continuos.py")
FIXTURE = Path(__file__).parent / "fixtures" / "contratosgov_2026-10-08.json"
MANIFESTO_EXECUCAO = Path("data/manifestos/execucao_mensal_atual.json")
REF = date(2026, 10, 8)

pytestmark = pytest.mark.skipif(
    not (FIXTURE.exists() and MANIFESTO_EXECUCAO.exists()),
    reason="Fixture do Contratos.gov ou manifesto atual da Execução Mensal ausente",
)

#: três registros do exercício 2026 — ligado por NE e conciliado; ligado por NE e divergente (vigência original
#: 2025-10-17, sem aditivos nativos; o gov tem 4 aditivos); sem par no gov.
REGISTROS = [
    {"contrato_numero": "13/2026", "ne_curta": "2026NE000522", "fornecedor": "PRIME CONSULTORIA",
     "vigencia_fim": "2027-09-10", "despesa_mensal": 1000.0},
    {"contrato_numero": "29/2021", "ne_curta": "2025NE000046", "fornecedor": "TEKIS TECNOLOGIAS",
     "vigencia_fim": "2025-10-17", "despesa_mensal": 1000.0},
    {"contrato_numero": "99/2026", "ne_curta": "2026NE999999", "fornecedor": "SEM PAR LTDA",
     "vigencia_fim": "2027-01-31", "despesa_mensal": 1000.0},
]


@pytest.fixture(scope="module", autouse=True)
def _aquecer_cache_das_bases_reais():
    aquecer_pagina(PAGINA)


def _ambiente(tmp_path, monkeypatch, *, com_fotografia: bool) -> list[dict]:
    monkeypatch.setattr(cadastro, "DIRETORIO_PADRAO", tmp_path / "continuos")
    manifestos, fotografias = tmp_path / "manifestos", tmp_path / "fotografias"
    monkeypatch.setattr(contratosgov_extracao, "DIRETORIO_MANIFESTOS", manifestos)
    monkeypatch.setattr(contratosgov_extracao, "DIRETORIO_FOTOGRAFIAS", fotografias)
    if com_fotografia:
        nova = json.loads(FIXTURE.read_text(encoding="utf-8"))
        gravar(
            nova, calcular_delta(None, nova), importado_em=datetime(2026, 10, 8, 9, 45), referencia=REF,
            dir_manifestos=manifestos, dir_fotografias=fotografias,
        )
    registros = [cadastro.novo_contrato(**r) for r in REGISTROS]
    for registro in registros:
        cadastro.salvar_contrato(2026, registro)
    return registros


@pytest.fixture
def com_gov(tmp_path, monkeypatch):
    return _ambiente(tmp_path, monkeypatch, com_fotografia=True)


@pytest.fixture
def sem_gov(tmp_path, monkeypatch):
    return _ambiente(tmp_path, monkeypatch, com_fotografia=False)


def _abrir() -> AppTest:
    app = AppTest.from_file(PAGINA, default_timeout=TEMPO_LIMITE_APPTEST)
    app.session_state["contratos_referencia"] = REF
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def _html(app: AppTest) -> str:
    return " ".join(m.value for m in app.markdown)


def _contem(texto: str, trecho: str) -> None:
    # mensagem curta de propósito: `assert trecho in texto` despejaria o HTML inteiro da página
    assert trecho in texto, f"trecho ausente na página: {trecho!r}"


def _botao(app: AppTest, prefixo: str, id_registro: str):
    return next(b for b in app.button if b.key and b.key.startswith(prefixo) and b.key.endswith(f"_{id_registro}"))


def _conteudo_do_cadastro(tmp_path) -> dict[str, str]:
    return {str(p.relative_to(tmp_path)): p.read_text(encoding="utf-8") for p in (tmp_path / "continuos").rglob("*.json")}


def test_linhas_mostram_conciliacao_e_aditivos_pendentes(com_gov):
    app = _abrir()
    html = _html(app)
    _contem(html, "Gov: vigência confere")  # 13/2026
    _contem(html, "Gov: vigência diverge")  # 29/2021
    _contem(html, "4 aditivo(s) do gov sem registro")  # 29/2021: 4 termos aditivos, nenhum nativo
    _contem(html, "sem par no Contratos.gov")  # 99/2026


def test_janela_de_edicao_lista_aditivos_do_gov_sem_gravar(com_gov, tmp_path):
    antes = _conteudo_do_cadastro(tmp_path)
    app = _abrir()
    _botao(app, "cc_editar_", com_gov[1]["id"]).click()
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    _contem(_html(app), "Contratos.gov")
    registrar = [b.label for b in app.button if b.label.startswith("Registrar aditivo do gov")]
    assert len(registrar) == 4
    for numero in ("00001/2022", "00002/2023", "00003/2024", "00004/2025"):
        assert any(numero in rotulo for rotulo in registrar), numero
    _contem(" ".join(c.value for c in app.caption), "Nada é gravado até clicar em Salvar")
    assert _conteudo_do_cadastro(tmp_path) == antes


def test_sem_fotografia_segue_com_aviso(sem_gov):
    app = _abrir()
    avisos = " ".join(str(e.value) for e in (*app.info, *app.warning))
    _contem(avisos, "Contratos.gov")
    html = _html(app)
    assert "Gov: vigência" not in html
    assert "sem par no Contratos.gov" not in html
    assert len([b for b in app.button if b.key and b.key.startswith("cc_editar_")]) == 3  # o registro continua


# --- Task 5: bloco "Novos no Contratos.gov" e inclusão -----------------------------------------------
# Cadastro de teste: 13/2026 (liga ao 1004328) e 29/2021 (liga ao 118872); candidatos = os outros dois
# vigentes do gov: 00021/2017 (id 18940, 14 NEs) e 00021/2023 (id 220038, sem empenhos).


def _campo(app: AppTest, rotulo: str):
    return next(w for w in (*app.text_input, *app.number_input, *app.date_input) if w.label == rotulo)


def _incluir(app: AppTest, contrato_id: str, ne: str | None = None) -> AppTest:
    if ne is not None:
        app.selectbox(key=f"cc_gov_ne_{contrato_id}").select(ne)
    next(b for b in app.button if b.key == f"cc_gov_incluir_{contrato_id}").click()
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def test_bloco_lista_candidatos_sem_ligados_inativos_e_encerrados(com_gov):
    app = _abrir()
    rotulos = [e.label for e in app.expander]
    assert any(r.startswith("Novos no Contratos.gov (2 candidato(s) · 0 em dúvida)") for r in rotulos), rotulos[:6]
    html = _html(app)
    _contem(html, "00021/2017")
    _contem(html, "00021/2023")
    # markdown simples, sem HTML: com `unsafe_allow_html` o Streamlit codificava `&` duas vezes ("C&C" virava
    # "C&amp;C" na tela real, conferido no navegador — o AppTest só vê o texto enviado, não o DOM renderizado).
    _contem(html, "**00021/2017** — RIO AVE IMOVEIS LTDA")
    assert "&amp;" not in html
    for ausente in ("00013/2026", "00029/2021", "00011/2017", "00018/2014"):  # ligados, inativo, encerrado
        assert ausente not in html, ausente


def test_incluir_abre_janela_pre_preenchida_sem_gravar(com_gov, tmp_path):
    antes = _conteudo_do_cadastro(tmp_path)
    app = _incluir(_abrir(), "18940")
    assert _campo(app, "Nº do contrato").value == "21/2017"
    assert _campo(app, "Fornecedor").value == "RIO AVE IMOVEIS LTDA"
    assert _campo(app, "Ano").value == 2017
    assert _campo(app, "CNPJ/CPF").value == "10729661000106"
    assert _campo(app, "Vigência (fim) — opcional").value == date(2027, 5, 28)
    for campo_manual in ("Ação", "PTRES", "UGR", "NE (opcional)", "ND", "PI"):  # NE não escolhida: tudo em branco
        assert _campo(app, campo_manual).value == "", campo_manual
    assert _campo(app, "Despesa mensal (R$)").value == 0.0  # padrão do formulário, não vem do gov
    assert _conteudo_do_cadastro(tmp_path) == antes


def test_ne_escolhida_preenche_ne_nd_e_pi(com_gov):
    app = _incluir(_abrir(), "18940", ne="2026NE000203")
    assert _campo(app, "NE (opcional)").value == "2026NE000203"
    assert _campo(app, "ND").value == "339092"
    assert _campo(app, "PI").value == "M20RKG01SCN"


def test_contrato_sem_empenhos_pode_ser_incluido(com_gov):
    app = _incluir(_abrir(), "220038")
    assert _campo(app, "Nº do contrato").value == "21/2023"
    assert _campo(app, "CNPJ/CPF").value == "00000000191"  # zeros preservados
    assert _campo(app, "NE (opcional)").value == ""
