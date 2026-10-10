"""Decisões registradas sobre divergência de dotação de Emendas (10/2026).

Camada: regra específica da base de Emendas (sem Streamlit). Spec:
`docs/superpowers/specs/2026-10-10-emendas-ajuste-dotacao-design.md`.

Quando a dotação de uma emenda no relatório importado difere da Dotação Anual do PTRES, o usuário decide —
adotar a Dotação Anual, manter o relatório ou informar outro valor — com justificativa e responsável. Cada
decisão (e cada desfazimento) é um evento JSON IMUTÁVEL em `data/emendas/ajustes_dotacao/`, no mesmo padrão dos
vínculos manuais (`src/vinculos_emendas.py`): nada é editado nem apagado, o estado vigente é reconstruído pela
sequência e validado, e arquivo ilegível LEVANTA erro (nunca vira "sem decisões"). O relatório importado e a
Dotação Anual nunca são alterados; o valor original continua guardado no próprio evento.

Regras: só exercícios >= `ANO_INICIO_ATUALIZACAO`; uma decisão ativa por vínculo (emenda × PTRES); `adotar`
só quando o PTRES tem uma única emenda (a Dotação Anual é do PTRES inteiro e não pode ser atribuída a uma
emenda quando há outras); valor informado aceita zero e recusa vazio/negativo.

Contrato público:
    ErroAjusteDotacao, DIRETORIO_AJUSTES, DECISOES
    registrar_decisao(...) -> dict
    desfazer_decisao(...) -> dict
    carregar_eventos(diretorio) -> list[dict]
    reconstruir_decisoes(eventos) -> list[dict]
    ptres_com_uma_emenda(vinculos, ano, resultado_primario_cod, ptres) -> bool
"""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.emendas_parlamentares import ANO_INICIO_ATUALIZACAO, RPS_EMENDA

DIRETORIO_AJUSTES = Path("data/emendas/ajustes_dotacao")
DECISOES = ("adotar_dotacao_anual", "manter_relatorio", "valor_informado")
ACOES_EVENTO = {"decidir", "desfazer"}
MIN_JUSTIFICATIVA = 10
VERSAO_SCHEMA = 1


class ErroAjusteDotacao(ValueError):
    """Decisão de dotação inválida, ou log de eventos ilegível/incoerente."""


# ------------------------------------------------------------------------------------------ validações


def _texto_obrigatorio(valor: object, campo: str, minimo: int = 1) -> str:
    if not isinstance(valor, str) or len(valor.strip()) < minimo:
        detalhe = f" (mínimo de {minimo} caracteres)" if minimo > 1 else ""
        raise ErroAjusteDotacao(f"{campo} é obrigatório{detalhe}.")
    return valor.strip()


def _numero(valor: object, campo: str, *, permitir_nulo: bool = False) -> float | None:
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        if permitir_nulo:
            return None
        raise ErroAjusteDotacao(f"{campo} deve ser informado.")
    if isinstance(valor, bool) or isinstance(valor, str):
        raise ErroAjusteDotacao(f"{campo} deve ser numérico.")
    numero = float(valor)
    if not math.isfinite(numero) or numero < 0:
        raise ErroAjusteDotacao(f"{campo} deve ser um número maior ou igual a zero.")
    return numero


def _chave(ano: object, resultado_primario_cod: object, emenda_numero: object, ptres: object) -> tuple[int, str, str, str]:
    if isinstance(ano, bool):
        raise ErroAjusteDotacao("Exercício inválido.")
    try:
        ano_inteiro = int(ano)  # type: ignore[arg-type]
        if float(ano) != ano_inteiro:  # type: ignore[arg-type]
            raise ValueError
    except (TypeError, ValueError) as erro:
        raise ErroAjusteDotacao("Exercício inválido.") from erro
    if ano_inteiro < ANO_INICIO_ATUALIZACAO:
        raise ErroAjusteDotacao(
            f"Decisão de dotação só vale para exercícios a partir de {ANO_INICIO_ATUALIZACAO}; "
            "os anteriores permanecem estáticos."
        )
    rp = _texto_obrigatorio(resultado_primario_cod, "Resultado Primário").upper().removeprefix("RP").strip()
    if rp not in RPS_EMENDA:
        raise ErroAjusteDotacao("O Resultado Primário deve ser 6, 7 ou 8.")
    return (
        ano_inteiro,
        rp,
        _texto_obrigatorio(emenda_numero, "Número da emenda"),
        _texto_obrigatorio(ptres, "PTRES"),
    )


