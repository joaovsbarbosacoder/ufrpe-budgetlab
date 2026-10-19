"""Testes do atualizador opcional do instalador Windows (sem rede)."""
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.instalador import atualizar as A

RAIZ_ZIP = "ufrpe-budgetlab-master/"


def _zip(caminho: Path, arquivos: dict[str, str]) -> Path:
    with zipfile.ZipFile(caminho, "w") as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    return caminho


def _app(tmp_path: Path, versao: dict | None = None) -> Path:
    app = tmp_path / "app"
    app.mkdir()
    if versao is not None:
        (app / "versao.txt").write_text(json.dumps(versao), encoding="utf-8")
    return app


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def _baixador(arquivos: dict[str, str]):
    def baixar(destino: Path) -> None:
        _zip(destino, {RAIZ_ZIP + k: v for k, v in arquivos.items()})

    return baixar


def _pip_nunca(*_):
    raise AssertionError("pip não deveria ser chamado")


def test_sem_novidade_quando_sha_igual(tmp_path):
    app = _app(tmp_path, {"commit": "abc", "requirements_sha256": "", "arquivos": []})

    def baixar(_):
        raise AssertionError("não deveria baixar")

    r = A.atualizar(app, Path("py"), sha=lambda: "abc", baixar=baixar, pip=_pip_nunca)
    assert r == "sem_novidade"


def test_atualiza_codigo_e_grava_versao(tmp_path):
    app = _app(tmp_path, {"commit": "velho", "requirements_sha256": _sha("r"), "arquivos": []})
    (app / "app.py").write_text("velho", encoding="utf-8")
    r = A.atualizar(
        app, Path("py"), sha=lambda: "novo",
        baixar=_baixador({"app.py": "novo", "requirements.txt": "r"}), pip=_pip_nunca,
    )
    assert r == "atualizado"
    assert (app / "app.py").read_text(encoding="utf-8") == "novo"
    versao = A.ler_versao(app)
    assert versao["commit"] == "novo"
    assert sorted(versao["arquivos"]) == ["app.py", "requirements.txt"]


@pytest.mark.skipif(sys.platform != "win32", reason="junção é recurso do Windows")
def test_data_nunca_extraida_nem_alterada(tmp_path):
    dados = tmp_path / "dados"
    dados.mkdir()
    (dados / "x.json").write_text("meu dado", encoding="utf-8")
    app = _app(tmp_path, {"commit": "velho", "requirements_sha256": _sha("r"), "arquivos": []})
    subprocess.run(["cmd", "/c", "mklink", "/J", str(app / "data"), str(dados)],
                   check=True, capture_output=True)
    r = A.atualizar(
        app, Path("py"), sha=lambda: "novo",
        baixar=_baixador({"app.py": "n", "requirements.txt": "r",
                          "data/.gitkeep": "", "data/x.json": "do zip"}),
        pip=_pip_nunca,
    )
    assert r == "atualizado"
    assert (dados / "x.json").read_text(encoding="utf-8") == "meu dado"
    assert not (dados / ".gitkeep").exists()


def test_remove_arquivo_que_sumiu_so_do_codigo(tmp_path):
    app = _app(tmp_path, {"commit": "velho", "requirements_sha256": _sha("r"),
                          "arquivos": ["old.py", "requirements.txt"]})
    (app / "old.py").write_text("x", encoding="utf-8")
    (app / "data").mkdir()
    (app / "data" / "y.json").write_text("dado", encoding="utf-8")
    A.atualizar(app, Path("py"), sha=lambda: "novo",
                baixar=_baixador({"requirements.txt": "r"}), pip=_pip_nunca)
    assert not (app / "old.py").exists()
    assert (app / "data" / "y.json").read_text(encoding="utf-8") == "dado"


def test_nunca_remove_data_mesmo_listado_na_versao_antiga(tmp_path):
    app = _app(tmp_path, {"commit": "velho", "requirements_sha256": _sha("r"),
                          "arquivos": ["data/y.json"]})
    (app / "data").mkdir()
    (app / "data" / "y.json").write_text("dado", encoding="utf-8")
    A.atualizar(app, Path("py"), sha=lambda: "novo",
                baixar=_baixador({"requirements.txt": "r"}), pip=_pip_nunca)
    assert (app / "data" / "y.json").exists()


