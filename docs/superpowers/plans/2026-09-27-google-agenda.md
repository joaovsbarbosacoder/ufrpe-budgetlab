# Integração com o Google Agenda — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ligar a aba Gerenciamento de Prazos ao calendário principal do Google: visualizar
eventos (fase A) e sincronizar prazos nos dois sentidos (fase B).

**Architecture:** `src/google_agenda.py` é o único módulo com rede (OAuth + API, eventos
normalizados em dicionários). `src/prazos_sincronizacao.py` concilia prazos ↔ eventos
recebendo um cliente por injeção (testável com cliente falso). `src/prazos_orcamentarios.py`
ganha campos de sincronização. `app_pages/painel_prazos.py` só monta a interface.

**Tech Stack:** Python 3.14, Streamlit 1.61.1, pandas 3, `unittest`,
`google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`.

**Spec:** `docs/superpowers/specs/2026-09-27-google-agenda-design.md`

## Global Constraints

- Interpretador do projeto: `.venv_local/Scripts/python.exe` (o `.venv` está quebrado). Todos
  os comandos de teste abaixo usam `PY=.venv_local/Scripts/python.exe`.
- Testes em `unittest` (não pytest): `$PY -m unittest tests.test_x -v`.
- A suíte completa leva mais de 10 minutos: rodar em segundo plano ao fim de cada fase
  (`$PY -m unittest discover -s tests`).
- Nenhum teste acessa a rede nem usa credencial real; nada lê/grava `data/google_agenda/` ou
  `data/prazos_orcamentarios/` reais (sempre `tempfile.TemporaryDirectory`).
- Módulos de `src/` não importam Streamlit.
- Calendário: `"primary"`. Fuso: `"America/Recife"`. Escopo OAuth único:
  `https://www.googleapis.com/auth/calendar.events`.
- Marcadores em `extendedProperties.private`: `budgetlab = "1"` e `budgetlab_prazo_id = <id>`.
- Lembrete: `min(dias_antecedencia, 28) × 1440` minutos, `popup`.
- Evento excluído no Google → prazo **concluído** (nunca excluído).
- Sincronização automática ao abrir a página: no máximo a cada 5 minutos por sessão.
- Dependências fixadas: `google-api-python-client==2.200.0`, `google-auth-oauthlib==1.4.1`,
  `google-auth-httplib2==0.4.2`.
- Persistência nova só em `data/google_agenda/` (ignorado pelo git, com `.gitkeep`).
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Não
  incluir nos commits as alterações pendentes do glossário que já estão na árvore
  (`app_pages/glossario.py`, `src/glossario.py`, `tests/test_glossario.py`,
  `src/glossario_cadastro.py`, `tests/test_glossario_cadastro.py`, `data/glossario/` e um
  bloco do `.gitignore`). Nunca usar `git add -A`/`git add .`; `git add -p` não funciona
  neste ambiente (interativo) — ver Task 1, Step 7, para o `.gitignore`.

## Review Focus

1. **Editar um prazo na tela não pode perder o vínculo com o evento.** Hoje o formulário
   reconstrói o registro com `novo_prazo`, o que zeraria `google_event_id` e criaria um evento
   duplicado. Coberto por `editar` e pelo uso dele na página (ambos na Task 4).
2. **Queda entre "criar evento" e "gravar estado".** Na próxima sincronização o evento já
   existe com o `prazo_id`, mas o prazo não tem `google_event_id`: deve ser adotado, não
   duplicado. Teste `test_adota_evento_existente_sem_duplicar` (Task 6).
3. **Eventos duplicados com o mesmo `prazo_id`** (duas sincronizações simultâneas em abas
   diferentes): manter o vinculado, excluir os demais. Teste
   `test_exclui_evento_duplicado_do_mesmo_prazo` (Task 6).
4. **Listagem paginada** (mais de 250 eventos): perder a segunda página faria prazos serem
   "concluídos por exclusão" por engano. Teste `test_listagem_percorre_todas_as_paginas`
   (Task 2).
5. **Cadastro legado sem os campos novos misturado a registros novos** gera `NaN` no
   DataFrame e `numpy.bool_` não serializável ao marcar concluído pelo card. Teste
   `test_registros_misturados_nao_geram_nan` (Task 4) e o card passa a usar `editar` com
   `bool(...)` (Task 4).

---

## Estrutura de arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `requirements.txt` | Modificar | 3 dependências novas |
| `.gitignore` | Modificar | `data/google_agenda/*` |
| `data/google_agenda/.gitkeep` | Criar | Manter diretório |
| `src/google_agenda.py` | Criar | OAuth, cliente da API, normalização de eventos |
| `tests/test_google_agenda.py` | Criar | Testes do módulo acima (sem rede) |
| `src/prazos_orcamentarios.py` | Modificar | Campos de sincronização, `editar`, `gravar_estado_sincronizacao` |
| `tests/test_prazos_orcamentarios.py` | Modificar | Testes dos campos novos |
| `src/prazos_sincronizacao.py` | Criar | Mapeamento prazo ↔ evento, conciliação, resumo |
| `tests/test_prazos_sincronizacao.py` | Criar | Testes com cliente falso |
| `app_pages/painel_prazos.py` | Modificar | Bloco Google Agenda, seção Agenda, sync, uso de `editar` |
| `tests/test_painel_prazos_page.py` | Criar | Smoke test da página com `AppTest` |
| `docs/google_agenda.md` | Criar | Passo a passo do cliente OAuth |
| `README.md` | Modificar | Seção curta sobre a integração |

---

# FASE A — Conexão e visualização

### Task 1: Dependências e normalização de eventos (`src/google_agenda.py`, parte pura)

**Files:**
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Create: `data/google_agenda/.gitkeep`
- Create: `src/google_agenda.py`
- Test: `tests/test_google_agenda.py`

**Interfaces:**
- Produces: constantes `DIRETORIO_PADRAO`, `ARQUIVO_CREDENCIAIS`, `ARQUIVO_TOKEN`,
  `ESCOPOS`, `CALENDARIO`, `FUSO`, `MARCADOR`, `MARCADOR_BUDGETLAB`; `ErroGoogleAgenda`;
  `normalizar_evento(bruto: dict) -> dict`; `situacao_conexao(diretorio=DIRETORIO_PADRAO) -> str`
  (`"sem_credenciais" | "desconectado" | "conectado"`).

- [ ] **Step 1: Instalar dependências**

Acrescentar ao fim de `requirements.txt`:

```
google-api-python-client==2.200.0
google-auth-oauthlib==1.4.1
google-auth-httplib2==0.4.2
```

Run: `$PY -m pip install -r requirements.txt`
Expected: instalação sem erro.

- [ ] **Step 2: Ignorar dados locais**

Acrescentar em `.gitignore`, antes de `# Sistema operacional`:

```
# Integracao com o Google Agenda: credenciais do cliente OAuth, token de acesso e resumo da
# ultima sincronizacao (segredo local, nunca versionado) - ver src/google_agenda.py.
data/google_agenda/*
!data/google_agenda/.gitkeep
```

Criar `data/google_agenda/.gitkeep` vazio.

- [ ] **Step 3: Escrever os testes que falham**

`tests/test_google_agenda.py`:

```python
"""Testes de src/google_agenda.py — normalização de eventos da API e situação da conexão.
Nenhum teste acessa a rede nem usa credencial real; diretórios são temporários.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, time
from pathlib import Path

from src.google_agenda import (
    ARQUIVO_CREDENCIAIS,
    ARQUIVO_TOKEN,
    MARCADOR,
    normalizar_evento,
    situacao_conexao,
)


def _bruto(**extras) -> dict:
    base = {
        "id": "ev1", "status": "confirmed", "summary": "Reunião PROPLAD",
        "description": "Pauta", "updated": "2026-09-20T12:00:00.000Z",
        "htmlLink": "https://calendar.google.com/ev1",
        "organizer": {"email": "chefe@ufrpe.br"},
        "start": {"dateTime": "2026-10-01T14:00:00-03:00"},
        "end": {"dateTime": "2026-10-01T15:30:00-03:00"},
    }
    base.update(extras)
    return base


class TestNormalizarEvento(unittest.TestCase):
    def test_evento_com_horario(self):
        evento = normalizar_evento(_bruto())
        self.assertEqual(evento["id"], "ev1")
        self.assertEqual(evento["titulo"], "Reunião PROPLAD")
        self.assertEqual(evento["descricao"], "Pauta")
        self.assertEqual(evento["data_inicio"], date(2026, 10, 1))
        self.assertEqual(evento["hora_inicio"], time(14, 0))
        self.assertEqual(evento["data_fim"], date(2026, 10, 1))
        self.assertEqual(evento["hora_fim"], time(15, 30))
        self.assertFalse(evento["cancelado"])
        self.assertEqual(evento["atualizado_em"], "2026-09-20T12:00:00.000Z")
        self.assertIsNone(evento["prazo_id"])
        self.assertEqual(evento["propriedades"], {})
        self.assertEqual(evento["organizador"], "chefe@ufrpe.br")
        self.assertIsNone(evento["minha_resposta"])
        self.assertEqual(evento["link"], "https://calendar.google.com/ev1")

    def test_horario_em_utc_e_convertido_para_recife(self):
        evento = normalizar_evento(_bruto(start={"dateTime": "2026-10-02T01:30:00Z"}))
        # 01:30 UTC = 22:30 do dia anterior em Recife (UTC-3)
        self.assertEqual(evento["data_inicio"], date(2026, 10, 1))
        self.assertEqual(evento["hora_inicio"], time(22, 30))

    def test_evento_de_dia_inteiro(self):
        evento = normalizar_evento(_bruto(start={"date": "2026-12-01"}, end={"date": "2026-12-02"}))
        self.assertEqual(evento["data_inicio"], date(2026, 12, 1))
        self.assertIsNone(evento["hora_inicio"])
        self.assertEqual(evento["data_fim"], date(2026, 12, 2))
        self.assertIsNone(evento["hora_fim"])

    def test_evento_cancelado_sem_datas(self):
        evento = normalizar_evento({"id": "ev9", "status": "cancelled", "updated": "2026-09-21T00:00:00Z"})
        self.assertTrue(evento["cancelado"])
        self.assertIsNone(evento["data_inicio"])
        self.assertEqual(evento["titulo"], "")
        self.assertEqual(evento["descricao"], "")

    def test_marcador_de_prazo(self):
        evento = normalizar_evento(_bruto(extendedProperties={"private": {MARCADOR: "abc", "budgetlab": "1"}}))
        self.assertEqual(evento["prazo_id"], "abc")
        self.assertEqual(evento["propriedades"]["budgetlab"], "1")

    def test_minha_resposta_vem_do_attendee_self(self):
        evento = normalizar_evento(_bruto(attendees=[
            {"email": "outro@ufrpe.br", "responseStatus": "accepted"},
            {"email": "eu@gmail.com", "self": True, "responseStatus": "needsAction"},
        ]))
        self.assertEqual(evento["minha_resposta"], "needsAction")


class TestSituacaoConexao(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_sem_credenciais(self):
        self.assertEqual(situacao_conexao(self.diretorio), "sem_credenciais")

    def test_diretorio_inexistente_e_sem_credenciais(self):
        self.assertEqual(situacao_conexao(self.diretorio / "nao_existe"), "sem_credenciais")

    def test_credenciais_sem_token_e_desconectado(self):
        (self.diretorio / ARQUIVO_CREDENCIAIS).write_text("{}", encoding="utf-8")
        self.assertEqual(situacao_conexao(self.diretorio), "desconectado")

    def test_token_com_refresh_token_e_conectado(self):
        (self.diretorio / ARQUIVO_CREDENCIAIS).write_text("{}", encoding="utf-8")
        (self.diretorio / ARQUIVO_TOKEN).write_text(json.dumps({
            "client_id": "x", "client_secret": "y", "refresh_token": "z",
            "token": "t", "scopes": ["https://www.googleapis.com/auth/calendar.events"],
        }), encoding="utf-8")
        self.assertEqual(situacao_conexao(self.diretorio), "conectado")

    def test_token_corrompido_e_desconectado(self):
        (self.diretorio / ARQUIVO_CREDENCIAIS).write_text("{}", encoding="utf-8")
        (self.diretorio / ARQUIVO_TOKEN).write_text("não é json", encoding="utf-8")
        self.assertEqual(situacao_conexao(self.diretorio), "desconectado")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `$PY -m unittest tests.test_google_agenda -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.google_agenda'`.

