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


# --------------------------------------------------------------------------------------
# Correções da revisão final
# --------------------------------------------------------------------------------------

def _numeros_na_ordem(app: AppTest) -> list[str]:
    """Números de contrato na ordem em que as linhas do registro aparecem."""
    achados = []
    for b in app.markdown:
        trecho = str(b.value)
        if 'class="cad-tit"' in trecho:
            achados.append(trecho.split('class="cad-tit">')[1].split("<")[0])
    return achados


def _aba(app: AppTest, rotulo: str) -> None:
    app.segmented_control(key="cad_abas_ctg").set_value(rotulo).run()
    assert not app.exception, [e.value for e in app.exception]


def test_fotografia_ausente_mostra_erro_e_permite_nova_carga(dirs, monkeypatch):
    manifesto = _gravar_fixture(dirs)
    (dirs[1] / manifesto.arquivo).unlink()
    monkeypatch.setattr(contratosgov_api, "ClienteContratosGov", _ClienteFalso)
    app = _app()  # não pode levantar exceção
    erros = "\n".join(str(e.value) for e in app.error)
    assert manifesto.arquivo in erros and "aba **Atualizar**" in erros
    assert not any(b.label == "Consultar agora" for b in app.button)  # nenhum dado do Cadastro
    _botao(app, "Fazer primeira carga").click().run()
    assert not app.exception, [e.value for e in app.exception]
    _botao(app, "Gravar fotografia").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(contratosgov_extracao.historico_atualizacoes()) == 2
    assert not app.error  # a nova fotografia é a atual e legível


def test_fotografia_adulterada_tambem_nao_derruba_a_pagina(dirs):
    manifesto = _gravar_fixture(dirs)
    caminho = dirs[1] / manifesto.arquivo
    caminho.write_bytes(caminho.read_bytes() + b"\n")
    app = _app()
    assert "sha256" in "\n".join(str(e.value) for e in app.error)
    _botao(app, "Fazer primeira carga")


def test_nova_consulta_que_falha_descarta_a_previa_antiga(dirs, monkeypatch):
    _gravar_fixture(dirs)
    monkeypatch.setattr(contratosgov_api, "ClienteContratosGov", _ClienteFalso)
    app = _app()
    _botao(app, "Consultar agora").click().run()
    assert not app.exception, [e.value for e in app.exception]
    _botao(app, "Gravar fotografia")  # prévia da primeira consulta na tela

    monkeypatch.setattr(contratosgov_api, "ClienteContratosGov", _ClienteQueFalha)
    _botao(app, "Consultar agora").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert app.error
    assert not any(b.label == "Gravar fotografia" for b in app.button)


def test_busca_com_letras_nao_casa_por_digitos_do_documento(dirs):
    _gravar_fixture(dirs)
    app = _app()
    _aba(app, "Todos")
    assert len(_numeros_na_ordem(app)) == 6
    app.text_input(key="ctg_busca").set_value("ltda 2").run()
    assert not app.exception, [e.value for e in app.exception]
    assert _numeros_na_ordem(app) == []
    assert "0 contrato(s)" in _textos(app)


def test_busca_numerica_curta_nao_casa_documento_mas_longa_sim(dirs):
    _gravar_fixture(dirs)
    app = _app()
    _aba(app, "Todos")
    app.text_input(key="ctg_busca").set_value("1004").run()  # 4 dígitos: casa o documento de ninguém aqui
    assert _numeros_na_ordem(app) == []
    app.text_input(key="ctg_busca").set_value("05.340.639/0001").run()
    assert _numeros_na_ordem(app) == ["00013/2026"]


def test_vencimento_mais_proximo_nao_poe_o_encerrado_ha_mais_tempo_primeiro(dirs):
    _gravar_fixture(dirs)
    app = _app()
    _aba(app, "Todos")
    ordem = _numeros_na_ordem(app)
    # |dias| crescente: 00029/2021 (9), 00021/2017 (232), 00013/2026 (337), 00021/2023 (360),
    # 00018/2014 (495 vencidos), 00011/2017 (3.403 vencidos, inativo)
    assert ordem == ["00029/2021", "00021/2017", "00013/2026", "00021/2023", "00018/2014", "00011/2017"]


def test_texto_da_api_no_detalhe_nao_e_interpretado_como_markdown(dirs):
    nova = _fixture()
    primeiro = nova["lista_ativos"][0]
    primeiro["objeto"] = "Pagar R$ 1,00 e R$ 2,00 com *ênfase* e _traço_"
    primeiro["fornecedor"]["nome"] = "A $ B * C"
    gravar(
        nova, calcular_delta(None, nova), importado_em=datetime(2026, 10, 8, 9, 45),
        referencia=REF, dir_manifestos=dirs[0], dir_fotografias=dirs[1],
    )
    app = _app()
    _aba(app, "Todos")
    botoes = [b for b in app.button if b.key == f"ctg_detalhe_{primeiro['id']}"]
    assert botoes
    botoes[0].click().run()
    assert not app.exception, [e.value for e in app.exception]
    legendas = [str(b.value) for b in app.markdown if "ctg-legenda" in str(b.value)]
    assert any("Pagar R$ 1,00 e R$ 2,00 com *ênfase* e _traço_" in t for t in legendas)
    assert any("A $ B * C" in t for t in legendas)
    assert not any("Objeto:" in str(c.value) for c in app.caption)


def test_termo_sem_novo_valor_global_rotula_o_valor_do_termo(dirs):
    _gravar_fixture(dirs)
    cid = next(c for c, d in _fixture()["detalhes"].items() if d["historico"])
    app = _app()
    _aba(app, "Todos")
    [b for b in app.button if b.key == f"ctg_detalhe_{cid}"][0].click().run()
    assert not app.exception, [e.value for e in app.exception]
    linha_do_tempo = "".join(str(b.value) for b in app.markdown if "ctg-timeline" in str(b.value))
    assert "valor global do termo R$" in linha_do_tempo or "novo valor global R$" in linha_do_tempo