def test_zip_malicioso_recusado(tmp_path):
    z = _zip(tmp_path / "m.zip", {RAIZ_ZIP + "../fora.txt": "x"})
    with pytest.raises(A.ErroAtualizacao):
        A.extrair_zip(z, tmp_path / "staging")
    assert not (tmp_path / "fora.txt").exists()


def test_atualizar_com_zip_malicioso_devolve_falhou(tmp_path):
    app = _app(tmp_path, {"commit": "velho", "requirements_sha256": "", "arquivos": []})
    r = A.atualizar(app, Path("py"), sha=lambda: "novo",
                    baixar=_baixador({"../fora.txt": "x"}), pip=_pip_nunca)
    assert r == "falhou"
    assert not (tmp_path / "fora.txt").exists()
    assert A.ler_versao(app)["commit"] == "velho"


def test_falha_no_pip_mantem_versao_anterior(tmp_path):
    app = _app(tmp_path, {"commit": "velho", "requirements_sha256": _sha("antigo"),
                          "arquivos": []})
    (app / "app.py").write_text("velho", encoding="utf-8")
    r = A.atualizar(app, Path("py"), sha=lambda: "novo",
                    baixar=_baixador({"app.py": "novo", "requirements.txt": "novo req"}),
                    pip=lambda *_: False)
    assert r == "falhou"
    assert (app / "app.py").read_text(encoding="utf-8") == "velho"
    assert A.ler_versao(app)["commit"] == "velho"


def test_pip_so_quando_requirements_muda(tmp_path):
    chamadas = []
    app = _app(tmp_path, {"commit": "velho", "requirements_sha256": _sha("antigo"),
                          "arquivos": []})
    r = A.atualizar(app, Path("py"), sha=lambda: "novo",
                    baixar=_baixador({"requirements.txt": "novo req"}),
                    pip=lambda *a: chamadas.append(a) or True)
    assert r == "atualizado"
    assert len(chamadas) == 1
    assert A.ler_versao(app)["requirements_sha256"] == _sha("novo req")


def test_falha_de_rede_devolve_falhou(tmp_path):
    app = _app(tmp_path, {"commit": "velho", "requirements_sha256": "", "arquivos": []})

    def sem_rede():
        raise A.ErroAtualizacao("sem internet")

    assert A.atualizar(app, Path("py"), sha=sem_rede,
                       baixar=_baixador({}), pip=_pip_nunca) == "falhou"


def test_interrupcao_no_meio_nao_grava_versao(tmp_path, monkeypatch):
    app = _app(tmp_path, {"commit": "velho", "requirements_sha256": _sha("r"), "arquivos": []})
    baixar = _baixador({"a.py": "1", "b.py": "2", "requirements.txt": "r"})
    copias = {"n": 0}
    original = A.shutil.copy2

    def quebra(origem, destino, *a, **k):
        copias["n"] += 1
        if copias["n"] == 2:
            raise OSError("energia caiu")
        return original(origem, destino, *a, **k)

    monkeypatch.setattr(A.shutil, "copy2", quebra)
    assert A.atualizar(app, Path("py"), sha=lambda: "novo", baixar=baixar,
                       pip=_pip_nunca) == "falhou"
    assert A.ler_versao(app)["commit"] == "velho"

    monkeypatch.setattr(A.shutil, "copy2", original)
    assert A.atualizar(app, Path("py"), sha=lambda: "novo", baixar=baixar,
                       pip=_pip_nunca) == "atualizado"
    assert A.ler_versao(app)["commit"] == "novo"


def test_ler_versao_ausente_ou_invalida(tmp_path):
    app = _app(tmp_path)
    assert A.ler_versao(app)["commit"] == ""
    (app / "versao.txt").write_text("{quebrado", encoding="utf-8")
    assert A.ler_versao(app)["arquivos"] == []


def test_ler_versao_aceita_bom_do_powershell(tmp_path):
    """`Set-Content -Encoding utf8` (Windows PowerShell 5.1) grava BOM; o build usa isso."""
    app = _app(tmp_path)
    (app / "versao.txt").write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"commit": "abc", "requirements_sha256": "h", "arquivos": ["a.py"]}).encode()
    )
    assert A.ler_versao(app) == {"commit": "abc", "requirements_sha256": "h", "arquivos": ["a.py"]}
