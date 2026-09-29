"""Remanejamento temporário de Limite de Empenho entre IDUSOs (`src/limite_empenho.py`).

Pedido explícito do usuário (28/09/2026): na prática, o saldo acumulado de um IDUSO (o "grande
grupo" cujo limite é compartilhado entre as ações dele) pode ser temporariamente remanejado
para outro IDUSO — o limite de uma AÇÃO ou PTRES específico não muda. O remanejamento precisa
poder ser desfeito a qualquer momento.

Regras desta implementação:
  * O ajuste é só no nível do IDUSO: Limite ajustado = Limite liberado (Dotação × fração, de
    `saldo_disponivel_a_empenhar`) + remanejado líquido (entradas − saídas). As linhas por
    PTRES e a Situação de cada uma continuam vindo do cálculo original, sem alteração.
  * O valor original e o ajustado ficam sempre lado a lado (reconciliação com a base).
  * Valor em R$ fixo (não uma fração), positivo, com no máximo 2 casas decimais — gravado como
    texto e lido como `Decimal`, sem arredondamento de ponto flutuante no arquivo.
  * Remanejar mais que o saldo do IDUSO de origem NÃO é bloqueado aqui — não há regra
    confirmada sobre isso; a página só avisa.
  * "Desfazer" não apaga o registro: marca `desfeito_em`, preservando o histórico.
  * Cada remanejamento pertence a um exercício (`ano`); só os do exercício corrente valem.

Persistência em disco aprovada explicitamente pelo usuário (28/09/2026), mesmo diretório não
versionado da fração liberada (`src/limite_empenho_preferencias.py`), com a mesma gravação
atômica. Diferente da fração, um arquivo ilegível LANÇA erro em vez de cair em "nenhum
remanejamento": aqui são valores financeiros, e voltar em silêncio aos limites originais
esconderia remanejamentos em vigor.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

CAMINHO_PADRAO = Path("data/limite_empenho/remanejamentos.json")


class RemanejamentoInvalido(ValueError):
    """Remanejamento recusado por regra de validação (origem = destino, valor ≤ 0, etc.)."""


@dataclass(frozen=True)
class Remanejamento:
    id: str
    ano: int
    iduso_origem: str
    iduso_destino: str
    valor: Decimal
    observacao: str
    criado_em: str
    desfeito_em: str | None = None


# ------------------------------------------------------------------ persistência
def _para_json(remanejamento: Remanejamento) -> dict:
    dado = asdict(remanejamento)
    dado["valor"] = str(remanejamento.valor)
    return dado


def _de_json(dado: dict) -> Remanejamento:
    return Remanejamento(
        id=str(dado["id"]),
        ano=int(dado["ano"]),
        iduso_origem=str(dado["iduso_origem"]),
        iduso_destino=str(dado["iduso_destino"]),
        valor=Decimal(str(dado["valor"])),
        observacao=str(dado.get("observacao") or ""),
        criado_em=str(dado["criado_em"]),
        desfeito_em=dado.get("desfeito_em"),
    )


def carregar_remanejamentos(caminho: str | Path | None = None) -> list[Remanejamento]:
    """Todos os remanejamentos gravados (ativos e desfeitos), na ordem de registro. Arquivo
    inexistente = nenhum remanejamento; arquivo ilegível lança `ValueError`."""

    caminho = Path(CAMINHO_PADRAO if caminho is None else caminho)
    if not caminho.exists():
        return []
    try:
        dado = json.loads(caminho.read_text(encoding="utf-8"))
        return [_de_json(item) for item in dado["remanejamentos"]]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation) as error:
        raise ValueError(f"Arquivo de remanejamentos ilegível ({caminho}): {error}") from error


def _gravar(remanejamentos: list[Remanejamento], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    dado = {"remanejamentos": [_para_json(item) for item in remanejamentos]}
    temporario = caminho.parent / f".{caminho.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(json.dumps(dado, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()


def registrar_remanejamento(
    ano: int,
    iduso_origem: str,
    iduso_destino: str,
    valor: Decimal,
    observacao: str = "",
    caminho: str | Path | None = None,
) -> Remanejamento:
    origem = str(iduso_origem).strip()
    destino = str(iduso_destino).strip()
    valor = Decimal(str(valor))
    if not origem or not destino:
        raise RemanejamentoInvalido("Informe o IDUSO de origem e o de destino.")
    if origem == destino:
        raise RemanejamentoInvalido("O IDUSO de origem e o de destino precisam ser diferentes.")
    if not valor.is_finite() or valor <= 0:
        raise RemanejamentoInvalido("O valor remanejado precisa ser maior que zero.")
    if valor != valor.quantize(Decimal("0.01")):
        raise RemanejamentoInvalido("O valor remanejado aceita no máximo 2 casas decimais.")

    caminho = Path(CAMINHO_PADRAO if caminho is None else caminho)
    existentes = carregar_remanejamentos(caminho)
    novo = Remanejamento(
        id=uuid.uuid4().hex,
        ano=int(ano),
        iduso_origem=origem,
        iduso_destino=destino,
        valor=valor,
        observacao=str(observacao or "").strip(),
        criado_em=datetime.now(timezone.utc).isoformat(),
    )
    _gravar(existentes + [novo], caminho)
    return novo


def desfazer_remanejamento(remanejamento_id: str, caminho: str | Path | None = None) -> Remanejamento:
    caminho = Path(CAMINHO_PADRAO if caminho is None else caminho)
    existentes = carregar_remanejamentos(caminho)
    atualizados: list[Remanejamento] = []
    desfeito: Remanejamento | None = None
    for item in existentes:
        if item.id == remanejamento_id and item.desfeito_em is None:
            desfeito = Remanejamento(**{**asdict(item), "desfeito_em": datetime.now(timezone.utc).isoformat()})
            atualizados.append(desfeito)
        else:
            atualizados.append(item)
    if desfeito is None:
        raise RemanejamentoInvalido("Remanejamento não encontrado ou já desfeito.")
    _gravar(atualizados, caminho)
    return desfeito


def remanejamentos_ativos(remanejamentos: list[Remanejamento], ano: int) -> list[Remanejamento]:
    return [item for item in remanejamentos if item.ano == int(ano) and item.desfeito_em is None]


# ------------------------------------------------------------------------ cálculo
def limite_por_iduso_com_remanejamentos(
    resultado: pd.DataFrame, ativos: list[Remanejamento]
) -> pd.DataFrame:
    """Uma linha por IDUSO: `limite_liberado`, `empenhada` e `saldo_disponivel` originais
    (somas de `resultado`, saída de `saldo_disponivel_a_empenhar`), `remanejado_liquido`,
    `limite_ajustado`, `saldo_ajustado` e `ausente_da_base` (IDUSO citado por um
    remanejamento, mas sem nenhuma linha em `resultado` — mostrado, não descartado).

    Limite base nulo (nenhuma Dotação Atualizada conhecida no grupo) mantém o ajustado nulo."""

    agrupado = resultado.groupby("iduso_cod", dropna=False, sort=False)
    base = agrupado[["limite_liberado", "empenhada", "saldo_disponivel"]].sum(min_count=1)
    base.insert(0, "iduso_desc", agrupado["iduso_desc"].first())
    base = base.reset_index()
    base["iduso_cod"] = base["iduso_cod"].astype("string")
    base["ausente_da_base"] = False

    liquido: dict[str, Decimal] = {}
    for item in ativos:
        liquido[item.iduso_origem] = liquido.get(item.iduso_origem, Decimal("0")) - item.valor
        liquido[item.iduso_destino] = liquido.get(item.iduso_destino, Decimal("0")) + item.valor

    presentes = set(base["iduso_cod"].dropna().tolist())
    faltantes = [iduso for iduso in liquido if iduso not in presentes]
    if faltantes:
        extras = pd.DataFrame(
            {
                "iduso_cod": pd.array(faltantes, dtype="string"),
                "iduso_desc": [None] * len(faltantes),
                "limite_liberado": pd.array([pd.NA] * len(faltantes), dtype="Float64"),
                "empenhada": pd.array([pd.NA] * len(faltantes), dtype="Float64"),
                "saldo_disponivel": pd.array([pd.NA] * len(faltantes), dtype="Float64"),
                "ausente_da_base": True,
            }
        )
        base = pd.concat([base, extras], ignore_index=True)

    for coluna in ("limite_liberado", "empenhada", "saldo_disponivel"):
        base[coluna] = base[coluna].astype("Float64")
    base["remanejado_liquido"] = pd.array(
        [float(liquido.get(iduso, Decimal("0"))) if pd.notna(iduso) else 0.0 for iduso in base["iduso_cod"]],
        dtype="Float64",
    )
    base["limite_ajustado"] = base["limite_liberado"] + base["remanejado_liquido"]
    base["saldo_ajustado"] = base["saldo_disponivel"] + base["remanejado_liquido"]
    return base
