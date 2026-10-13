"""
Preferências de tela persistidas (12/10/2026).

Camada: persistência mínima, sem Streamlit. Lembra escolhas de interface (hoje: a "Base da necessidade de empenho" de
Contratos Contínuos) entre páginas e entre sessões. PERSISTÊNCIA autorizada pelo usuário em 12/10/2026 ("inclua a
persistência da seleção"); um único arquivo `data/preferencias/ui.json` (fora do Git), `versao_schema` 1, gravação atômica
(tmp + replace), uma chave por preferência. Arquivo ilegível levanta `ErroPreferencia` e NUNCA é sobrescrito; valor salvo
fora das opções válidas (opção removida numa versão futura) volta ao padrão.

Contrato público:
    ErroPreferencia
    carregar(chave, padrao, validas=None, diretorio=None) -> valor
    salvar(chave, valor, diretorio=None) -> None
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DIRETORIO_PADRAO = Path("data/preferencias")
NOME_ARQUIVO = "ui.json"
VERSAO_SCHEMA = 1


class ErroPreferencia(RuntimeError):
    """Arquivo de preferências ilegível ou inválido."""


def _caminho(diretorio: Path | None) -> Path:
    return Path(diretorio if diretorio is not None else DIRETORIO_PADRAO) / NOME_ARQUIVO


def _ler(caminho: Path) -> dict:
    if not caminho.exists():
        return {}
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
        if bruto["versao_schema"] != VERSAO_SCHEMA or not isinstance(bruto["preferencias"], dict):
            raise KeyError("versão/forma")
        return dict(bruto["preferencias"])
    except (OSError, ValueError, KeyError, TypeError) as erro:
        raise ErroPreferencia(f"Não foi possível ler {caminho}: {erro}") from erro


def carregar(chave: str, padrao, validas=None, diretorio: Path | None = None):
    """Valor salvo de `chave`; `padrao` se não há arquivo, a chave não existe ou o valor não está em `validas`."""

    preferencias = _ler(_caminho(diretorio))
    if chave not in preferencias:
        return padrao
    valor = preferencias[chave]
    return padrao if validas is not None and valor not in validas else valor


def salvar(chave: str, valor, diretorio: Path | None = None) -> None:
    """Grava `chave` preservando as demais; se o arquivo existente está ilegível, levanta erro sem tocá-lo."""

    caminho = _caminho(diretorio)
    preferencias = _ler(caminho)
    preferencias[chave] = valor
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(
        json.dumps({"versao_schema": VERSAO_SCHEMA, "preferencias": preferencias}, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporario, caminho)
