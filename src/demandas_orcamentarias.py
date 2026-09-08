"""Captação de Demandas Orçamentárias — camada de dados.

Primeiro módulo de ESCRITA do BudgetLab: até aqui todo o app só lia bases já validadas
do Tesouro Gerencial (Dotação Anual, Execução Anual). Aqui cada setor da UFRPE registra
uma demanda orçamentária para o próximo exercício, que a equipe da PROPLAD consolida.

Persistência: um arquivo JSON por demanda em `DIRETORIO_DEMANDAS` (nome = `{id}.json`),
não um arquivo único compartilhado — evita condição de corrida entre setores diferentes
salvando ao mesmo tempo, já que cada escrita toca só o próprio arquivo. Mesmo espírito de
simplicidade do `Manifesto.salvar()` em `src/importacao_versionada.py`: grava o JSON
direto, sem lock adicional (volume esperado — dezenas/centenas de demandas — não
justifica mais que isso). O diretório é git-ignorado (é dado real de produção), ao
contrário das listas de referência abaixo.

`status` é string livre (não um enum fechado) de propósito: uma versão futura vai
acomodar mais estados (aprovada, rejeitada, incorporada) sem exigir migração de schema —
só adicionar entradas em `STATUS_LABELS`/`STATUS_BADGE_COLOR`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DIRETORIO_REFERENCIA = Path("data/referencia")
DIRETORIO_DEMANDAS = Path("data/demandas")

CAMINHO_SETORES = DIRETORIO_REFERENCIA / "setores.csv"
CAMINHO_METAS_PDI_PLS = DIRETORIO_REFERENCIA / "metas_pdi_pls.csv"

STATUS_RASCUNHO = "rascunho"
STATUS_ENVIADA = "enviada"

STATUS_LABELS = {
    STATUS_RASCUNHO: "Rascunho",
    STATUS_ENVIADA: "Enviada",
}

# Cores válidas de st.badge (ver src/ui_theme.py/render_page_header para outro uso do
# mesmo widget): cor com função de comunicar status, não decoração.
STATUS_BADGE_COLOR = {
    STATUS_RASCUNHO: "gray",
    STATUS_ENVIADA: "blue",
}

TIPOS_DESPESA = ("Custeio", "Capital")

# Campos que compõem "classificação avançada" — todos opcionais nesta versão (ver
# briefing, seção 5.2: fica em segundo plano, recolhida por padrão).
CAMPOS_CLASSIFICACAO_AVANCADA = (
    "acao_codigo", "acao_descricao",
    "pi_codigo", "pi_descricao",
    "gnd_codigo", "gnd_descricao",
    "natureza_detalhada_codigo", "natureza_detalhada_descricao",
)


def carregar_setores() -> pd.DataFrame:
    """Lista de setores (placeholder até a lista oficial da UFRPE substituir o CSV)."""

    return pd.read_csv(CAMINHO_SETORES, dtype="string")


def carregar_metas_pdi_pls() -> pd.DataFrame:
    """Metas do PDI/PLS (placeholder até a lista oficial substituir o CSV)."""

    return pd.read_csv(CAMINHO_METAS_PDI_PLS, dtype="string")


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def nova_demanda(unidade_codigo: str, unidade_nome: str, exercicio: int) -> dict:
    """Esqueleto de uma demanda nova, em Rascunho — demais campos ficam vazios/None até
    o representante do setor preencher o formulário."""

    agora = _agora_iso()
    return {
        "id": str(uuid.uuid4()),
        "unidade_codigo": unidade_codigo,
        "unidade_nome": unidade_nome,
        "exercicio": exercicio,
        "metas_pdi_pls": [],
        "tipo_despesa": None,
        "quantidade": None,
        "valor_unitario": None,
        "valor_total": None,
        "descricao_necessidade": "",
        "justificativa": "",
        "classificacao_avancada": {campo: None for campo in CAMPOS_CLASSIFICACAO_AVANCADA},
        "status": STATUS_RASCUNHO,
        "criado_em": agora,
        "atualizado_em": agora,
        "enviado_em": None,
    }


def _caminho_demanda(demanda_id: str) -> Path:
    return DIRETORIO_DEMANDAS / f"{demanda_id}.json"


def salvar(demanda: dict) -> None:
    """Grava (cria ou sobrescreve) o JSON da demanda. `atualizado_em` é sempre
    recalculado aqui — quem chama não precisa lembrar de atualizá-lo à mão."""

    demanda = dict(demanda)
    demanda["atualizado_em"] = _agora_iso()
    DIRETORIO_DEMANDAS.mkdir(parents=True, exist_ok=True)
    caminho = _caminho_demanda(demanda["id"])
    caminho.write_text(json.dumps(demanda, ensure_ascii=False, indent=2), encoding="utf-8")


def enviar(demanda: dict) -> dict:
    """Marca a demanda como Enviada e persiste — devolve o dict atualizado (não muta o
    argumento, para o chamador poder decidir se descarta o rascunho em memória)."""

    demanda = dict(demanda)
    demanda["status"] = STATUS_ENVIADA
    demanda["enviado_em"] = _agora_iso()
    salvar(demanda)
    return demanda


def carregar_demanda(demanda_id: str) -> dict | None:
    caminho = _caminho_demanda(demanda_id)
    if not caminho.exists():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


_COLUNAS_DEMANDAS = [
    "id", "unidade_codigo", "unidade_nome", "exercicio", "metas_pdi_pls",
    "tipo_despesa", "quantidade", "valor_unitario", "valor_total",
    "descricao_necessidade", "justificativa", "classificacao_avancada",
    "status", "criado_em", "atualizado_em", "enviado_em",
]


def carregar_demandas() -> pd.DataFrame:
    """Todas as demandas já salvas (rascunho e enviada), uma linha por arquivo JSON.

    DataFrame vazio (mas com as colunas certas) se `DIRETORIO_DEMANDAS` ainda não tem
    nenhuma demanda — nunca `None`, pra quem chama não precisar checar os dois casos.
    """

    if not DIRETORIO_DEMANDAS.exists():
        return pd.DataFrame(columns=_COLUNAS_DEMANDAS)

    registros = [
        json.loads(caminho.read_text(encoding="utf-8"))
        for caminho in sorted(DIRETORIO_DEMANDAS.glob("*.json"))
    ]
    if not registros:
        return pd.DataFrame(columns=_COLUNAS_DEMANDAS)

    df = pd.DataFrame.from_records(registros, columns=_COLUNAS_DEMANDAS)
    # `pd.DataFrame.from_records` infere um dtype por coluna e troca `None` (o que o JSON
    # de um campo opcional ainda vazio guarda) por NaN/pd.NA — e isso é *verdadeiro* em
    # Python (`nan or 0.0` avalia pra `nan`, não pra `0.0`), então qualquer código que
    # leia esta base com `valor or padrao` para um campo opcional falha silenciosamente.
    # Normaliza de volta pra `None` uma única vez aqui, não em cada página que lê.
    return df.astype(object).where(pd.notna(df), None)


def explodir_por_meta(demandas: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (demanda, meta PDI/PLS) — para consolidar valor por meta sem
    duplicar no total geral (que usa `demandas` sem explodir). Uma demanda com 2 metas
    conta o `valor_total` inteiro nas duas ao consolidar por meta — é o comportamento
    esperado (a demanda atende as duas ao mesmo tempo, não metade em cada)."""

    if demandas.empty:
        return demandas.assign(meta_codigo=pd.Series(dtype="string"), meta_descricao=pd.Series(dtype="string"))

    linhas = []
    for _, linha in demandas.iterrows():
        metas = linha["metas_pdi_pls"] or []
        if not metas:
            registro = linha.to_dict()
            registro["meta_codigo"] = None
            registro["meta_descricao"] = None
            linhas.append(registro)
            continue
        for meta in metas:
            registro = linha.to_dict()
            registro["meta_codigo"] = meta.get("codigo")
            registro["meta_descricao"] = meta.get("descricao")
            linhas.append(registro)
    return pd.DataFrame.from_records(linhas)


def validar_para_envio(demanda: dict) -> list[str]:
    """Mensagens de campo obrigatório faltando para permitir o envio. Lista vazia =
    pode enviar. Rascunho não passa por esta validação (só exige Unidade, garantida
    pelo próprio fluxo de "quem sou eu" antes de chegar ao formulário)."""

    erros = []
    if not demanda.get("unidade_codigo"):
        erros.append("Unidade solicitante")
    if not demanda.get("exercicio"):
        erros.append("Exercício de referência")
    if not demanda.get("metas_pdi_pls"):
        erros.append("Vínculo com planejamento institucional (PDI/PLS)")
    if not demanda.get("tipo_despesa"):
        erros.append("Tipo de despesa")
    if not demanda.get("quantidade") or demanda["quantidade"] <= 0:
        erros.append("Quantidade")
    if not demanda.get("valor_unitario") or demanda["valor_unitario"] <= 0:
        erros.append("Valor unitário")
    if not (demanda.get("descricao_necessidade") or "").strip():
        erros.append("Descrição da necessidade")
    if not (demanda.get("justificativa") or "").strip():
        erros.append("Justificativa")
    return erros