- [ ] **Step 5: Implementar a parte pura de `src/google_agenda.py`**

```python
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
```

- [ ] **Step 6: Rodar e ver passar**

Run: `$PY -m unittest tests.test_google_agenda -v`
Expected: 11 testes, OK.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt data/google_agenda/.gitkeep src/google_agenda.py tests/test_google_agenda.py
# .gitignore: preparar no índice só o bloco do Google Agenda (o bloco do glossário, pendente
# do usuário, fica fora). Monta a versão do índice a partir do HEAD + bloco novo:
.venv_local/Scripts/python.exe - <<'PY'
import subprocess
base = subprocess.run(["git", "show", "HEAD:.gitignore"], capture_output=True, text=True, check=True).stdout
bloco = (
    "# Integracao com o Google Agenda: credenciais do cliente OAuth, token de acesso e resumo da\n"
    "# ultima sincronizacao (segredo local, nunca versionado) - ver src/google_agenda.py.\n"
    "data/google_agenda/*\n"
    "!data/google_agenda/.gitkeep\n\n"
)
novo = base.replace("# Sistema operacional", bloco + "# Sistema operacional", 1)
assert novo != base
sha = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=novo, capture_output=True, text=True, check=True).stdout.strip()
subprocess.run(["git", "update-index", "--cacheinfo", f"100644,{sha},.gitignore"], check=True)
PY
git diff --cached .gitignore   # conferir: só o bloco do Google Agenda
git commit -m "feat: normalizacao de eventos e situacao da conexao com o Google Agenda

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: OAuth e cliente da API (`src/google_agenda.py`, parte com rede)

**Files:**
- Modify: `src/google_agenda.py`
- Test: `tests/test_google_agenda.py`

**Interfaces:**
- Consumes: `normalizar_evento`, `_carregar_credenciais`, `_gravar_atomico`, constantes (Task 1).
- Produces:
  - `conectar(diretorio=DIRETORIO_PADRAO) -> None`
  - `desconectar(diretorio=DIRETORIO_PADRAO) -> None`
  - `cliente(diretorio=DIRETORIO_PADRAO) -> ClienteGoogleAgenda`
  - `class ClienteGoogleAgenda(servico)` com `listar_eventos(inicio: datetime, fim: datetime) -> list[dict]`,
    `listar_eventos_de_prazos() -> list[dict]`, `criar_evento(corpo: dict) -> dict`,
    `atualizar_evento(event_id: str, corpo: dict) -> dict`, `excluir_evento(event_id: str) -> None`.
    Todos devolvem eventos normalizados; falhas viram `ErroGoogleAgenda`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/test_google_agenda.py` (imports no topo do arquivo):

```python
from datetime import datetime, timezone
from unittest import mock

import httplib2
from googleapiclient.errors import HttpError

from src.google_agenda import (
    ClienteGoogleAgenda,
    ErroGoogleAgenda,
    conectar,
    desconectar,
)


class _Requisicao:
    def __init__(self, resposta=None, erro=None):
        self._resposta, self._erro = resposta, erro

    def execute(self):
        if self._erro is not None:
            raise self._erro
        return self._resposta


class _EventosFalsos:
    """Imita `servico.events()`: registra os parâmetros e devolve respostas enfileiradas."""

    def __init__(self, paginas=None, erro=None):
        self.paginas = list(paginas or [])
        self.erro = erro
        self.chamadas: list[tuple[str, dict]] = []

    def list(self, **params):
        self.chamadas.append(("list", params))
        return _Requisicao(self.paginas.pop(0) if self.paginas else {"items": []}, self.erro)

    def insert(self, **params):
        self.chamadas.append(("insert", params))
        return _Requisicao({"id": "novo", "updated": "2026-09-27T10:00:00Z", **params["body"]}, self.erro)

    def patch(self, **params):
        self.chamadas.append(("patch", params))
        return _Requisicao({"id": params["eventId"], "updated": "2026-09-27T11:00:00Z", **params["body"]}, self.erro)

    def delete(self, **params):
        self.chamadas.append(("delete", params))
        return _Requisicao("", self.erro)


class _ServicoFalso:
    def __init__(self, eventos: _EventosFalsos):
        self._eventos = eventos

    def events(self):
        return self._eventos


def _http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"erro")


class TestClienteGoogleAgenda(unittest.TestCase):
    def test_listagem_percorre_todas_as_paginas(self):
        eventos = _EventosFalsos(paginas=[
            {"items": [{"id": "a"}], "nextPageToken": "p2"},
            {"items": [{"id": "b"}]},
        ])
        resultado = ClienteGoogleAgenda(_ServicoFalso(eventos)).listar_eventos_de_prazos()
        self.assertEqual([e["id"] for e in resultado], ["a", "b"])
        self.assertEqual(eventos.chamadas[1][1]["pageToken"], "p2")

    def test_listar_eventos_de_prazos_filtra_marcador_e_inclui_excluidos(self):
        eventos = _EventosFalsos()
        ClienteGoogleAgenda(_ServicoFalso(eventos)).listar_eventos_de_prazos()
        params = eventos.chamadas[0][1]
        self.assertEqual(params["calendarId"], "primary")
        self.assertEqual(params["privateExtendedProperty"], "budgetlab=1")
        self.assertTrue(params["showDeleted"])

    def test_listar_eventos_usa_janela_e_expande_recorrentes(self):
        eventos = _EventosFalsos()
        inicio = datetime(2026, 9, 27, tzinfo=timezone.utc)
        fim = datetime(2026, 10, 27, tzinfo=timezone.utc)
        ClienteGoogleAgenda(_ServicoFalso(eventos)).listar_eventos(inicio, fim)
        params = eventos.chamadas[0][1]
        self.assertEqual(params["timeMin"], inicio.isoformat())
        self.assertEqual(params["timeMax"], fim.isoformat())
        self.assertTrue(params["singleEvents"])
        self.assertEqual(params["orderBy"], "startTime")

    def test_listar_eventos_exige_datetime_com_fuso(self):
        cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos()))
        with self.assertRaises(ValueError):
            cliente.listar_eventos(datetime(2026, 9, 27), datetime(2026, 10, 27))

    def test_falha_na_listagem_vira_erro_google_agenda(self):
        cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos(erro=_http_error(500))))
        with self.assertRaises(ErroGoogleAgenda):
            cliente.listar_eventos_de_prazos()

    def test_criar_e_atualizar_devolvem_evento_normalizado(self):
        eventos = _EventosFalsos()
        cliente = ClienteGoogleAgenda(_ServicoFalso(eventos))
        criado = cliente.criar_evento({"summary": "Prazo", "start": {"date": "2026-12-01"}, "end": {"date": "2026-12-02"}})
        self.assertEqual(criado["id"], "novo")
        self.assertEqual(criado["titulo"], "Prazo")
        atualizado = cliente.atualizar_evento("novo", {"summary": "Prazo 2"})
        self.assertEqual(atualizado["atualizado_em"], "2026-09-27T11:00:00Z")
        self.assertEqual(eventos.chamadas[1][0], "patch")

    def test_excluir_evento_ja_removido_nao_e_erro(self):
        for status in (404, 410):
            cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos(erro=_http_error(status))))
            cliente.excluir_evento("x")  # não lança

    def test_excluir_com_outro_erro_vira_erro_google_agenda(self):
        cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos(erro=_http_error(403))))
        with self.assertRaises(ErroGoogleAgenda):
            cliente.excluir_evento("x")


