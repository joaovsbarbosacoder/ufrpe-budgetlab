"""Testes da página Contratos (`app_pages/contratos.py`), cadastro a partir do Contratos.gov.br.

Nenhum teste acessa a rede nem escreve em `data/`: os diretórios de fotografias e manifestos
(`src.contratosgov_extracao.DIRETORIO_FOTOGRAFIAS`/`DIRETORIO_MANIFESTOS`) e o arquivo de
complementos (`src.contratos_complementos.CAMINHO_PADRAO`) são trocados por `tmp_path` com
`monkeypatch` — a página os lê em tempo de execução. O cliente HTTP é trocado por um falso
(`src.contratosgov_api.ClienteContratosGov`, que a página também resolve em tempo de execução).

Data de referência: a página usa `date.today()`, a não ser que `st.session_state` traga
`contratos_referencia` (gancho só para testes determinísticos). Aqui fixamos 08/10/2026, a data
dos valores conferidos à mão na docstring de `tests/test_contratos_cadastro.py`: 6 contratos
(5 ativos + 1 inativo na API), 4 vigentes, 1 vence em até 90 dias (00029/2021), valor global
dos vigentes R$ 11.278.519,41.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

from src import contratos_complementos, contratosgov_api, contratosgov_extracao
from src.contratosgov_extracao import calcular_delta, gravar
from tests._apptest import TEMPO_LIMITE_APPTEST

PAGINA = str(Path(__file__).resolve().parents[1] / "app_pages" / "contratos.py")
FIXTURE = Path(__file__).parent / "fixtures" / "contratosgov_2026-10-08.json"
REF = date(2026, 10, 8)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    manifestos, fotografias = tmp_path / "manifestos", tmp_path / "fotografias"
    monkeypatch.setattr(contratosgov_extracao, "DIRETORIO_MANIFESTOS", manifestos)
    monkeypatch.setattr(contratosgov_extracao, "DIRETORIO_FOTOGRAFIAS", fotografias)
    monkeypatch.setattr(contratos_complementos, "CAMINHO_PADRAO", tmp_path / "contratos" / "complementos.json")
    return manifestos, fotografias


def _gravar_fixture(dirs):
    nova = _fixture()
    return gravar(
        nova, calcular_delta(None, nova), importado_em=datetime(2026, 10, 8, 9, 45),
        referencia=REF, dir_manifestos=dirs[0], dir_fotografias=dirs[1],
    )


def _app() -> AppTest:
    app = AppTest.from_file(PAGINA, default_timeout=TEMPO_LIMITE_APPTEST)
    app.session_state["contratos_referencia"] = REF
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def _textos(app: AppTest) -> str:
    return "\n".join(str(b.value) for b in app.markdown) + "\n" + "\n".join(
        str(b.value) for b in (*app.caption, *app.info, *app.error, *app.warning, *app.success)
    )


def _botao(app: AppTest, rotulo: str):
    achados = [b for b in app.button if b.label == rotulo]
    assert achados, f"botão {rotulo!r} ausente: {[b.label for b in app.button]}"
    return achados[0]


class _ClienteFalso:
    """Responde a partir da fixture, como a API faria (sem rede)."""

    def __init__(self, *args, **kwargs):
        self.foto = _fixture()
        self.chamadas = 0

    def contratos_ug(self, ug):
        self.chamadas += 1
        return self.foto["lista_ativos"]

    def contratos_inativos_ug(self, ug):
        self.chamadas += 1
        return self.foto["lista_inativos"]

    def historico(self, cid):
        self.chamadas += 1
        return self.foto["detalhes"][cid]["historico"]

    def empenhos(self, cid):
        self.chamadas += 1
        return self.foto["detalhes"][cid]["empenhos"]


class _ClienteQueFalha(_ClienteFalso):
    def contratos_ug(self, ug):
        raise contratosgov_api.ErroApiContratosGov(
            "HTTP 503", "https://contratos.comprasnet.gov.br/api/contrato/ug/153165", 503
        )


def test_sem_fotografia_mostra_primeira_carga(dirs):
    app = _app()
    _botao(app, "Fazer primeira carga")
    assert not any(b.label == "Consultar agora" for b in app.button)


def test_com_fotografia_mostra_resumo_e_lista(dirs):
    _gravar_fixture(dirs)
    app = _app()
    textos = _textos(app)
    assert "00013/2026" in textos
    assert 'cad-tile-rotulo">Vigentes</div><div class="cad-tile-valor">4<' in textos
    assert 'cad-tile-rotulo">Vencem em 90 dias</div><div class="cad-tile-valor">1<' in textos
    assert "R$ 11.278.519,41" in textos
    _botao(app, "Consultar agora")


def test_historico_lista_manifesto(dirs):
    manifesto = _gravar_fixture(dirs)
    app = _app()
    assert manifesto.sha256[:12] in _textos(app)


def test_nao_chama_a_rede_ao_abrir(dirs, monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("a página não pode chamar a rede ao abrir")

    monkeypatch.setattr(requests.Session, "get", proibido)
    _gravar_fixture(dirs)
    _app()


def test_erro_da_api_mostra_url_e_mantem_fotografia(dirs, monkeypatch):
    manifesto = _gravar_fixture(dirs)
    monkeypatch.setattr(contratosgov_api, "ClienteContratosGov", _ClienteQueFalha)
    app = _app()
    _botao(app, "Consultar agora").click().run()
    assert not app.exception, [e.value for e in app.exception]
    erros = "\n".join(str(e.value) for e in app.error)
    assert "https://contratos.comprasnet.gov.br/api/contrato/ug/153165" in erros
    assert "A fotografia anterior continua valendo." in erros
    assert [m.sha256 for m in contratosgov_extracao.historico_atualizacoes()] == [manifesto.sha256]


def test_primeira_carga_mostra_previa_e_grava_so_ao_confirmar(dirs, monkeypatch):
    monkeypatch.setattr(contratosgov_api, "ClienteContratosGov", _ClienteFalso)
    app = _app()
    _botao(app, "Fazer primeira carga").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert contratosgov_extracao.historico_atualizacoes() == []  # nada gravado antes de confirmar
    assert "Contratos novos (6)" in [e.label for e in app.expander]
    gravar_btn = _botao(app, "Gravar fotografia")
    assert not gravar_btn.disabled
    gravar_btn.click().run()
    assert not app.exception, [e.value for e in app.exception]
    historico = contratosgov_extracao.historico_atualizacoes()
    assert len(historico) == 1
    assert historico[0].contagens["contratos"] == 6


def test_remocao_exige_ciencia_para_gravar(dirs, monkeypatch):
    anterior = _fixture()
    anterior["lista_ativos"].append(
        {**anterior["lista_ativos"][0], "id": 999999, "numero": "00099/2099"}
    )
    anterior["detalhes"]["999999"] = anterior["detalhes"][str(anterior["lista_ativos"][0]["id"])]
    gravar(
        anterior, calcular_delta(None, anterior), importado_em=datetime(2026, 10, 1, 10, 0),
        referencia=REF, dir_manifestos=dirs[0], dir_fotografias=dirs[1],
    )
    monkeypatch.setattr(contratosgov_api, "ClienteContratosGov", _ClienteFalso)
    app = _app()
    _botao(app, "Consultar agora").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert _botao(app, "Gravar fotografia").disabled
    assert "00099/2099" in _textos(app)
    ciente = [c for c in app.checkbox if c.label == "Estou ciente da remoção"]
    assert ciente
    ciente[0].check().run()
    assert not _botao(app, "Gravar fotografia").disabled
    _botao(app, "Gravar fotografia").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(contratosgov_extracao.historico_atualizacoes()) == 2
