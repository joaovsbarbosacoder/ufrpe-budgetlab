"""Teste de página da seção "Sincronização com o Google Drive" em `app_pages/backup_dados.py` (21/10/2026).

O Drive é trocado por um armazenamento em memória e o diretório de trabalho vai para `tmp_path`: nada toca a rede nem
`data/` de verdade.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import sincronizacao_drive as sd
from tests._apptest import TEMPO_LIMITE_APPTEST
from tests.test_sincronizacao_drive import Memoria

PAGINA = Path(__file__).resolve().parents[1] / "app_pages" / "backup_dados.py"


def _abrir(sessao: dict | None = None) -> AppTest:
    app = AppTest.from_file(str(PAGINA), default_timeout=TEMPO_LIMITE_APPTEST)
    for chave, valor in (sessao or {}).items():
        app.session_state[chave] = valor
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def _textos(app: AppTest) -> str:
    blocos = [*app.markdown, *app.caption, *app.info, *app.warning, *app.error, *app.success]
    return "\n".join(str(b.value) for b in blocos)


@pytest.fixture
def ambiente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Memoria:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    drive = Memoria()
    monkeypatch.setattr(sd, "situacao_conexao_drive", lambda *a, **k: "conectado")
    monkeypatch.setattr(sd, "criar_armazenamento_drive", lambda *a, **k: drive)
    return drive


def test_sem_credenciais_orienta_e_nao_oferece_conexao(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sd, "situacao_conexao_drive", lambda *a, **k: "sem_credenciais")
    app = _abrir()
    assert any(s.value == "Sincronização com o Google Drive" for s in app.subheader)
    assert "credentials.json" in _textos(app)
    assert not [b for b in app.button if b.key == "sinc_conectar"]


def test_desconectado_oferece_conectar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sd, "situacao_conexao_drive", lambda *a, **k: "desconectado")
    assert [b for b in _abrir().button if b.key == "sinc_conectar"]


def test_sincronizar_agora_envia_as_decisoes_ao_drive(ambiente, tmp_path):
    arquivo = tmp_path / "data" / "resultado_orcamentario" / "2026" / "celulas.json"
    arquivo.parent.mkdir(parents=True)
    arquivo.write_text("{}", encoding="utf-8")
    app = _abrir()
    app.button(key="sinc_agora").click().run()

    assert not app.exception, [e.value for e in app.exception]
    assert len(ambiente.arquivos) == 1
    assert "enviad" in _textos(app).lower()
    assert (tmp_path / "data" / "sincronizacao" / "estado.json").exists()


def test_conflito_mostra_as_duas_escolhas_e_trazer_aplica_a_versao_do_drive(ambiente, tmp_path):
    # outro dispositivo enviou uma versão
    origem = tmp_path / "outro" / "data"
    (origem / "resultado_orcamentario").mkdir(parents=True)
    (origem / "resultado_orcamentario" / "celulas.json").write_text('{"de": "outro"}', encoding="utf-8")
    ambiente.enviar("decisoes-20261021-090000-000000-outro123.zip", sd.gerar_pacote(origem))

    conflito = sd.ResultadoSincronizacao(sd.ACAO_CONFLITO, "O Drive tem uma versão mais nova e este dispositivo também mudou.")
    app = _abrir({"sinc_resultado": conflito})
    assert {b.key for b in app.button} >= {"sinc_trazer", "sinc_manter"}

    app.button(key="sinc_trazer").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert (tmp_path / "data" / "resultado_orcamentario" / "celulas.json").read_text(encoding="utf-8") == '{"de": "outro"}'


def test_falha_de_rede_mostra_o_erro_e_a_pagina_segue(ambiente, tmp_path):
    ambiente.falhar = True
    app = _abrir()
    app.button(key="sinc_agora").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert "Sem conexão" in _textos(app)