class TestConectarDesconectar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self._tmp.name)
        (self.diretorio / ARQUIVO_CREDENCIAIS).write_text("{}", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_conectar_grava_token(self):
        credenciais = mock.Mock()
        credenciais.to_json.return_value = '{"refresh_token": "z"}'
        fluxo = mock.Mock()
        fluxo.run_local_server.return_value = credenciais
        with mock.patch("src.google_agenda.InstalledAppFlow") as classe_fluxo:
            classe_fluxo.from_client_secrets_file.return_value = fluxo
            conectar(self.diretorio)
        self.assertEqual(
            json.loads((self.diretorio / ARQUIVO_TOKEN).read_text(encoding="utf-8")),
            {"refresh_token": "z"},
        )

    def test_conectar_sem_credenciais_e_erro(self):
        (self.diretorio / ARQUIVO_CREDENCIAIS).unlink()
        with self.assertRaises(ErroGoogleAgenda):
            conectar(self.diretorio)

    def test_desconectar_apaga_so_o_token(self):
        (self.diretorio / ARQUIVO_TOKEN).write_text("{}", encoding="utf-8")
        desconectar(self.diretorio)
        self.assertFalse((self.diretorio / ARQUIVO_TOKEN).exists())
        self.assertTrue((self.diretorio / ARQUIVO_CREDENCIAIS).exists())
        desconectar(self.diretorio)  # idempotente
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `$PY -m unittest tests.test_google_agenda -v`
Expected: FAIL — `ImportError: cannot import name 'ClienteGoogleAgenda'`.

- [ ] **Step 3: Implementar**

Acrescentar a `src/google_agenda.py`:

1. Nos imports do topo:

```python
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
```

2. No fim do arquivo:

```python
def conectar(diretorio: str | Path = DIRETORIO_PADRAO) -> None:
    """Abre o navegador para o usuário autorizar e grava o `token.json`. Bloqueia até a
    autorização terminar — aceitável num app local de um único usuário."""

    diretorio = Path(diretorio)
    caminho_credenciais = diretorio / ARQUIVO_CREDENCIAIS
    if not caminho_credenciais.exists():
        raise ErroGoogleAgenda(f"Arquivo {caminho_credenciais} não encontrado — ver docs/google_agenda.md.")
    fluxo = InstalledAppFlow.from_client_secrets_file(str(caminho_credenciais), ESCOPOS)
    credenciais = fluxo.run_local_server(port=0)
    _gravar_atomico(diretorio / ARQUIVO_TOKEN, credenciais.to_json())


def desconectar(diretorio: str | Path = DIRETORIO_PADRAO) -> None:
    """Apaga só o `token.json`; o `credentials.json` permanece para reconectar."""

    (Path(diretorio) / ARQUIVO_TOKEN).unlink(missing_ok=True)


def cliente(diretorio: str | Path = DIRETORIO_PADRAO) -> "ClienteGoogleAgenda":
    """Cliente pronto para uso, renovando o token se expirado. Token revogado é apagado (a
    situação volta a "desconectado") e vira `ErroGoogleAgenda` pedindo reconexão."""

    diretorio = Path(diretorio)
    credenciais = _carregar_credenciais(diretorio)
    if credenciais is None:
        raise ErroGoogleAgenda("Google Agenda não conectado.")
    if not credenciais.valid:
        if not credenciais.refresh_token:
            raise ErroGoogleAgenda("Autorização do Google Agenda expirada — conecte novamente.")
        try:
            credenciais.refresh(Request())
        except RefreshError as erro:
            desconectar(diretorio)
            raise ErroGoogleAgenda("Autorização do Google Agenda revogada ou expirada — conecte novamente.") from erro
        _gravar_atomico(diretorio / ARQUIVO_TOKEN, credenciais.to_json())
    servico = build("calendar", "v3", credentials=credenciais, cache_discovery=False)
    return ClienteGoogleAgenda(servico)


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
            raise ErroGoogleAgenda(f"Erro na API do Google Agenda (HTTP {erro.resp.status}).") from erro
        except OSError as erro:
            raise ErroGoogleAgenda(f"Sem conexão com o Google Agenda: {erro}") from erro

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
            raise ErroGoogleAgenda(f"Erro ao excluir evento no Google Agenda (HTTP {erro.resp.status}).") from erro
        except OSError as erro:
            raise ErroGoogleAgenda(f"Sem conexão com o Google Agenda: {erro}") from erro
```

Nota: o `_EventosFalsos.list` do teste recebe `pageToken=None` na primeira chamada — isso é
aceito pela API real (parâmetro `None` é omitido pelo cliente do Google).

- [ ] **Step 4: Rodar e ver passar**

Run: `$PY -m unittest tests.test_google_agenda -v`
Expected: 22 testes, OK.

- [ ] **Step 5: Commit**

```bash
git add src/google_agenda.py tests/test_google_agenda.py
git commit -m "feat: cliente OAuth e chamadas a Calendar API do Google Agenda

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Tela — bloco de conexão e seção "Agenda" + documentação

**Files:**
- Modify: `app_pages/painel_prazos.py`
- Create: `tests/test_painel_prazos_page.py`
- Create: `docs/google_agenda.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `situacao_conexao`, `conectar`, `desconectar`, `cliente`, `ErroGoogleAgenda`,
  `DIRETORIO_PADRAO as DIRETORIO_AGENDA`, `FUSO` (Tasks 1–2).
- Produces: `_formulario(prazo_existente, sugestao=None)` e `_dialogo_novo(sugestao=None)`
  aceitam um evento normalizado como sugestão (usado por "Transformar em prazo").

- [ ] **Step 1: Escrever o smoke test que falha**

`tests/test_painel_prazos_page.py`:

```python
"""Smoke test da página Gerenciamento de Prazos — bloco Google Agenda por situação de
conexão. A situação é simulada com `mock.patch` (nunca lê `data/google_agenda/` real)."""

import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PainelPrazosGoogleAgendaTests(unittest.TestCase):
    def _abrir(self, situacao: str) -> AppTest:
        with mock.patch("src.google_agenda.situacao_conexao", return_value=situacao):
            app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
            app.run()
            app.switch_page("app_pages/painel_prazos.py")
            app.run(timeout=20)
        return app

    def test_sem_credenciais_mostra_instrucao(self):
        app = self._abrir("sem_credenciais")
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("docs/google_agenda.md" in m.value for m in app.markdown))

    def test_desconectado_mostra_botao_conectar(self):
        app = self._abrir("desconectado")
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Conectar ao Google Agenda", [b.label for b in app.button])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `$PY -m unittest tests.test_painel_prazos_page -v`
Expected: FAIL — assert sobre `docs/google_agenda.md` e botão ausente.

- [ ] **Step 3: Implementar na página**

Em `app_pages/painel_prazos.py`:

1. Imports (depois dos imports de `src.prazos_orcamentarios`):

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src import google_agenda
from src.google_agenda import ErroGoogleAgenda
```

(Importar o módulo, não as funções, para que o `mock.patch("src.google_agenda.situacao_conexao")`
do teste e chamadas futuras vejam o atributo atual.)

2. `_formulario` ganha o parâmetro `sugestao: dict | None = None` (evento normalizado).
   Trocar a linha do `prefixo` e os `value=` de título, data e descrição:

```python
def _formulario(prazo_existente, sugestao: dict | None = None) -> None:
    """... (docstring atual) ... `sugestao` (evento do Google Agenda, botão "Transformar em
    prazo") só pré-preenche título, data e descrição de um prazo NOVO."""

    if prazo_existente is not None:
        prefixo = f"pp_form_{prazo_existente['id']}"
    elif sugestao is not None:
        prefixo = f"pp_form_evento_{sugestao['id']}"
    else:
        prefixo = "pp_form_novo"
    sugestao = sugestao or {}
    titulo = st.text_input(
        "Título do prazo",
        value=prazo_existente["titulo"] if prazo_existente is not None else sugestao.get("titulo", ""),
        placeholder="ex.: Prestação de contas — Convênio 12/2026", key=f"{prefixo}_titulo",
    )
```

   e, nos campos de data e descrição:

```python
    data_prazo = c3.date_input(
        "Vencimento",
        value=prazo_existente["data_prazo"] if prazo_existente is not None else sugestao.get("data_inicio"),
        format="DD/MM/YYYY", key=f"{prefixo}_data",
    )
```

```python
    descricao = st.text_area(
        "Descrição",
        value=prazo_existente["descricao"] if prazo_existente is not None else sugestao.get("descricao", ""),
        key=f"{prefixo}_descricao",
    )
```

   E o diálogo:

```python
@st.dialog("Novo prazo")
def _dialogo_novo(sugestao: dict | None = None) -> None:
    _formulario(None, sugestao)
```

3. Novas funções, antes do bloco `# --- página`:

```python
_FUSO = ZoneInfo(google_agenda.FUSO)
_RESPOSTAS = {"accepted": "Aceito", "declined": "Recusado", "tentative": "Talvez", "needsAction": "Pendente"}


@st.cache_data(ttl=300, show_spinner=False)
def _eventos_proximos(dias: int = 30) -> list[dict]:
    """Cache de 5 min: o Streamlit reexecuta a página a cada clique."""

    agora = datetime.now(_FUSO)
    return google_agenda.cliente().listar_eventos(agora, agora + timedelta(days=dias))


def _render_conexao() -> str:
    """Bloco "Google Agenda". Devolve a situação da conexão."""

    situacao = google_agenda.situacao_conexao()
    with st.container(border=True):
        st.markdown("<div class='pp-label'>Google Agenda</div>", unsafe_allow_html=True)
        if situacao == "sem_credenciais":
            st.markdown(
                "Integração não configurada. Siga o passo a passo em `docs/google_agenda.md` "
                f"e coloque o `credentials.json` em `{google_agenda.DIRETORIO_PADRAO}`."
            )
        elif situacao == "desconectado":
            if st.button("Conectar ao Google Agenda", icon=":material/link:"):
                try:
                    google_agenda.conectar()
                except ErroGoogleAgenda as erro:
                    render_alert(str(erro), "error")
                else:
                    _eventos_proximos.clear()
                    st.rerun()
        else:
            st.markdown("Conectado ao calendário principal.")
            if st.button("Desconectar", icon=":material/link_off:"):
                google_agenda.desconectar()
                _eventos_proximos.clear()
                st.rerun()
    return situacao


def _render_agenda() -> None:
    with st.expander("Agenda — próximos 30 dias", expanded=False):
        try:
            eventos = _eventos_proximos()
        except ErroGoogleAgenda as erro:
            render_alert(str(erro), "error")
            return
        if not eventos:
            st.info("Nenhum evento nos próximos 30 dias.")
            return
        dia_atual = None
        for evento in eventos:
            if evento["data_inicio"] != dia_atual:
                dia_atual = evento["data_inicio"]
                st.markdown(f"<div class='pp-label'>{dia_atual.strftime('%d/%m/%Y')}</div>", unsafe_allow_html=True)
            e_prazo = evento["prazo_id"] is not None
            rotulo = _badge("Prazo", ACCENT) if e_prazo else _badge("Reunião/evento", TEXT_MUTED)
            horario = "Dia inteiro" if evento["hora_inicio"] is None else evento["hora_inicio"].strftime("%H:%M")
            detalhes = [horario]
            if not e_prazo and evento["organizador"]:
                detalhes.append(evento["organizador"])
            if evento["minha_resposta"]:
                detalhes.append(_RESPOSTAS.get(evento["minha_resposta"], evento["minha_resposta"]))
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.markdown(
                f"{rotulo} **{evento['titulo'] or '(sem título)'}** "
                f"<span style='color:{TEXT_MUTED};font-size:12px'>{' · '.join(detalhes)}</span>",
                unsafe_allow_html=True,
            )
            if not e_prazo and c2.button("Transformar em prazo", key=f"pp_evento_{evento['id']}",
                                          use_container_width=True):
                _dialogo_novo(evento)
```

4. No bloco da página, logo depois do cabeçalho (antes de `prazos_brutos = carregar_prazos()`):

```python
situacao_google = _render_conexao()
if situacao_google == "conectado":
    _render_agenda()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `$PY -m unittest tests.test_painel_prazos_page tests.test_prazos_orcamentarios tests.test_home_page -v`
Expected: OK.

- [ ] **Step 5: Documentação**

`docs/google_agenda.md`:

```markdown
# Integração com o Google Agenda

A aba **Gerenciamento de Prazos** pode se conectar ao calendário principal da sua conta
Google para (a) mostrar os eventos dos próximos 30 dias, inclusive reuniões em que você é
convidado, e (b) sincronizar os prazos cadastrados nos dois sentidos.

## Configuração (uma única vez)

1. Acesse <https://console.cloud.google.com/> com a conta que tem a agenda.
2. Crie um projeto (ex.: "UFRPE BudgetLab").
3. Em **APIs e serviços → Biblioteca**, ative a **Google Calendar API**.
4. Em **APIs e serviços → Tela de permissão OAuth**: tipo **Externo**, preencha nome e
   e-mail, e adicione sua própria conta em **Usuários de teste**.
5. Em **APIs e serviços → Credenciais → Criar credenciais → ID do cliente OAuth**, escolha
   **App para computador (Desktop app)**.
6. Baixe o JSON e salve como `data/google_agenda/credentials.json` dentro do projeto.
7. Abra **Gerenciamento de Prazos** e clique em **Conectar ao Google Agenda**. O navegador
   abre para você autorizar; depois disso a página mostra "Conectado".

O `credentials.json` e o `token.json` ficam só na sua máquina (`data/google_agenda/` está no
`.gitignore`). Para desconectar, use o botão **Desconectar** — só o token é apagado.

## Observações

- **App em modo de teste:** enquanto a tela de permissão estiver em "Testing", o Google
  expira a autorização em 7 dias e a página pede para conectar de novo. Para evitar, em
  **Tela de permissão OAuth** clique em **Publicar app**; para uso próprio não é necessário
  passar pela verificação do Google (o aviso "app não verificado" continua aparecendo na
  autorização — clique em "Avançado → Acessar").
- **Conta institucional (Google Workspace):** o administrador pode bloquear apps não
  verificados. Nesse caso, use uma conta pessoal ou peça liberação ao administrador.
- **Lembretes:** o Google aceita lembretes até 28 dias antes. Prazos com antecedência maior
  recebem lembrete de 28 dias na agenda; o alerta "Vencendo" do BudgetLab continua usando a
  antecedência completa.
```

`README.md` — na seção que descreve Gerenciamento de Prazos (localizar com
`grep -n "Prazos" README.md`), acrescentar o parágrafo:

```markdown
A página pode se conectar ao calendário principal do Google (opcional, ver
`docs/google_agenda.md`) e mostra os eventos dos próximos 30 dias — inclusive reuniões em
que o usuário é convidado. Acesso à API isolado em `src/google_agenda.py`.
```

- [ ] **Step 6: Verificação manual**

Run: `$PY -m streamlit run app.py` e abrir Gerenciamento de Prazos.
Expected: bloco "Google Agenda" com a instrução (sem `credentials.json`); resto da página
inalterado. Se o usuário já tiver `credentials.json`, conectar e conferir a seção Agenda.

- [ ] **Step 7: Suíte completa (em segundo plano) e commit**

Run: `$PY -m unittest discover -s tests` (segundo plano; > 10 min)
Expected: mesmo resultado da linha de base + testes novos passando.

```bash
git add app_pages/painel_prazos.py tests/test_painel_prazos_page.py docs/google_agenda.md README.md
git commit -m "feat: conexao e visualizacao da agenda no Gerenciamento de Prazos

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

# FASE B — Sincronização de prazos

### Task 4: Campos de sincronização no cadastro de prazos

**Files:**
- Modify: `src/prazos_orcamentarios.py`
- Test: `tests/test_prazos_orcamentarios.py`

**Interfaces:**
- Modify: `app_pages/painel_prazos.py` (formulário e card passam a usar `editar`)
- Produces:
  - `CAMPOS_SINCRONIZACAO = ("google_event_id", "sincronizado_em", "google_atualizado_em", "removido_no_google")`
  - `CAMPOS_EDITAVEIS = ("titulo", "data_prazo", "descricao", "responsavel", "dias_antecedencia", "tipo", "categoria", "prioridade", "concluido")`
  - `carregar_prazo(identificador: str, diretorio=DIRETORIO_PADRAO) -> dict` (lança `FileNotFoundError`)
  - `editar(identificador: str, campos: dict, diretorio=DIRETORIO_PADRAO) -> dict` — mescla só
    `CAMPOS_EDITAVEIS`, preserva id/criado_em/campos de sincronização, grava via `atualizar`,
    devolve o registro gravado.
  - `gravar_estado_sincronizacao(prazo: dict, diretorio=DIRETORIO_PADRAO) -> Path` — grava sem
    alterar `atualizado_em`.
  - `atualizar(...)`: quando `concluido` é falso, zera `removido_no_google`.
  - `novo_prazo(...)`: devolve os 4 campos de sincronização (`None, None, None, False`).
  - `prazos_com_criticidade`: colunas novas, sem `NaN`.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/test_prazos_orcamentarios.py` (e incluir `CAMPOS_SINCRONIZACAO`,
`carregar_prazo`, `editar`, `gravar_estado_sincronizacao` no import do topo):

```python
class TestCamposSincronizacao(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _salvo(self, **extras) -> dict:
        prazo = {**novo_prazo("Prazo A", date(2026, 12, 1)), **extras}
        salvar(prazo, self.diretorio)
        return prazo

    def test_novo_prazo_traz_campos_de_sincronizacao_vazios(self):
        prazo = novo_prazo("Prazo A", date(2026, 12, 1))
        self.assertIsNone(prazo["google_event_id"])
        self.assertIsNone(prazo["sincronizado_em"])
        self.assertIsNone(prazo["google_atualizado_em"])
        self.assertFalse(prazo["removido_no_google"])

    def test_gravar_estado_sincronizacao_preserva_atualizado_em(self):
        prazo = self._salvo()
        prazo["google_event_id"] = "ev1"
        prazo["sincronizado_em"] = prazo["atualizado_em"]
        gravar_estado_sincronizacao(prazo, self.diretorio)
        gravado = carregar_prazo(prazo["id"], self.diretorio)
        self.assertEqual(gravado["atualizado_em"], prazo["atualizado_em"])
        self.assertEqual(gravado["google_event_id"], "ev1")

    def test_gravar_estado_exige_registro_existente(self):
        with self.assertRaises(FileNotFoundError):
            gravar_estado_sincronizacao(novo_prazo("X", date(2026, 12, 1)), self.diretorio)

    def test_editar_preserva_vinculo_com_o_evento(self):
        prazo = self._salvo(google_event_id="ev1", sincronizado_em="s", google_atualizado_em="g")
        editado = editar(prazo["id"], {"titulo": "Prazo B", "data_prazo": "2026-12-05"}, self.diretorio)
        self.assertEqual(editado["titulo"], "Prazo B")
        self.assertEqual(editado["google_event_id"], "ev1")
        self.assertEqual(editado["criado_em"], prazo["criado_em"])
        self.assertEqual(carregar_prazo(prazo["id"], self.diretorio), editado)

    def test_editar_ignora_campos_nao_editaveis(self):
        prazo = self._salvo(google_event_id="ev1")
        editado = editar(prazo["id"], {"id": "outro", "google_event_id": None}, self.diretorio)
        self.assertEqual(editado["id"], prazo["id"])
        self.assertEqual(editado["google_event_id"], "ev1")

    def test_editar_converte_concluido_para_bool_nativo(self):
        import numpy as np
        prazo = self._salvo()
        editar(prazo["id"], {"concluido": np.bool_(True)}, self.diretorio)
        self.assertIs(carregar_prazo(prazo["id"], self.diretorio)["concluido"], True)

    def test_reabrir_limpa_removido_no_google(self):
        prazo = self._salvo(concluido=True, removido_no_google=True)
        editar(prazo["id"], {"concluido": False}, self.diretorio)
        self.assertFalse(carregar_prazo(prazo["id"], self.diretorio)["removido_no_google"])

    def test_manter_concluido_preserva_removido_no_google(self):
        prazo = self._salvo(concluido=True, removido_no_google=True)
        editar(prazo["id"], {"titulo": "Novo título"}, self.diretorio)
        self.assertTrue(carregar_prazo(prazo["id"], self.diretorio)["removido_no_google"])

    def test_registro_legado_sem_campos_de_sincronizacao(self):
        legado = novo_prazo("Legado", date(2026, 12, 1))
        for campo in CAMPOS_SINCRONIZACAO:
            legado.pop(campo)
        df = prazos_com_criticidade([legado], hoje=date(2026, 9, 27))
        self.assertIsNone(df.loc[0, "google_event_id"])
        self.assertFalse(df.loc[0, "removido_no_google"])

    def test_registros_misturados_nao_geram_nan(self):
        legado = novo_prazo("Legado", date(2026, 12, 1))
        for campo in CAMPOS_SINCRONIZACAO:
            legado.pop(campo)
        novo = {**novo_prazo("Novo", date(2026, 12, 2)), "google_event_id": "ev1"}
        df = prazos_com_criticidade([legado, novo], hoje=date(2026, 9, 27))
        linha_legado = df[df["titulo"] == "Legado"].iloc[0]
        self.assertIsNone(linha_legado["google_event_id"])
        self.assertIsNone(linha_legado["sincronizado_em"])
        self.assertIs(bool(linha_legado["removido_no_google"]), False)
```

Ajustar `test_lista_vazia_devolve_dataframe_vazio_com_colunas` se ele compara a lista exata
de colunas (conferir antes; as 4 colunas novas passam a existir).

- [ ] **Step 2: Rodar e ver falhar**

Run: `$PY -m unittest tests.test_prazos_orcamentarios -v`
Expected: FAIL — `ImportError: cannot import name 'CAMPOS_SINCRONIZACAO'`.

- [ ] **Step 3: Implementar em `src/prazos_orcamentarios.py`**

1. Na docstring do módulo, no "Contrato público", acrescentar as funções novas e um
   parágrafo:

```
Campos de sincronização com o Google Agenda (27/09/2026, ver
`docs/superpowers/specs/2026-09-27-google-agenda-design.md`): `google_event_id`,
`sincronizado_em`, `google_atualizado_em`, `removido_no_google` — gravados só por
`src/prazos_sincronizacao.py` via `gravar_estado_sincronizacao` (que NÃO carimba
`atualizado_em`, senão toda sincronização pareceria alteração local). A tela edita com
`editar`, que preserva esses campos — reconstruir o registro com `novo_prazo` perderia o
vínculo e duplicaria o evento no Google.
```

2. Constantes (depois de `PRIORIDADE_PADRAO`):

```python
#: estado da sincronização com o Google Agenda — nunca editado pela tela.
CAMPOS_SINCRONIZACAO = ("google_event_id", "sincronizado_em", "google_atualizado_em", "removido_no_google")
#: únicos campos que a tela (formulário/checkbox do card) pode alterar via `editar`.
CAMPOS_EDITAVEIS = (
    "titulo", "data_prazo", "descricao", "responsavel", "dias_antecedencia",
    "tipo", "categoria", "prioridade", "concluido",
)
```

3. `_COLUNAS` passa a terminar em:

```python
    "concluido", "criado_em", "atualizado_em", *CAMPOS_SINCRONIZACAO,
    "dias_para_vencer", "criticidade",
```

(mover a definição de `CAMPOS_SINCRONIZACAO` para antes de `_COLUNAS`).

4. `novo_prazo` — acrescentar ao dicionário devolvido:

```python
        "google_event_id": None,
        "sincronizado_em": None,
        "google_atualizado_em": None,
        "removido_no_google": False,
```

5. `atualizar` — trocar a linha que monta `prazo`:

```python
    prazo = {**prazo, "atualizado_em": _agora_iso()}
    if not prazo.get("concluido"):
        # reaberto: o evento deve ser recriado na próxima sincronização
        prazo["removido_no_google"] = False
```

6. Funções novas (depois de `excluir`):

```python
def carregar_prazo(identificador: str, diretorio: str | Path = DIRETORIO_PADRAO) -> dict:
    caminho = _caminho(identificador, Path(diretorio))
    if not caminho.exists():
        raise FileNotFoundError(f"Nenhum prazo cadastrado com o ID {identificador}.")
    return json.loads(caminho.read_text(encoding="utf-8"))


def editar(identificador: str, campos: dict, diretorio: str | Path = DIRETORIO_PADRAO) -> dict:
    """Aplica uma edição da tela sobre o registro gravado: só `CAMPOS_EDITAVEIS` são
    considerados (id, criado_em e estado de sincronização são preservados). Converte
    `concluido`/`dias_antecedencia` para tipos nativos (valores vindos de uma linha do
    DataFrame são `numpy.bool_`/`numpy.int64`, que o `json` não grava)."""

    anterior = carregar_prazo(identificador, diretorio)
    alteracoes = {chave: valor for chave, valor in campos.items() if chave in CAMPOS_EDITAVEIS}
    if "concluido" in alteracoes:
        alteracoes["concluido"] = bool(alteracoes["concluido"])
    if "dias_antecedencia" in alteracoes:
        alteracoes["dias_antecedencia"] = int(alteracoes["dias_antecedencia"])
    if isinstance(alteracoes.get("data_prazo"), date):
        alteracoes["data_prazo"] = alteracoes["data_prazo"].isoformat()
    atualizar({**anterior, **alteracoes}, diretorio)
    return carregar_prazo(identificador, diretorio)


def gravar_estado_sincronizacao(prazo: dict, diretorio: str | Path = DIRETORIO_PADRAO) -> Path:
    """Grava o registro como está — sem carimbar `atualizado_em` (diferente de `atualizar`).
    Uso exclusivo de `src/prazos_sincronizacao.py`."""

    caminho = _caminho(str(prazo["id"]), Path(diretorio))
    if not caminho.exists():
        raise FileNotFoundError(f"Nenhum prazo cadastrado com o ID {prazo['id']}.")
    _gravar_atomico(prazo, caminho)
    return caminho
```

7. `prazos_com_criticidade` — antes de `dataframe["data_prazo"] = ...`:

```python
    for campo in ("google_event_id", "sincronizado_em", "google_atualizado_em"):
        if campo not in dataframe.columns:
            dataframe[campo] = None
        dataframe[campo] = dataframe[campo].astype(object).where(dataframe[campo].notna(), None)
    if "removido_no_google" not in dataframe.columns:
        dataframe["removido_no_google"] = False
    dataframe["removido_no_google"] = dataframe["removido_no_google"].fillna(False).astype(bool)
```

- [ ] **Step 4: Página passa a editar com `editar`**

Com as colunas novas, a linha do DataFrame traz `removido_no_google` como `numpy.bool_`, que
o `json` não grava — o checkbox do card (que hoje monta o registro a partir da linha)
quebraria. E o formulário de edição (que reconstrói o registro com `novo_prazo`) perderia o
vínculo com o evento. As duas telas passam a usar `editar`.

Em `app_pages/painel_prazos.py`:

1. Import: trocar `atualizar,` por `editar,` na lista de `src.prazos_orcamentarios` (conferir
   com `grep -n "atualizar" app_pages/painel_prazos.py` que não sobra outro uso).

2. Salvar do formulário — trocar o bloco que começa em `candidato["concluido"] = bool(concluido)`
   até o `st.rerun()` por:

```python
        candidato["concluido"] = bool(concluido)
        if prazo_existente is not None:
            editar(prazo_existente["id"], candidato)
        else:
            salvar(candidato)
        st.rerun()
```

3. Checkbox do card — trocar o bloco `if concluido_novo != row["concluido"]:` por:

```python
        if concluido_novo != row["concluido"]:
            editar(row["id"], {"concluido": bool(concluido_novo)})
            st.rerun()
```

- [ ] **Step 5: Rodar e ver passar**

Run: `$PY -m unittest tests.test_prazos_orcamentarios tests.test_painel_prazos_page tests.test_home_page -v`
Expected: OK (testes antigos e novos).

Verificação manual: `$PY -m streamlit run app.py` → Gerenciamento de Prazos → marcar e
desmarcar "Concluído" num card e editar um prazo pelo formulário; ambos gravam sem erro.

- [ ] **Step 6: Commit**

```bash
git add src/prazos_orcamentarios.py tests/test_prazos_orcamentarios.py app_pages/painel_prazos.py
git commit -m "feat: campos de sincronizacao com o Google Agenda no cadastro de prazos

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Mapeamento prazo ↔ evento

**Files:**
- Create: `src/prazos_sincronizacao.py`
- Test: `tests/test_prazos_sincronizacao.py`

**Interfaces:**
- Consumes: `MARCADOR`, `MARCADOR_BUDGETLAB` (Task 1); `DIAS_ANTECEDENCIA_PADRAO`,
  `TIPO_PADRAO`, `PRIORIDADE_PADRAO` (existentes).
- Produces:
  - `DIAS_MAXIMOS_LEMBRETE = 28`, `PREFIXO_CONCLUIDO = "✓ "`
  - `class ErroSincronizacao(ValueError)`
  - `corpo_evento(prazo: dict) -> dict`
  - `campos_do_evento(evento: dict) -> dict` → `{"titulo": str, "data_prazo": "AAAA-MM-DD", "descricao": str}`
  - `sincronizacao_devida(ultima: datetime | None, agora: datetime, intervalo=timedelta(minutes=5)) -> bool`

- [ ] **Step 1: Escrever os testes que falham**

`tests/test_prazos_sincronizacao.py`:

```python
"""Testes de src/prazos_sincronizacao.py — mapeamento prazo ↔ evento e conciliação com um
cliente falso em memória (nunca acessa a rede). Diretórios temporários a cada teste."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone

from src.google_agenda import MARCADOR
from src.prazos_orcamentarios import novo_prazo
from src.prazos_sincronizacao import (
    ErroSincronizacao,
    campos_do_evento,
    corpo_evento,
    sincronizacao_devida,
)


def _evento(**extras) -> dict:
    base = {
        "id": "ev1", "titulo": "Prazo A", "descricao": "", "data_inicio": date(2026, 12, 1),
        "hora_inicio": None, "data_fim": date(2026, 12, 2), "hora_fim": None,
        "cancelado": False, "atualizado_em": "2026-09-27T10:00:00Z", "prazo_id": None,
        "propriedades": {}, "organizador": "", "minha_resposta": None, "link": "",
    }
    base.update(extras)
    return base


class TestCorpoEvento(unittest.TestCase):
    def test_evento_de_dia_inteiro_com_marcadores(self):
        prazo = novo_prazo("Prestação de contas", date(2026, 12, 1), "Obs", "Fulano", 10,
                           "Calendário anual", "SIAFI", "Essencial")
        corpo = corpo_evento(prazo)
        self.assertEqual(corpo["summary"], "Prestação de contas")
        self.assertEqual(corpo["description"], "Obs")
        self.assertEqual(corpo["start"], {"date": "2026-12-01"})
        self.assertEqual(corpo["end"], {"date": "2026-12-02"})
        privadas = corpo["extendedProperties"]["private"]
        self.assertEqual(privadas["budgetlab"], "1")
        self.assertEqual(privadas[MARCADOR], prazo["id"])
        self.assertEqual(privadas["tipo"], "Calendário anual")
        self.assertEqual(privadas["categoria"], "SIAFI")
        self.assertEqual(privadas["prioridade"], "Essencial")
        self.assertEqual(privadas["responsavel"], "Fulano")
        self.assertEqual(privadas["dias_antecedencia"], "10")
        self.assertTrue(all(isinstance(v, str) for v in privadas.values()))

    def test_lembrete_em_minutos(self):
        corpo = corpo_evento(novo_prazo("A", date(2026, 12, 1), dias_antecedencia=10))
        self.assertEqual(corpo["reminders"], {"useDefault": False, "overrides": [{"method": "popup", "minutes": 14400}]})

    def test_lembrete_limitado_a_28_dias(self):
        corpo = corpo_evento(novo_prazo("A", date(2026, 12, 1), dias_antecedencia=60))
        self.assertEqual(corpo["reminders"]["overrides"][0]["minutes"], 28 * 1440)

    def test_concluido_prefixa_titulo(self):
        prazo = {**novo_prazo("A", date(2026, 12, 1)), "concluido": True}
        self.assertEqual(corpo_evento(prazo)["summary"], "✓ A")

    def test_prazo_legado_sem_campos_opcionais(self):
        prazo = novo_prazo("A", date(2026, 12, 1))
        for campo in ("dias_antecedencia", "tipo", "categoria", "prioridade"):
            prazo.pop(campo)
        corpo = corpo_evento(prazo)
        self.assertEqual(corpo["reminders"]["overrides"][0]["minutes"], 28 * 1440)  # padrão 30 → 28
        self.assertEqual(corpo["extendedProperties"]["private"]["tipo"], "Solicitação")


class TestCamposDoEvento(unittest.TestCase):
    def test_mapeia_titulo_data_descricao(self):
        self.assertEqual(
            campos_do_evento(_evento(titulo="Novo", descricao="D", data_inicio=date(2026, 12, 3))),
            {"titulo": "Novo", "data_prazo": "2026-12-03", "descricao": "D"},
        )

    def test_prefixo_de_concluido_e_removido(self):
        self.assertEqual(campos_do_evento(_evento(titulo="✓ Prazo A"))["titulo"], "Prazo A")
        self.assertEqual(campos_do_evento(_evento(titulo="✓Prazo A"))["titulo"], "Prazo A")

    def test_prefixo_nao_devolve_concluido(self):
        self.assertNotIn("concluido", campos_do_evento(_evento(titulo="✓ Prazo A")))

    def test_evento_com_horario_usa_data_de_inicio(self):
        campos = campos_do_evento(_evento(data_inicio=date(2026, 12, 4), hora_inicio=time(9, 0)))
        self.assertEqual(campos["data_prazo"], "2026-12-04")

    def test_titulo_vazio_e_rejeitado(self):
        for titulo in ("", "   ", "✓ "):
            with self.assertRaises(ErroSincronizacao):
                campos_do_evento(_evento(titulo=titulo))

    def test_evento_sem_data_e_rejeitado(self):
        with self.assertRaises(ErroSincronizacao):
            campos_do_evento(_evento(data_inicio=None))


class TestSincronizacaoDevida(unittest.TestCase):
    agora = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)

    def test_nunca_sincronizou(self):
        self.assertTrue(sincronizacao_devida(None, self.agora))

    def test_dentro_do_intervalo(self):
        self.assertFalse(sincronizacao_devida(self.agora - timedelta(minutes=4), self.agora))

    def test_intervalo_vencido(self):
        self.assertTrue(sincronizacao_devida(self.agora - timedelta(minutes=5), self.agora))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `$PY -m unittest tests.test_prazos_sincronizacao -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.prazos_sincronizacao'`.

- [ ] **Step 3: Implementar**

`src/prazos_sincronizacao.py`:

```python
"""
Sincronização bidirecional entre o cadastro de Prazos Orçamentários e o Google Agenda.

Camada: regra de negócio da integração. Não acessa a rede diretamente — recebe um cliente com
a interface de `src.google_agenda.ClienteGoogleAgenda` (injeção), o que permite testar toda a
conciliação com um cliente falso. Não importa Streamlit.

Regras (decididas com o usuário em 27/09/2026 — ver
`docs/superpowers/specs/2026-09-27-google-agenda-design.md`):
- todo prazo vira um evento de DIA INTEIRO no calendário principal;
- só título, data e descrição são editáveis pelo Google; tipo, categoria, prioridade,
  responsável e antecedência viajam em `extendedProperties.private` e só se editam aqui;
- lembrete do Google limitado a 28 dias (limite da API); a criticidade "Vencendo" do
  BudgetLab continua usando `dias_antecedencia` integral;
- evento excluído no Google → prazo CONCLUÍDO (nunca excluído);
- prazo excluído no BudgetLab → evento excluído no Google;
- os dois lados alterados → vence o mais recente, sempre registrado no resumo com o valor
  descartado (rastreabilidade: nada é sobrescrito sem registro).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from src.google_agenda import MARCADOR, MARCADOR_BUDGETLAB
from src.prazos_orcamentarios import DIAS_ANTECEDENCIA_PADRAO, PRIORIDADE_PADRAO, TIPO_PADRAO

#: limite da Calendar API para lembretes (40320 minutos = 4 semanas).
DIAS_MAXIMOS_LEMBRETE = 28
#: só visual: acrescentá-lo ou removê-lo no Google NÃO altera `concluido`.
PREFIXO_CONCLUIDO = "✓ "
INTERVALO_SINCRONIZACAO_AUTOMATICA = timedelta(minutes=5)


class ErroSincronizacao(ValueError):
    """Evento do Google que não pode ser aplicado ao prazo (ex.: título vazio)."""


def corpo_evento(prazo: dict) -> dict:
    data = date.fromisoformat(prazo["data_prazo"])
    dias_antecedencia = int(prazo.get("dias_antecedencia", DIAS_ANTECEDENCIA_PADRAO))
    minutos = min(dias_antecedencia, DIAS_MAXIMOS_LEMBRETE) * 1440
    return {
        "summary": (PREFIXO_CONCLUIDO if prazo.get("concluido") else "") + prazo["titulo"],
        "description": prazo.get("descricao", ""),
        "start": {"date": data.isoformat()},
        "end": {"date": (data + timedelta(days=1)).isoformat()},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutos}]},
        "extendedProperties": {"private": {
            MARCADOR_BUDGETLAB: "1",
            MARCADOR: str(prazo["id"]),
            "tipo": str(prazo.get("tipo", TIPO_PADRAO)),
            "categoria": str(prazo.get("categoria", "")),
            "prioridade": str(prazo.get("prioridade", PRIORIDADE_PADRAO)),
            "responsavel": str(prazo.get("responsavel", "")),
            "dias_antecedencia": str(dias_antecedencia),
        }},
    }


def campos_do_evento(evento: dict) -> dict:
    """Os 3 campos editáveis pelo Google, prontos para `editar`/gravação. Rejeita evento sem
    título ou sem data (o prazo local fica intacto e o erro vai para o resumo)."""

    titulo = evento["titulo"].strip()
    if titulo.startswith(PREFIXO_CONCLUIDO.strip()):
        titulo = titulo[len(PREFIXO_CONCLUIDO.strip()):].strip()
    if not titulo:
        raise ErroSincronizacao("evento sem título no Google Agenda — alteração não aplicada.")
    if evento["data_inicio"] is None:
        raise ErroSincronizacao("evento sem data no Google Agenda — alteração não aplicada.")
    return {
        "titulo": titulo,
        "data_prazo": evento["data_inicio"].isoformat(),
        "descricao": evento["descricao"],
    }


def sincronizacao_devida(
    ultima: datetime | None, agora: datetime,
    intervalo: timedelta = INTERVALO_SINCRONIZACAO_AUTOMATICA,
) -> bool:
    """Controle da sincronização automática ao abrir a página (o Streamlit reexecuta o
    script a cada clique — sem este limite cada interação chamaria a API)."""

    return ultima is None or agora - ultima >= intervalo
```

- [ ] **Step 4: Rodar e ver passar**

Run: `$PY -m unittest tests.test_prazos_sincronizacao -v`
Expected: 14 testes, OK.

- [ ] **Step 5: Commit**

```bash
git add src/prazos_sincronizacao.py tests/test_prazos_sincronizacao.py
git commit -m "feat: mapeamento entre prazo e evento do Google Agenda

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Algoritmo de conciliação e resumo

**Files:**
- Modify: `src/prazos_sincronizacao.py`
- Test: `tests/test_prazos_sincronizacao.py`

**Interfaces:**
- Consumes: `corpo_evento`, `campos_do_evento`, `ErroSincronizacao` (Task 5);
  `carregar_prazos`, `atualizar`, `gravar_estado_sincronizacao`, `ErroPrazoOrcamentario`,
  `DIRETORIO_PADRAO` (Task 4 / existentes); `ErroGoogleAgenda`, `DIRETORIO_PADRAO as
  DIRETORIO_AGENDA` (Task 1).
- Produces:
  - `@dataclass ResumoSincronizacao` com `executado_em: str` e listas `criados`,
    `atualizados_no_google`, `atualizados_no_budgetlab`, `concluidos_por_exclusao`,
    `eventos_excluidos`, `erros` (listas de `str`) e `conflitos` (lista de `dict` com
    `titulo`, `vencedor` ∈ {"BudgetLab", "Google"}, `valor_budgetlab`, `valor_google`).
    Método `total_alteracoes() -> int`.
  - `sincronizar(cliente, diretorio=DIRETORIO_PADRAO, agora: datetime | None = None) -> ResumoSincronizacao`
    — `ErroGoogleAgenda` na listagem inicial propaga (nada alterado).
  - `salvar_resumo(resumo, diretorio=DIRETORIO_AGENDA) -> Path` e
    `carregar_ultimo_resumo(diretorio=DIRETORIO_AGENDA) -> dict | None`
    (arquivo `ultima_sincronizacao.json`).

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `tests/test_prazos_sincronizacao.py` (imports no topo):

```python
import tempfile
from pathlib import Path

from src.google_agenda import ErroGoogleAgenda
from src.prazos_orcamentarios import atualizar, carregar_prazo, excluir, salvar
from src.prazos_sincronizacao import (
    carregar_ultimo_resumo,
    salvar_resumo,
    sincronizar,
)


class ClienteFalso:
    """Calendário em memória com a interface de ClienteGoogleAgenda. `updated` avança a cada
    escrita; `falhar_em` faz uma operação específica lançar ErroGoogleAgenda."""

    def __init__(self):
        self.eventos: dict[str, dict] = {}
        self._seq = 0
        # relógio no passado: toda alteração local real (agora) é posterior a ele
        self._relogio = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.falhar_listagem = False
        self.falhar_em: set[tuple[str, str]] = set()  # (operação, prazo_id)
        self.excluidos: list[str] = []

    def _carimbo(self) -> str:
        self._relogio += timedelta(seconds=1)
        return self._relogio.isoformat().replace("+00:00", "Z")

    def _normalizar(self, event_id: str, corpo: dict, cancelado=False) -> dict:
        privadas = corpo["extendedProperties"]["private"]
        return _evento(
            id=event_id, titulo=corpo["summary"], descricao=corpo["description"],
            data_inicio=date.fromisoformat(corpo["start"]["date"]),
            cancelado=cancelado, atualizado_em=self._carimbo(),
            prazo_id=privadas[MARCADOR], propriedades=dict(privadas),
        ) | {"_corpo": corpo}

    def listar_eventos_de_prazos(self):
        if self.falhar_listagem:
            raise ErroGoogleAgenda("falha simulada")
        return [dict(e) for e in self.eventos.values()]

    def criar_evento(self, corpo):
        if ("criar", corpo["extendedProperties"]["private"][MARCADOR]) in self.falhar_em:
            raise ErroGoogleAgenda("falha simulada")
        self._seq += 1
        event_id = f"ev{self._seq}"
        self.eventos[event_id] = self._normalizar(event_id, corpo)
        return dict(self.eventos[event_id])

    def atualizar_evento(self, event_id, corpo):
        corpo_total = {**self.eventos[event_id]["_corpo"], **corpo}
        self.eventos[event_id] = self._normalizar(event_id, corpo_total)
        return dict(self.eventos[event_id])

    def excluir_evento(self, event_id):
        self.excluidos.append(event_id)
        self.eventos.pop(event_id, None)

    # --- ações "do usuário no Google" ---
    def editar_no_google(self, event_id, **campos):
        evento = self.eventos[event_id]
        evento.update(campos)
        evento["atualizado_em"] = self._carimbo()

    def cancelar_no_google(self, event_id):
        self.eventos[event_id].update(cancelado=True, atualizado_em=self._carimbo())


class TestSincronizar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self._tmp.name)
        self.cliente = ClienteFalso()

    def tearDown(self):
        self._tmp.cleanup()

    def _prazo(self, titulo="Prazo A", **extras) -> dict:
        prazo = {**novo_prazo(titulo, date(2026, 12, 1)), **extras}
        salvar(prazo, self.diretorio)
        return prazo

    def _sync(self):
        return sincronizar(self.cliente, self.diretorio)

    def _recarregar(self, prazo) -> dict:
        return carregar_prazo(prazo["id"], self.diretorio)

    def test_prazo_novo_cria_evento_e_grava_estado(self):
        prazo = self._prazo()
        resumo = self._sync()
        self.assertEqual(resumo.criados, ["Prazo A"])
        gravado = self._recarregar(prazo)
        evento = self.cliente.eventos[gravado["google_event_id"]]
        self.assertEqual(evento["prazo_id"], prazo["id"])
        self.assertEqual(gravado["sincronizado_em"], gravado["atualizado_em"])
        self.assertEqual(gravado["google_atualizado_em"], evento["atualizado_em"])
        self.assertEqual(gravado["atualizado_em"], prazo["atualizado_em"])  # não virou "alteração local"

    def test_segunda_sincronizacao_sem_mudancas_nao_faz_nada(self):
        self._prazo()
        self._sync()
        resumo = self._sync()
        self.assertEqual(resumo.total_alteracoes(), 0)
        self.assertEqual(len(self.cliente.eventos), 1)

    def test_alteracao_local_atualiza_evento(self):
        prazo = self._prazo()
        self._sync()
        atualizar({**self._recarregar(prazo), "titulo": "Prazo B"}, self.diretorio)
        resumo = self._sync()
        self.assertEqual(resumo.atualizados_no_google, ["Prazo B"])
        evento = next(iter(self.cliente.eventos.values()))
        self.assertEqual(evento["titulo"], "Prazo B")
        self.assertEqual(self._sync().total_alteracoes(), 0)

    def test_alteracao_no_google_atualiza_prazo(self):
        prazo = self._prazo()
        self._sync()
        event_id = self._recarregar(prazo)["google_event_id"]
        self.cliente.editar_no_google(event_id, titulo="Renomeado", descricao="Nova",
                                      data_inicio=date(2026, 12, 10))
        resumo = self._sync()
        self.assertEqual(resumo.atualizados_no_budgetlab, ["Renomeado"])
        gravado = self._recarregar(prazo)
        self.assertEqual((gravado["titulo"], gravado["descricao"], gravado["data_prazo"]),
                         ("Renomeado", "Nova", "2026-12-10"))
        self.assertEqual(gravado["tipo"], prazo["tipo"])
        self.assertEqual(self._sync().total_alteracoes(), 0)

    def test_conflito_vence_o_mais_recente_e_fica_registrado(self):
        prazo = self._prazo()
        self._sync()
        event_id = self._recarregar(prazo)["google_event_id"]
        self.cliente.editar_no_google(event_id, titulo="Do Google")  # relógio falso: 01/01/2000
        atualizar({**self._recarregar(prazo), "titulo": "Do BudgetLab"}, self.diretorio)  # agora real, posterior
        resumo = self._sync()
        self.assertEqual(len(resumo.conflitos), 1)
        conflito = resumo.conflitos[0]
        self.assertEqual(conflito["vencedor"], "BudgetLab")
        self.assertEqual(conflito["valor_google"]["titulo"], "Do Google")
        self.assertEqual(conflito["valor_budgetlab"]["titulo"], "Do BudgetLab")
        self.assertEqual(self.cliente.eventos[event_id]["titulo"], "Do BudgetLab")

    def test_conflito_vencido_pelo_google(self):
        prazo = self._prazo()
        self._sync()
        gravado = self._recarregar(prazo)
        # alteração local antiga (carimbo manual) x alteração no Google posterior
        gravado.update(titulo="Do BudgetLab", atualizado_em="1999-01-01T00:00:00+00:00")
        from src.prazos_orcamentarios import gravar_estado_sincronizacao
        gravar_estado_sincronizacao(gravado, self.diretorio)
        self.cliente.editar_no_google(gravado["google_event_id"], titulo="Do Google")
        resumo = self._sync()
        self.assertEqual(resumo.conflitos[0]["vencedor"], "Google")
        self.assertEqual(self._recarregar(prazo)["titulo"], "Do Google")

    def test_evento_excluido_no_google_conclui_o_prazo(self):
        prazo = self._prazo()
        self._sync()
        self.cliente.cancelar_no_google(self._recarregar(prazo)["google_event_id"])
        resumo = self._sync()
        self.assertEqual(resumo.concluidos_por_exclusao, ["Prazo A"])
        gravado = self._recarregar(prazo)
        self.assertTrue(gravado["concluido"])
        self.assertTrue(gravado["removido_no_google"])
        self.assertIsNone(gravado["google_event_id"])
        # não recria na próxima sincronização
        self.assertEqual(self._sync().total_alteracoes(), 0)

    def test_evento_ausente_da_listagem_conclui_o_prazo(self):
        prazo = self._prazo()
        self._sync()
        self.cliente.eventos.clear()
        self._sync()
        self.assertTrue(self._recarregar(prazo)["concluido"])

    def test_reabrir_prazo_removido_no_google_recria_evento(self):
        prazo = self._prazo()
        self._sync()
        self.cliente.cancelar_no_google(self._recarregar(prazo)["google_event_id"])
        self._sync()
        atualizar({**self._recarregar(prazo), "concluido": False}, self.diretorio)
        resumo = self._sync()
        self.assertEqual(resumo.criados, ["Prazo A"])
        self.assertIsNotNone(self._recarregar(prazo)["google_event_id"])

    def test_concluir_localmente_prefixa_evento(self):
        prazo = self._prazo()
        self._sync()
        atualizar({**self._recarregar(prazo), "concluido": True}, self.diretorio)
        self._sync()
        evento = self.cliente.eventos[self._recarregar(prazo)["google_event_id"]]
        self.assertEqual(evento["titulo"], "✓ Prazo A")

    def test_prefixo_editado_no_google_nao_altera_concluido(self):
        prazo = self._prazo()
        self._sync()
        self.cliente.editar_no_google(self._recarregar(prazo)["google_event_id"], titulo="✓ Prazo A")
        self._sync()
        gravado = self._recarregar(prazo)
        self.assertFalse(gravado["concluido"])
        self.assertEqual(gravado["titulo"], "Prazo A")

    def test_prazo_excluido_localmente_exclui_evento(self):
        prazo = self._prazo()
        self._sync()
        event_id = self._recarregar(prazo)["google_event_id"]
        excluir(prazo["id"], self.diretorio)
        resumo = self._sync()
        self.assertEqual(self.cliente.excluidos, [event_id])
        self.assertEqual(resumo.eventos_excluidos, ["Prazo A"])

    def test_falha_na_listagem_nao_altera_nada(self):
        prazo = self._prazo()
        self._sync()
        antes = self._recarregar(prazo)
        self.cliente.falhar_listagem = True
        with self.assertRaises(ErroGoogleAgenda):
            self._sync()
        self.assertEqual(self._recarregar(prazo), antes)

    def test_erro_em_um_item_nao_interrompe_os_demais(self):
        a = self._prazo("Prazo A")
        b = self._prazo("Prazo B")
        self.cliente.falhar_em.add(("criar", a["id"]))
        resumo = self._sync()
        self.assertEqual(resumo.criados, ["Prazo B"])
        self.assertEqual(len(resumo.erros), 1)
        self.assertIn("Prazo A", resumo.erros[0])
        self.assertIsNone(self._recarregar(a)["google_event_id"])
        self.assertIsNotNone(self._recarregar(b)["google_event_id"])

    def test_titulo_vazio_no_google_nao_e_aplicado(self):
        prazo = self._prazo()
        self._sync()
        self.cliente.editar_no_google(self._recarregar(prazo)["google_event_id"], titulo="  ")
        resumo = self._sync()
        self.assertEqual(len(resumo.erros), 1)
        self.assertEqual(self._recarregar(prazo)["titulo"], "Prazo A")

    def test_adota_evento_existente_sem_duplicar(self):
        prazo = self._prazo()
        self._sync()
        # simula queda depois de criar o evento e antes de gravar o estado
        gravado = self._recarregar(prazo)
        gravado.update(google_event_id=None, sincronizado_em=None, google_atualizado_em=None)
        from src.prazos_orcamentarios import gravar_estado_sincronizacao
        gravar_estado_sincronizacao(gravado, self.diretorio)
        self._sync()
        self.assertEqual(len(self.cliente.eventos), 1)
        self.assertIsNotNone(self._recarregar(prazo)["google_event_id"])

    def test_exclui_evento_duplicado_do_mesmo_prazo(self):
        prazo = self._prazo()
        self._sync()
        vinculado = self._recarregar(prazo)["google_event_id"]
        from src.prazos_sincronizacao import corpo_evento
        duplicado = self.cliente.criar_evento(corpo_evento(self._recarregar(prazo)))["id"]
        self._sync()
        self.assertIn(vinculado, self.cliente.eventos)
        self.assertNotIn(duplicado, self.cliente.eventos)

    def test_prazo_legado_sem_campos_de_sincronizacao(self):
        prazo = novo_prazo("Legado", date(2026, 12, 1))
        for campo in ("google_event_id", "sincronizado_em", "google_atualizado_em", "removido_no_google"):
            prazo.pop(campo)
        salvar(prazo, self.diretorio)
        resumo = self._sync()
        self.assertEqual(resumo.criados, ["Legado"])


class TestResumoPersistido(unittest.TestCase):
    def test_salvar_e_carregar_ultimo_resumo(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            self.assertIsNone(carregar_ultimo_resumo(diretorio))
            dados = tempfile.TemporaryDirectory()
            try:
                prazos = Path(dados.name)
                salvar(novo_prazo("A", date(2026, 12, 1)), prazos)
                resumo = sincronizar(ClienteFalso(), prazos)
            finally:
                dados.cleanup()
            salvar_resumo(resumo, diretorio)
            carregado = carregar_ultimo_resumo(diretorio)
            self.assertEqual(carregado["criados"], ["A"])
            self.assertEqual(carregado["executado_em"], resumo.executado_em)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `$PY -m unittest tests.test_prazos_sincronizacao -v`
Expected: FAIL — `ImportError: cannot import name 'sincronizar'`.

- [ ] **Step 3: Implementar**

Acrescentar a `src/prazos_sincronizacao.py`:

1. Imports (substituir o bloco de imports):

```python
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.google_agenda import DIRETORIO_PADRAO as DIRETORIO_AGENDA
from src.google_agenda import MARCADOR, MARCADOR_BUDGETLAB, ErroGoogleAgenda, _gravar_atomico
from src.prazos_orcamentarios import (
    DIAS_ANTECEDENCIA_PADRAO,
    DIRETORIO_PADRAO,
    PRIORIDADE_PADRAO,
    TIPO_PADRAO,
    ErroPrazoOrcamentario,
    atualizar,
    carregar_prazos,
    gravar_estado_sincronizacao,
)

ARQUIVO_RESUMO = "ultima_sincronizacao.json"
```

2. No fim do arquivo:

```python
@dataclass
class ResumoSincronizacao:
    executado_em: str
    criados: list[str] = field(default_factory=list)
    atualizados_no_google: list[str] = field(default_factory=list)
    atualizados_no_budgetlab: list[str] = field(default_factory=list)
    concluidos_por_exclusao: list[str] = field(default_factory=list)
    eventos_excluidos: list[str] = field(default_factory=list)
    conflitos: list[dict] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)

    def total_alteracoes(self) -> int:
        return sum(len(lista) for lista in (
            self.criados, self.atualizados_no_google, self.atualizados_no_budgetlab,
            self.concluidos_por_exclusao, self.eventos_excluidos,
        ))


def _momento(texto: str | None) -> datetime:
    if not texto:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(texto)


def _valores(origem: dict) -> dict:
    return {"titulo": origem["titulo"], "data_prazo": origem["data_prazo"], "descricao": origem.get("descricao", "")}


def _vincular(prazo: dict, evento: dict, diretorio: Path) -> None:
    """Grava o estado "sincronizado" do prazo com este evento, sem carimbar alteração local."""

    gravar_estado_sincronizacao({
        **prazo,
        "google_event_id": evento["id"],
        "sincronizado_em": prazo["atualizado_em"],
        "google_atualizado_em": evento["atualizado_em"],
    }, diretorio)


def _enviar(cliente, prazo: dict, evento: dict | None, diretorio: Path) -> None:
    """BudgetLab → Google: cria (sem evento) ou atualiza o evento e vincula."""

    corpo = corpo_evento(prazo)
    novo = cliente.criar_evento(corpo) if evento is None else cliente.atualizar_evento(evento["id"], corpo)
    _vincular(prazo, novo, diretorio)


def _receber(prazo: dict, evento: dict, diretorio: Path, agora: datetime) -> dict:
    """Google → BudgetLab: aplica os 3 campos editáveis e marca como sincronizado. Carimba
    `atualizado_em` (é uma alteração real do registro) e iguala `sincronizado_em` a ele."""

    campos = campos_do_evento(evento)
    carimbo = agora.isoformat()
    atualizado = {
        **prazo, **campos,
        "atualizado_em": carimbo,
        "sincronizado_em": carimbo,
        "google_event_id": evento["id"],
        "google_atualizado_em": evento["atualizado_em"],
    }
    gravar_estado_sincronizacao(atualizado, diretorio)
    return atualizado


def sincronizar(cliente, diretorio: str | Path = DIRETORIO_PADRAO, agora: datetime | None = None) -> ResumoSincronizacao:
    """Concilia todos os prazos com os eventos marcados do calendário principal. Falha na
    listagem inicial propaga `ErroGoogleAgenda` sem alterar nada. Erro em um item vai para
    `resumo.erros` e não interrompe os demais (será tentado de novo na próxima vez)."""

    diretorio = Path(diretorio)
    agora = agora or datetime.now(timezone.utc)
    eventos = cliente.listar_eventos_de_prazos()  # pode lançar ErroGoogleAgenda: aborta aqui
    resumo = ResumoSincronizacao(executado_em=agora.isoformat())

    eventos_por_prazo: dict[str, list[dict]] = {}
    for evento in eventos:
        if evento["prazo_id"]:
            eventos_por_prazo.setdefault(evento["prazo_id"], []).append(evento)

    prazos = carregar_prazos(diretorio)
    for prazo in prazos:
        titulo = prazo["titulo"]
        prazo.setdefault("atualizado_em", prazo.get("criado_em"))
        candidatos = eventos_por_prazo.get(prazo["id"], [])
        ativos = [e for e in candidatos if not e["cancelado"]]
        event_id = prazo.get("google_event_id")
        try:
            if event_id is None:
                if ativos:  # queda entre criar e gravar: adota em vez de duplicar
                    evento, duplicados = ativos[0], ativos[1:]
                    _enviar(cliente, prazo, evento, diretorio)
                    resumo.atualizados_no_google.append(titulo)
                elif prazo.get("removido_no_google"):
                    continue
                else:
                    duplicados = []
                    _enviar(cliente, prazo, None, diretorio)
                    resumo.criados.append(titulo)
            else:
                evento = next((e for e in ativos if e["id"] == event_id), None)
                duplicados = [e for e in ativos if e["id"] != event_id]
                if evento is None:
                    atualizar({**prazo, "concluido": True, "removido_no_google": True,
                               "google_event_id": None}, diretorio)
                    resumo.concluidos_por_exclusao.append(titulo)
                else:
                    mudou_local = prazo["atualizado_em"] != prazo.get("sincronizado_em")
                    mudou_google = evento["atualizado_em"] != prazo.get("google_atualizado_em")
                    if mudou_local and mudou_google:
                        google_vence = _momento(evento["atualizado_em"]) > _momento(prazo["atualizado_em"])
                        resumo.conflitos.append({
                            "titulo": titulo,
                            "vencedor": "Google" if google_vence else "BudgetLab",
                            "valor_budgetlab": _valores(prazo),
                            "valor_google": {
                                "titulo": evento["titulo"],
                                "data_prazo": evento["data_inicio"].isoformat() if evento["data_inicio"] else None,
                                "descricao": evento["descricao"],
                            },
                        })
                        if google_vence:
                            titulo = _receber(prazo, evento, diretorio, agora)["titulo"]
                            resumo.atualizados_no_budgetlab.append(titulo)
                        else:
                            _enviar(cliente, prazo, evento, diretorio)
                            resumo.atualizados_no_google.append(titulo)
                    elif mudou_local:
                        _enviar(cliente, prazo, evento, diretorio)
                        resumo.atualizados_no_google.append(titulo)
                    elif mudou_google:
                        titulo = _receber(prazo, evento, diretorio, agora)["titulo"]
                        resumo.atualizados_no_budgetlab.append(titulo)
            for duplicado in duplicados:
                cliente.excluir_evento(duplicado["id"])
        except (ErroGoogleAgenda, ErroSincronizacao, ErroPrazoOrcamentario, OSError) as erro:
            resumo.erros.append(f"{titulo}: {erro}")

    ids_locais = {prazo["id"] for prazo in prazos}
    for prazo_id, candidatos in eventos_por_prazo.items():
        if prazo_id in ids_locais:
            continue
        for evento in candidatos:
            if evento["cancelado"]:
                continue
            try:
                cliente.excluir_evento(evento["id"])
                resumo.eventos_excluidos.append(evento["titulo"].removeprefix(PREFIXO_CONCLUIDO))
            except ErroGoogleAgenda as erro:
                resumo.erros.append(f"{evento['titulo']}: {erro}")

    return resumo


def salvar_resumo(resumo: ResumoSincronizacao, diretorio: str | Path = DIRETORIO_AGENDA) -> Path:
    caminho = Path(diretorio) / ARQUIVO_RESUMO
    _gravar_atomico(caminho, json.dumps(asdict(resumo), ensure_ascii=False, indent=2))
    return caminho


def carregar_ultimo_resumo(diretorio: str | Path = DIRETORIO_AGENDA) -> dict | None:
    caminho = Path(diretorio) / ARQUIVO_RESUMO
    if not caminho.exists():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))
```

Notas para o implementador:
- `_gravar_atomico` de `src.google_agenda` recebe `(caminho, texto)` — é diferente do
  `_gravar_atomico(prazo, caminho)` de `src.prazos_orcamentarios`. Não confundir.
- O relógio do `ClienteFalso` começa em 01/01/2000 de propósito: toda alteração local real
  (carimbada com a hora atual por `atualizar`) é posterior a ele, então os testes de conflito
  não dependem da data de execução.

- [ ] **Step 4: Rodar e ver passar**

Run: `$PY -m unittest tests.test_prazos_sincronizacao -v`
Expected: OK (14 da Task 5 + 19 novos).

- [ ] **Step 5: Commit**

```bash
git add src/prazos_sincronizacao.py tests/test_prazos_sincronizacao.py
git commit -m "feat: conciliacao bidirecional entre prazos e Google Agenda

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Tela — sincronização, resumo e edição segura

**Files:**
- Modify: `app_pages/painel_prazos.py`
- Modify: `tests/test_painel_prazos_page.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `sincronizar`, `salvar_resumo`, `carregar_ultimo_resumo`,
  `sincronizacao_devida` (Tasks 5–6); `google_agenda.cliente` (Task 2).

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/test_painel_prazos_page.py`:

```python
    def test_conectado_sincroniza_ao_abrir_e_mostra_botao(self):
        from src.prazos_sincronizacao import ResumoSincronizacao
        resumo = ResumoSincronizacao(executado_em="2026-09-27T12:00:00+00:00")
        with mock.patch("src.google_agenda.situacao_conexao", return_value="conectado"), \
             mock.patch("src.google_agenda.cliente", return_value=mock.Mock(listar_eventos=mock.Mock(return_value=[]))), \
             mock.patch("src.prazos_sincronizacao.sincronizar", return_value=resumo) as sync, \
             mock.patch("src.prazos_sincronizacao.salvar_resumo"), \
             mock.patch("src.prazos_sincronizacao.carregar_ultimo_resumo", return_value=None):
            app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
            app.run()
            app.switch_page("app_pages/painel_prazos.py")
            app.run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(sync.call_count, 1)
        self.assertIn("Sincronizar agora", [b.label for b in app.button])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `$PY -m unittest tests.test_painel_prazos_page -v`
Expected: FAIL — `sync.call_count == 0` / botão ausente.

- [ ] **Step 3: Implementar**

Em `app_pages/painel_prazos.py`:

(O formulário e o card já usam `editar` desde a Task 4.)

1. Import:

```python
from src import prazos_sincronizacao
```

2. Função nova (junto de `_render_conexao`):

```python
def _executar_sincronizacao() -> None:
    try:
        resumo = prazos_sincronizacao.sincronizar(google_agenda.cliente())
    except ErroGoogleAgenda as erro:
        render_alert(f"Sincronização com o Google Agenda não realizada: {erro}", "error")
        return
    prazos_sincronizacao.salvar_resumo(resumo)
    st.session_state["pp_google_ultima_sync"] = datetime.now(_FUSO)
    _eventos_proximos.clear()


def _render_resumo_sincronizacao() -> None:
    resumo = prazos_sincronizacao.carregar_ultimo_resumo()
    if resumo is None:
        st.caption("Ainda não sincronizado.")
        return
    quando = datetime.fromisoformat(resumo["executado_em"]).astimezone(_FUSO).strftime("%d/%m/%Y %H:%M")
    partes = [
        f"{len(resumo['criados'])} criado(s)",
        f"{len(resumo['atualizados_no_google'])} atualizado(s) no Google",
        f"{len(resumo['atualizados_no_budgetlab'])} atualizado(s) aqui",
        f"{len(resumo['concluidos_por_exclusao'])} concluído(s) por exclusão no Google",
        f"{len(resumo['eventos_excluidos'])} evento(s) excluído(s)",
    ]
    st.caption(f"Última sincronização: {quando} — " + " · ".join(partes))
    if resumo["conflitos"] or resumo["erros"]:
        with st.expander(f"{len(resumo['conflitos'])} conflito(s) · {len(resumo['erros'])} erro(s)"):
            for conflito in resumo["conflitos"]:
                st.markdown(
                    f"**{conflito['titulo']}** — venceu {conflito['vencedor']}. "
                    f"BudgetLab: `{conflito['valor_budgetlab']}` · Google: `{conflito['valor_google']}`"
                )
            for erro in resumo["erros"]:
                st.markdown(f"- {erro}")
```

3. Em `_render_conexao`, no ramo `conectado`, substituir o conteúdo por:

```python
        else:
            ultima = st.session_state.get("pp_google_ultima_sync")
            if prazos_sincronizacao.sincronizacao_devida(ultima, datetime.now(_FUSO)):
                _executar_sincronizacao()
            c1, c2 = st.columns([1, 1])
            if c1.button("Sincronizar agora", icon=":material/sync:", use_container_width=True):
                _executar_sincronizacao()
                st.rerun()
            if c2.button("Desconectar", icon=":material/link_off:", use_container_width=True):
                google_agenda.desconectar()
                _eventos_proximos.clear()
                st.rerun()
            _render_resumo_sincronizacao()
```

(A sincronização roda antes de `carregar_prazos()` porque `_render_conexao` é chamado antes
dele no corpo da página — a grade já mostra os dados sincronizados.)

4. README: acrescentar ao parágrafo criado na Task 3:

```markdown
Os prazos cadastrados também são sincronizados nos dois sentidos: excluir o evento de um
prazo no Google marca o prazo como concluído (nunca o exclui). Conciliação em
`src/prazos_sincronizacao.py`.
```

- [ ] **Step 4: Rodar e ver passar**

Run: `$PY -m unittest tests.test_painel_prazos_page tests.test_prazos_orcamentarios tests.test_prazos_sincronizacao tests.test_google_agenda tests.test_home_page -v`
Expected: OK.

- [ ] **Step 5: Verificação manual**

Run: `$PY -m streamlit run app.py`, abrir Gerenciamento de Prazos.
Sem `credentials.json`: página funciona como antes, com a instrução. Editar um prazo e
marcar/desmarcar concluído continuam funcionando. Com conta conectada (se o usuário tiver
configurado): criar prazo → aparece no Google após "Sincronizar agora"; editar título no
Google → reflete aqui; excluir no Google → prazo concluído.

- [ ] **Step 6: Suíte completa (segundo plano) e commit**

Run: `$PY -m unittest discover -s tests` (segundo plano)
Expected: sem regressões.

```bash
git add app_pages/painel_prazos.py tests/test_painel_prazos_page.py README.md
git commit -m "feat: sincronizacao de prazos com o Google Agenda na tela de prazos

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
