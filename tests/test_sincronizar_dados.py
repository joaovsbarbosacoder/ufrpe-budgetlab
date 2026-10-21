"""Teste de `scripts/sincronizar_dados.ps1` (junções para uma pasta compartilhada), numa árvore temporária.

Só no Windows com PowerShell. Cobre: ensaio sem alterar nada, aplicar (copia, guarda a original, liga), idempotência,
segundo dispositivo vendo os mesmos dados e recusa de conflito sem tocar nos dados locais.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sincronizar_dados.ps1"
POWERSHELL = shutil.which("powershell")

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None, reason="Junções de diretório: só no Windows com PowerShell."
)


def _rodar(raiz: Path, compartilhada: Path, aplicar: bool) -> str:
    comando = [
        POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
        "-PastaCompartilhada", str(compartilhada), "-RaizProjeto", str(raiz),
    ]
    if aplicar:
        comando.append("-Aplicar")
    resultado = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    return resultado.stdout


def _juncao(caminho: Path) -> bool:
    return caminho.is_junction() if hasattr(caminho, "is_junction") else False


def _projeto(base: Path, nome: str, arquivos: dict[str, str]) -> Path:
    raiz = base / nome
    pasta = raiz / "data" / "resultado_orcamentario"
    pasta.mkdir(parents=True)
    (pasta / ".gitkeep").write_text("")
    for relativo, conteudo in arquivos.items():
        (pasta / relativo).parent.mkdir(parents=True, exist_ok=True)
        (pasta / relativo).write_text(conteudo, encoding="utf-8")
    return raiz


def test_ensaio_nao_altera_nada(tmp_path: Path):
    raiz = _projeto(tmp_path, "a", {"2026/despesas_manuais.json": "{}"})
    drive = tmp_path / "drive"
    drive.mkdir()
    saida = _rodar(raiz, drive, aplicar=False)

    assert "[ensaio]" in saida and "ENSAIO" in saida
    assert not _juncao(raiz / "data" / "resultado_orcamentario")
    assert not (drive / "ufrpe-budgetlab-dados").exists()


def test_aplicar_copia_guarda_original_liga_e_e_idempotente(tmp_path: Path):
    raiz = _projeto(tmp_path, "a", {"2026/despesas_manuais.json": '{"x": 1}'})
    drive = tmp_path / "drive"
    drive.mkdir()
    _rodar(raiz, drive, aplicar=True)

    local = raiz / "data" / "resultado_orcamentario"
    assert _juncao(local)
    assert (local / "2026" / "despesas_manuais.json").read_text(encoding="utf-8") == '{"x": 1}'
    assert (drive / "ufrpe-budgetlab-dados" / "resultado_orcamentario" / "2026" / "despesas_manuais.json").exists()
    assert (local / ".gitkeep").exists()  # o marcador versionado continua visível pela junção
    guardadas = list((raiz / "data" / "_antes_da_sincronizacao").glob("resultado_orcamentario-*"))
    assert len(guardadas) == 1 and (guardadas[0] / "2026" / "despesas_manuais.json").exists()

    assert "[ok]" in _rodar(raiz, drive, aplicar=True)


def test_segundo_dispositivo_ve_os_mesmos_dados_e_conflito_e_recusado(tmp_path: Path):
    drive = tmp_path / "drive"
    drive.mkdir()
    _rodar(_projeto(tmp_path, "a", {"celulas.json": '{"a": 1}'}), drive, aplicar=True)

    vazio = _projeto(tmp_path, "b", {})
    _rodar(vazio, drive, aplicar=True)
    assert (vazio / "data" / "resultado_orcamentario" / "celulas.json").read_text(encoding="utf-8") == '{"a": 1}'

    com_dados = _projeto(tmp_path, "c", {"celulas.json": '{"c": 1}'})
    saida = _rodar(com_dados, drive, aplicar=True)
    assert "[CONFLITO]" in saida
    local = com_dados / "data" / "resultado_orcamentario"
    assert not _juncao(local) and (local / "celulas.json").read_text(encoding="utf-8") == '{"c": 1}'
