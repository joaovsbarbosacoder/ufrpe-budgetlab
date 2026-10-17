"""Componente visual da página Empenhos com Execução Retardada (Streamlit `components.v2`).

Camada: interface. Registra um componente com HTML/CSS/JS próprios (arquivos em
`src/assets/empenhos_retardada/`) que reproduz o layout do mockup aprovado em 17/10/2026 —
filtros, resumo, cortes, tabela ordenável/agrupável e painel lateral de detalhe. O componente só
desenha os dados que recebe (montados por `src/empenhos_retardada_tela.py`) e devolve as ações do
usuário pelo gatilho "acao"; nenhuma regra de negócio mora no JavaScript.

As cores vêm de `src/design_tokens.py` (mesma identidade visual do resto do sistema), injetadas
como variáveis CSS no `:host` do componente (estilos isolados em shadow DOM).

Contrato público:
    renderizar(dados, *, key, ao_agir) -> None
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import streamlit as st

from src import design_tokens as d

_PASTA = Path(__file__).resolve().parent / "assets" / "empenhos_retardada"
NOME_COMPONENTE = "budgetlab_empenhos_retardada"


def _variaveis_css() -> str:
    return f""":host {{
  --surface: {d.SURFACE}; --surface-alt: {d.SURFACE_ALT}; --border: {d.BORDER};
  --text: {d.TEXT}; --muted: {d.TEXT_MUTED}; --faint: {d.TEXT_FAINT};
  --accent: {d.ACCENT}; --accent-strong: {d.ACCENT_STRONG}; --accent-soft: {d.ACCENT_SOFT}; --accent-line: {d.ACCENT_LINE};
  --pos: {d.POSITIVE}; --pos-soft: {d.POSITIVE_SOFT};
  --neg: {d.NEGATIVE};
  --warn: {d.WARNING}; --warn-soft: {d.WARNING_SOFT}; --warn-line: rgba(201,106,0,0.28);
  --radius: {d.RADIUS};
  --shadow: 0 1px 2px rgba(11,53,87,.06), 0 6px 18px rgba(11,53,87,.06);
}}
"""


_componente = st.components.v2.component(
    NOME_COMPONENTE,
    css=_variaveis_css() + (_PASTA / "componente.css").read_text(encoding="utf-8"),
    js=(_PASTA / "componente.js").read_text(encoding="utf-8"),
)


def renderizar(dados: dict[str, Any], *, key: str, ao_agir: Callable[[], None]) -> None:
    """Monta o componente. `ao_agir` roda (antes da reexecução da página) a cada ação do usuário;
    a ação em si fica em `st.session_state[key]["acao"]`."""

    _componente(key=key, data=dados, on_acao_change=ao_agir)
