"""Retrato de referência dos números de Contratos Contínuos SEM aditivo (06/10/2026).

Congela, para os contratos reais do exercício de 2026, o que a necessidade de empenho, a projeção
mensal, a despesa anual e a sugestão do Relatório de Reforço calculavam ANTES dos aditivos
(`docs/superpowers/specs/2026-10-06-aditivos-contratos-design.md`). Depois da mudança, o mesmo cálculo
precisa devolver números idênticos para contrato sem aditivo — é o teste de não regressão da troca
de "valor × meses" pela soma da série mensal.

A execução (Execução Mensal / Liquidação por Competência) é SINTÉTICA e determinística, derivada do
próprio cadastro: assim o retrato não depende de planilha nem de manifesto. Só `entradas_do_retrato`
lê o cadastro, e o resultado é gravado em `tests/fixtures/` (uma vez, deliberadamente).
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

from src.contratos_continuos import com_efeitos_da_suspensao
from src.contratos_continuos_cadastro import como_dataframe
from src.relatorio_necessidade_empenho import montar_relatorio, necessidade_por_ne
from src.relatorio_reforco_empenho import CONTRATOS_CONTINUOS, linhas_para_processo, processos_disponiveis

CAMINHO_FIXTURE = Path(__file__).parent / "fixtures" / "retrato_contratos_sem_aditivo_2026-10-06.json"
HOJE_DO_RETRATO = date(2026, 10, 6)
MES_REFERENCIA = 9

#: campos usados nas contas (sem CNPJ nem dados sem efeito no cálculo)
CAMPOS_DO_RETRATO = [
    "id", "ne_curta", "contrato_numero", "fornecedor", "processo_empenho", "status_contrato",
    "vigencia_fim", "inicio_execucao_data", "inicio_execucao_mes", "data_suspensao", "meses_no_ano",
    "despesa_mensal", "valor_empenhado", "saldo_colado_planilha", "meses_empenhados", "meses_liquidados",
    "itens", "unidade_cod", "acao_cod", "ptres", "fonte_cod", "natureza_despesa_cod", "ugr_cod", "pi_cod",
]


def entradas_do_retrato(contratos: list[dict]) -> list[dict]:
    """Só os campos de cálculo de cada contrato do cadastro (`carregar_contratos`)."""

    return [{campo: contrato.get(campo) for campo in CAMPOS_DO_RETRATO} for contrato in contratos]


def _numero(valor: object) -> float | None:
    if valor is None or pd.isna(valor):
        return None
    return float(valor)


def _com_execucao_sintetica(df: pd.DataFrame) -> pd.DataFrame:
    """Execução derivada só do cadastro: empenhado = o do cadastro; liquidado = metade dele."""

    resultado = df.copy()
    empenhado = pd.to_numeric(resultado["valor_empenhado"], errors="coerce")
    resultado["valor_empenhado_execucao"] = empenhado
    resultado["valor_empenhado_planilha_total_ne"] = empenhado
    resultado["valor_empenhado_autoritativo"] = empenhado
    resultado["valor_liquidado_execucao"] = empenhado * 0.5
    resultado["saldo_execucao"] = empenhado - empenhado * 0.5
    resultado["saldo_autoritativo"] = resultado["saldo_execucao"]
    resultado["liquidado_via_competencia"] = False
    resultado["inicio_execucao_efetivo"] = resultado["inicio_execucao_mes"]
    return com_efeitos_da_suspensao(resultado)


class _DataFixa(date):
    @classmethod
    def today(cls) -> date:
        return HOJE_DO_RETRATO


def calcular_retrato(entradas: list[dict], exercicio: int = 2026) -> dict:
    """Números congelados: necessidade por NE/contrato, projeção mensal, despesa anual e Reforço."""

    df = _com_execucao_sintetica(como_dataframe(entradas, exercicio))
    por_ne, sem_ne = necessidade_por_ne(df, None, exercicio)

    necessidade = {
        linha.ne_curta: [_numero(linha.necessidade), _numero(linha.meses_restantes), _numero(linha.meses_vigentes)]
        for linha in por_ne.itertuples()
    }
    sem_ne_retrato = {
        f"{linha.contrato_numero}#{posicao}": [
            _numero(linha.necessidade), _numero(linha.meses_restantes), _numero(linha.meses_vigentes)
        ]
        for posicao, linha in enumerate(sem_ne.itertuples())
    }

    relatorio = montar_relatorio(por_ne, sem_ne, None, exercicio, MES_REFERENCIA)
    projecao = {}
    for linha, mensal in zip(relatorio.linhas.itertuples(), relatorio.mensal.itertuples()):
        # sem a posição na chave: a ordem entre linhas de necessidade empatada não é garantida
        chave = linha.ne_curta if isinstance(linha.ne_curta, str) else linha.contrato_numero
        projecao[chave] = [_numero(getattr(mensal, f"p{mes}")) for mes in range(1, 13)]

    despesa_anual = {str(id_): _numero(valor) for id_, valor in zip(df["id"], df["despesa_anual"])}

    reforco = {}
    with mock.patch("src.necessidade_empenho.date", _DataFixa):
        for processo in processos_disponiveis(df, CONTRATOS_CONTINUOS):
            linhas = linhas_para_processo(df, CONTRATOS_CONTINUOS, processo, exercicio)
            reforco[processo] = [
                [str(linha.ne_curta), str(linha.item_despesa), _numero(linha.valor_mensal), _numero(linha.meses_sugeridos)]
                for linha in linhas.itertuples()
            ]

    return {
        "necessidade_por_ne": necessidade,
        "sem_ne": sem_ne_retrato,
        "projecao": projecao,
        "despesa_anual": despesa_anual,
        "reforco": reforco,
    }


def gerar_fixture(contratos: list[dict]) -> None:
    """Grava o retrato (deliberadamente, só quando se decide congelar de novo)."""

    entradas = entradas_do_retrato(contratos)
    esperado = calcular_retrato(entradas)
    CAMINHO_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    CAMINHO_FIXTURE.write_text(
        json.dumps({"entradas": entradas, "esperado": esperado}, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )


def iguais(esperado: object, obtido: object, caminho: str = "") -> list[str]:
    """Diferenças entre dois retratos (lista vazia = idênticos). `None` só casa com NaN/None."""

    if isinstance(esperado, dict):
        if not isinstance(obtido, dict) or set(esperado) != set(obtido):
            return [f"{caminho}: chaves diferentes"]
        return [d for chave in esperado for d in iguais(esperado[chave], obtido[chave], f"{caminho}/{chave}")]
    if isinstance(esperado, list):
        if not isinstance(obtido, list) or len(esperado) != len(obtido):
            return [f"{caminho}: tamanho diferente"]
        return [d for i, (a, b) in enumerate(zip(esperado, obtido)) for d in iguais(a, b, f"{caminho}[{i}]")]
    if esperado is None or (isinstance(esperado, float) and math.isnan(esperado)):
        vazio = obtido is None or (isinstance(obtido, float) and math.isnan(obtido))
        return [] if vazio else [f"{caminho}: esperado nulo, obtido {obtido!r}"]
    if isinstance(esperado, (int, float)) and isinstance(obtido, (int, float)):
        return [] if math.isclose(esperado, obtido, rel_tol=1e-9, abs_tol=1e-6) else [
            f"{caminho}: esperado {esperado!r}, obtido {obtido!r}"
        ]
    return [] if esperado == obtido else [f"{caminho}: esperado {esperado!r}, obtido {obtido!r}"]
