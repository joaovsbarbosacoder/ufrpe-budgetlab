"""
Leitura e normalização da base de Liquidação por Competência (Tesouro Gerencial / SIAFI).

Detalha, para cada Documento Hábil de uma Nota de Empenho, o MÊS DE REFERÊNCIA (competência —
quando o fato gerador da despesa ocorreu), diferente do mês em que a liquidação foi formalmente
lançada (Execução Mensal, `src/tesouro_execucao_mensal.py`). As duas bases não medem o mesmo
eixo de tempo — ver docs/BudgetLab_competencia_por_empenho.md, item 1, para a especificação
completa (a versão implementada aqui cobre só o que a Linha do Tempo da Consulta de Empenhos
precisa: a série de competência por NE/mês, sem o bucket "sem competência" nem o cruzamento
com a base BI de liquidado — combinados, ver conversa de definição de escopo).

Camada: regra específica de base (não é leitor genérico, não é analítica, não é interface).
Depende só de pandas/openpyxl. Não importa Streamlit.

Origem esperada: aba única, cabeçalho de 1 linha, 7 colunas —
    NE, Documento Hábil, DH - Doc. Contábil, Ano Referência ACC, Mês Referência ACC,
    Métrica, <valor, coluna sem cabeçalho>.
A chave `NE + Documento Hábil + DH - Doc. Contábil + Ano Referência + Mês Referência` é única
(confirmado na extração de referência: 3.696 linhas = 3.696 chaves).

Estornos entram com sinal — nunca `abs()`, nunca filtrar `valor > 0` (infla a apropriação e
esconde o cancelamento). Um mesmo Documento Hábil pode aparecer em mais de uma NE (rateio já
resolvido na origem) e uma NE costuma ter vários Documentos Hábeis — nunca agregar por DH
isoladamente, sempre por NE.

Contrato público:
    ler_liquidacao_competencia(caminho) -> pd.DataFrame
    liquidado_por_ne_e_mes(df) -> pd.DataFrame
    reconciliar(df) -> dict
    validar(df, esperado=None) -> RelatorioValidacao
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.cache_bases import em_cache
from src.leitura_excel import motor_excel

# --------------------------------------------------------------------------------------
# 1. Contrato do arquivo de origem
# --------------------------------------------------------------------------------------

#: nomes esperados da linha 1 (nesta ordem) — a 7ª coluna (valor) não tem cabeçalho na
#: origem, por isso fica fora desta lista e é resolvida pela posição.
CABECALHO_ESPERADO = [
    "NE", "Documento Hábil", "DH - Doc. Contábil",
    "Ano Referência ACC", "Mês Referência ACC", "Métrica",
]

COLUNAS = [
    "ne_ccor", "documento_habil", "doc_contabil",
    "ano_referencia", "mes_referencia_rotulo", "metrica", "valor",
]

#: mês abreviado (Tesouro Gerencial, PT-BR, maiúsculo) -> número do mês — mesmo vocabulário de
#: `src.tesouro_execucao_mensal._MESES_PT`, duplicado aqui de propósito (cada leitor de base
#: fica auto-contido, ver AGENTS.md: "mantenha toda regra específica de uma base separada").
_MESES_PT = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}
_PADRAO_ROTULO_MES = re.compile(r"^([A-ZÇ]{3})/(\d{4})$")

_METRICA_ESPERADA = "DetaCusto DH - R$"


class ErroLayoutBase(ValueError):
    """Layout do arquivo diferente do contrato — falhar cedo, nunca adivinhar."""


# --------------------------------------------------------------------------------------
# 2. Leitura
# --------------------------------------------------------------------------------------

def _rotulo_mes(texto: object) -> tuple[int, int]:
    """`"MAI/2026"` -> `(2026, 5)`. Levanta `ErroLayoutBase` se não casar o padrão."""

    encontrado = _PADRAO_ROTULO_MES.match(str(texto).strip().upper())
    if not encontrado or encontrado.group(1) not in _MESES_PT:
        raise ErroLayoutBase(f"Mês Referência ACC fora do padrão esperado (ex. 'MAI/2026'): {texto!r}.")
    return int(encontrado.group(2)), _MESES_PT[encontrado.group(1)]


def _validar_assinatura(caminho: Path) -> None:
    cabecalho = pd.read_excel(caminho, header=None, nrows=1, dtype=str, engine=motor_excel()).iloc[0].tolist()
    for posicao, esperado in enumerate(CABECALHO_ESPERADO):
        obtido = str(cabecalho[posicao] or "").strip()
        if obtido != esperado:
            raise ErroLayoutBase(
                f"Coluna {posicao + 1}: esperado cabeçalho {esperado!r}, obtido {obtido!r}."
            )


def _para_numero(serie: pd.Series) -> pd.Series:
    """Mesma conversão de `src.execucao_anual._para_numero` (texto monetário -> float,
    preservando NaN e o sinal de estorno)."""

    limpo = (
        serie.astype("string")
        .str.strip()
        .str.replace(r"^R\$\s*", "", regex=True)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    original = pd.to_numeric(serie.astype("string").str.strip(), errors="coerce")
    convertido = pd.to_numeric(limpo, errors="coerce")
    return original.where(original.notna(), convertido)


@em_cache
def ler_liquidacao_competencia(caminho: str | Path) -> pd.DataFrame:
    """Lê a base bruta e devolve o DataFrame normalizado — uma linha por (NE, Documento
    Hábil, Doc. Contábil, Ano Referência, Mês Referência), com `mes_referencia`/
    `ano_mes_referencia` derivados do rótulo "Mês Referência ACC" (nunca de "Ano Referência
    ACC" isolado — ver `validar` para a checagem cruzada entre os dois)."""

    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(caminho)

    _validar_assinatura(caminho)

    bruto = pd.read_excel(caminho, header=0, dtype=str, engine=motor_excel())
    if bruto.shape[1] != len(COLUNAS):
        raise ErroLayoutBase(f"Esperado {len(COLUNAS)} colunas, obtido {bruto.shape[1]}.")
    bruto.columns = COLUNAS

    resultado = bruto.copy()
    for coluna in ("ne_ccor", "documento_habil", "doc_contabil", "mes_referencia_rotulo", "metrica"):
        resultado[coluna] = resultado[coluna].astype("string").str.strip()
    resultado["ano_referencia"] = pd.to_numeric(resultado["ano_referencia"], errors="raise").astype("int16")
    resultado["valor"] = _para_numero(bruto["valor"])

    meses = resultado["mes_referencia_rotulo"].map(_rotulo_mes)
    resultado["ano_referencia_rotulo"] = [m[0] for m in meses]
    resultado["mes_referencia"] = [m[1] for m in meses]
    resultado["ano_mes_referencia"] = resultado["ano_referencia_rotulo"] * 100 + resultado["mes_referencia"]

    resultado.insert(0, "linha_origem", range(2, 2 + len(resultado)))
    resultado.insert(1, "arquivo_origem", caminho.name)

    return resultado.sort_values(["ne_ccor", "ano_mes_referencia"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# 3. Analítica mínima — série por NE/mês (o resto da modelagem, incluindo o bucket "sem
#    competência" e a classificação por elemento, fica em aberto até termos os dois pontos de
#    integração aprovados: ver docs/BudgetLab_competencia_por_empenho.md)
# --------------------------------------------------------------------------------------

def liquidado_por_ne(df: pd.DataFrame) -> pd.Series:
    """Total de `valor` (todos os meses de referência somados, sinal preservado) por NE —
    para quem só precisa do total apurado por competência, não da série mensal (ex.:
    "Necessidade de Empenho" de `app_pages/contratos_continuos.py`, que já trabalha com o
    total acumulado por NE, não com uma série por mês). Indexada por `ne_ccor` (forma
    completa) — quem consome decide se precisa converter para a forma curta
    (`execucao_anual.ne_curta`), mesmo padrão de `liquidado_por_ne_e_mes`."""

    return df.groupby("ne_ccor")["valor"].sum()


def liquidado_por_ne_e_mes(df: pd.DataFrame) -> pd.DataFrame:
    """Soma de `valor` (sinal preservado — estornos incluídos) por (NE, mês de referência).
    Uma NE só aparece nos meses em que teve ao menos uma linha de competência: ausência não
    significa liquidado zero, significa ausência de dado (a NE pode ter liquidado sem
    competência apurada — ver item 4 do documento). Quem consome decide como tratar a
    ausência (reindexar com 0 para um gráfico, por exemplo — nunca interpretar a ausência
    como zero por conta própria dentro desta função)."""

    return (
        df.groupby(["ne_ccor", "ano_mes_referencia"])["valor"]
        .sum()
        .reset_index()
        .rename(columns={"ano_mes_referencia": "ano_mes"})
        .sort_values(["ne_ccor", "ano_mes"])
        .reset_index(drop=True)
    )


# --------------------------------------------------------------------------------------
# 4. Reconciliação e validação
# --------------------------------------------------------------------------------------

def reconciliar(df: pd.DataFrame) -> dict:
    return {
        "linhas": int(len(df)),
        "documentos_habeis_distintos": int(df["documento_habil"].nunique()),
        "notas_empenho_distintas": int(df["ne_ccor"].nunique()),
        "meses_referencia": sorted(df["ano_mes_referencia"].unique().tolist()),
        "total": round(float(df["valor"].sum()), 2),
        "total_estornos": round(float(df.loc[df["valor"] < 0, "valor"].sum() or 0.0), 2),
    }


@dataclass
class RelatorioValidacao:
    ok: bool
    erros: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    resumo: dict = field(default_factory=dict)


def validar(df: pd.DataFrame, esperado: dict | None = None) -> RelatorioValidacao:
    erros: list[str] = []
    alertas: list[str] = []
    resumo = reconciliar(df)

    if df["ne_ccor"].isna().any() or df["ne_ccor"].eq("").any():
        erros.append("Há linhas sem NE.")

    chave = ["ne_ccor", "documento_habil", "doc_contabil", "ano_mes_referencia"]
    duplicadas = df.duplicated(subset=chave).sum()
    if duplicadas:
        erros.append(
            f"{duplicadas} linha(s) repetem a chave NE+Documento Hábil+Doc. Contábil+Mês "
            "Referência — a granularidade esperada é uma linha por combinação."
        )

    metricas_inesperadas = set(df["metrica"].dropna().unique()) - {_METRICA_ESPERADA}
    if metricas_inesperadas:
        alertas.append(f"Métrica(s) além de {_METRICA_ESPERADA!r} encontrada(s): {sorted(metricas_inesperadas)}.")

    if not df["ano_referencia"].eq(df["ano_referencia_rotulo"]).all():
        alertas.append(
            "Existe linha em que 'Ano Referência ACC' diverge do ano embutido em "
            "'Mês Referência ACC' — checar manualmente antes de confiar na competência."
        )

    if esperado:
        for chave_esperada, valor_esperado in esperado.items():
            if chave_esperada not in resumo:
                continue
            if isinstance(valor_esperado, (int, float)) and abs(resumo[chave_esperada] - valor_esperado) > 0.01:
                erros.append(f"{chave_esperada}: esperado {valor_esperado}, obtido {resumo[chave_esperada]}.")

    return RelatorioValidacao(ok=not erros, erros=erros, alertas=alertas, resumo=resumo)
