"""Testes do inicializador do instalador Windows."""
import socket
from pathlib import Path

import pytest

from scripts.instalador import iniciar as I


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_sistema_aberto_true_com_200():
    assert I.sistema_aberto(8501, abrir=lambda url, timeout: _Resp(200)) is True


def test_sistema_aberto_false_com_erro():
    def erro(url, timeout):
        raise OSError("recusado")

    assert I.sistema_aberto(8501, abrir=erro) is False


def test_porta_livre_pula_ocupada():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        ocupada = s.getsockname()[1]
        livre = I.porta_livre(ocupada, ocupada + 20)
        assert livre != ocupada
        assert livre > ocupada


def test_porta_livre_sem_nenhuma_levanta():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        p = s.getsockname()[1]
        with pytest.raises(RuntimeError):
            I.porta_livre(p, p)


def test_comando_streamlit_com_caminho_com_espacos_e_acentos():
    py = Path("C:/Users/João Silva/UFRPE BudgetLab/python/python.exe")
    cmd = I.comando_streamlit(py, 8503)
    assert cmd[0] == str(py)
    assert cmd[1:6] == ["-m", "streamlit", "run", "app.py", "--server.headless"]
    assert cmd[cmd.index("--server.port") + 1] == "8503"
    assert cmd[cmd.index("--browser.gatherUsageStats") + 1] == "false"


def test_inicializador_funciona_sem_cwd_no_sys_path():
    """Python embutido ignora a pasta atual: o script precisa achar `scripts.*` sozinho."""
    import subprocess
    import sys

    raiz = Path(__file__).resolve().parents[1]
    codigo = (
        "import runpy, sys\n"
        f"m = runpy.run_path(r'{raiz / 'scripts' / 'instalador' / 'iniciar.py'}')\n"
        "import scripts.instalador.atualizar\n"
    )
    r = subprocess.run([sys.executable, "-I", "-c", codigo], cwd=raiz,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_sistema_aberto_usa_127_0_0_1_sem_passar_por_ipv6():
    """`localhost` tenta ::1 antes (4 s de espera no Windows); o health check usa IPv4 direto."""
    urls = []

    def abrir(url, timeout):
        urls.append(url)
        return _Resp(200)

    I.sistema_aberto(8501, abrir=abrir)
    assert urls == ["http://127.0.0.1:8501/_stcore/health"]


def test_porta_livre_nao_demora_com_porta_fechada():
    import time

    t = time.time()
    I.porta_livre(8590, 8599)
    assert time.time() - t < 1.0


def test_abrir_navegador_usa_startfile_se_webbrowser_falha(monkeypatch):
    chamadas = []
    monkeypatch.setattr(I.webbrowser, "open", lambda url: False)
    monkeypatch.setattr(I.os, "startfile", lambda url: chamadas.append(url), raising=False)
    I.abrir_navegador("http://localhost:8501")
    assert chamadas == ["http://localhost:8501"]


def test_comando_streamlit_escuta_so_em_127_0_0_1():
    cmd = I.comando_streamlit(Path("py"), 8501)
    assert cmd[cmd.index("--server.address") + 1] == "127.0.0.1"
