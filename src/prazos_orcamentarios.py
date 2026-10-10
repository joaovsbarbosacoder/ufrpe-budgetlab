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
o antigo `classificar_criticidade` de Contratos — Vigência (régua fixa de 60/120 dias —
fazia sentido só enquanto a criticidade não era configurável por item). Reconfirmado em
10/09/2026 ao adotar o layout "Gerenciamento de Prazos" (`LAYOUT.md` anexado pelo usuário,
que sugeria um limiar fixo de 7 dias): o usuário optou por MANTER a antecedência própria por
prazo em vez de trocar pelo limiar fixo do layout — só os RÓTULOS de criticidade
("Em dia"/"Vencendo"/"Atrasado"/"Concluído") vieram do layout novo, a REGRA por trás
continua a mesma.

`tipo`/`categoria`/`prioridade` (campos novos, mesmo pedido de 10/09/2026 — layout
"Gerenciamento de Prazos"): `tipo` distingue prazo fixo do calendário do exercício
("Calendário anual") de tarefa do dia a dia ("Solicitação"); `categoria` é texto livre
(ex. "SIAFI", "PROPLAD"); `prioridade` não afeta a criticidade (que já vem da data/
antecedência) — é só um campo informativo de cadastro, como no layout de referência.
Registro gravado ANTES destes 3 campos existirem é tratado como legado: `prazos_com_
criticidade` preenche com o padrão (`TIPO_PADRAO`/`""`/`PRIORIDADE_PADRAO`), mesmo
princípio já usado para `dias_antecedencia` ausente.

Campos de sincronização com o Google Agenda (27/09/2026, ver
`docs/superpowers/specs/2026-09-27-google-agenda-design.md`): `google_event_id`,
`sincronizado_em`, `google_atualizado_em`, `removido_no_google` — gravados só por
`src/prazos_sincronizacao.py` via `gravar_estado_sincronizacao` (que NÃO carimba
`atualizado_em`, senão toda sincronização pareceria alteração local). A tela edita com
`editar`, que preserva esses campos — reconstruir o registro com `novo_prazo` perderia o
vínculo e duplicaria o evento no Google.

Contrato público:
    novo_prazo(titulo, data_prazo, descricao="", responsavel="", dias_antecedencia=30,
               tipo=TIPO_PADRAO, categoria="", prioridade=PRIORIDADE_PADRAO) -> dict
    salvar(prazo, diretorio=DIRETORIO_PADRAO) -> Path
    atualizar(prazo, diretorio=DIRETORIO_PADRAO) -> Path
    editar(identificador, campos, diretorio=DIRETORIO_PADRAO) -> dict
    gravar_estado_sincronizacao(prazo, diretorio=DIRETORIO_PADRAO) -> Path
    excluir(identificador, diretorio=DIRETORIO_PADRAO) -> None
    carregar_prazo(identificador, diretorio=DIRETORIO_PADRAO) -> dict
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

#: layout "Gerenciamento de Prazos" (10/09/2026) — dois tipos de prazo: fixo do calendário
#: do exercício, ou tarefa do dia a dia.
TIPOS_PRAZO = ("Calendário anual", "Solicitação")
TIPO_PADRAO = "Solicitação"

#: só informativo no cadastro — não entra na regra de criticidade (que já vem da data e da
#: antecedência própria do prazo).
PRIORIDADES_PRAZO = ("Essencial", "Importante", "Desejável")
PRIORIDADE_PADRAO = "Importante"

#: estado da sincronização com o Google Agenda — nunca editado pela tela.
CAMPOS_SINCRONIZACAO = ("google_event_id", "sincronizado_em", "google_atualizado_em", "removido_no_google")
#: únicos campos que a tela (formulário/checkbox do card) pode alterar via `editar`.
CAMPOS_EDITAVEIS = (
    "titulo", "data_prazo", "descricao", "responsavel", "dias_antecedencia",
    "tipo", "categoria", "prioridade", "concluido",
)

