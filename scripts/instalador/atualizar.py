"""Atualização opcional do UFRPE BudgetLab instalado, pelo GitHub (repositório público).

Regras (ver docs/superpowers/specs/2026-10-19-instalador-windows-design.md):
- tudo ou nada: o código novo só entra se as dependências novas (quando mudaram)
  foram instaladas; `versao.txt` é gravado por último;
- nunca toca em `data/` (em `app\\`, `data` é junção para `dados\\`): o zip é
  filtrado e a remoção de arquivos que sumiram é feita arquivo a arquivo, sem
  remoção recursiva;
- qualquer falha (rede, GitHub, zip inválido, disco) só devolve "falhou".
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPO = "joaovsbarbosacoder/ufrpe-budgetlab"
RAMO = "master"
_VERSAO_VAZIA = {"commit": "", "requirements_sha256": "", "arquivos": []}


class ErroAtualizacao(Exception):
    """Falha esperada da atualização (rede, zip inválido, entrada insegura)."""


def ler_versao(app: Path) -> dict:
    try:
        dados = json.loads((app / "versao.txt").read_text(encoding="utf-8-sig"))
        return {**_VERSAO_VAZIA, **dados}
    except (OSError, ValueError, TypeError):
        return dict(_VERSAO_VAZIA)


def sha_remoto(abrir=urllib.request.urlopen, timeout: float = 5) -> str:
    pedido = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/commits/{RAMO}",
        headers={"Accept": "application/vnd.github.sha", "User-Agent": "UFRPE-BudgetLab"},
    )
    try:
        with abrir(pedido, timeout=timeout) as resposta:
            return resposta.read().decode("ascii").strip()
    except (OSError, ValueError) as erro:
        raise ErroAtualizacao(f"não foi possível consultar o GitHub: {erro}") from erro


def baixar_zip(destino: Path, abrir=urllib.request.urlopen, timeout: float = 30) -> None:
    url = f"https://github.com/{REPO}/archive/refs/heads/{RAMO}.zip"
    pedido = urllib.request.Request(url, headers={"User-Agent": "UFRPE-BudgetLab"})
    try:
        with abrir(pedido, timeout=timeout) as resposta, open(destino, "wb") as saida:
            shutil.copyfileobj(resposta, saida)
    except (OSError, ValueError) as erro:
        raise ErroAtualizacao(f"não foi possível baixar a atualização: {erro}") from erro


def rodar_pip(python: Path, requirements: Path) -> bool:
    resultado = subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check",
         "-r", str(requirements)],
        check=False,
    )
    return resultado.returncode == 0


def extrair_zip(zip_path: Path, destino: Path) -> list[str]:
    """Extrai o zip do GitHub em `destino`, sem o diretório raiz e sem `data/`."""
    destino = destino.resolve()
    extraidos: list[str] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                partes = PurePosixPath(info.filename).parts
                if info.is_dir() or len(partes) < 2:
                    continue
                relativo = PurePosixPath(*partes[1:])
                if relativo.is_absolute() or ".." in relativo.parts or ":" in relativo.parts[0]:
                    raise ErroAtualizacao(f"entrada insegura no zip: {info.filename}")
                if relativo.parts[0] == "data":
                    continue
                alvo = (destino / Path(*relativo.parts)).resolve()
                if destino not in alvo.parents:
                    raise ErroAtualizacao(f"entrada insegura no zip: {info.filename}")
                alvo.parent.mkdir(parents=True, exist_ok=True)
                alvo.write_bytes(zf.read(info))
                extraidos.append(relativo.as_posix())
    except zipfile.BadZipFile as erro:
        raise ErroAtualizacao("arquivo de atualização inválido") from erro
    return extraidos


def aplicar(staging: Path, app: Path, versao_antiga: dict) -> list[str]:
    """Copia arquivo a arquivo e remove só o código que sumiu (nunca `data/`)."""
    novos = sorted(p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file())
    for relativo in novos:
        destino = app / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staging / relativo, destino)
    for relativo in set(versao_antiga.get("arquivos", [])) - set(novos):
        if PurePosixPath(relativo).parts[0] == "data":
            continue
        antigo = app / relativo
        if antigo.is_file():
            antigo.unlink()
            pai = antigo.parent
            while pai != app:
                try:
                    pai.rmdir()  # só remove se estiver vazia
                except OSError:
                    break
                pai = pai.parent
    return novos


def _sha256(arquivo: Path) -> str:
    return hashlib.sha256(arquivo.read_bytes()).hexdigest() if arquivo.is_file() else ""


PAUSA_ENTRE_TENTATIVAS_S = 3
TENTATIVAS = 2
# Motivo da última falha ("" se a última chamada de `atualizar` não falhou); o inicializador
# o grava no log, para saber por que uma atualização não chegou.
ultimo_motivo = ""


def _uma_tentativa(app: Path, python: Path, sha, baixar, pip, aplicar_fn) -> str:
    """Uma tentativa completa. Levanta ErroAtualizacao/OSError/ValueError se falhar."""
    versao = ler_versao(app)
    novo_sha = sha()
    if novo_sha == versao["commit"]:
        return "sem_novidade"
    with tempfile.TemporaryDirectory(prefix="budgetlab_upd_") as tmp:
        tmp = Path(tmp)
        zip_path = tmp / "novo.zip"
        baixar(zip_path)
        staging = tmp / "staging"
        staging.mkdir()
        extrair_zip(zip_path, staging)
        requirements = staging / "requirements.txt"
        hash_novo = _sha256(requirements)
        if hash_novo and hash_novo != versao["requirements_sha256"]:
            if not pip(python, requirements):
                raise ErroAtualizacao("falha ao instalar as dependências (pip)")
        novos = aplicar_fn(staging, app, versao)
    (app / "versao.txt").write_text(
        json.dumps({"commit": novo_sha,
                    "requirements_sha256": hash_novo or versao["requirements_sha256"],
                    "arquivos": novos}),
        encoding="utf-8",
    )
    return "atualizado"


def atualizar(app: Path, python: Path, *, sha=sha_remoto, baixar=baixar_zip,
              pip=rodar_pip, esperar=None, _aplicar=aplicar) -> str:
    """Devolve "sem_novidade", "atualizado" ou "falhou". Nunca levanta.

    Em caso de falha tenta mais uma vez, depois de uma pausa (rede que oscila); o motivo da
    última falha fica em `ultimo_motivo`.
    """
    global ultimo_motivo
    ultimo_motivo = ""
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            resultado = _uma_tentativa(app, python, sha, baixar, pip, _aplicar)
            ultimo_motivo = ""
            return resultado
        except (ErroAtualizacao, OSError, ValueError) as erro:
            ultimo_motivo = str(erro) if isinstance(erro, ErroAtualizacao)                 else f"{type(erro).__name__}: {erro}"
            if tentativa < TENTATIVAS:
                (esperar or time.sleep)(PAUSA_ENTRE_TENTATIVAS_S)
    return "falhou"
