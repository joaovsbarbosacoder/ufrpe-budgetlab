"""Regras de negócio da Captação de Demandas — funções puras, sem banco nem interface.

Cada regra cita o código RN-xx / seção do projeto de origem (`docs/PROJETO.md`).
Valores monetários são sempre `Decimal` (nunca `float`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# --- Domínios -----------------------------------------------------------------------

TIPOS = ("MATERIAL_CONSUMO", "SERVICO", "EQUIPAMENTO_PERMANENTE", "OBRA_REFORMA")
NATUREZAS = ("CUSTEIO", "CAPITAL")
PRIORIDADES = ("ESSENCIAL", "IMPORTANTE", "DESEJAVEL")

FASES_CICLO = ("RASCUNHO", "AGENDADO", "ABERTO", "ENCERRADO", "EM_ANALISE", "CONCLUIDO")

SITUACAO_RASCUNHO = "RASCUNHO"
SITUACAO_ENVIADA = "ENVIADA"
SITUACAO_VALIDADA_CHEFIA = "VALIDADA_CHEFIA"
SITUACAO_VALIDADA_PROPLAD = "VALIDADA_PROPLAD"
SITUACAO_INCLUIDA = "INCLUIDA_PROPOSTA"
SITUACAO_NAO_INCLUIDA = "NAO_INCLUIDA"

# Seção 5.2: devolução (chefia ou PROPLAD) é evento, não situação — a demanda volta a
# RASCUNHO com `devolvida=True`.
TRANSICOES: dict[str, frozenset[str]] = {
    SITUACAO_RASCUNHO: frozenset({SITUACAO_ENVIADA}),
    SITUACAO_ENVIADA: frozenset({SITUACAO_VALIDADA_CHEFIA, SITUACAO_RASCUNHO}),
    SITUACAO_VALIDADA_CHEFIA: frozenset({SITUACAO_VALIDADA_PROPLAD, SITUACAO_RASCUNHO}),
    SITUACAO_VALIDADA_PROPLAD: frozenset({SITUACAO_INCLUIDA, SITUACAO_NAO_INCLUIDA}),
    SITUACAO_INCLUIDA: frozenset(),
    SITUACAO_NAO_INCLUIDA: frozenset(),
}

MINIMO_CARACTERES_JUSTIFICATIVA = 200  # RN-02

_NATUREZA_POR_TIPO = {
    "MATERIAL_CONSUMO": "CUSTEIO",
    "SERVICO": "CUSTEIO",
    "EQUIPAMENTO_PERMANENTE": "CAPITAL",
    "OBRA_REFORMA": "CAPITAL",
}

_CENTAVOS = Decimal("0.01")


class ErroRegra(Exception):
    """Violação de regra de negócio; `pendencias` lista cada motivo (RN-08)."""

    def __init__(self, pendencias: Sequence[str]):
        self.pendencias = list(pendencias)
        super().__init__("; ".join(self.pendencias))


# --- RN-03 / RN-04 / RN-10 ----------------------------------------------------------


def para_decimal(valor: object) -> Decimal | None:
    """Converte para `Decimal`; `None` para vazio ou inválido. `float` é recusado de
    propósito (TypeError) — o valor financeiro chega como `str`, `int` ou `Decimal`."""

    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if isinstance(valor, float):
        raise TypeError("Valor monetário não pode ser float; use Decimal ou str.")
    try:
        numero = Decimal(str(valor).strip().replace(",", ".")) if isinstance(valor, str) else Decimal(valor)
    except (InvalidOperation, ValueError):
        return None
    return numero if numero.is_finite() else None


def calcular_valor_total(quantidade: object, valor_unitario: object) -> Decimal | None:
    """RN-03: quantidade × valor unitário, em `Decimal`, 2 casas (meio para cima).

    `None` quando algum dos dois está ausente/inválido ou não é positivo — nunca zero:
    diferencia valor nulo de zero. O valor total vindo do cliente nunca é consultado."""

    unitario = para_decimal(valor_unitario)
    if isinstance(quantidade, bool) or not isinstance(quantidade, int):
        return None
    if quantidade <= 0 or unitario is None or unitario <= 0:
        return None
    return (Decimal(quantidade) * unitario).quantize(_CENTAVOS, rounding=ROUND_HALF_UP)


def natureza_sugerida(tipo: str | None) -> str | None:
    """RN-04: Material de consumo e Serviço → Custeio; Equipamento e Obra/reforma → Capital."""

    return _NATUREZA_POR_TIPO.get(tipo or "")


def natureza_efetiva(natureza_final: str | None, sugerida: str | None) -> str | None:
    """A natureza final (PROPLAD) vale; se vazia, vale a sugerida."""

    return natureza_final or sugerida


def exige_alerta_classificacao(tipo: str | None) -> bool:
    """RN-04: Obra/reforma deve mostrar o alerta de classificação (manutenção e
    conservação tendem a Custeio; ampliação e benfeitoria tendem a Capital)."""

    return tipo == "OBRA_REFORMA"


# --- Ciclo: fases e prazos (seção 4, RN-05, RN-06) ----------------------------------


def fase_por_data(fase: str, abertura: date | None, encerramento: date | None, hoje: date) -> str:
    """Fase do ciclo considerando a transição automática pela data (seção 4.1).

    Só AGENDADO → ABERTO (a partir da data de abertura, inclusive) e ABERTO → ENCERRADO
    (depois da data de encerramento) são automáticas; as demais fases só mudam por ação
    manual do gestor. Datas ausentes não disparam transição."""

    if fase == "AGENDADO" and abertura is not None and hoje >= abertura:
        fase = "ABERTO"
    if fase == "ABERTO" and encerramento is not None and hoje > encerramento:
        fase = "ENCERRADO"
    return fase


def prazo_efetivo(encerramento: date | None, prorrogacao: date | None) -> date | None:
    """Seção 4.3: com prorrogação, o prazo da unidade passa a ser o da prorrogação."""

    return prorrogacao if prorrogacao is not None else encerramento


def pode_registrar(
    fase: str,
    abertura: date | None,
    encerramento: date | None,
    prorrogacao: date | None,
    hoje: date,
    permite_rascunho_antecipado: bool = False,
) -> bool:
    """RN-05: criar, editar, importar e enviar só com o ciclo ABERTO e hoje ≤ prazo efetivo
    da unidade. A fase armazenada decide (ex.: encerramento manual bloqueia mesmo antes do
    prazo); a data decide a abertura e o prazo — por isso uma unidade prorrogada continua
    podendo registrar depois do encerramento geral.

    Antes da abertura (AGENDADO) só vale se o ciclo permitir rascunho antecipado, e então
    apenas para salvar rascunho — o envio exige `hoje >= abertura` (ver `pode_enviar`)."""

    if fase not in ("AGENDADO", "ABERTO"):
        return False
    if abertura is not None and hoje < abertura:
        return fase == "AGENDADO" and permite_rascunho_antecipado
    limite = prazo_efetivo(encerramento, prorrogacao)
    return limite is None or hoje <= limite


def pode_enviar(
    fase: str,
    abertura: date | None,
    encerramento: date | None,
    prorrogacao: date | None,
    hoje: date,
    devolvida: bool = False,
    prazo_validacao: date | None = None,
) -> bool:
    """RN-05 e RN-06 para o envio. Enviar exige o ciclo já aberto (`hoje >= abertura`).
    Demanda devolvida pode ser corrigida e reenviada até o prazo de validação pela chefia,
    mesmo após o encerramento do registro (RN-06)."""

    if devolvida and prazo_validacao is not None and hoje <= prazo_validacao and fase != "RASCUNHO":
        return True
    if abertura is not None and hoje < abertura:
        return False
    return pode_registrar(fase, abertura, encerramento, prorrogacao, hoje)


# --- RN-01 / RN-02 / RN-08: validação de envio --------------------------------------


def validar_envio(
    demanda: Mapping[str, object],
    permitir_excecao_vinculo_pls: bool = True,
) -> list[str]:
    """Pendências que impedem o envio; lista vazia = pode enviar (RN-08: nada é enviado
    parcialmente). Rascunhos incompletos podem ser salvos sem passar por aqui (RN-02).

    `demanda` traz `objetivos_pdi` e `metas_pls` (listas de ids), além dos campos da
    seção 5.1. O vínculo ao PDI é sempre obrigatório. A exceção da RN-01 (envio sem meta
    do PLS quando a unidade solicita análise pela PROPLAD) segue o padrão do projeto, mas
    o próprio projeto marca como PONTO EM ABERTO (seção 13, item 4) — por isso é um
    parâmetro, não uma regra fixa."""

    pendencias: list[str] = []

    if demanda.get("tipo") not in TIPOS:
        pendencias.append("Tipo da demanda")
    if not str(demanda.get("descricao") or "").strip():
        pendencias.append("Descrição do item")
    quantidade = demanda.get("quantidade")
    if isinstance(quantidade, bool) or not isinstance(quantidade, int) or quantidade <= 0:
        pendencias.append("Quantidade (inteiro maior que zero)")
    if not str(demanda.get("unidade_fornecimento") or "").strip():
        pendencias.append("Unidade de fornecimento")
    unitario = para_decimal(demanda.get("valor_unitario"))
    if unitario is None or unitario <= 0:
        pendencias.append("Valor unitário (maior que zero)")
    if demanda.get("prioridade") not in PRIORIDADES:
        pendencias.append("Prioridade")

    if not demanda.get("objetivos_pdi"):
        pendencias.append("Pelo menos um objetivo do PDI")
    if not demanda.get("metas_pls"):
        if not (permitir_excecao_vinculo_pls and demanda.get("solicita_analise_vinculo")):
            pendencias.append("Pelo menos uma meta do PLS")

    if not str(demanda.get("contribuicao") or "").strip():
        pendencias.append("Contribuição para as metas")
    justificativa = str(demanda.get("justificativa") or "").strip()
    if len(justificativa) < MINIMO_CARACTERES_JUSTIFICATIVA:
        pendencias.append(f"Justificativa com pelo menos {MINIMO_CARACTERES_JUSTIFICATIVA} caracteres")

    return pendencias


def transicao_permitida(de: str, para: str) -> bool:
    """Seção 5.2: só as transições do diagrama de situações."""

    return para in TRANSICOES.get(de, frozenset())
