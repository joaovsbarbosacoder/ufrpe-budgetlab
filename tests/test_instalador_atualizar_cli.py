"""Testes do atualizar_cli.py (usado pelo Electron antes de abrir o sistema)."""
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.instalador import atualizar_cli as C


@pytest.mark.parametrize("resultado", ["sem_novidade", "atualizado", "falhou"])
def test_imprime_resultado_e_sai_zero(resultado, capsys):
    codigo = C.main(["app", "py"], atualizar_fn=lambda app, python: resultado)
    assert capsys.readouterr().out.strip() == resultado
    assert codigo == 0


def test_passa_app_e_python_como_path():
    recebido = []
    C.main(["C:/a b/app", "C:/a b/python.exe"],
           atualizar_fn=lambda app, python: recebido.append((app, python)) or "sem_novidade")
    assert recebido == [(Path("C:/a b/app"), Path("C:/a b/python.exe"))]


def test_sem_argumentos_devolve_2():
    assert C.main([], atualizar_fn=lambda *a: "sem_novidade") == 2


def test_funciona_por_script_sem_cwd_no_sys_path():
    """Python embutido ignora a pasta atual: o script precisa achar `scripts.*` sozinho."""
    raiz = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-I", str(raiz / "scripts" / "instalador" / "atualizar_cli.py")],
                       cwd=raiz, capture_output=True, text=True)
    assert r.returncode == 2, r.stderr
