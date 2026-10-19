"""Atualização opcional chamada pelo Electron antes de abrir o sistema.

Uso: `python scripts/instalador/atualizar_cli.py <pasta app> <python.exe>`.
Imprime uma linha (`sem_novidade`, `atualizado` ou `falhou`) e devolve 0: falha de
atualização nunca impede abrir o sistema. Sem argumentos devolve 2.
"""
from __future__ import annotations

import sys
from pathlib import Path

# O Python embutido ignora a pasta atual ao importar: acrescenta a raiz do app.
_RAIZ = str(Path(__file__).resolve().parents[2])
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from scripts.instalador.atualizar import atualizar  # noqa: E402


def main(argv: list[str] | None = None, atualizar_fn=atualizar) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("uso: atualizar_cli.py <pasta app> <python.exe>", file=sys.stderr)
        return 2
    print(atualizar_fn(Path(argv[0]), Path(argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
