"""
Execução do Tesouro Gerencial para o módulo de TEDs — derivada da Execução Mensal.

Confirmado pelo usuário em 22/09/2026 (ver `docs/base_teds.md` seção 6): a base do Tesouro
Gerencial usada pelo módulo É a extração de Execução Mensal já implementada em
`src/tesouro_execucao_mensal.py` (versionada por `src/importacao_execucao_mensal.py`) — não há
uma segunda extração nem leitor de arquivo próprio. Este módulo só REMONTA a saída dessa base
no formato de `execucao_tg` (uma linha por NE × mês de lançamento); quem grava no SQLite é
`src/teds_lotes.py::sincronizar_execucao_tg`.

Mapeamento (Execução Mensal → `execucao_tg`):

  * `numero_completo_ne` ← `src.execucao_ne_utils.ne_curta(ne_ccor)` (ex. "2026NE000100") — a
    mesma forma curta usada no resto do projeto e a que `src.teds_normalizacao.decompor_numero_ne`
    espera. NE fora desse formato é REJEITADA (nunca gravada com chave inválida).
  * `empenhado`/`liquidado`/`pago` ← `linha_do_tempo_por_ne` (Empenhado já deduplicado por
    bloco). São movimentos do MÊS, não acumulados: somar por NE dá o total (é o que `teds_ui`
    e a Conciliação já fazem). `linha_do_tempo_por_ne` preenche com 0 o mês em que a NE não tem
    linha de Liquidada/Paga — convenção da própria função, coerente aqui: sem lançamento no
    mês, o movimento do mês é zero.
  * `ano_lancamento`/`mes_lancamento` ← `ano_mes` (`ano*100+mes`). É o mês em que o movimento
    foi LANÇADO, não a competência (fato gerador) — as duas medem eixos de tempo diferentes
    (ver `src/liquidacao_competencia.py`), por isso os nomes não são "competência".
  * `favorecido` ← `ne_favorecido`; `descricao` ← `ne_descricao` (só das linhas de tipo
    "empenho" — as de item de execução trazem sentinela, ver `agregar_por_ne`).

`documento_habil`/`documento_contabil`/`valor_competencia` saíram do schema: a Execução Mensal
não os tem. Competência real (Documento Hábil × mês de referência) existe na base de Liquidação
por Competência, mas integrá-la ao TEDs é decisão futura, fora deste escopo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pandas as pd

from src.execucao_ne_utils import ne_curta
from src.teds_importacao_simec import LinhaRejeitada
from src.teds_normalizacao import decompor_numero_ne, parse_valor_brl
from src.tesouro_execucao_mensal import linha_do_tempo_por_ne


@dataclass
class ResultadoLeituraTG:
    registros: list[dict[str, Any]] = field(default_factory=list)
    rejeitadas: list[LinhaRejeitada] = field(default_factory=list)


def _texto_ou_none(valor: object) -> str | None:
    if valor is None or pd.isna(valor):
        return None
    texto = str(valor).strip()
    return texto or None


def _valor(numero: float) -> Decimal:
    """`Decimal` exato em centavos a partir do float da Execução Mensal (via `parse_valor_brl`);
    `+ 0` normaliza o "-0,00" (zero negativo de ponto flutuante) para "0,00" — zero é zero."""

    return parse_valor_brl(float(numero)) + Decimal("0")


def montar_execucao_tg(execucao_mensal: pd.DataFrame) -> ResultadoLeituraTG:
    """Uma linha de `execucao_tg` por (NE × mês de lançamento) da Execução Mensal — ver
    docstring do módulo para o mapeamento. `execucao_mensal` é o DataFrame já normalizado de
    `src.tesouro_execucao_mensal.ler_execucao_mensal`/
    `src.importacao_execucao_mensal.carregar_atual` (não relê nenhum arquivo, não o altera).

    `linha_origem` guarda a chave de reconciliação com a base de origem (`ne_ccor` completo e
    `ano_mes`) e os três valores como vieram, para auditoria."""

    resultado = ResultadoLeituraTG()
    if execucao_mensal.empty:
        return resultado

    tempo = linha_do_tempo_por_ne(execucao_mensal)

    dimensoes = execucao_mensal.groupby("ne_ccor")["ne_favorecido"].first()
    descricoes = execucao_mensal.loc[execucao_mensal["tipo_linha"] == "empenho"].groupby("ne_ccor")["ne_descricao"].first()

    for indice, linha in tempo.iterrows():
        ne_ccor = str(linha["ne_ccor"])
        origem = {
            "ne_ccor": ne_ccor,
            "ano_mes": int(linha["ano_mes"]),
            "empenhada": float(linha["empenhada"]),
            "liquidada": float(linha["liquidada"]),
            "paga": float(linha["paga"]),
        }

        numero = ne_curta(ne_ccor)
        if decompor_numero_ne(numero) is None:
            resultado.rejeitadas.append(
                LinhaRejeitada(indice, f"NE fora do formato AAAANEnnnnnn: {ne_ccor!r}", origem)
            )
            continue

        ano_mes = int(linha["ano_mes"])
        resultado.registros.append(
            {
                "numero_completo_ne": numero,
                "favorecido": _texto_ou_none(dimensoes.get(ne_ccor)),
                "descricao": _texto_ou_none(descricoes.get(ne_ccor)),
                "empenhado": _valor(linha["empenhada"]),
                "liquidado": _valor(linha["liquidada"]),
                "pago": _valor(linha["paga"]),
                "ano_lancamento": ano_mes // 100,
                "mes_lancamento": ano_mes % 100,
                "linha_origem": origem,
            }
        )

    return resultado
