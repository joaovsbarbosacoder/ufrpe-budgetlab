"""
Importação versionada da base ANUAL de Execução da Despesa.

Especialização do núcleo genérico em `src/importacao_versionada.py` para a Execução Anual:
fixa a base ("execucao_anual"), as medidas (`MEDIDAS`) e os leitores/validadores próprios
(`src/execucao_anual.py`). Toda a mecânica de manifesto, delta entre extrações e política de
confirmação vive no núcleo genérico — este módulo só amarra essa mecânica a esta base
específica e reexporta os nomes que já eram públicos, para não quebrar quem já importa daqui
(a página `execucao_orcamentaria.py` e a suíte de testes desta base).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.execucao_anual import MEDIDAS, ler_execucao_anual, reconciliar, validar
from src.importacao_versionada import (
    DIRETORIO_MANIFESTOS_PADRAO,
    Delta,
    Manifesto as _ManifestoGenerico,
    MotivosGate,
    ResultadoImportacao,
    TOLERANCIA_PADRAO,
    comparar as _comparar_generico,
    exige_confirmacao,
    gerar_manifesto as _gerar_manifesto_generico,
    historico as _historico_generico,
    historico_como_tabela as _historico_como_tabela_generico,
    importar as _importar_generico,
    manifestos_por_ano,
    nome_ponteiro,
)

DIRETORIO_DADOS_BRUTOS_PADRAO = Path("data/raw")

BASE = "execucao_anual"
NOME_PONTEIRO = nome_ponteiro(BASE)
TOLERANCIA = TOLERANCIA_PADRAO

__all__ = [
    "BASE",
    "DIRETORIO_DADOS_BRUTOS_PADRAO",
    "DIRETORIO_MANIFESTOS_PADRAO",
    "NOME_PONTEIRO",
    "TOLERANCIA",
    "Manifesto",
    "Delta",
    "MotivosGate",
    "ResultadoImportacao",
    "exige_confirmacao",
    "gerar_manifesto",
    "comparar",
    "importar",
    "carregar_atual",
    "historico",
    "historico_como_tabela",
]


class Manifesto(_ManifestoGenerico):
    """Manifesto da Execução Anual — base fixa, para que `Manifesto.atual()` funcione sem
    exigir o argumento `base` a cada chamada (compatibilidade com todo o código existente)."""

    BASE = BASE


def gerar_manifesto(df: pd.DataFrame, caminho: Path, base: str = BASE) -> Manifesto:
    return _gerar_manifesto_generico(df, caminho, base=base, reconciliar=reconciliar)


def comparar(anterior: Manifesto | None, novo: Manifesto) -> Delta:
    return _comparar_generico(anterior, novo, medidas=MEDIDAS)


def _validar_sem_esperado(df: pd.DataFrame) -> object:
    # Nada a conferir contra: a nova extração define os próprios totais.
    return validar(df, esperado=None)


def importar(
    caminho: str | Path,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
    registrar: bool = True,
) -> ResultadoImportacao:
    """
    Lê, valida, compara com a última extração e registra o manifesto.

    Substituição total: o DataFrame devolvido é a base inteira e deve substituir o que estiver
    em memória/persistência. O manifesto só é gravado se a validação não tiver erros —
    extração inválida não vira referência histórica.
    """
    return _importar_generico(
        caminho,
        base=BASE,
        ler=ler_execucao_anual,
        reconciliar=reconciliar,
        validar=_validar_sem_esperado,
        medidas=MEDIDAS,
        diretorio_manifestos=diretorio_manifestos,
        registrar=registrar,
    )


def carregar_atual(
    diretorio_dados_brutos: str | Path = DIRETORIO_DADOS_BRUTOS_PADRAO,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
) -> pd.DataFrame | None:
    """Base composta por ano — o que as páginas devem ler no lugar de `ler_execucao_anual`
    direto no arquivo de `Manifesto.atual()`. `None` se nenhuma importação foi feita ainda.

    Agrupa os anos por manifesto (via `sha256`, ver `manifestos_por_ano`) antes de ler
    qualquer arquivo — um manifesto que hoje só é dono de parte dos anos que ele trouxe (por
    ter sido parcialmente sobreposto por uma importação mais nova) é filtrado para só esses
    anos, senão um ano já sobreposto apareceria duplicado (uma vez pela versão antiga, outra
    pela nova)."""
    por_ano = manifestos_por_ano(BASE, diretorio_manifestos)
    if not por_ano:
        return None

    anos_por_sha: dict[str, list[int]] = {}
    manifesto_por_sha: dict[str, Manifesto] = {}
    for ano, manifesto in por_ano.items():
        anos_por_sha.setdefault(manifesto.sha256, []).append(ano)
        manifesto_por_sha[manifesto.sha256] = manifesto

    diretorio_dados_brutos = Path(diretorio_dados_brutos)
    partes = []
    for sha, anos in sorted(anos_por_sha.items(), key=lambda item: min(item[1])):
        manifesto = manifesto_por_sha[sha]
        df = ler_execucao_anual(diretorio_dados_brutos / manifesto.arquivo)
        partes.append(df[df["ano"].isin(anos)])

    return partes[0] if len(partes) == 1 else pd.concat(partes, ignore_index=True)


def historico(diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO) -> list[Manifesto]:
    """Manifestos de todas as importações já feitas, do mais antigo ao mais recente."""
    return _historico_generico(BASE, diretorio_manifestos)


def historico_como_tabela(diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO) -> pd.DataFrame:
    """Uma linha por importação, com totais — pronto para exibir na aba."""
    return _historico_como_tabela_generico(
        BASE, MEDIDAS, diretorio_manifestos, contagem_destaque="linhas"
    )


if __name__ == "__main__":
    import sys

    resultado = importar(sys.argv[1], *(sys.argv[2:3] or []))
    print("Extração:", resultado.manifesto.data_extracao, "| hash", resultado.manifesto.sha256[:8])
    print("Linhas:", resultado.manifesto.linhas, "| exercícios:", resultado.manifesto.anos)
    print("Totais:", resultado.manifesto.totais)
    print("Validação OK:", resultado.ok, "| erros:", resultado.validacao.erros or "nenhum")
    print("Alertas:", resultado.validacao.alertas or "nenhum")
    print("--- mudanças desde a última importação ---")
    for linha in resultado.delta.resumo_texto():
        print(" ", linha)
    for alerta in resultado.delta.alertas:
        print("  ⚠", alerta)
