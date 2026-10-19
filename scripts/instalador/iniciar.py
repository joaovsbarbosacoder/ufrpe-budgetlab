"""Inicializador do UFRPE BudgetLab instalado (atalho do menu Iniciar / área de trabalho).

Tenta a atualização opcional (scripts/instalador/atualizar.py), escolhe uma porta livre,
abre o navegador quando o servidor responder e executa o Streamlit com o Python embutido.
Uso: `python scripts/instalador/iniciar.py` com a pasta de trabalho na pasta `app` da instalação
(o Python embutido ignora a pasta atual ao importar, por isso `-m` não funciona).
"""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PORTA_PADRAO = 8501


def sistema_aberto(porta: int, abrir=urllib.request.urlopen) -> bool:
    try:
        with abrir(f"http://localhost:{porta}/_stcore/health", timeout=2) as resposta:
            return resposta.status == 200
    except (OSError, ValueError):
        return False


def porta_livre(inicio: int = PORTA_PADRAO, fim: int = PORTA_PADRAO + 9) -> int:
    for porta in range(inicio, fim + 1):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", porta)) != 0:
                return porta
    raise RuntimeError(f"nenhuma porta livre entre {inicio} e {fim}")


def comando_streamlit(python: Path, porta: int) -> list[str]:
    return [
        str(python), "-m", "streamlit", "run", "app.py",
        "--server.headless", "true",
        "--server.port", str(porta),
        "--browser.gatherUsageStats", "false",
    ]


def preparar_sys_path(raiz: Path) -> None:
    """O Python embutido não põe a pasta atual no sys.path: acrescenta a raiz do app."""
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))


preparar_sys_path(Path(__file__).resolve().parents[2])


def _abrir_navegador_quando_pronto(porta: int, tentativas: int = 90) -> None:
    for _ in range(tentativas):
        if sistema_aberto(porta):
            webbrowser.open(f"http://localhost:{porta}")
            return
        time.sleep(1)


def main() -> int:
    raiz = Path(__file__).resolve().parents[2]
    python = raiz.parent / "python" / "python.exe"
    if not python.is_file():
        python = Path(sys.executable)

    print("== UFRPE BudgetLab ==")
    from scripts.instalador.atualizar import atualizar

    resultado = atualizar(raiz, python)
    print({
        "sem_novidade": "Sistema já está na versão mais recente.",
        "atualizado": "Sistema atualizado.",
        "falhou": "Aviso: não foi possível atualizar; abrindo a versão instalada.",
    }[resultado])

    if sistema_aberto(PORTA_PADRAO):
        webbrowser.open(f"http://localhost:{PORTA_PADRAO}")
        return 0
    try:
        porta = porta_livre()
    except RuntimeError as erro:
        print(f"Erro: {erro}")
        return 1
    threading.Thread(target=_abrir_navegador_quando_pronto, args=(porta,), daemon=True).start()
    print(f"Iniciando em http://localhost:{porta} — mantenha esta janela aberta; "
          "fechá-la encerra o sistema.")
    return subprocess.run(comando_streamlit(python, porta), cwd=raiz, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
