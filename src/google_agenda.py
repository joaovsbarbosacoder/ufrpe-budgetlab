"""
Integração com o Google Agenda — autenticação OAuth e chamadas à Calendar API v3.

Único módulo do projeto que acessa a rede para o Google Agenda. Não conhece prazos: expõe
eventos como dicionários normalizados (`normalizar_evento`), e a conciliação com o cadastro
de prazos vive em `src/prazos_sincronizacao.py`. Não importa Streamlit.

Persistência (aprovada pelo usuário em 27/09/2026 — ver
`docs/superpowers/specs/2026-09-27-google-agenda-design.md`): `DIRETORIO_PADRAO` guarda o
`credentials.json` (cliente OAuth "Desktop app" colocado pelo usuário, ver
`docs/google_agenda.md`) e o `token.json` gravado após a autorização. Segredo local, fora do
git (`.gitignore`).

Calendário sempre o principal (`primary`): o usuário quer ver também as reuniões em que é
convidado. Eventos criados pelo BudgetLab levam `budgetlab="1"` e `budgetlab_prazo_id=<id>` em
`extendedProperties.private` — é assim que prazo e reunião se distinguem no mesmo calendário.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

DIRETORIO_PADRAO = Path("data/google_agenda")
ARQUIVO_CREDENCIAIS = "credentials.json"
ARQUIVO_TOKEN = "token.json"
#: um único escopo para as duas fases (leitura e escrita de eventos) — evita pedir nova
#: autorização quando a sincronização de prazos entrar.
ESCOPOS = ["https://www.googleapis.com/auth/calendar.events"]
CALENDARIO = "primary"
FUSO = "America/Recife"
MARCADOR = "budgetlab_prazo_id"
#: a API só filtra `privateExtendedProperty` por `chave=valor`, nunca por existência da
#: chave — por isso todo evento de prazo também leva este marcador fixo.
MARCADOR_BUDGETLAB = "budgetlab"

_FUSO_INFO = ZoneInfo(FUSO)


class ErroGoogleAgenda(RuntimeError):
    """Falha de conexão, autorização ou chamada à API — a página exibe e segue funcionando."""


def _data_hora(parte: dict | None) -> tuple[date | None, time | None]:
    if not parte:
        return None, None
    if "date" in parte:
        return date.fromisoformat(parte["date"]), None
    if "dateTime" in parte:
        momento = datetime.fromisoformat(parte["dateTime"]).astimezone(_FUSO_INFO)
        return momento.date(), momento.time()
    return None, None


def normalizar_evento(bruto: dict) -> dict:
    """Formato bruto da API → dicionário estável usado pelo resto do projeto. Evento de dia
    inteiro tem `hora_inicio`/`hora_fim` `None`; evento com horário é convertido para o fuso
    de Recife. Evento cancelado (`showDeleted=True`) pode vir sem datas nem título."""

    data_inicio, hora_inicio = _data_hora(bruto.get("start"))
    data_fim, hora_fim = _data_hora(bruto.get("end"))
    propriedades = dict((bruto.get("extendedProperties") or {}).get("private") or {})
    minha_resposta = next(
        (a.get("responseStatus") for a in bruto.get("attendees") or [] if a.get("self")), None,
    )
    return {
        "id": bruto["id"],
        "titulo": bruto.get("summary") or "",
        "descricao": bruto.get("description") or "",
        "data_inicio": data_inicio,
        "hora_inicio": hora_inicio,
        "data_fim": data_fim,
        "hora_fim": hora_fim,
        "cancelado": bruto.get("status") == "cancelled",
        "atualizado_em": bruto.get("updated") or "",
        "prazo_id": propriedades.get(MARCADOR),
        "propriedades": propriedades,
        "organizador": (bruto.get("organizer") or {}).get("email", ""),
        "minha_resposta": minha_resposta,
        "link": bruto.get("htmlLink") or "",
    }


def _carregar_credenciais(diretorio: Path):
    """Credenciais do `token.json`, ou `None` se ausente/ilegível. Não renova (sem rede)."""

    from google.oauth2.credentials import Credentials

    caminho = diretorio / ARQUIVO_TOKEN
    if not caminho.exists():
        return None
    try:
        return Credentials.from_authorized_user_file(str(caminho), ESCOPOS)
    except (ValueError, json.JSONDecodeError):
        return None


def situacao_conexao(diretorio: str | Path = DIRETORIO_PADRAO) -> str:
    """"sem_credenciais" (falta o `credentials.json`), "desconectado" (sem token utilizável)
    ou "conectado". Não acessa a rede — um token revogado só é detectado em `cliente`."""

    diretorio = Path(diretorio)
    if not (diretorio / ARQUIVO_CREDENCIAIS).exists():
        return "sem_credenciais"
    credenciais = _carregar_credenciais(diretorio)
    if credenciais is None or not (credenciais.valid or credenciais.refresh_token):
        return "desconectado"
    return "conectado"


def _gravar_atomico(caminho: Path, texto: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.parent / f".{caminho.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(texto, encoding="utf-8")
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()
