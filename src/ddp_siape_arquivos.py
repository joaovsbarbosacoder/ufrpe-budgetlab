"""Armazenamento versionado das DDPs e Créditos Bancários do SIAPE (27/10/2026).

Autorizado pelo usuário em 27/10/2026 (AGENTS.md exige aprovação explícita para persistência):
os PDFs enviados na aba "Folha (DDP)" ficam guardados e valem depois de fechar o app. Segue o
padrão das demais bases (`src/importacao_versionada.py`): o arquivo original é copiado SEM
alteração para `data/raw/` (fora do git), nunca é sobrescrito, e um manifesto versionado em
`data/manifestos/` diz qual é a versão atual de cada competência, com hash e data.

- PDF: `data/raw/ddp_siape/AAAAMM/<tipo>_<público>_<folha>_<sha8>.pdf`. Só DDP e Crédito
  Bancário — as consignações listam as consignatárias e não entram no cálculo.
- Manifesto de versão: `data/manifestos/ddp_siape_AAAAMM_<AAAA-MM-DD>_<versão>.json`, com a lista
  de arquivos da competência naquele momento. Ponteiro da versão atual:
  `data/manifestos/ddp_siape_AAAAMM_atual.json` (mesmo conteúdo).
- Reenviar o mesmo PDF não muda nada. Enviar um PDF diferente para o mesmo tipo/público/folha
  da competência cria uma nova versão (o PDF antigo e o manifesto antigo ficam). Enviar só uma
  parte dos PDFs da competência preserva os demais da versão atual.
- A leitura confere o hash de cada PDF com o manifesto: arquivo ausente ou alterado é erro, não
  dado silenciosamente diferente.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.ddp_siape import PUBLICO_PENSIONISTA, PUBLICO_SERVIDOR, TIPO_DDP, RelatorioSiape, ler_relatorio

DIRETORIO_DADOS_BRUTOS = Path("data/raw")
DIRETORIO_MANIFESTOS = Path("data/manifestos")
SUBDIRETORIO = "ddp_siape"
BASE = "ddp_siape"


class ArquivoGuardadoInvalido(FileNotFoundError):
    """PDF guardado ausente ou com hash diferente do manifesto."""


@dataclass
class ResultadoGuarda:
    versoes_novas: list[int]   # competências que ganharam uma versão nova
    sem_mudanca: list[int]     # competências cujos PDFs já estavam guardados, idênticos


def _brutos(diretorio) -> Path:
    return Path(diretorio) if diretorio is not None else Path(DIRETORIO_DADOS_BRUTOS)


def _manifestos(diretorio) -> Path:
    return Path(diretorio) if diretorio is not None else Path(DIRETORIO_MANIFESTOS)


def _chave(entrada: dict) -> tuple[str, str, str]:
    return (entrada["tipo"], entrada["publico"], entrada["folha"])


def _gravar_atomico(caminho: Path, conteudo: bytes) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_bytes(conteudo)
    os.replace(temporario, caminho)


def _nome_arquivo(relatorio: RelatorioSiape, sha256: str) -> str:
    folha = relatorio.folha.lower().replace(" ", "-")
    tipo = relatorio.tipo.lower()
    return f"{tipo}_{relatorio.publico.lower()}_{folha}_{sha256[:8]}.pdf"


def manifesto_atual(competencia: int, diretorio_manifestos=None) -> dict | None:
    caminho = _manifestos(diretorio_manifestos) / f"{BASE}_{competencia}_atual.json"
    if not caminho.exists():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def competencias_guardadas(diretorio_manifestos=None) -> list[int]:
    """Competências (AAAAMM) com versão atual guardada, da mais antiga à mais recente."""
    diretorio = _manifestos(diretorio_manifestos)
    if not diretorio.exists():
        return []
    competencias = []
    for caminho in diretorio.glob(f"{BASE}_*_atual.json"):
        parte = caminho.name[len(BASE) + 1:-len("_atual.json")]
        if parte.isdigit():
            competencias.append(int(parte))
    return sorted(competencias)


def competencias_com_ddp(diretorio_manifestos=None) -> set[int]:
    """Competências guardadas cuja versão atual tem ao menos uma DDP (não só Crédito Bancário)."""
    return {c for c in competencias_guardadas(diretorio_manifestos)
            if any(a["tipo"] == TIPO_DDP for a in manifesto_atual(c, diretorio_manifestos)["arquivos"])}


def chave_cache(diretorio_manifestos=None) -> tuple[tuple[int, str], ...]:
    """(competência, versão) de cada competência guardada — muda quando entra uma versão nova;
    serve de chave para o cache da página."""
    return tuple((c, manifesto_atual(c, diretorio_manifestos)["versao"]) for c in competencias_guardadas(diretorio_manifestos))


def historico(competencia: int, diretorio_manifestos=None) -> list[dict]:
    """Todas as versões já guardadas da competência, da mais antiga à mais recente."""
    diretorio = _manifestos(diretorio_manifestos)
    if not diretorio.exists():
        return []
    versoes = [json.loads(c.read_text(encoding="utf-8")) for c in diretorio.glob(f"{BASE}_{competencia}_2*.json")]
    return sorted(versoes, key=lambda v: (v["gravado_em"], v["versao"]))


def guardar(itens: list[tuple[RelatorioSiape, bytes]], diretorio_dados_brutos=None, diretorio_manifestos=None,
            agora: datetime | None = None) -> ResultadoGuarda:
    """Guarda os PDFs lidos (par `RelatorioSiape` + bytes originais). Só DDP e Crédito Bancário
    chegam aqui (`ler_relatorio` recusa os demais). Devolve o que mudou, por competência."""
    brutos, manifestos = _brutos(diretorio_dados_brutos), _manifestos(diretorio_manifestos)
    agora = agora or datetime.now(timezone.utc)
    por_competencia: dict[int, list[tuple[RelatorioSiape, bytes]]] = {}
    for relatorio, conteudo in itens:
        por_competencia.setdefault(relatorio.competencia, []).append((relatorio, conteudo))

    novas, iguais = [], []
    for competencia, enviados in sorted(por_competencia.items()):
        atual = manifesto_atual(competencia, manifestos)
        arquivos = {_chave(a): a for a in (atual["arquivos"] if atual else [])}
        mudou = False
        for relatorio, conteudo in enviados:
            sha = hashlib.sha256(conteudo).hexdigest()
            chave = (relatorio.tipo, relatorio.publico, relatorio.folha)
            if arquivos.get(chave, {}).get("sha256") == sha:
                continue
            relativo = f"{SUBDIRETORIO}/{competencia}/{_nome_arquivo(relatorio, sha)}"
            destino = brutos / relativo
            if not destino.exists():  # nunca sobrescreve; o hash no nome garante o mesmo conteúdo
                _gravar_atomico(destino, conteudo)
            arquivos[chave] = {
                "tipo": relatorio.tipo, "publico": relatorio.publico, "folha": relatorio.folha, "arquivo": relativo,
                "sha256": sha, "nome_original": relatorio.nome,
                "data_geracao": relatorio.data_geracao.isoformat() if relatorio.data_geracao else None,
            }
            mudou = True
        if not mudou:
            iguais.append(competencia)
            continue
        lista = sorted(arquivos.values(), key=lambda a: (a["tipo"], a["publico"], a["folha"]))
        versao = hashlib.sha256("|".join(a["sha256"] for a in lista).encode()).hexdigest()[:8]
        manifesto = {"base": BASE, "competencia": competencia, "versao": versao, "gravado_em": agora.isoformat(),
                     "arquivos": lista}
        conteudo_json = json.dumps(manifesto, ensure_ascii=False, indent=2).encode("utf-8")
        nome = f"{BASE}_{competencia}_{agora.strftime('%Y-%m-%d')}_{versao}.json"
        _gravar_atomico(manifestos / nome, conteudo_json)
        _gravar_atomico(manifestos / f"{BASE}_{competencia}_atual.json", conteudo_json)
        novas.append(competencia)
    return ResultadoGuarda(versoes_novas=novas, sem_mudanca=iguais)


def carregar(competencia: int, diretorio_dados_brutos=None, diretorio_manifestos=None) -> list[RelatorioSiape]:
    """Relatórios da versão atual da competência, relidos dos PDFs guardados (hash conferido)."""
    manifesto = manifesto_atual(competencia, diretorio_manifestos)
    if manifesto is None:
        return []
    brutos = _brutos(diretorio_dados_brutos)
    relatorios = []
    for entrada in manifesto["arquivos"]:
        caminho = brutos / entrada["arquivo"]
        if not caminho.exists():
            raise ArquivoGuardadoInvalido(f"PDF guardado ausente: {caminho} (manifesto {competencia}, versão {manifesto['versao']}).")
        conteudo = caminho.read_bytes()
        if hashlib.sha256(conteudo).hexdigest() != entrada["sha256"]:
            raise ArquivoGuardadoInvalido(f"PDF guardado alterado: {caminho} não confere com o hash do manifesto.")
        relatorios.append(ler_relatorio(conteudo, entrada["nome_original"]))
    return relatorios


def tem_ddp_completa(relatorios: list[RelatorioSiape]) -> bool:
    """Há DDP de servidor e de pensionista (as duas, para o painel não usar só metade da folha)."""
    publicos = {r.publico for r in relatorios if r.tipo == TIPO_DDP}
    return {PUBLICO_SERVIDOR, PUBLICO_PENSIONISTA} <= publicos


def ultima_ddp_completa(diretorio_dados_brutos=None, diretorio_manifestos=None) -> list[RelatorioSiape] | None:
    """Relatórios da competência mais recente que tem DDP de servidor e de pensionista; `None`
    se não houver nenhuma guardada. Erro de arquivo (`ArquivoGuardadoInvalido`) sobe para quem chama."""
    for competencia in reversed(competencias_guardadas(diretorio_manifestos)):
        relatorios = carregar(competencia, diretorio_dados_brutos, diretorio_manifestos)
        if tem_ddp_completa(relatorios):
            return relatorios
    return None