def _id_valido(valor: object, nome: str) -> str:
    if not isinstance(valor, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", valor):
        raise ErroAjusteDotacao(f"O identificador do {nome} é inválido.")
    return valor


def _validar_evento(evento: object) -> None:
    if not isinstance(evento, dict):
        raise ErroAjusteDotacao("Evento de decisão de dotação deve ser um objeto JSON.")
    if evento.get("versao_schema") != VERSAO_SCHEMA:
        raise ErroAjusteDotacao("Versão de evento de decisão de dotação não reconhecida.")
    if evento.get("acao") not in ACOES_EVENTO:
        raise ErroAjusteDotacao("Ação de evento de decisão de dotação inválida.")
    _id_valido(evento.get("evento_id"), "evento")
    _id_valido(evento.get("decisao_id"), "decisão")
    _texto_obrigatorio(evento.get("responsavel"), "Responsável")
    _texto_obrigatorio(evento.get("justificativa"), "Justificativa", MIN_JUSTIFICATIVA)
    registrado_em = evento.get("registrado_em")
    try:
        instante = datetime.fromisoformat(registrado_em)  # type: ignore[arg-type]
    except (TypeError, ValueError) as erro:
        raise ErroAjusteDotacao("O evento não possui data de registro válida.") from erro
    if instante.tzinfo is None:
        raise ErroAjusteDotacao("A data do evento deve informar o fuso horário.")
    if evento["acao"] == "decidir":
        _chave(evento.get("ano"), evento.get("resultado_primario_cod"), evento.get("emenda_numero"), evento.get("ptres"))
        if evento.get("decisao") not in DECISOES:
            raise ErroAjusteDotacao("Decisão de dotação inválida no evento.")
        _numero(evento.get("valor_relatorio"), "Valor do relatório")
        _numero(evento.get("valor_dotacao_anual"), "Dotação Anual", permitir_nulo=True)
        _numero(evento.get("valor_efetivo"), "Valor efetivo")


def _ordem(evento: dict) -> tuple[str, str]:
    return str(evento.get("registrado_em", "")), str(evento.get("evento_id", ""))


def _chave_do_evento(evento: dict) -> tuple[int, str, str, str]:
    return _chave(evento["ano"], evento["resultado_primario_cod"], evento["emenda_numero"], evento["ptres"])


# ------------------------------------------------------------------------------------ persistência


def _salvar_evento(evento: dict, diretorio: str | Path) -> Path:
    _validar_evento(evento)
    pasta = Path(diretorio)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{evento['evento_id']}.json"
    if caminho.exists():
        raise FileExistsError(f"Já existe o evento {evento['evento_id']}.")
    temporario = pasta / f".{evento['evento_id']}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(json.dumps(evento, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()
    return caminho


def carregar_eventos(diretorio: str | Path = DIRETORIO_AJUSTES) -> list[dict]:
    """Lê e valida todo o log; um evento inválido ou um histórico incoerente nunca é ignorado."""

    pasta = Path(diretorio)
    if not pasta.exists():
        return []
    eventos: list[dict] = []
    for caminho in sorted(pasta.glob("*.json")):
        try:
            evento = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erro:
            raise ErroAjusteDotacao(f"Não foi possível ler o evento de decisão de dotação {caminho}.") from erro
        try:
            _validar_evento(evento)
        except ErroAjusteDotacao as erro:
            raise ErroAjusteDotacao(f"Evento de decisão de dotação inválido em {caminho}: {erro}") from erro
        evento = dict(evento)
        evento["_arquivo_evento"] = str(caminho)
        eventos.append(evento)
    eventos = sorted(eventos, key=_ordem)
    reconstruir_decisoes(eventos)
    return eventos


def reconstruir_decisoes(eventos: list[dict]) -> list[dict]:
    """Decisões na ordem em que foram tomadas, cada uma com `desfeita`/`desfeita_*`. Levanta
    `ErroAjusteDotacao` para histórico incoerente (desfazer sem decisão, desfazer duas vezes, duas decisões
    ativas no mesmo vínculo, `decisao_id` repetido)."""

    decisoes: dict[str, dict] = {}
    ativa_por_chave: dict[tuple, str] = {}
    for evento in sorted(eventos, key=_ordem):
        decisao_id = evento["decisao_id"]
        if evento["acao"] == "decidir":
            chave = _chave_do_evento(evento)
            if decisao_id in decisoes:
                raise ErroAjusteDotacao(f"Decisão {decisao_id} registrada mais de uma vez.")
            if chave in ativa_por_chave:
                raise ErroAjusteDotacao("Histórico incoerente: duas decisões ativas para o mesmo vínculo.")
            ativa_por_chave[chave] = decisao_id
            decisoes[decisao_id] = {
                "decisao_id": decisao_id,
                "evento_id": evento["evento_id"],
                "ano": chave[0],
                "resultado_primario_cod": chave[1],
                "emenda_numero": chave[2],
                "ptres": chave[3],
                "decisao": evento["decisao"],
                "valor_relatorio": float(evento["valor_relatorio"]),
                "valor_dotacao_anual": None if evento["valor_dotacao_anual"] is None else float(evento["valor_dotacao_anual"]),
                "valor_efetivo": float(evento["valor_efetivo"]),
                "justificativa": evento["justificativa"].strip(),
                "responsavel": evento["responsavel"].strip(),
                "registrado_em": evento["registrado_em"],
                "desfeita": False,
                "desfeita_em": None,
                "desfeita_motivo": None,
                "desfeita_por": None,
            }
        else:
            decisao = decisoes.get(decisao_id)
            if decisao is None:
                raise ErroAjusteDotacao(f"Histórico incoerente: desfazimento de decisão desconhecida ({decisao_id}).")
            if decisao["desfeita"]:
                raise ErroAjusteDotacao(f"Histórico incoerente: decisão {decisao_id} desfeita mais de uma vez.")
            decisao.update(
                desfeita=True,
                desfeita_em=evento["registrado_em"],
                desfeita_motivo=evento["justificativa"].strip(),
                desfeita_por=evento["responsavel"].strip(),
            )
            ativa_por_chave.pop(_chave_da_decisao(decisao), None)
    return list(decisoes.values())


def _chave_da_decisao(decisao: dict) -> tuple[int, str, str, str]:
    return decisao["ano"], decisao["resultado_primario_cod"], decisao["emenda_numero"], decisao["ptres"]


# --------------------------------------------------------------------------------------- operações


def _linhas_da_chave(vinculos: pd.DataFrame, chave: tuple[int, str, str, str]) -> pd.DataFrame:
    ano, rp, emenda, ptres = chave
    rp_serie = vinculos["resultado_primario_cod"].astype("string").str.strip().str.upper().str.removeprefix("RP").str.strip()
    return vinculos[
        vinculos["ano"].astype("Int64").eq(ano)
        & rp_serie.eq(rp)
        & vinculos["emenda_numero"].astype("string").str.strip().eq(emenda)
        & vinculos["ptres"].astype("string").str.strip().eq(ptres)
    ]


def ptres_com_uma_emenda(vinculos: pd.DataFrame, ano: int, resultado_primario_cod: str, ptres: str) -> bool:
    """`True` quando só UMA emenda usa o PTRES naquele exercício/RP — a Dotação Anual (que é do PTRES inteiro)
    só pode ser adotada como dotação de uma emenda nesse caso. PTRES inexistente → `False`."""

    rp = str(resultado_primario_cod).strip().upper().removeprefix("RP").strip()
    rp_serie = vinculos["resultado_primario_cod"].astype("string").str.strip().str.upper().str.removeprefix("RP").str.strip()
    do_ptres = vinculos[
        vinculos["ano"].astype("Int64").eq(int(ano))
        & rp_serie.eq(rp)
        & vinculos["ptres"].astype("string").str.strip().eq(str(ptres).strip())
    ]
    return do_ptres["emenda_numero"].astype("string").str.strip().nunique() == 1


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def registrar_decisao(
    *,
    vinculos: pd.DataFrame,
    ano: int,
    resultado_primario_cod: str,
    emenda_numero: str,
    ptres: str,
    decisao: str,
    valor_informado: float | None,
    justificativa: str,
    responsavel: str,
    diretorio: str | Path = DIRETORIO_AJUSTES,
) -> dict:
    """Valida e grava a decisão sobre a divergência de dotação de um vínculo (emenda × PTRES). `vinculos` é
    `ResultadoVinculoEmendas.vinculos`; os valores de referência (relatório e Dotação Anual) são lidos DELE no
    momento da decisão e gravados no evento — é o que permite detectar, depois, que o relatório mudou
    (decisão obsoleta). Devolve o evento gravado."""

    if decisao not in DECISOES:
        raise ErroAjusteDotacao(f"Decisão inválida: {decisao!r}.")
    justificativa = _texto_obrigatorio(justificativa, "Justificativa", MIN_JUSTIFICATIVA)
    responsavel = _texto_obrigatorio(responsavel, "Responsável")
    chave = _chave(ano, resultado_primario_cod, emenda_numero, ptres)

    linhas = _linhas_da_chave(vinculos, chave)
    if linhas.empty:
        raise ErroAjusteDotacao("Vínculo (emenda × PTRES) não encontrado nos dados atuais.")
    if len(linhas) > 1:
        raise ErroAjusteDotacao("Mais de uma linha para o mesmo vínculo; não é possível decidir com segurança.")
    linha = linhas.iloc[0]

    original = linha["dotacao_relatorio"] if "dotacao_relatorio" in linhas.columns else linha["dotacao_atualizada"]
    valor_relatorio = _numero(original, "Dotação do relatório")
    anual = linha["dotacao_anual_ptres"] if "dotacao_anual_ptres" in linhas.columns else None
    valor_anual = _numero(anual, "Dotação Anual", permitir_nulo=True)

    if decisao == "adotar_dotacao_anual":
        if valor_anual is None:
            raise ErroAjusteDotacao("Não há Dotação Anual para este PTRES: não é possível adotá-la.")
        if not ptres_com_uma_emenda(vinculos, chave[0], chave[1], chave[3]):
            raise ErroAjusteDotacao(
                "O PTRES tem mais de uma emenda: a Dotação Anual é do PTRES inteiro e não pode ser adotada "
                "como dotação de uma só. Informe o valor da emenda."
            )
        valor_efetivo = valor_anual
    elif decisao == "manter_relatorio":
        valor_efetivo = valor_relatorio
    else:
        valor_efetivo = _numero(valor_informado, "Valor informado")

    for existente in reconstruir_decisoes(carregar_eventos(diretorio)):
        if not existente["desfeita"] and _chave_da_decisao(existente) == chave:
            raise ErroAjusteDotacao("Já existe uma decisão ativa para este vínculo: desfaça-a antes de decidir de novo.")

    evento = {
        "versao_schema": VERSAO_SCHEMA,
        "evento_id": str(uuid.uuid4()),
        "acao": "decidir",
        "decisao_id": str(uuid.uuid4()),
        "ano": chave[0],
        "resultado_primario_cod": chave[1],
        "emenda_numero": chave[2],
        "ptres": chave[3],
        "decisao": decisao,
        "valor_relatorio": valor_relatorio,
        "valor_dotacao_anual": valor_anual,
        "valor_efetivo": valor_efetivo,
        "justificativa": justificativa,
        "responsavel": responsavel,
        "registrado_em": _agora(),
    }
    _salvar_evento(evento, diretorio)
    return evento


def desfazer_decisao(
    *,
    decisao_id: str,
    justificativa: str,
    responsavel: str,
    diretorio: str | Path = DIRETORIO_AJUSTES,
) -> dict:
    """Acrescenta o evento de desfazimento; o evento original permanece. A decisão precisa existir e estar ativa."""

    justificativa = _texto_obrigatorio(justificativa, "Justificativa", MIN_JUSTIFICATIVA)
    responsavel = _texto_obrigatorio(responsavel, "Responsável")
    decisoes = {d["decisao_id"]: d for d in reconstruir_decisoes(carregar_eventos(diretorio))}
    decisao = decisoes.get(decisao_id)
    if decisao is None:
        raise ErroAjusteDotacao("Decisão não encontrada.")
    if decisao["desfeita"]:
        raise ErroAjusteDotacao("Esta decisão já foi desfeita.")
    evento = {
        "versao_schema": VERSAO_SCHEMA,
        "evento_id": str(uuid.uuid4()),
        "acao": "desfazer",
        "decisao_id": decisao_id,
        "justificativa": justificativa,
        "responsavel": responsavel,
        "registrado_em": _agora(),
    }
    _salvar_evento(evento, diretorio)
    return evento
