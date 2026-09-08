"""
Cadastro manual de Prazos Orçamentários — datas que o próprio usuário registra (ex.:
prestação de contas, envio de relatório, prazo de empenho de uma fonte específica) para
receber alerta conforme a data se aproxima. Não deriva de nenhuma base do Tesouro nem de
outra página do projeto (nem Contratos, nem Bolsas — pedido explícito): um cadastro simples,
tipicamente feito no início do exercício.

Camada: regra de negócio de uma base própria (cadastro manual). Depende só de pandas/stdlib.
Não importa Streamlit.

Persistência: um arquivo JSON por registro em `DIRETORIO_PADRAO`, gravação atômica via
arquivo temporário + rename — mesmo padrão de `src.emendas_parlamentares.salvar`/
`carregar_emendas_cadastradas`. Dado real de produção, não versionado (ver `.gitignore`,
mesmo motivo de `data/emendas/`).

Antecedência do alerta é por prazo, não um limiar fixo global: cada prazo tem seu próprio
`dias_antecedencia` (pedido explícito — "selecionar com quantos dias de antecedência eu
gostaria de estar recebendo alertas"), porque prazos diferentes pedem antecedências
diferentes (ex.: uma licitação precisa de meses de aviso; uma tarefa simples, de dias). Por
isso a classificação aqui é própria (`_classificar`), não mais
`src.contratos_vigencia.classificar_criticidade` (que usa uma régua fixa de 60/120 dias —
fazia sentido só enquanto a criticidade não era configurável por item).

Contrato público:
    novo_prazo(titulo, data_prazo, descricao="", responsavel="", dias_antecedencia=30) -> dict
    salvar(prazo, diretorio=DIRETORIO_PADRAO) -> Path
    atualizar(prazo, diretorio=DIRETORIO_PADRAO) -> Path
    excluir(identificador, diretorio=DIRETORIO_PADRAO) -> None
    carregar_prazos(diretorio=DIRETORIO_PADRAO) -> list[dict]
    prazos_com_criticidade(prazos, hoje=None) -> pd.DataFrame
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

DIRETORIO_PADRAO = Path("data/prazos_orcamentarios")

#: antecedência padrão (dias) sugerida no cadastro quando o usuário não escolhe outra.
DIAS_ANTECEDENCIA_PADRAO = 30

#: colunas do DataFrame vazio devolvido por `prazos_com_criticidade` quando não há cadastro —
#: mesmo esquema de quando há dados, para quem consome não precisar tratar caso especial.
_COLUNAS = (
    "id", "titulo", "data_prazo", "descricao", "responsavel", "dias_antecedencia",
    "concluido", "criado_em", "atualizado_em", "dias_para_vencer", "criticidade",
)


class ErroPrazoOrcamentario(ValueError):
    """Cadastro de prazo inválido — nunca gravar um registro incompleto."""


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def novo_prazo(
    titulo: str,
    data_prazo: date,
    descricao: str = "",
    responsavel: str = "",
    dias_antecedencia: int = DIAS_ANTECEDENCIA_PADRAO,
) -> dict:
    """Monta um registro novo (ainda não gravado — ver `salvar`). `id` sempre novo, mesmo que
    o título repita um prazo já cadastrado (não há chave natural: dois prazos podem ter o
    mesmo título em contextos diferentes)."""

    titulo = titulo.strip()
    if not titulo:
        raise ErroPrazoOrcamentario("Informe um título para o prazo.")
    if not isinstance(data_prazo, date):
        raise ErroPrazoOrcamentario("Data do prazo inválida.")
    if isinstance(dias_antecedencia, bool) or not isinstance(dias_antecedencia, int) or dias_antecedencia < 0:
        raise ErroPrazoOrcamentario("Dias de antecedência deve ser um número inteiro não negativo.")

    agora = _agora_iso()
    return {
        "id": str(uuid.uuid4()),
        "titulo": titulo,
        "data_prazo": data_prazo.isoformat(),
        "descricao": descricao.strip(),
        "responsavel": responsavel.strip(),
        "dias_antecedencia": dias_antecedencia,
        "concluido": False,
        "criado_em": agora,
        "atualizado_em": agora,
    }


def _caminho(identificador: str, diretorio: Path) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", identificador):
        raise ErroPrazoOrcamentario("Identificador de prazo inválido.")
    return diretorio / f"{identificador}.json"


def _gravar_atomico(prazo: dict, caminho: Path) -> None:
    temporario = caminho.parent / f".{prazo['id']}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(json.dumps(prazo, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()


def salvar(prazo: dict, diretorio: str | Path = DIRETORIO_PADRAO) -> Path:
    """Grava um cadastro novo atomicamente, sem sobrescrever outro ID — mesmo padrão de
    `src.emendas_parlamentares.salvar`."""

    diretorio = Path(diretorio)
    diretorio.mkdir(parents=True, exist_ok=True)
    caminho = _caminho(str(prazo["id"]), diretorio)
    if caminho.exists():
        raise FileExistsError(f"Já existe um prazo com o ID {prazo['id']}.")
    _gravar_atomico(prazo, caminho)
    return caminho


def atualizar(prazo: dict, diretorio: str | Path = DIRETORIO_PADRAO) -> Path:
    """Sobrescreve um cadastro já existente (edição de campo ou marcar concluído/reabrir) — só
    aceita ID já gravado, para este caminho nunca criar um registro novo por engano."""

    diretorio = Path(diretorio)
    caminho = _caminho(str(prazo["id"]), diretorio)
    if not caminho.exists():
        raise FileNotFoundError(f"Nenhum prazo cadastrado com o ID {prazo['id']}.")
    prazo = {**prazo, "atualizado_em": _agora_iso()}
    _gravar_atomico(prazo, caminho)
    return caminho


def excluir(identificador: str, diretorio: str | Path = DIRETORIO_PADRAO) -> None:
    """Remove o cadastro em definitivo — sem lixeira nem histórico (diferente do log de
    eventos de vínculos de Emendas: aqui não há dado oficial pra reconciliar depois, só um
    lembrete que deixou de fazer sentido)."""

    _caminho(identificador, Path(diretorio)).unlink(missing_ok=True)


def carregar_prazos(diretorio: str | Path = DIRETORIO_PADRAO) -> list[dict]:
    diretorio = Path(diretorio)
    if not diretorio.exists():
        return []
    return [
        json.loads(caminho.read_text(encoding="utf-8"))
        for caminho in sorted(diretorio.glob("*.json"))
    ]


def _classificar(dias_para_vencer: int, dias_antecedencia: int) -> str:
    """Vencido (passou da data) / Em alerta (dentro da antecedência escolhida para ESTE
    prazo) / No prazo (fora da antecedência ainda). Não há "Crítico"/"Atenção" fixos: quem
    decide o quão cedo avisar é o `dias_antecedencia` de cada prazo, não uma régua global."""

    if dias_para_vencer < 0:
        return "Vencido"
    if dias_para_vencer <= dias_antecedencia:
        return "Em alerta"
    return "No prazo"


def prazos_com_criticidade(prazos: list[dict], hoje: date | None = None) -> pd.DataFrame:
    """Uma linha por prazo cadastrado, com `dias_para_vencer`/`criticidade` calculados a
    partir de `hoje` (padrão `date.today()`, parametrizável para os testes ficarem
    determinísticos) — nunca de um campo gravado, para não desatualizar sozinho.

    `criticidade` é "Vencido"/"Em alerta"/"No prazo" a partir da antecedência própria de
    cada prazo (`dias_antecedencia`, ver `_classificar`) — dois prazos com o mesmo
    `dias_para_vencer` podem ter criticidades diferentes se pediram antecedências diferentes.
    Prazo já `concluido` sempre mostra "Concluído", mesmo com a data já vencida.

    Ordena por: não concluídos primeiro, depois por dias até vencer (vencidos primeiro; sem
    data — não deveria acontecer, mas não é motivo pra quebrar a tela — por último)."""

    hoje = hoje or date.today()
    if not prazos:
        return pd.DataFrame(columns=_COLUNAS)

    dataframe = pd.DataFrame(prazos)
    if "dias_antecedencia" not in dataframe.columns:
        dataframe["dias_antecedencia"] = DIAS_ANTECEDENCIA_PADRAO
    dataframe["dias_antecedencia"] = dataframe["dias_antecedencia"].fillna(DIAS_ANTECEDENCIA_PADRAO).astype(int)
    dataframe["data_prazo"] = pd.to_datetime(dataframe["data_prazo"]).dt.date
    dataframe["dias_para_vencer"] = dataframe["data_prazo"].apply(lambda d: (d - hoje).days)
    dataframe["criticidade"] = [
        _classificar(dias, antecedencia)
        for dias, antecedencia in zip(dataframe["dias_para_vencer"], dataframe["dias_antecedencia"])
    ]
    dataframe.loc[dataframe["concluido"], "criticidade"] = "Concluído"

    return dataframe.sort_values(["concluido", "dias_para_vencer"], na_position="last").reset_index(drop=True)
