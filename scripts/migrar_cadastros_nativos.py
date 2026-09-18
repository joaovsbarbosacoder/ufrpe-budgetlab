"""CLI para a migração segura de Bolsas e Contratos Contínuos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.migracao_cadastros_nativos import migrar_cadastros_nativos


ORIGEM_BOLSAS_PADRAO = Path("data/raw/BOLSAS E AUXÍLIOS 2026 - AGO A DEZ.xlsx")
ORIGEM_CONTRATOS_PADRAO = Path("data/raw/SERVIÇOS CONTÍNUOS - 2026 - AGO A DEZ.xlsm")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Valida e migra as planilhas de trabalho para os cadastros nativos. "
            "Sem --aplicar, executa somente a simulação."
        )
    )
    parser.add_argument("--bolsas", type=Path, default=ORIGEM_BOLSAS_PADRAO)
    parser.add_argument("--contratos", type=Path, default=ORIGEM_CONTRATOS_PADRAO)
    parser.add_argument("--ano", type=int, default=2026)
    parser.add_argument(
        "--diretorio-bolsas", type=Path, default=Path("data/bolsas_auxilios")
    )
    parser.add_argument(
        "--diretorio-contratos", type=Path, default=Path("data/contratos_continuos")
    )
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Promove os cadastros validados. Nunca sobrescreve um exercício existente.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    argumentos = parser.parse_args(argv)
    try:
        resultado = migrar_cadastros_nativos(
            argumentos.bolsas,
            argumentos.contratos,
            argumentos.ano,
            diretorio_bolsas=argumentos.diretorio_bolsas,
            diretorio_contratos=argumentos.diretorio_contratos,
            aplicar=argumentos.aplicar,
        )
    except Exception as erro:
        parser.exit(1, f"ERRO: {erro}\n")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
