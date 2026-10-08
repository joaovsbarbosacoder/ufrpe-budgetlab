"""Persistência da seleção de células e das despesas manuais do Resultado Orçamentário.

Decisão (08/10/2026): gravar em disco a seleção de células (quais combinações de IDUSO,
resultado primário, ação, PTRES, plano orçamentário, grupo de despesa e fonte detalhada o
usuário escolheu) e as despesas manuais (valores que ainda não existem na base de execução).
Motivo: sem isso, atualizar a página (F5) cria uma sessão nova no Streamlit e o usuário
perderia o que montou. Persistência em arquivo aprovada explicitamente pelo usuário em
08/10/2026, conforme exige o AGENTS.md deste projeto.

Um diretório por exercício: `<diretorio>/<exercicio>/celulas.json` e
`<diretorio>/<exercicio>/despesas_manuais.json`. Gravação atômica (temporário + `Path.replace`),
mesmo padrão de `src.limite_empenho_preferencias`. Os códigos são sempre texto, para preservar
zeros à esquerda (ex.: plano orçamentário "0000"). Células que não existem mais na base são
mantidas na seleção — quem consome decide como exibi-las. Dado real de instância, não
versionado (ver `.gitignore`).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

CHAVE_CELULA: tuple[str, ...] = (
    "iduso_codigo",
    "resultado_primario_codigo",
    "acao_codigo",
    "ptres_codigo",
    "plano_orcamentario_codigo",
    "grupo_despesa_codigo",
    "fonte_recursos_detalhada_codigo",
)
CelulaChave = tuple[str | None, ...]
DIRETORIO_PADRAO = Path("data/resultado_orcamentario")


class ArquivoCorrompido(ValueError):
    """O arquivo JSON existe, mas não pôde ser lido no formato esperado."""


@dataclass(frozen=True)
class DespesaManual:
    id: str
    descricao: str
    valor: float
    observacao: str | None
    celula: CelulaChave | None
    criado_em: str
    atualizado_em: str


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pasta(exercicio: int, diretorio: Path) -> Path:
    return Path(diretorio) / str(int(exercicio))


def _gravar_atomico(caminho: Path, dado: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.parent / f".{caminho.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(json.dumps(dado, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()


def _ler(caminho: Path) -> dict | None:
    if not caminho.exists():
        return None
    try:
        dado = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as erro:
        raise ArquivoCorrompido(f"Arquivo ilegível: {caminho}") from erro
    if not isinstance(dado, dict):
        raise ArquivoCorrompido(f"Formato inesperado: {caminho}")
    return dado


def _para_chave(valores: list) -> CelulaChave:
    return tuple(None if v is None else str(v) for v in valores)


def carregar_selecao(exercicio: int, diretorio: Path = DIRETORIO_PADRAO) -> list[CelulaChave]:
    dado = _ler(_pasta(exercicio, diretorio) / "celulas.json")
    if dado is None:
        return []
    try:
        return [_para_chave(c) for c in dado["celulas"]]
    except (KeyError, TypeError) as erro:
        raise ArquivoCorrompido("Formato inesperado em celulas.json") from erro


def salvar_selecao(exercicio: int, celulas: list[CelulaChave], diretorio: Path = DIRETORIO_PADRAO) -> None:
    dado = {"celulas": [list(c) for c in celulas], "atualizado_em": _agora()}
    _gravar_atomico(_pasta(exercicio, diretorio) / "celulas.json", dado)


def _caminho_despesas(exercicio: int, diretorio: Path) -> Path:
    return _pasta(exercicio, diretorio) / "despesas_manuais.json"


def carregar_despesas(exercicio: int, diretorio: Path = DIRETORIO_PADRAO) -> list[DespesaManual]:
    dado = _ler(_caminho_despesas(exercicio, diretorio))
    if dado is None:
        return []
    try:
        return [
            DespesaManual(
                id=d["id"],
                descricao=d["descricao"],
                valor=float(d["valor"]),
                observacao=d.get("observacao"),
                celula=None if d.get("celula") is None else _para_chave(d["celula"]),
                criado_em=d["criado_em"],
                atualizado_em=d["atualizado_em"],
            )
            for d in dado["despesas"]
        ]
    except (KeyError, TypeError, ValueError) as erro:
        raise ArquivoCorrompido("Formato inesperado em despesas_manuais.json") from erro


def _salvar_despesas(exercicio: int, despesas: list[DespesaManual], diretorio: Path) -> None:
    itens = []
    for d in despesas:
        item = asdict(d)
        item["celula"] = None if d.celula is None else list(d.celula)
        itens.append(item)
    _gravar_atomico(_caminho_despesas(exercicio, diretorio), {"despesas": itens})


def validar_despesa(descricao: str, valor: float | None) -> list[str]:
    """Mensagens de erro da despesa informada; lista vazia significa válida."""

    erros = []
    if not (descricao or "").strip():
        erros.append("Informe a descrição da despesa.")
    if valor is None:
        erros.append("Informe o valor da despesa.")
    elif valor <= 0:
        erros.append("O valor da despesa deve ser maior que zero.")
    return erros


def _validar_ou_levantar(descricao: str, valor: float | None) -> None:
    erros = validar_despesa(descricao, valor)
    if erros:
        raise ValueError("; ".join(erros))


def incluir_despesa(
    exercicio: int,
    descricao: str,
    valor: float,
    observacao: str | None,
    celula: CelulaChave | None,
    diretorio: Path = DIRETORIO_PADRAO,
) -> DespesaManual:
    _validar_ou_levantar(descricao, valor)
    agora = _agora()
    nova = DespesaManual(
        id=uuid.uuid4().hex,
        descricao=descricao.strip(),
        valor=float(valor),
        observacao=observacao,
        celula=None if celula is None else tuple(celula),
        criado_em=agora,
        atualizado_em=agora,
    )
    _salvar_despesas(exercicio, [*carregar_despesas(exercicio, diretorio), nova], diretorio)
    return nova


def atualizar_despesa(
    exercicio: int,
    id_despesa: str,
    descricao: str,
    valor: float,
    observacao: str | None,
    celula: CelulaChave | None,
    diretorio: Path = DIRETORIO_PADRAO,
) -> DespesaManual:
    _validar_ou_levantar(descricao, valor)
    despesas = carregar_despesas(exercicio, diretorio)
    for i, atual in enumerate(despesas):
        if atual.id == id_despesa:
            nova = replace(
                atual,
                descricao=descricao.strip(),
                valor=float(valor),
                observacao=observacao,
                celula=None if celula is None else tuple(celula),
                atualizado_em=_agora(),
            )
            despesas[i] = nova
            _salvar_despesas(exercicio, despesas, diretorio)
            return nova
    raise KeyError(f"Despesa inexistente: {id_despesa}")


def excluir_despesa(exercicio: int, id_despesa: str, diretorio: Path = DIRETORIO_PADRAO) -> None:
    despesas = carregar_despesas(exercicio, diretorio)
    _salvar_despesas(exercicio, [d for d in despesas if d.id != id_despesa], diretorio)
