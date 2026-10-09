"""Backup e restauração dos dados locais (`data/`) — um único `.zip` com manifesto de integridade.

Por que existe: `data/raw/`, os cadastros nativos e os bancos SQLite não são versionados no git
(dado real de produção, ver `.gitignore`), então levar o sistema para outra máquina exigia copiar
pastas à mão, sem verificação. Aqui o backup é produzido e recebido pelo próprio app.

Regras (todas cobertas por `tests/test_backup_dados.py`):

  * Nada é alterado na origem: exportar só LÊ `data/`. Os bancos SQLite são copiados pela API de
    backup do próprio SQLite (consistente mesmo com o app aberto), para um arquivo temporário.
  * Cada arquivo entra no `MANIFESTO_BACKUP.json` com tamanho e SHA-256 — rastreabilidade e
    possibilidade de reconciliar a restauração com a origem.
  * Senha opcional: com `senha`, o `.zip` inteiro é cifrado com AES-256-GCM (chave derivada da senha
    por scrypt) num envelope próprio — conteúdo, nomes de arquivo e manifesto ficam ilegíveis, e
    senha errada ou arquivo adulterado são recusados antes de qualquer leitura ou gravação.
  * Segredos: o `token.json` do Google Agenda vive fora de `data/` (ver `src/google_agenda.py`) e
    NUNCA entra; um `token.json` achado dentro de `data/` também é descartado. O
    `credentials.json` (cliente OAuth) só entra com opção explícita. `.env` e
    `.streamlit/secrets.toml` estão fora de `data/` e não são tocados.
  * Restaurar valida tudo ANTES de gravar: pacote que não seja zip, sem manifesto, com caminho
    fora da lista de pastas conhecidas, com `..`/caminho absoluto, com arquivo ausente, extra ou
    de hash/tamanho divergente é recusado inteiro, sem gravar nada.
  * Nunca sobrescreve em silêncio: arquivo existente e diferente só é substituído se o chamador
    pedir (`substituir=True`), e a cópia atual é preservada em `data/_backup_restauracao/`.
    A gravação é tudo-ou-nada: se qualquer arquivo falhar, o que já foi gravado é desfeito.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

BASE_PADRAO = Path("data")
FORMATO_VERSAO = 1
NOME_MANIFESTO = "MANIFESTO_BACKUP.json"
PASTA_COPIAS_RESTAURACAO = "_backup_restauracao"

#: pastas de `data/` cobertas pelo backup (nome da pasta -> rótulo). `processed/` e `referencia/`
#: ficam de fora: a primeira é derivada e a segunda é versionada no git.
GRUPOS: dict[str, str] = {
    "raw": "Planilhas originais importadas (inclui as versões substituídas)",
    "manifestos": "Manifestos das importações versionadas",
    "demandas": "Demandas orçamentárias (formato antigo)",
    "captacao": "Captação de demandas (banco SQLite)",
    "emendas": "Emendas parlamentares",
    "prazos_orcamentarios": "Prazos orçamentários",
    "bolsas_auxilios": "Cadastro de Bolsas e Auxílios",
    "contratos_continuos": "Cadastro de Contratos Contínuos",
    "teds": "TEDs (banco SQLite e uploads)",
    "limite_empenho": "Fração liberada e remanejamentos do Limite de Empenho",
    "glossario": "Verbetes do Glossário",
    "dou": "Termos de busca do Diário Oficial",
    "google_agenda": "Google Agenda (histórico de sincronização; credenciais só se pedido)",
}

#: nomes que nunca entram no backup, em qualquer pasta (token de acesso à agenda).
_NOMES_NUNCA = {"token.json"}
#: segredo que só entra com opção explícita (cliente OAuth do Google).
ARQUIVO_CREDENCIAIS = "google_agenda/credentials.json"
_SUFIXOS_SQLITE = (".db", ".sqlite", ".sqlite3")
_SUFIXOS_IGNORADOS = (".tmp", "-wal", "-shm", "-journal")


#: envelope de criptografia: MAGIC | salt (16) | nonce (12) | AES-256-GCM(zip). O cabeçalho
#: (magic + salt + nonce) é autenticado como dado associado. Parâmetros do scrypt fixos pela versão.
_MAGIC_CRIPTO = b"BLABKP01"
_TAM_SALT, _TAM_NONCE = 16, 12
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1
TAMANHO_MINIMO_SENHA = 8


class ErroBackup(Exception):
    """Backup inválido ou operação impossível; a mensagem é mostrada ao usuário."""


@dataclass(frozen=True)
class ItemBackup:
    caminho: str  # relativo a `data/`, com "/" (ex.: "raw/planilha.xlsx")
    tamanho: int
    sha256: str
    situacao: str = ""  # "novo" | "identico" | "diferente" (só após `analisar_backup`)


@dataclass(frozen=True)
class PreviaBackup:
    criado_em: str
    credenciais_incluidas: bool
    itens: tuple[ItemBackup, ...]

    def com_situacao(self, situacao: str) -> list[ItemBackup]:
        return [i for i in self.itens if i.situacao == situacao]


@dataclass
class ResultadoRestauracao:
    novos: list[str] = field(default_factory=list)
    substituidos: list[str] = field(default_factory=list)
    mantidos_diferentes: list[str] = field(default_factory=list)
    identicos: list[str] = field(default_factory=list)
    pasta_copias: Path | None = None


def esta_criptografado(conteudo: bytes) -> bool:
    return conteudo.startswith(_MAGIC_CRIPTO)


def _derivar_chave(senha: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P).derive(
        senha.encode("utf-8")
    )


def _criptografar(conteudo: bytes, senha: str) -> bytes:
    if len(senha) < TAMANHO_MINIMO_SENHA:
        raise ErroBackup(f"A senha precisa ter ao menos {TAMANHO_MINIMO_SENHA} caracteres.")
    salt, nonce = os.urandom(_TAM_SALT), os.urandom(_TAM_NONCE)
    cabecalho = _MAGIC_CRIPTO + salt + nonce
    cifrado = AESGCM(_derivar_chave(senha, salt)).encrypt(nonce, conteudo, cabecalho)
    return cabecalho + cifrado


def _descriptografar(conteudo: bytes, senha: str | None) -> bytes:
    if not senha:
        raise ErroBackup("Este backup está protegido por senha: informe a senha.")
    tam_cabecalho = len(_MAGIC_CRIPTO) + _TAM_SALT + _TAM_NONCE
    if len(conteudo) <= tam_cabecalho:
        raise ErroBackup("Backup criptografado truncado ou inválido.")
    cabecalho = conteudo[:tam_cabecalho]
    salt = cabecalho[len(_MAGIC_CRIPTO) : len(_MAGIC_CRIPTO) + _TAM_SALT]
    nonce = cabecalho[len(_MAGIC_CRIPTO) + _TAM_SALT :]
    try:
        return AESGCM(_derivar_chave(senha, salt)).decrypt(nonce, conteudo[tam_cabecalho:], cabecalho)
    except InvalidTag as exc:
        raise ErroBackup("Senha incorreta ou arquivo de backup adulterado.") from exc


def _sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def _eh_sqlite(caminho: Path) -> bool:
    return caminho.suffix.lower() in _SUFIXOS_SQLITE


def _ignorado(caminho: Path) -> bool:
    nome = caminho.name
    return (
        nome == ".gitkeep"
        or nome.startswith("~$")  # lock do Excel
        or (nome.startswith(".") and nome.endswith(".tmp"))  # gravação atômica em andamento
        or nome.endswith(_SUFIXOS_IGNORADOS)
        or nome in _NOMES_NUNCA
    )


def _listar_arquivos(base: Path, grupos: list[str], incluir_credenciais: bool) -> list[Path]:
    arquivos: list[Path] = []
    for grupo in grupos:
        pasta = base / grupo
        if not pasta.is_dir():
            continue
        for caminho in sorted(p for p in pasta.rglob("*") if p.is_file()):
            if _ignorado(caminho):
                continue
            relativo = caminho.relative_to(base).as_posix()
            if relativo == ARQUIVO_CREDENCIAIS and not incluir_credenciais:
                continue
            arquivos.append(caminho)
    return arquivos


def _copia_consistente_sqlite(origem: Path, destino: Path) -> None:
    """Copia o banco pela API de backup do SQLite (somente leitura na origem)."""

    leitura = sqlite3.connect(f"file:{origem.as_posix()}?mode=ro", uri=True)
    try:
        saida = sqlite3.connect(destino)
        try:
            leitura.backup(saida)
        finally:
            saida.close()
    finally:
        leitura.close()


def gerar_backup(
    base: str | Path | None = None,
    grupos: list[str] | None = None,
    incluir_credenciais: bool = False,
    agora: datetime | None = None,
    senha: str | None = None,
) -> bytes:
    """Conteúdo do backup (`.zip`, ou o envelope cifrado se `senha`). Só lê `base`."""

    base = Path(base if base is not None else BASE_PADRAO)
    grupos = list(GRUPOS) if grupos is None else grupos
    desconhecidos = [g for g in grupos if g not in GRUPOS]
    if desconhecidos:
        raise ErroBackup(f"Pasta(s) desconhecida(s) para backup: {', '.join(desconhecidos)}.")
    agora = agora or datetime.now()

    itens: list[dict] = []
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory() as temporario, zipfile.ZipFile(
        buffer, "w", zipfile.ZIP_DEFLATED
    ) as zf:
        for caminho in _listar_arquivos(base, grupos, incluir_credenciais):
            relativo = caminho.relative_to(base).as_posix()
            fonte = caminho
            if _eh_sqlite(caminho):
                fonte = Path(temporario) / uuid.uuid4().hex
                _copia_consistente_sqlite(caminho, fonte)
            zf.write(fonte, relativo)
            itens.append(
                {
                    "caminho": relativo,
                    "tamanho": fonte.stat().st_size,
                    "sha256": _sha256_arquivo(fonte),
                }
            )
        manifesto = {
            "formato_versao": FORMATO_VERSAO,
            "criado_em": agora.isoformat(timespec="seconds"),
            "grupos": grupos,
            "credenciais_incluidas": bool(incluir_credenciais),
            "arquivos": itens,
        }
        zf.writestr(NOME_MANIFESTO, json.dumps(manifesto, ensure_ascii=False, indent=2))
    pacote = buffer.getvalue()
    return _criptografar(pacote, senha) if senha else pacote


def _caminho_seguro(caminho: object) -> str:
    """Valida um caminho do manifesto; devolve-o ou levanta `ErroBackup`."""

    if not isinstance(caminho, str) or not caminho:
        raise ErroBackup("Manifesto com caminho de arquivo inválido.")
    partes = PurePosixPath(caminho).parts
    if (
        "\\" in caminho
        or ":" in caminho
        or caminho.startswith("/")
        or any(p in ("", ".", "..") for p in partes)
        or len(partes) < 2
        or "/".join(partes) != caminho  # "raw//a" e afins: forma não canônica
    ):
        raise ErroBackup(f"Caminho recusado no backup (fora de `data/`): {caminho!r}.")
    if partes[0] not in GRUPOS:
        raise ErroBackup(f"Caminho recusado no backup (pasta desconhecida): {caminho!r}.")
    if partes[-1] in _NOMES_NUNCA:
        raise ErroBackup(f"Arquivo recusado no backup (segredo): {caminho!r}.")
    return caminho


def _abrir_zip(conteudo: bytes, senha: str | None = None) -> zipfile.ZipFile:
    if esta_criptografado(conteudo):
        conteudo = _descriptografar(conteudo, senha)
    try:
        return zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile as exc:
        raise ErroBackup("O arquivo enviado não é um .zip válido.") from exc


def _ler_manifesto(zf: zipfile.ZipFile) -> tuple[dict, list[ItemBackup]]:
    try:
        manifesto = json.loads(zf.read(NOME_MANIFESTO).decode("utf-8"))
    except KeyError as exc:
        raise ErroBackup(f"O .zip não contém o {NOME_MANIFESTO}: não é um backup do BudgetLab.") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise ErroBackup(f"{NOME_MANIFESTO} ilegível.") from exc
    if not isinstance(manifesto, dict) or manifesto.get("formato_versao") != FORMATO_VERSAO:
        raise ErroBackup("Versão do formato de backup não suportada.")
    brutos = manifesto.get("arquivos")
    if not isinstance(brutos, list):
        raise ErroBackup(f"{NOME_MANIFESTO} sem a lista de arquivos.")

    itens: list[ItemBackup] = []
    vistos: set[str] = set()
    for bruto in brutos:
        if not isinstance(bruto, dict):
            raise ErroBackup(f"{NOME_MANIFESTO} com entrada inválida.")
        caminho = _caminho_seguro(bruto.get("caminho"))
        tamanho, sha = bruto.get("tamanho"), bruto.get("sha256")
        if not isinstance(tamanho, int) or isinstance(tamanho, bool) or tamanho < 0 or not isinstance(sha, str):
            raise ErroBackup(f"Entrada inválida no manifesto: {caminho!r}.")
        if caminho in vistos:
            raise ErroBackup(f"Caminho duplicado no manifesto: {caminho!r}.")
        vistos.add(caminho)
        itens.append(ItemBackup(caminho, tamanho, sha))

    membros = {i.filename for i in zf.infolist() if not i.is_dir()} - {NOME_MANIFESTO}
    if membros != vistos:
        extras = sorted(membros - vistos)
        faltando = sorted(vistos - membros)
        raise ErroBackup(
            "O conteúdo do .zip não confere com o manifesto"
            + (f" (fora do manifesto: {extras[:3]})" if extras else "")
            + (f" (ausentes: {faltando[:3]})" if faltando else "")
            + "."
        )
    return manifesto, itens


def _extrair_verificando(zf: zipfile.ZipFile, item: ItemBackup, destino: Path | None) -> None:
    """Lê o membro em blocos, confere tamanho e hash e, se `destino`, grava nele."""

    h = hashlib.sha256()
    total = 0
    saida = destino.open("wb") if destino is not None else None
    try:
        with zf.open(item.caminho) as f:
            for bloco in iter(lambda: f.read(1024 * 1024), b""):
                total += len(bloco)
                if total > item.tamanho:  # protege contra zip que declara menos do que contém
                    break
                h.update(bloco)
                if saida is not None:
                    saida.write(bloco)
    finally:
        if saida is not None:
            saida.close()
    if total != item.tamanho or h.hexdigest() != item.sha256:
        raise ErroBackup(f"Arquivo corrompido ou adulterado no backup: {item.caminho!r}.")


def _situacao(base: Path, item: ItemBackup) -> str:
    atual = base / item.caminho
    if not atual.is_file():
        return "novo"
    return "identico" if _sha256_arquivo(atual) == item.sha256 else "diferente"


def analisar_backup(
    conteudo: bytes, base: str | Path | None = None, senha: str | None = None
) -> PreviaBackup:
    """Valida o pacote inteiro (estrutura, tamanhos e hashes) e compara com `base`.

    Não grava nada. Qualquer problema levanta `ErroBackup`.
    """

    base = Path(base if base is not None else BASE_PADRAO)
    with _abrir_zip(conteudo, senha) as zf:
        manifesto, itens = _ler_manifesto(zf)
        for item in itens:
            _extrair_verificando(zf, item, None)
    return PreviaBackup(
        criado_em=str(manifesto.get("criado_em", "")),
        credenciais_incluidas=bool(manifesto.get("credenciais_incluidas", False)),
        itens=tuple(
            ItemBackup(i.caminho, i.tamanho, i.sha256, _situacao(base, i)) for i in itens
        ),
    )


def restaurar_backup(
    conteudo: bytes,
    base: str | Path | None = None,
    substituir: bool = False,
    agora: datetime | None = None,
    senha: str | None = None,
) -> ResultadoRestauracao:
    """Restaura o backup em `base`, tudo-ou-nada.

    Arquivos novos sempre são gravados. Arquivos existentes e diferentes só são substituídos com
    `substituir=True` — e a cópia atual vai para `base/_backup_restauracao/<carimbo>/`. Idênticos
    não são tocados.
    """

    base = Path(base if base is not None else BASE_PADRAO)
    base.mkdir(parents=True, exist_ok=True)
    agora = agora or datetime.now()
    raiz = base.resolve()

    with _abrir_zip(conteudo, senha) as zf:
        _, itens = _ler_manifesto(zf)
        resultado = ResultadoRestauracao()
        a_gravar: list[ItemBackup] = []
        for item in itens:
            destino = (base / item.caminho).resolve()
            if raiz not in destino.parents:
                raise ErroBackup(f"Caminho recusado no backup (fora de `data/`): {item.caminho!r}.")
            situacao = _situacao(base, item)
            if situacao == "identico":
                resultado.identicos.append(item.caminho)
            elif situacao == "diferente" and not substituir:
                resultado.mantidos_diferentes.append(item.caminho)
            else:
                a_gravar.append(item)

        staging = base / f".restauracao-{uuid.uuid4().hex}"
        acoes: list[tuple[Path, Path | None]] = []
        try:
            # fase 1: extrai e confere TUDO em área temporária, antes de tocar em `data/`
            for item in a_gravar:
                provisorio = staging / item.caminho
                provisorio.parent.mkdir(parents=True, exist_ok=True)
                _extrair_verificando(zf, item, provisorio)

            # fase 2: grava; qualquer falha desfaz o que já foi gravado
            pasta_copias = base / PASTA_COPIAS_RESTAURACAO / agora.strftime("%Y-%m-%d-%Hh%Mm%Ss")
            try:
                for item in a_gravar:
                    destino = base / item.caminho
                    copia: Path | None = None
                    if destino.exists():
                        copia = pasta_copias / item.caminho
                        copia.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(destino, copia)
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staging / item.caminho, destino)
                    acoes.append((destino, copia))
                    (resultado.substituidos if copia else resultado.novos).append(item.caminho)
            except BaseException:
                for destino, copia in reversed(acoes):
                    if copia is not None:
                        shutil.copy2(copia, destino)
                    else:
                        destino.unlink(missing_ok=True)
                raise
            if resultado.substituidos:
                resultado.pasta_copias = pasta_copias
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return resultado