#: colunas do DataFrame vazio devolvido por `prazos_com_criticidade` quando não há cadastro —
#: mesmo esquema de quando há dados, para quem consome não precisar tratar caso especial.
_COLUNAS = (
    "id", "titulo", "data_prazo", "descricao", "responsavel", "dias_antecedencia",
    "tipo", "categoria", "prioridade",
    "concluido", "criado_em", "atualizado_em", *CAMPOS_SINCRONIZACAO,
    "dias_para_vencer", "criticidade",
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
    tipo: str = TIPO_PADRAO,
    categoria: str = "",
    prioridade: str = PRIORIDADE_PADRAO,
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
    if tipo not in TIPOS_PRAZO:
        raise ErroPrazoOrcamentario(f"Tipo de prazo inválido: {tipo!r}.")
    if prioridade not in PRIORIDADES_PRAZO:
        raise ErroPrazoOrcamentario(f"Prioridade inválida: {prioridade!r}.")

    agora = _agora_iso()
    return {
        "id": str(uuid.uuid4()),
        "titulo": titulo,
        "data_prazo": data_prazo.isoformat(),
        "descricao": descricao.strip(),
        "responsavel": responsavel.strip(),
        "dias_antecedencia": dias_antecedencia,
        "tipo": tipo,
        "categoria": categoria.strip(),
        "prioridade": prioridade,
        "concluido": False,
        "criado_em": agora,
        "atualizado_em": agora,
        "google_event_id": None,
        "sincronizado_em": None,
        "google_atualizado_em": None,
        "removido_no_google": False,
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
    if not prazo.get("concluido"):
        # reaberto: o evento deve ser recriado na próxima sincronização
        prazo["removido_no_google"] = False
    _gravar_atomico(prazo, caminho)
    return caminho


def excluir(identificador: str, diretorio: str | Path = DIRETORIO_PADRAO) -> None:
    """Remove o cadastro em definitivo — sem lixeira nem histórico (diferente do log de
    eventos de vínculos de Emendas: aqui não há dado oficial pra reconciliar depois, só um
    lembrete que deixou de fazer sentido)."""

    _caminho(identificador, Path(diretorio)).unlink(missing_ok=True)


def carregar_prazo(identificador: str, diretorio: str | Path = DIRETORIO_PADRAO) -> dict:
    caminho = _caminho(identificador, Path(diretorio))
    if not caminho.exists():
        raise FileNotFoundError(f"Nenhum prazo cadastrado com o ID {identificador}.")
    return json.loads(caminho.read_text(encoding="utf-8"))


def editar(identificador: str, campos: dict, diretorio: str | Path = DIRETORIO_PADRAO) -> dict:
    """Aplica uma edição da tela sobre o registro gravado: só `CAMPOS_EDITAVEIS` são
    considerados (id, criado_em e estado de sincronização são preservados). Converte
    `concluido`/`dias_antecedencia` para tipos nativos (valores vindos de uma linha do
    DataFrame são `numpy.bool_`/`numpy.int64`, que o `json` não grava)."""

    anterior = carregar_prazo(identificador, diretorio)
    alteracoes = {chave: valor for chave, valor in campos.items() if chave in CAMPOS_EDITAVEIS}
    if "concluido" in alteracoes:
        alteracoes["concluido"] = bool(alteracoes["concluido"])
    if "dias_antecedencia" in alteracoes:
        alteracoes["dias_antecedencia"] = int(alteracoes["dias_antecedencia"])
    if isinstance(alteracoes.get("data_prazo"), date):
        alteracoes["data_prazo"] = alteracoes["data_prazo"].isoformat()
    atualizar({**anterior, **alteracoes}, diretorio)
    return carregar_prazo(identificador, diretorio)


def gravar_estado_sincronizacao(prazo: dict, diretorio: str | Path = DIRETORIO_PADRAO) -> Path:
    """Grava o registro como está — sem carimbar `atualizado_em` (diferente de `atualizar`).
    Uso exclusivo de `src/prazos_sincronizacao.py`."""

    caminho = _caminho(str(prazo["id"]), Path(diretorio))
    if not caminho.exists():
        raise FileNotFoundError(f"Nenhum prazo cadastrado com o ID {prazo['id']}.")
    _gravar_atomico(prazo, caminho)
    return caminho


def carregar_prazos(diretorio: str | Path = DIRETORIO_PADRAO) -> list[dict]:
    diretorio = Path(diretorio)
    if not diretorio.exists():
        return []
    return [
        json.loads(caminho.read_text(encoding="utf-8"))
        for caminho in sorted(diretorio.glob("*.json"))
    ]


#: rótulos do layout "Gerenciamento de Prazos" (10/09/2026) — a REGRA por trás continua a
#: antecedência própria de cada prazo (não um limiar fixo de 7 dias, ver docstring do
#: módulo); só o texto exibido veio do layout novo.
CRITICIDADE_ATRASADO = "Atrasado"
CRITICIDADE_VENCENDO = "Vencendo"
CRITICIDADE_EM_DIA = "Em dia"
CRITICIDADE_CONCLUIDO = "Concluído"


def _classificar(dias_para_vencer: int, dias_antecedencia: int) -> str:
    """Atrasado (passou da data) / Vencendo (dentro da antecedência escolhida para ESTE
    prazo) / Em dia (fora da antecedência ainda). Não há limiar fixo global: quem decide o
    quão cedo avisar é o `dias_antecedencia` de cada prazo."""

    if dias_para_vencer < 0:
        return CRITICIDADE_ATRASADO
    if dias_para_vencer <= dias_antecedencia:
        return CRITICIDADE_VENCENDO
    return CRITICIDADE_EM_DIA


def prazos_com_criticidade(prazos: list[dict], hoje: date | None = None) -> pd.DataFrame:
    """Uma linha por prazo cadastrado, com `dias_para_vencer`/`criticidade` calculados a
    partir de `hoje` (padrão `date.today()`, parametrizável para os testes ficarem
    determinísticos) — nunca de um campo gravado, para não desatualizar sozinho.

    `criticidade` é "Atrasado"/"Vencendo"/"Em dia" a partir da antecedência própria de
    cada prazo (`dias_antecedencia`, ver `_classificar`) — dois prazos com o mesmo
    `dias_para_vencer` podem ter criticidades diferentes se pediram antecedências diferentes.
    Prazo já `concluido` sempre mostra "Concluído", mesmo com a data já vencida.

    Registro gravado antes de `dias_antecedencia`/`tipo`/`categoria`/`prioridade` existirem
    (cadastro legado) recebe o padrão de cada campo, nunca quebra a leitura.

    Ordena por: não concluídos primeiro, depois por dias até vencer (vencidos primeiro; sem
    data — não deveria acontecer, mas não é motivo pra quebrar a tela — por último)."""

    hoje = hoje or date.today()
    if not prazos:
        return pd.DataFrame(columns=_COLUNAS)

    dataframe = pd.DataFrame(prazos)
    if "dias_antecedencia" not in dataframe.columns:
        dataframe["dias_antecedencia"] = DIAS_ANTECEDENCIA_PADRAO
    dataframe["dias_antecedencia"] = dataframe["dias_antecedencia"].fillna(DIAS_ANTECEDENCIA_PADRAO).astype(int)
    if "tipo" not in dataframe.columns:
        dataframe["tipo"] = TIPO_PADRAO
    dataframe["tipo"] = dataframe["tipo"].fillna(TIPO_PADRAO)
    if "categoria" not in dataframe.columns:
        dataframe["categoria"] = ""
    dataframe["categoria"] = dataframe["categoria"].fillna("")
    if "prioridade" not in dataframe.columns:
        dataframe["prioridade"] = PRIORIDADE_PADRAO
    dataframe["prioridade"] = dataframe["prioridade"].fillna(PRIORIDADE_PADRAO)
    for campo in ("google_event_id", "sincronizado_em", "google_atualizado_em"):
        if campo not in dataframe.columns:
            dataframe[campo] = None
        dataframe[campo] = dataframe[campo].astype(object).where(dataframe[campo].notna(), None)
    if "removido_no_google" not in dataframe.columns:
        dataframe["removido_no_google"] = False
    dataframe["removido_no_google"] = dataframe["removido_no_google"].fillna(False).astype(bool)
    dataframe["data_prazo"] = pd.to_datetime(dataframe["data_prazo"]).dt.date
    dataframe["dias_para_vencer"] = dataframe["data_prazo"].apply(lambda d: (d - hoje).days)
    dataframe["criticidade"] = [
        _classificar(dias, antecedencia)
        for dias, antecedencia in zip(dataframe["dias_para_vencer"], dataframe["dias_antecedencia"])
    ]
    dataframe.loc[dataframe["concluido"], "criticidade"] = CRITICIDADE_CONCLUIDO

    return dataframe.sort_values(["concluido", "dias_para_vencer"], na_position="last").reset_index(drop=True)
