"""
Importação versionada da base ANUAL de Dotação (BI CPOC - Por Ano).

Especialização do núcleo genérico em `src/importacao_versionada.py` para a Dotação Anual —
mesmo papel que `src/importacao_execucao.py` cumpre para a Execução Anual: fixa a base
("dotacao_anual"), as medidas e os leitores/validadores próprios. Não reimplementa
normalização: `ler_dotacao_anual`/`reconciliar_dotacao_anual`/`validar_dotacao_anual` são
adaptações finas do que já existe e já é testado em `src/tesouro_dotacao_anual_workbook.py`
e `src/dotacao_anual_analysis.py` — a assinatura muda (para caber no contrato do núcleo
genérico), a lógica de normalização e as regras de integridade não.

Medidas: os quatro indicadores conhecidos da Dotação Anual — `dotacao_inicial`,
`dotacao_suplementar`, `dotacao_atualizada`, `dotacao_cancelada_remanejada` — vêm de
`KNOWN_ITEM_INDICATORS` em `dotacao_anual_analysis.py`. Não têm nenhuma relação com
empenhada/liquidada/paga da Execução.

`app_pages/dotacao_orcamentaria.py` e `app_pages/painel_acoes.py` leem `Manifesto.atual()`
direto (não `st.session_state`); a reimportação pela interface vive na seção "Reimportar
base" de `dotacao_orcamentaria.py`, via `src/ui_reimportacao.py`. Ver `docs/base_dotacao_anual.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.dotacao_anual_analysis import (
    KNOWN_ITEM_INDICATORS,
    build_dotacao_anual_year_analysis,
    build_item_indicators,
    prepare_validated_dotacao_anual_dataset,
)
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
from src.tesouro_dotacao_anual_workbook import (
    DotacaoAnualWorkbookResult,
    process_dotacao_anual_workbook,
)

BASE = "dotacao_anual"
NOME_PONTEIRO = nome_ponteiro(BASE)
TOLERANCIA = TOLERANCIA_PADRAO

#: Nomes e semântica reais da Dotação Anual — não os de Execução. `ROTULOS_MEDIDAS` reaproveita
#: o mesmo texto que a análise em sessão já mostra ao usuário.
MEDIDAS: tuple[str, ...] = tuple(KNOWN_ITEM_INDICATORS)
ROTULOS_MEDIDAS: dict[str, str] = dict(KNOWN_ITEM_INDICATORS)

__all__ = [
    "BASE",
    "DIRETORIO_MANIFESTOS_PADRAO",
    "NOME_PONTEIRO",
    "TOLERANCIA",
    "MEDIDAS",
    "ROTULOS_MEDIDAS",
    "Manifesto",
    "RelatorioValidacao",
    "LeituraDotacaoAnual",
    "Delta",
    "MotivosGate",
    "ResultadoImportacao",
    "exige_confirmacao",
    "ler_dotacao_anual",
    "reconciliar_dotacao_anual",
    "validar_dotacao_anual",
    "gerar_manifesto",
    "comparar",
    "importar",
    "historico",
    "historico_como_tabela",
]


class Manifesto(_ManifestoGenerico):
    """Manifesto da Dotação Anual — base fixa, mesma razão de ser da subclasse em
    `importacao_execucao.Manifesto`: permite `Manifesto.atual()` sem exigir `base`
    a cada chamada."""

    BASE = BASE


@dataclass
class RelatorioValidacao:
    """Mesmo contrato duck-typed que `src.execucao_anual.RelatorioValidacao` usa
    (`.ok`, `.erros`, `.alertas`) — definido aqui, não importado de lá: a Dotação Anual
    não deveria depender do módulo de outra base por causa de um dataclass genérico."""

    ok: bool
    erros: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)


@dataclass
class LeituraDotacaoAnual:
    """O que `ler_dotacao_anual` devolve para o núcleo genérico.

    Carrega o `DotacaoAnualWorkbookResult` inteiro (não só o DataFrame consolidado) porque
    `reconciliar_dotacao_anual`/`validar_dotacao_anual` precisam das contagens por aba e da
    soma bruta × normalizada — informação que não sobra no DataFrame final. Carrega também os
    bytes originais para poder reaproveitar `prepare_validated_dotacao_anual_dataset` na
    validação sem reler o arquivo do disco uma segunda vez.
    """

    workbook: DotacaoAnualWorkbookResult
    conteudo: bytes


def ler_dotacao_anual(caminho: str | Path) -> LeituraDotacaoAnual:
    """Lê e normaliza todas as abas reconhecidas do arquivo.

    Só adapta "caminho em disco" para "bytes" — `process_dotacao_anual_workbook` (leitura,
    reconhecimento dinâmico de blocos mesclados, normalização multiaba) é reaproveitado sem
    nenhuma alteração.
    """

    caminho = Path(caminho)
    conteudo = caminho.read_bytes()
    workbook = process_dotacao_anual_workbook(conteudo, caminho.name)
    return LeituraDotacaoAnual(workbook=workbook, conteudo=conteudo)


def reconciliar_dotacao_anual(leitura: LeituraDotacaoAnual) -> dict:
    """Totais por indicador e por ano, reaproveitando as agregações já testadas de
    `dotacao_anual_analysis.py` — `build_item_indicators` (total geral, por indicador) e
    `build_dotacao_anual_year_analysis` (por ano). As duas preservam nulo ≠ zero via
    `sum(min_count=1)`; esta função só reformata o resultado no formato de dict que o
    manifesto genérico espera (`anos`, `totais`, `totais_por_ano`, demais chaves viram
    contagens estruturais)."""

    dataframe = leitura.workbook.consolidated_data

    indicadores = build_item_indicators(dataframe)
    totais: dict[str, float | None] = {
        str(linha["item_informacao_codigo"]): (
            None
            if pd.isna(linha["valor_movimento_liquido"])
            else float(linha["valor_movimento_liquido"])
        )
        for _, linha in indicadores.iterrows()
    }

    por_ano = build_dotacao_anual_year_analysis(dataframe)
    totais_por_ano: dict[int, dict[str, float | None]] = {}
    for _, linha in por_ano.iterrows():
        ano = linha["ano_lancamento"]
        if pd.isna(ano):
            continue
        totais_por_ano[int(ano)] = {
            medida: (None if pd.isna(linha[medida]) else float(linha[medida]))
            for medida in MEDIDAS
        }

    return {
        "anos": sorted(totais_por_ano),
        "totais": totais,
        "totais_por_ano": totais_por_ano,
        "abas_reconhecidas": len(leitura.workbook.recognized_sheets),
        "linhas_normalizadas": leitura.workbook.normalized_row_count,
        "nulos": leitura.workbook.null_count,
        "zeros": leitura.workbook.zero_count,
        "negativos": leitura.workbook.negative_count,
    }


def validar_dotacao_anual(leitura: LeituraDotacaoAnual) -> RelatorioValidacao:
    """Reaproveita as checagens de `prepare_validated_dotacao_anual_dataset` — integridade
    multiaba aprovada, colunas obrigatórias presentes, base não vazia, coordenadas de origem
    sem duplicata, contagem e soma batendo com a validação multiaba. Nenhuma checagem nova:
    só adapta o estilo de `raise ValueError` para a lista `.erros` que o núcleo genérico
    espera, igual ao que a interface de reimportação já faz para os erros de `validar()` da
    Execução Anual."""

    erros = list(leitura.workbook.processing_errors)
    alertas: list[str] = []
    if not leitura.workbook.consolidated_inconsistencies.empty:
        alertas.append(
            f"{len(leitura.workbook.consolidated_inconsistencies)} inconsistência(s) na "
            "base consolidada (ver detalhamento por aba)."
        )

    try:
        prepare_validated_dotacao_anual_dataset(leitura.workbook, leitura.conteudo)
    except ValueError as erro:
        erros.append(str(erro))

    return RelatorioValidacao(ok=not erros, erros=erros, alertas=alertas)


def gerar_manifesto(leitura: LeituraDotacaoAnual, caminho: Path, base: str = BASE) -> Manifesto:
    return _gerar_manifesto_generico(
        leitura, caminho, base=base, reconciliar=reconciliar_dotacao_anual
    )


def comparar(anterior: Manifesto | None, novo: Manifesto) -> Delta:
    return _comparar_generico(anterior, novo, medidas=MEDIDAS)


def importar(
    caminho: str | Path,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
    registrar: bool = True,
) -> ResultadoImportacao:
    """
    Lê, valida, compara com a última extração e registra o manifesto.

    Substituição total: o `LeituraDotacaoAnual` devolvido é a base inteira e deve substituir
    o que estiver em memória/persistência. O manifesto só é gravado se a validação não tiver
    erros — extração inválida não vira referência histórica.
    """
    return _importar_generico(
        caminho,
        base=BASE,
        ler=ler_dotacao_anual,
        reconciliar=reconciliar_dotacao_anual,
        validar=validar_dotacao_anual,
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
        BASE, MEDIDAS, diretorio_manifestos, contagem_destaque="abas_reconhecidas"
    )


if __name__ == "__main__":
    import sys

    resultado = importar(sys.argv[1], *(sys.argv[2:3] or []))
    print("Extração:", resultado.manifesto.data_extracao, "| hash", resultado.manifesto.sha256[:8])
    print("Abas reconhecidas:", resultado.manifesto.contagens.get("abas_reconhecidas"))
    print("Exercícios:", resultado.manifesto.anos)
    print("Totais:", resultado.manifesto.totais)
    print("Validação OK:", resultado.ok, "| erros:", resultado.validacao.erros or "nenhum")
    print("Alertas:", resultado.validacao.alertas or "nenhum")
    print("--- mudanças desde a última importação ---")
    for linha in resultado.delta.resumo_texto():
        print(" ", linha)
    for alerta in resultado.delta.alertas:
        print("  ⚠", alerta)
