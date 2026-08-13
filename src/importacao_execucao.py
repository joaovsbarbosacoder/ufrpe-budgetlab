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
    nome_ponteiro,
)

BASE = "execucao_anual"
NOME_PONTEIRO = nome_ponteiro(BASE)
TOLERANCIA = TOLERANCIA_PADRAO

__all__ = [
    "BASE",
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
