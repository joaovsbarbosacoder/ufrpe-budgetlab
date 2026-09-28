"""
Integração com o Google Agenda — autenticação OAuth e chamadas à Calendar API v3.

Único módulo do projeto que acessa a rede para o Google Agenda. Não conhece prazos: expõe
eventos como dicionários normalizados (`normalizar_evento`), e a conciliação com o cadastro
de prazos vive em `src/prazos_sincronizacao.py`. Não importa Streamlit.

Persistência (aprovada pelo usuário em 27/09/2026 — ver
`docs/superpowers/specs/2026-09-27-google-agenda-design.md`): `DIRETORIO_PADRAO` guarda o
`credentials.json` (cliente OAuth "Desktop app" colocado pelo usuário, ver
`docs/google_agenda.md`). Segredo local, fora do git (`.gitignore`).

O `token.json` (refresh token com acesso de leitura e escrita à agenda) fica em
`DIRETORIO_TOKEN`, no perfil do Windows (`%APPDATA%\\UFRPE BudgetLab`), NÃO na pasta do
projeto — decisão do usuário em 28/09/2026: a pasta do projeto é sincronizada com o Google
Drive, e o token não deve ir para a nuvem. Um token gravado no local antigo (antes dessa
decisão) é migrado automaticamente na primeira leitura. `desconectar` também revoga o acesso
na conta Google, e apaga o token local mesmo se a revogação falhar.

Calendário sempre o principal (`primary`): o usuário quer ver também as reuniões em que é
convidado. Eventos criados pelo BudgetLab levam `budgetlab="1"` e `budgetlab_prazo_id=<id>` em
`extendedProperties.private` — é assim que prazo e reunião se distinguem no mesmo calendário.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import httplib2
import requests
from google.auth.exceptions import GoogleAuthError, RefreshError, TransportError
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

DIRETORIO_PADRAO = Path("data/google_agenda")
#: fora da pasta do projeto (sincronizada com o Google Drive) — ver docstring do módulo.
DIRETORIO_TOKEN = Path(os.environ.get("APPDATA") or Path.home()) / "UFRPE BudgetLab"
ARQUIVO_CREDENCIAIS = "credentials.json"
ARQUIVO_TOKEN = "token.json"
URL_REVOGACAO = "https://oauth2.googleapis.com/revoke"
#: tempo máximo (s) esperando o usuário concluir a autorização no navegador — sem ele, fechar
#: a aba deixaria a página do BudgetLab presa para sempre.
TEMPO_LIMITE_AUTORIZACAO = 300
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


def _caminho_token(diretorio: Path, diretorio_token: Path) -> Path:
    """Caminho do token, migrando um token gravado no local antigo (pasta do projeto). Se os
    dois existirem, o novo prevalece e o antigo é apagado — nunca fica cópia no Drive."""

    antigo = diretorio / ARQUIVO_TOKEN
    novo = diretorio_token / ARQUIVO_TOKEN
    if antigo.exists():
        if not novo.exists():
            _gravar_atomico(novo, antigo.read_text(encoding="utf-8"))
        antigo.unlink()
    return novo


def _carregar_credenciais(diretorio: Path, diretorio_token: Path):
    """Credenciais do `token.json`, ou `None` se ausente/ilegível. Não renova (sem rede)."""

    from google.oauth2.credentials import Credentials

    caminho = _caminho_token(diretorio, diretorio_token)
    if not caminho.exists():
        return None
    try:
        return Credentials.from_authorized_user_file(str(caminho), ESCOPOS)
    except (ValueError, json.JSONDecodeError):
        return None


def situacao_conexao(
    diretorio: str | Path = DIRETORIO_PADRAO, diretorio_token: str | Path = DIRETORIO_TOKEN,
) -> str:
    """"sem_credenciais" (falta o `credentials.json`), "desconectado" (sem token utilizável)
    ou "conectado". Não acessa a rede — um token revogado só é detectado em `cliente`."""

    diretorio = Path(diretorio)
    if not (diretorio / ARQUIVO_CREDENCIAIS).exists():
        return "sem_credenciais"
    credenciais = _carregar_credenciais(diretorio, Path(diretorio_token))
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


def conectar(
    diretorio: str | Path = DIRETORIO_PADRAO, diretorio_token: str | Path = DIRETORIO_TOKEN,
) -> None:
    """Abre o navegador para o usuário autorizar e grava o `token.json`. Bloqueia até a
    autorização terminar (no máximo `TEMPO_LIMITE_AUTORIZACAO`) — aceitável num app local de
    um único usuário. Qualquer falha do fluxo (acesso negado, aba fechada, porta ocupada) vira
    `ErroGoogleAgenda`: a página mostra um aviso e nenhum token é gravado."""

    diretorio = Path(diretorio)
    caminho_credenciais = diretorio / ARQUIVO_CREDENCIAIS
    if not caminho_credenciais.exists():
        raise ErroGoogleAgenda(f"Arquivo {caminho_credenciais} não encontrado — ver docs/google_agenda.md.")
    try:
        fluxo = InstalledAppFlow.from_client_secrets_file(str(caminho_credenciais), ESCOPOS)
        credenciais = fluxo.run_local_server(port=0, timeout_seconds=TEMPO_LIMITE_AUTORIZACAO)
    except Exception as erro:  # noqa: BLE001 — as exceções do oauthlib/wsgiref não têm base comum
        raise ErroGoogleAgenda(
            "Autorização do Google Agenda não concluída (acesso negado, janela fechada ou tempo "
            f"esgotado). Tente conectar novamente. Detalhe: {erro}"
        ) from erro
    _gravar_atomico(_caminho_token(diretorio, Path(diretorio_token)), credenciais.to_json())


def _revogar(token: str) -> bool:
    """Revoga o acesso na conta Google. 400 = token já inválido no Google (acesso já não
    existe), conta como revogado."""

    try:
        resposta = requests.post(
            URL_REVOGACAO, data={"token": token},
            headers={"content-type": "application/x-www-form-urlencoded"}, timeout=10,
        )
    except requests.RequestException:
        return False
    return resposta.status_code in (200, 400)


def desconectar(
    diretorio: str | Path = DIRETORIO_PADRAO, diretorio_token: str | Path = DIRETORIO_TOKEN,
    revogar: bool = True,
) -> bool:
    """Revoga o acesso na conta Google (se `revogar`) e apaga o `token.json` local — SEMPRE,
    mesmo se a revogação falhar (sem internet). O `credentials.json` permanece para
    reconectar. Devolve `False` só quando havia token e a revogação no Google não foi
    confirmada: a página avisa para revogar manualmente."""

    caminho = _caminho_token(Path(diretorio), Path(diretorio_token))
    revogado = True
    if revogar and caminho.exists():
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            dados = {}
        token = dados.get("refresh_token") or dados.get("token")
        revogado = _revogar(token) if token else True
    caminho.unlink(missing_ok=True)
    return revogado


def cliente(
    diretorio: str | Path = DIRETORIO_PADRAO, diretorio_token: str | Path = DIRETORIO_TOKEN,
) -> "ClienteGoogleAgenda":
    """Cliente pronto para uso, renovando o token se expirado. Token revogado é apagado (a
    situação volta a "desconectado") e vira `ErroGoogleAgenda` pedindo reconexão."""

    diretorio, diretorio_token = Path(diretorio), Path(diretorio_token)
    credenciais = _carregar_credenciais(diretorio, diretorio_token)
    if credenciais is None:
        raise ErroGoogleAgenda("Google Agenda não conectado.")
    if not credenciais.valid:
        if not credenciais.refresh_token:
            raise ErroGoogleAgenda("Autorização do Google Agenda expirada — conecte novamente.")
        try:
            credenciais.refresh(Request())
        except RefreshError as erro:
            # o Google já recusou o token: revogar de novo só custaria uma chamada de rede
            desconectar(diretorio, diretorio_token, revogar=False)
            raise ErroGoogleAgenda("Autorização do Google Agenda revogada ou expirada — conecte novamente.") from erro
        except TransportError as erro:  # sem internet: o token continua válido para depois
            raise ErroGoogleAgenda(f"Sem conexão com o Google Agenda: {erro}") from erro
        _gravar_atomico(diretorio_token / ARQUIVO_TOKEN, credenciais.to_json())
    servico = build("calendar", "v3", credentials=credenciais, cache_discovery=False)
    return ClienteGoogleAgenda(servico)


#: falhas de rede/autorização durante uma requisição. Nenhuma delas é `OSError`: o httplib2
#: converte falha de DNS ("sem internet") em `ServerNotFoundError`, e o `AuthorizedHttp`
#: lança `RefreshError`/`TransportError` ao tentar renovar um token revogado ou sem rede.
_ERROS_DE_CONEXAO = (OSError, httplib2.HttpLib2Error, GoogleAuthError)


def _erro_http(erro: HttpError, acao: str = "Erro na API do Google Agenda") -> ErroGoogleAgenda:
    """Inclui o motivo dado pelo Google (ex.: "Rate Limit Exceeded", "Forbidden") — sem ele,
    um 403 no resumo/histórico não diz se foi limite de uso ou falta de permissão."""

    motivo = getattr(erro, "reason", "") or ""
    return ErroGoogleAgenda(f"{acao} (HTTP {erro.resp.status}{': ' + motivo if motivo else ''}).")


def _erro_de_conexao(erro: Exception) -> ErroGoogleAgenda:
    if isinstance(erro, RefreshError):
        return ErroGoogleAgenda("Autorização do Google Agenda revogada ou expirada — desconecte e conecte novamente.")
    return ErroGoogleAgenda(f"Sem conexão com o Google Agenda: {erro}")


class ClienteGoogleAgenda:
    """Chamadas à Calendar API sobre o calendário principal. Recebe o `servico` pronto
    (injeção) para os testes usarem um falso. Todo retorno é evento normalizado."""

    def __init__(self, servico) -> None:
        self._eventos = servico.events()

    @staticmethod
    def _executar(requisicao):
        try:
            return requisicao.execute()
        except HttpError as erro:
            raise _erro_http(erro) from erro
        except _ERROS_DE_CONEXAO as erro:
            raise _erro_de_conexao(erro) from erro

    def _listar_todas(self, **params) -> list[dict]:
        """Percorre todas as páginas; só retorna se a listagem completou (uma listagem
        parcial faria a sincronização concluir prazos por engano)."""

        eventos: list[dict] = []
        token = None
        while True:
            resposta = self._executar(self._eventos.list(
                calendarId=CALENDARIO, maxResults=250, pageToken=token, **params,
            ))
            eventos.extend(normalizar_evento(bruto) for bruto in resposta.get("items", []))
            token = resposta.get("nextPageToken")
            if not token:
                return eventos

    def listar_eventos(self, inicio: datetime, fim: datetime) -> list[dict]:
        if inicio.tzinfo is None or fim.tzinfo is None:
            raise ValueError("inicio e fim precisam ter fuso horário.")
        return self._listar_todas(
            timeMin=inicio.isoformat(), timeMax=fim.isoformat(),
            singleEvents=True, orderBy="startTime",
        )

    def listar_eventos_de_prazos(self) -> list[dict]:
        return self._listar_todas(
            privateExtendedProperty=f"{MARCADOR_BUDGETLAB}=1", showDeleted=True,
        )

    def criar_evento(self, corpo: dict) -> dict:
        return normalizar_evento(self._executar(self._eventos.insert(calendarId=CALENDARIO, body=corpo)))

    def atualizar_evento(self, event_id: str, corpo: dict) -> dict:
        # patch (não update): preserva o que o usuário acrescentou no Google (cor, anexos...).
        return normalizar_evento(self._executar(
            self._eventos.patch(calendarId=CALENDARIO, eventId=event_id, body=corpo),
        ))

    def excluir_evento(self, event_id: str) -> None:
        try:
            self._eventos.delete(calendarId=CALENDARIO, eventId=event_id).execute()
        except HttpError as erro:
            if erro.resp.status in (404, 410):
                return  # já não existe — o objetivo foi atingido
            raise _erro_http(erro, "Erro ao excluir evento no Google Agenda") from erro
        except _ERROS_DE_CONEXAO as erro:
            raise _erro_de_conexao(erro) from erro
