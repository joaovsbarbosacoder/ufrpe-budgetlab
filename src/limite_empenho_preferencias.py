"""Preferência persistida da fração liberada do Limite de Empenho (`src/limite_empenho.py`).

Pedido explícito do usuário (22/09/2026, depois de reportar "ao atualizar a página, ele volta
pra o 12"): a fração informada manualmente precisa sobreviver a um F5/atualização de página,
não só à sessão do navegador — `st.session_state` sozinho não cobre isso, porque atualizar a
página cria uma sessão nova no Streamlit (comportamento documentado, não um bug). Persistência
em arquivo aprovada explicitamente pelo usuário, via pergunta direta, depois de eu confirmar
que o AGENTS.md deste projeto exige essa aprovação antes de qualquer persistência.

Um único arquivo JSON (não um registro por ID, como `src.prazos_orcamentarios`) — só existe UM
valor de fração vigente por vez, não uma coleção. Gravação atômica (arquivo temporário +
`Path.replace`), mesmo padrão de `src.prazos_orcamentarios._gravar_atomico`. Diretório
`data/limite_empenho/` segue a mesma convenção de `data/demandas/`/`data/prazos_orcamentarios/`
— dado real de instância, não versionado (ver `.gitignore`), com `.gitkeep` preservando a
estrutura de diretório vazia no git.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

CAMINHO_PADRAO = Path("data/limite_empenho/fracao_liberada.json")


def carregar_fracao_liberada(caminho: str | Path = CAMINHO_PADRAO) -> tuple[int, int] | None:
    """Devolve `(numerador, denominador)` gravados, ou `None` se nunca foi salvo nada ainda —
    ou se o arquivo está corrompido/ilegível, caso em que o chamador cai no padrão 12/12 em vez
    de travar a página por causa de uma preferência de interface."""

    caminho = Path(caminho)
    if not caminho.exists():
        return None
    try:
        dado = json.loads(caminho.read_text(encoding="utf-8"))
        return int(dado["numerador"]), int(dado["denominador"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def salvar_fracao_liberada(numerador: int, denominador: int, caminho: str | Path = CAMINHO_PADRAO) -> None:
    """Grava a fração atomicamente — quem lê nunca vê um arquivo pela metade."""

    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    dado = {
        "numerador": int(numerador),
        "denominador": int(denominador),
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
    }
    temporario = caminho.parent / f".{caminho.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(json.dumps(dado, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()
