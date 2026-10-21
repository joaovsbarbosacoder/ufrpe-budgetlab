"""Sincronização das decisões do usuário entre dispositivos, por uma pasta no Google Drive (pedido de 21/10/2026).

Em vez de sincronizar `data/` inteiro (planilhas brutas, cache e bancos SQLite pesam centenas de MB), o sistema envia ao
Drive um PACOTE PEQUENO só com as decisões do usuário (`GRUPOS_DECISOES`, ~100 KB), reaproveitando o formato do backup
(`src/backup_dados.py`: `.zip` com manifesto de tamanhos e SHA-256, restauração validada antes de gravar, cópia do que for
substituído em `data/_backup_restauracao/`). Sem senha (decisão de 21/10/2026: a busca automática ao iniciar não pode
pedir senha); o pacote nunca leva `token.json` nem `credentials.json`.

Regras (decisões do usuário em 21/10/2026):
  * Cada envio é um arquivo NOVO (`decisoes-AAAAMMDD-HHMMSS-ffffff-<dispositivo>.zip`): nada é sobrescrito. Ficam as
    `LIMITE_VERSOES` mais recentes; as mais antigas são apagadas depois de um envio bem-sucedido.
  * Ao iniciar (e de tempos em tempos, só se houver alteração), o sistema compara a versão mais nova do Drive com a
    última sincronizada neste dispositivo:
      - Drive igual à última sincronizada e nada mudou aqui  -> em dia;
      - Drive igual e algo mudou aqui                          -> envia uma versão nova;
      - Drive mais novo e nada mudou aqui desde a última sync  -> TRAZ sozinho (guardando o que for substituído);
      - Drive mais novo e algo mudou aqui                      -> CONFLITO: não muda nada e avisa; o usuário escolhe
        "trazer a do Drive" (a local fica guardada) ou "manter a local" (vira a versão mais nova).
    Dados idênticos nos dois lados (ex.: primeiro uso num dispositivo que já tinha os mesmos dados) não são conflito.
  * Sem internet, sem login ou com qualquer falha de rede: nada é alterado e o sistema segue; o estado aparece na página.
  * Exclusões não são sincronizadas: um arquivo que existe só aqui permanece (as decisões do sistema só criam ou reescrevem
    arquivos; excluir uma despesa reescreve o JSON).

Persistência autorizada em 21/10/2026: `data/sincronizacao/estado.json` (identificador do dispositivo, última versão
sincronizada e a impressão digital das decisões nesse momento), fora do Git e fora do pacote. Arquivo ilegível levanta
`ErroSincronizacao` e nunca é sobrescrito.

Camada: este módulo não importa Streamlit. A lógica fala com um `Armazenamento` (Drive de verdade ou memória nos testes).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import threading
import time
import uuid
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from src import backup_dados

#: decisões do usuário (as mesmas pastas de `scripts/sincronizar_dados.ps1`). Fora, de propósito: planilhas, cache e bancos.
GRUPOS_DECISOES: tuple[str, ...] = (
    "resultado_orcamentario",
    "projecao_execucao",
    "projecao_execucao_bolsas",
    "preferencias",
    "limite_empenho",
    "conciliacao_decisoes",
    "contratos_continuos",
    "bolsas_auxilios",
)
BASE_PADRAO = Path("data")
DIRETORIO_ESTADO = Path("data/sincronizacao")
LIMITE_VERSOES = 20
PREFIXO_NOME = "decisoes-"
#: intervalo mínimo (s) entre ciclos dentro de uma mesma sessão (o primeiro, ao iniciar, roda sempre)
INTERVALO_CICLO = 60.0
#: `BUDGETLAB_SINCRONIZACAO=desligado` desliga o ciclo automático (usado por `tests/conftest.py`: a suíte nunca fala com um
#: Drive real, nem com um token da máquina de quem roda os testes).
VARIAVEL_AMBIENTE = "BUDGETLAB_SINCRONIZACAO"
#: mesmo diretório do token da Agenda (fora de `data/`, que fica numa pasta sincronizada); duplicado aqui para o ciclo ao
#: iniciar não precisar importar as bibliotecas do Google quando não há conexão.
DIRETORIO_TOKEN = Path(os.environ.get("APPDATA") or Path.home()) / "UFRPE BudgetLab"

#: o Streamlit executa cada sessão (aba do navegador) numa thread do mesmo processo: sem a trava, duas sessões abrindo ao
#: mesmo tempo enviariam a mesma versão duas vezes (visto em 21/10/2026). Um ciclo por vez, que já enxerga o estado do anterior.
_TRAVA = threading.Lock()

ACAO_NADA = "nada"
ACAO_EM_DIA = "em_dia"
ACAO_ENVIADO = "enviado"
ACAO_TRAZIDO = "trazido"
ACAO_CONFLITO = "conflito"
ACAO_ERRO = "erro"


class ErroSincronizacao(RuntimeError):
    """Falha de rede, de login ou de arquivo de estado ilegível: o chamador mostra a mensagem e segue sem alterar dados."""


@dataclass(frozen=True)
class VersaoRemota:
    id: str
    nome: str

    @property
    def chave(self) -> tuple[str, str]:
        """Ordem cronológica: o carimbo está no nome, e o nome inclui microssegundos."""

        return (self.nome, self.id)

    @property
    def dispositivo(self) -> str:
        return self.nome.removesuffix(".zip").rsplit("-", 1)[-1]

    @property
    def criado_em(self) -> str:
        partes = self.nome.removeprefix(PREFIXO_NOME).split("-")
        try:
            return datetime.strptime("-".join(partes[:3]), "%Y%m%d-%H%M%S-%f").strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            return ""


class Armazenamento(Protocol):
    def listar(self) -> list[VersaoRemota]: ...
    def enviar(self, nome: str, conteudo: bytes) -> str: ...
    def baixar(self, id_versao: str) -> bytes: ...
    def apagar(self, id_versao: str) -> None: ...


@dataclass
class Estado:
    dispositivo_id: str
    dispositivo_nome: str = ""
    ultima_versao_id: str | None = None
    ultimo_hash: str | None = None
    ultima_sincronizacao_em: str | None = None
    #: sincroniza sozinho (ao iniciar e a cada alteração); desligado, só pelos botões da página
    automatica: bool = True


@dataclass
class ResultadoSincronizacao:
    acao: str
    mensagem: str
    versao: VersaoRemota | None = None
    #: arquivos substituídos ao trazer (cópias em `data/_backup_restauracao/`)
    substituidos: int = 0
    novos: int = 0


# --------------------------------------------------------------------------------------------- estado local
def _agora() -> datetime:
    return datetime.now()


def _caminho_estado(diretorio_estado: Path) -> Path:
    return Path(diretorio_estado) / "estado.json"


def carregar_estado(diretorio_estado: Path = DIRETORIO_ESTADO) -> Estado:
    """Estado gravado, ou um novo (com identificador do dispositivo, gravado na hora) se ainda não existe. Ilegível: `ErroSincronizacao`."""

    caminho = _caminho_estado(diretorio_estado)
    if not caminho.exists():
        novo = Estado(dispositivo_id=uuid.uuid4().hex[:8], dispositivo_nome=socket.gethostname())
        salvar_estado(novo, diretorio_estado)  # a identidade do dispositivo tem de ser estável, mesmo sem sincronização bem-sucedida
        return novo
    try:
        dado = json.loads(caminho.read_text(encoding="utf-8"))
        return Estado(
            dispositivo_id=str(dado["dispositivo_id"]),
            dispositivo_nome=str(dado.get("dispositivo_nome", "")),
            ultima_versao_id=dado.get("ultima_versao_id"),
            ultimo_hash=dado.get("ultimo_hash"),
            ultima_sincronizacao_em=dado.get("ultima_sincronizacao_em"),
            automatica=bool(dado.get("automatica", True)),
        )
    except (ValueError, KeyError, TypeError, OSError) as erro:
        raise ErroSincronizacao(
            f"Arquivo de estado da sincronização ilegível ({caminho}); corrija ou restaure — nada foi sobrescrito."
        ) from erro


def salvar_estado(estado: Estado, diretorio_estado: Path = DIRETORIO_ESTADO) -> None:
    caminho = _caminho_estado(diretorio_estado)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.parent / f".{caminho.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(
            json.dumps(estado.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()


def impressao_digital(base: Path = BASE_PADRAO) -> str:
    """Resumo do conteúdo das decisões em `base` (caminho + SHA-256 de cada arquivo). Vazio (`""`) = sem dados."""

    arquivos = backup_dados._listar_arquivos(Path(base), list(GRUPOS_DECISOES), incluir_credenciais=False)
    if not arquivos:
        return ""
    resumo = hashlib.sha256()
    for caminho in arquivos:  # já ordenados por pasta e nome
        resumo.update(caminho.relative_to(base).as_posix().encode("utf-8"))
        resumo.update(b"\0")
        resumo.update(backup_dados._sha256_arquivo(caminho).encode("ascii"))
        resumo.update(b"\0")
    return resumo.hexdigest()


def gerar_pacote(base: Path = BASE_PADRAO, agora: datetime | None = None) -> bytes:
    return backup_dados.gerar_backup(
        base, grupos=list(GRUPOS_DECISOES), incluir_credenciais=False, agora=agora, grupos_permitidos=GRUPOS_DECISOES,
    )


def _nome_versao(estado: Estado, agora: datetime) -> str:
    return f"{PREFIXO_NOME}{agora.strftime('%Y%m%d-%H%M%S-%f')}-{estado.dispositivo_id}.zip"


# --------------------------------------------------------------------------------------------- operações
def _mais_nova(versoes: list[VersaoRemota]) -> VersaoRemota | None:
    return max(versoes, key=lambda v: v.chave) if versoes else None


def _enviar(
    armazenamento: Armazenamento, estado: Estado, base: Path, diretorio_estado: Path, agora: datetime,
) -> VersaoRemota:
    pacote = gerar_pacote(base, agora)
    nome = _nome_versao(estado, agora)
    id_versao = armazenamento.enviar(nome, pacote)
    versao = VersaoRemota(id_versao, nome)
    estado.ultima_versao_id = id_versao
    estado.ultimo_hash = impressao_digital(base)
    estado.ultima_sincronizacao_em = agora.isoformat(timespec="seconds")
    salvar_estado(estado, diretorio_estado)
    _aparar_versoes(armazenamento)
    return versao


def _aparar_versoes(armazenamento: Armazenamento) -> None:
    """Mantém as `LIMITE_VERSOES` mais recentes. Só mexe depois de um envio bem-sucedido; falha ao apagar não é erro."""

    versoes = sorted(armazenamento.listar(), key=lambda v: v.chave)
    for antiga in versoes[: max(0, len(versoes) - LIMITE_VERSOES)]:
        try:
            armazenamento.apagar(antiga.id)
        except ErroSincronizacao:
            return


def _trazer(
    armazenamento: Armazenamento, versao: VersaoRemota, estado: Estado, base: Path, diretorio_estado: Path, agora: datetime,
) -> ResultadoSincronizacao:
    conteudo = armazenamento.baixar(versao.id)
    try:
        previa = backup_dados.analisar_backup(conteudo, base, grupos_permitidos=GRUPOS_DECISOES)
        fora = sorted({i.caminho for i in previa.itens if i.caminho.split("/", 1)[0] not in GRUPOS_DECISOES})
        if fora:  # o pacote de decisões nunca leva planilhas, cache, bancos nem segredos
            raise ErroSincronizacao(f"Pacote do Drive recusado ({versao.nome}): arquivos fora das decisões: {fora[:3]}.")
        resultado = backup_dados.restaurar_backup(
            conteudo, base, substituir=True, agora=agora, grupos_permitidos=GRUPOS_DECISOES
        )
    except backup_dados.ErroBackup as erro:
        raise ErroSincronizacao(f"Pacote do Drive recusado ({versao.nome}): {erro}") from erro
    estado.ultima_versao_id = versao.id
    estado.ultimo_hash = impressao_digital(base)
    estado.ultima_sincronizacao_em = agora.isoformat(timespec="seconds")
    salvar_estado(estado, diretorio_estado)
    return ResultadoSincronizacao(
        ACAO_TRAZIDO,
        f"Dados atualizados a partir do Drive (versão de {versao.criado_em}, dispositivo {versao.dispositivo})"
        + (f"; {len(resultado.substituidos)} arquivo(s) substituído(s) com cópia guardada." if resultado.substituidos else "."),
        versao, substituidos=len(resultado.substituidos), novos=len(resultado.novos),
    )


def _remota_identica_ao_local(armazenamento: Armazenamento, versao: VersaoRemota, base: Path) -> bool:
    """O pacote do Drive tem exatamente o que já existe aqui? (então não há o que decidir)"""

    try:
        previa = backup_dados.analisar_backup(
            armazenamento.baixar(versao.id), base, grupos_permitidos=GRUPOS_DECISOES
        )
    except backup_dados.ErroBackup:
        return False
    return all(item.situacao == "identico" for item in previa.itens)


def _sincronizar(
    armazenamento: Armazenamento,
    base: Path = BASE_PADRAO,
    diretorio_estado: Path = DIRETORIO_ESTADO,
    agora: datetime | None = None,
) -> ResultadoSincronizacao:
    """Um ciclo de sincronização (ver a docstring do módulo). Levanta `ErroSincronizacao` em falha de rede/estado, sem alterar dados."""

    base, agora = Path(base), agora or _agora()
    estado = carregar_estado(diretorio_estado)
    local = impressao_digital(base)
    remota = _mais_nova(armazenamento.listar())
    mudou_aqui = local != (estado.ultimo_hash or "")

    if remota is None:
        if not local:
            return ResultadoSincronizacao(ACAO_NADA, "Nada a sincronizar: sem decisões aqui nem no Drive.")
        versao = _enviar(armazenamento, estado, base, diretorio_estado, agora)
        return ResultadoSincronizacao(ACAO_ENVIADO, "Primeira versão enviada ao Drive.", versao)

    if remota.id == estado.ultima_versao_id:
        if not mudou_aqui:
            return ResultadoSincronizacao(ACAO_EM_DIA, f"Em dia com o Drive (versão de {remota.criado_em}).", remota)
        versao = _enviar(armazenamento, estado, base, diretorio_estado, agora)
        return ResultadoSincronizacao(ACAO_ENVIADO, "Alterações enviadas ao Drive.", versao)

    # o Drive tem uma versão que este dispositivo ainda não sincronizou
    if local and _remota_identica_ao_local(armazenamento, remota, base):
        estado.ultima_versao_id, estado.ultimo_hash = remota.id, local
        estado.ultima_sincronizacao_em = agora.isoformat(timespec="seconds")
        salvar_estado(estado, diretorio_estado)
        return ResultadoSincronizacao(ACAO_EM_DIA, "Dados idênticos aos do Drive; sincronizado.", remota)
    if not mudou_aqui or not local:
        return _trazer(armazenamento, remota, estado, base, diretorio_estado, agora)
    return ResultadoSincronizacao(
        ACAO_CONFLITO,
        f"O Drive tem uma versão mais nova ({remota.criado_em}, dispositivo {remota.dispositivo}) e este dispositivo também "
        "foi alterado. Nada foi mudado: escolha trazer a do Drive (a local fica guardada) ou manter a local.",
        remota,
    )


def _resolver_conflito(
    escolha: str,
    armazenamento: Armazenamento,
    base: Path = BASE_PADRAO,
    diretorio_estado: Path = DIRETORIO_ESTADO,
    agora: datetime | None = None,
) -> ResultadoSincronizacao:
    """`"trazer"`: aplica a versão mais nova do Drive (o que for substituído fica em `data/_backup_restauracao/`).
    `"manter"`: envia a local como a versão mais nova. Qualquer outra escolha levanta `ValueError`."""

    if escolha not in ("trazer", "manter"):
        raise ValueError(f"Escolha desconhecida: {escolha!r}")
    base, agora = Path(base), agora or _agora()
    estado = carregar_estado(diretorio_estado)
    if escolha == "manter":
        versao = _enviar(armazenamento, estado, base, diretorio_estado, agora)
        return ResultadoSincronizacao(ACAO_ENVIADO, "Versão local mantida e enviada como a mais nova.", versao)
    remota = _mais_nova(armazenamento.listar())
    if remota is None:
        raise ErroSincronizacao("O Drive não tem nenhuma versão para trazer.")
    return _trazer(armazenamento, remota, estado, base, diretorio_estado, agora)


def sincronizar(
    armazenamento: Armazenamento,
    base: Path = BASE_PADRAO,
    diretorio_estado: Path = DIRETORIO_ESTADO,
    agora: datetime | None = None,
) -> ResultadoSincronizacao:
    """Um ciclo de sincronização (ver a docstring do módulo), um por vez no processo. Levanta `ErroSincronizacao` em falha
    de rede/estado, sem alterar dados."""

    with _TRAVA:
        return _sincronizar(armazenamento, base, diretorio_estado, agora)


def resolver_conflito(
    escolha: str,
    armazenamento: Armazenamento,
    base: Path = BASE_PADRAO,
    diretorio_estado: Path = DIRETORIO_ESTADO,
    agora: datetime | None = None,
) -> ResultadoSincronizacao:
    """`"trazer"`: aplica a versão mais nova do Drive (o que for substituído fica em `data/_backup_restauracao/`).
    `"manter"`: envia a local como a versão mais nova. Outra escolha levanta `ValueError`. Um por vez no processo."""

    with _TRAVA:
        return _resolver_conflito(escolha, armazenamento, base, diretorio_estado, agora)


# --------------------------------------------------------------------------------------------- ciclo da sessão
def executar_ciclo_na_sessao(
    sessao: MutableMapping,
    criar_armazenamento,
    base: Path = BASE_PADRAO,
    diretorio_estado: Path = DIRETORIO_ESTADO,
    relogio=time.monotonic,
) -> ResultadoSincronizacao | None:
    """Ciclo automático chamado a cada execução do app: o primeiro da sessão roda sempre; os demais, no máximo a cada
    `INTERVALO_CICLO`. `criar_armazenamento()` devolve o armazenamento ou `None` (não conectado: não faz nada). O
    resultado fica em `sessao["sinc_resultado"]`; erros viram `ACAO_ERRO` (o app segue). O conflito é recalculado a cada
    ciclo (idempotente) e continua visível até o usuário resolvê-lo."""

    if os.environ.get(VARIAVEL_AMBIENTE, "").strip().lower() == "desligado":
        return None
    agora_relogio = relogio()
    ultimo = sessao.get("sinc_ultimo_ciclo")
    if ultimo is not None and agora_relogio - ultimo < INTERVALO_CICLO:
        return sessao.get("sinc_resultado")
    sessao["sinc_ultimo_ciclo"] = agora_relogio
    try:
        if not carregar_estado(diretorio_estado).automatica:
            return sessao.get("sinc_resultado")
        armazenamento = criar_armazenamento()
        if armazenamento is None:
            sessao.pop("sinc_resultado", None)
            return None
        resultado = sincronizar(armazenamento, base, diretorio_estado)
    except ErroSincronizacao as erro:
        resultado = ResultadoSincronizacao(ACAO_ERRO, str(erro))
    except Exception as erro:  # noqa: BLE001 — a sincronização nunca pode derrubar o app; a página mostra a mensagem
        resultado = ResultadoSincronizacao(ACAO_ERRO, f"Falha inesperada na sincronização: {type(erro).__name__}: {erro}")
    sessao["sinc_resultado"] = resultado
    return resultado


# --------------------------------------------------------------------------------------------- Google Drive
NOME_PASTA_DRIVE = "UFRPE BudgetLab - Sincronizacao"
ESCOPOS_DRIVE = ["https://www.googleapis.com/auth/drive.file"]
ARQUIVO_TOKEN_DRIVE = "token_drive.json"
TEMPO_LIMITE_REDE = 15


def _modulo_google():
    from src import google_agenda

    return google_agenda


def _caminho_token_drive(diretorio_token: Path | None = None) -> Path:
    return Path(diretorio_token or DIRETORIO_TOKEN) / ARQUIVO_TOKEN_DRIVE


def situacao_conexao_drive(
    diretorio_credenciais: Path | None = None, diretorio_token: Path | None = None,
) -> str:
    """`"sem_credenciais"` (falta o `credentials.json`, o mesmo da Agenda), `"desconectado"` ou `"conectado"`. Sem rede."""

    agenda = _modulo_google()
    pasta = Path(diretorio_credenciais or agenda.DIRETORIO_PADRAO)
    if not (pasta / agenda.ARQUIVO_CREDENCIAIS).exists():
        return "sem_credenciais"
    caminho = _caminho_token_drive(diretorio_token)
    if not caminho.exists():
        return "desconectado"
    try:
        from google.oauth2.credentials import Credentials

        credenciais = Credentials.from_authorized_user_file(str(caminho), ESCOPOS_DRIVE)
    except (ValueError, OSError):
        return "desconectado"
    return "conectado" if (credenciais.valid or credenciais.refresh_token) else "desconectado"


def conectar_drive(
    diretorio_credenciais: Path | None = None, diretorio_token: Path | None = None,
) -> None:
    """Abre o navegador para autorizar o acesso (só aos arquivos que o próprio app criar) e grava `token_drive.json` fora
    de `data/`. Falha do fluxo vira `ErroSincronizacao`; nenhum token é gravado."""

    from google_auth_oauthlib.flow import InstalledAppFlow

    agenda = _modulo_google()
    credenciais_json = Path(diretorio_credenciais or agenda.DIRETORIO_PADRAO) / agenda.ARQUIVO_CREDENCIAIS
    if not credenciais_json.exists():
        raise ErroSincronizacao(f"Arquivo {credenciais_json} não encontrado — o mesmo `credentials.json` da Agenda (docs/google_agenda.md).")
    try:
        fluxo = InstalledAppFlow.from_client_secrets_file(str(credenciais_json), ESCOPOS_DRIVE)
        credenciais = fluxo.run_local_server(port=0, timeout_seconds=agenda.TEMPO_LIMITE_AUTORIZACAO)
    except Exception as erro:  # noqa: BLE001 — as exceções do oauthlib/wsgiref não têm base comum
        raise ErroSincronizacao(
            f"Autorização do Google Drive não concluída (acesso negado, janela fechada ou tempo esgotado). Detalhe: {erro}"
        ) from erro
    agenda._gravar_atomico(_caminho_token_drive(diretorio_token), credenciais.to_json())


def desconectar_drive(diretorio_token: Path | None = None, revogar: bool = True) -> bool:
    """Apaga o token local (sempre) e revoga o acesso no Google (se `revogar`). `False` = havia token e a revogação não foi
    confirmada (sem internet): a página orienta a revogar manualmente."""

    agenda = _modulo_google()
    caminho = _caminho_token_drive(diretorio_token)
    revogado = True
    if revogar and caminho.exists():
        try:
            dado = json.loads(caminho.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            dado = {}
        token = dado.get("refresh_token") or dado.get("token")
        revogado = agenda._revogar(token) if token else True
    caminho.unlink(missing_ok=True)
    return revogado


class ArmazenamentoDrive:
    """`Armazenamento` no Google Drive: pasta `NOME_PASTA_DRIVE` criada pelo app (escopo `drive.file`: o app só enxerga o
    que ele mesmo criou, e dispositivos com o MESMO `credentials.json` enxergam os mesmos arquivos)."""

    def __init__(self, servico) -> None:
        self._servico = servico
        self._pasta_id: str | None = None

    def _chamar(self, requisicao):
        import httplib2
        from google.auth.exceptions import GoogleAuthError
        from googleapiclient.errors import HttpError

        try:
            return requisicao.execute()
        except HttpError as erro:
            motivo = getattr(erro, "reason", "") or ""
            raise ErroSincronizacao(
                f"Erro na API do Google Drive (HTTP {erro.resp.status}{': ' + motivo if motivo else ''})."
            ) from erro
        except (OSError, httplib2.HttpLib2Error, GoogleAuthError) as erro:
            raise ErroSincronizacao(f"Sem conexão com o Google Drive: {erro}") from erro

    def _pasta(self) -> str:
        if self._pasta_id:
            return self._pasta_id
        consulta = (
            f"name = '{NOME_PASTA_DRIVE}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        achadas = self._chamar(self._servico.files().list(q=consulta, fields="files(id,name)", pageSize=10)).get("files", [])
        if achadas:
            self._pasta_id = achadas[0]["id"]
        else:
            corpo = {"name": NOME_PASTA_DRIVE, "mimeType": "application/vnd.google-apps.folder"}
            self._pasta_id = self._chamar(self._servico.files().create(body=corpo, fields="id"))["id"]
        return self._pasta_id

    def listar(self) -> list[VersaoRemota]:
        pasta = self._pasta()
        consulta = f"'{pasta}' in parents and trashed = false and name contains '{PREFIXO_NOME}'"
        versoes: list[VersaoRemota] = []
        token = None
        while True:
            resposta = self._chamar(
                self._servico.files().list(q=consulta, fields="nextPageToken,files(id,name)", pageSize=100, pageToken=token)
            )
            versoes += [
                VersaoRemota(f["id"], f["name"]) for f in resposta.get("files", [])
                if f["name"].startswith(PREFIXO_NOME) and f["name"].endswith(".zip")
            ]
            token = resposta.get("nextPageToken")
            if not token:
                return versoes

    def enviar(self, nome: str, conteudo: bytes) -> str:
        from googleapiclient.http import MediaIoBaseUpload

        midia = MediaIoBaseUpload(io.BytesIO(conteudo), mimetype="application/zip", resumable=False)
        corpo = {"name": nome, "parents": [self._pasta()]}
        return self._chamar(self._servico.files().create(body=corpo, media_body=midia, fields="id"))["id"]

    def baixar(self, id_versao: str) -> bytes:
        return bytes(self._chamar(self._servico.files().get_media(fileId=id_versao)))

    def apagar(self, id_versao: str) -> None:
        self._chamar(self._servico.files().delete(fileId=id_versao))


def criar_armazenamento_drive(diretorio_token: Path | None = None) -> ArmazenamentoDrive | None:
    """Armazenamento pronto, renovando o token se preciso; `None` se não está conectado. Token revogado: apaga-o e levanta
    `ErroSincronizacao` pedindo nova conexão. Sem internet na renovação: `ErroSincronizacao` (o token continua válido)."""

    caminho = _caminho_token_drive(diretorio_token)
    if not caminho.exists():  # não conectado: sem importar as bibliotecas do Google
        return None
    import google_auth_httplib2
    import httplib2
    from google.auth.exceptions import RefreshError, TransportError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    agenda = _modulo_google()
    try:
        credenciais = Credentials.from_authorized_user_file(str(caminho), ESCOPOS_DRIVE)
    except (ValueError, OSError):
        return None
    if not credenciais.valid:
        if not credenciais.refresh_token:
            raise ErroSincronizacao("Autorização do Google Drive expirada — conecte novamente.")
        try:
            credenciais.refresh(Request())
        except RefreshError as erro:
            caminho.unlink(missing_ok=True)
            raise ErroSincronizacao("Autorização do Google Drive revogada ou expirada — conecte novamente.") from erro
        except TransportError as erro:
            raise ErroSincronizacao(f"Sem conexão com o Google Drive: {erro}") from erro
        agenda._gravar_atomico(caminho, credenciais.to_json())
    http = google_auth_httplib2.AuthorizedHttp(credenciais, http=httplib2.Http(timeout=TEMPO_LIMITE_REDE))
    return ArmazenamentoDrive(build("drive", "v3", http=http, cache_discovery=False))
