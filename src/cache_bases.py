"""
Cache em Parquet das bases já lidas e normalizadas (pedido e aprovação do usuário, 07/10/2026).

Ler as planilhas é o que mais custa no sistema (segundos por arquivo); o `st.cache_data` do
Streamlit guarda o resultado só na memória do processo — a cada reinício do sistema, tudo é relido.
Este cache grava o DataFrame que o leitor devolveu num arquivo Parquet derivado, em
`data/processed/cache_bases/` (fora do Git), e nas próximas leituras do MESMO arquivo, pelo MESMO
código, devolve a cópia gravada.

Garantias (dados financeiros não podem ser modificados silenciosamente):
  * A chave é o conteúdo do arquivo (SHA-256 dos bytes) e o caminho dele, não a data: qualquer alteração na
    planilha gera outra chave, e arquivos de mesmo conteúdo com nomes diferentes não compartilham a cópia
    (os leitores gravam o nome em `arquivo_origem`). A chave também inclui o código-fonte do módulo do leitor, deste módulo
    e de `src/leitura_excel.py`, o motor de Excel em uso e as versões do pandas e do pyarrow — mudar o
    leitor invalida o cache dele.
  * Só é gravado o que volta IDÊNTICO: depois de gravar, o arquivo é relido e comparado com o original
    (`assert_frame_equal`, tipos e valores exatos); se não bater (tipo que o Parquet não preserva, por
    exemplo), a cópia é apagada e aquele leitor segue sem cache para aquele arquivo.
  * Qualquer falha do cache (pyarrow ausente, disco, permissão) cai na leitura normal — o cache nunca
    impede o sistema de ler a planilha. O arquivo original nunca é alterado.
  * Desligado por padrão: só o app (`app.py`) liga, com `ativar_no_app()`. Testes e scripts leem sempre a
    planilha, salvo quando ligam explicitamente com `ativar(diretorio)`. Os testes de página executam o
    `app.py`; por isso `tests/conftest.py` define `BUDGETLAB_CACHE_BASES=desligado`, que faz o
    `ativar_no_app()` não ligar nada (sem isso, a suíte gravava e reaproveitava cópias na pasta real).

Mantém no máximo `LIMITE_ARQUIVOS` cópias (as mais antigas são apagadas).
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import inspect
import os
import sys
from pathlib import Path
from typing import Callable

import pandas as pd

from src.leitura_excel import motor_excel

DIRETORIO_PADRAO = Path("data/processed/cache_bases")
LIMITE_ARQUIVOS = 60
VARIAVEL_AMBIENTE = "BUDGETLAB_CACHE_BASES"

_diretorio: Path | None = None


def ativar(diretorio: str | Path = DIRETORIO_PADRAO) -> bool:
    """Liga o cache gravando em `diretorio`. Devolve False (e fica desligado) sem pyarrow."""

    global _diretorio
    if importlib.util.find_spec("pyarrow") is None:
        _diretorio = None
        return False
    _diretorio = Path(diretorio)
    return True


def ativar_no_app() -> bool:
    """O que o `app.py` chama: liga em `DIRETORIO_PADRAO`, salvo com `BUDGETLAB_CACHE_BASES=desligado`
    (definida pelos testes) — aí desliga e devolve False."""

    if os.environ.get(VARIAVEL_AMBIENTE, "").strip().lower() == "desligado":
        desativar()
        return False
    return ativar()


def desativar() -> None:
    global _diretorio
    _diretorio = None


def ativo() -> bool:
    return _diretorio is not None


def _hash_arquivo(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def _hash_codigo(funcao: Callable) -> str:
    resumo = hashlib.sha256()
    modulos = [sys.modules.get(funcao.__module__), sys.modules[__name__], sys.modules.get("src.leitura_excel")]
    for modulo in modulos:
        arquivo = getattr(modulo, "__file__", None)
        if arquivo and os.path.exists(arquivo):
            resumo.update(Path(arquivo).read_bytes())
    versao_pyarrow = ""
    if importlib.util.find_spec("pyarrow") is not None:
        import pyarrow

        versao_pyarrow = pyarrow.__version__
    resumo.update(f"{pd.__version__}|{versao_pyarrow}|{motor_excel()}".encode())
    return resumo.hexdigest()


def _limpar_excesso(diretorio: Path) -> None:
    arquivos = sorted(diretorio.glob("*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
    for antigo in arquivos[LIMITE_ARQUIVOS:]:
        try:
            antigo.unlink()
        except OSError:
            pass


def em_cache(funcao: Callable[..., pd.DataFrame]) -> Callable[..., pd.DataFrame]:
    """Decorador para leitores `funcao(caminho, *args)` que devolvem um DataFrame. Argumentos extras
    (ex.: `ano`) entram na chave. Com o cache desligado, chama o leitor direto."""

    assinatura = inspect.signature(funcao)

    @functools.wraps(funcao)
    def envoltorio(*args, **kwargs):
        diretorio = _diretorio
        if diretorio is None:
            return funcao(*args, **kwargs)
        try:
            ligados = assinatura.bind(*args, **kwargs)
            ligados.apply_defaults()
            argumentos = dict(ligados.arguments)
            caminho = Path(argumentos.pop(next(iter(assinatura.parameters))))
            # o caminho também entra: leitores gravam o nome do arquivo (`arquivo_origem`), e dois arquivos
            # com os mesmos bytes não podem compartilhar a cópia
            chave = hashlib.sha256(
                "|".join([
                    funcao.__module__, funcao.__qualname__, str(caminho.resolve()), _hash_arquivo(caminho),
                    _hash_codigo(funcao),
                    repr(sorted(argumentos.items())),
                ]).encode()
            ).hexdigest()[:32]
            destino = diretorio / f"{funcao.__qualname__}_{chave}.parquet"
        except Exception:
            return funcao(*args, **kwargs)

        if destino.exists():
            try:
                return pd.read_parquet(destino)
            except Exception:
                try:
                    destino.unlink()
                except OSError:
                    pass

        resultado = funcao(*args, **kwargs)
        if not isinstance(resultado, pd.DataFrame):
            return resultado
        temporario = destino.with_suffix(f".{os.getpid()}.tmp")
        try:
            diretorio.mkdir(parents=True, exist_ok=True)
            resultado.to_parquet(temporario, index=True)
            pd.testing.assert_frame_equal(pd.read_parquet(temporario), resultado, check_dtype=True, check_exact=True)
            os.replace(temporario, destino)
            _limpar_excesso(diretorio)
        except Exception:
            # tipo que o Parquet não devolve idêntico, disco, permissão: segue sem cache
            try:
                temporario.unlink()
            except OSError:
                pass
        return resultado

    envoltorio.sem_cache = funcao  # leitura direta, para comparação/testes
    return envoltorio
