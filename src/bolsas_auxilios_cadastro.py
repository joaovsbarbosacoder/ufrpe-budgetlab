"""
Cadastro nativo, multi-exercício, de Bolsas e Auxílios — substitui a leitura de planilha
(`src.bolsas_auxilios.ler_bolsas_auxilios`) como fonte de dados de `app_pages/bolsas_auxilios.py`
(pedido explícito: desvincular a página de reimportação manual de planilha — o cadastro passa a
viver só no sistema, editável em tela).

Constrói em cima do motor genérico `src.cadastro_por_exercicio` (persistência em disco, um JSON
por registro, agrupado por exercício em `data/bolsas_auxilios/<ano>/`), definindo aqui só o que
é específico desta feature: quais campos são "identidade" (copiados ao duplicar um exercício
para o próximo, ver `duplicar_exercicio`) e quais são "execução" (em branco/zerados no
exercício novo — o vínculo com a Execução Anual se refaz quando o usuário digitar o novo número
de empenho, via `com_saldo_execucao`, que já é multi-ano por natureza: `ne_curta` embute o ano,
"2027NE000123" nunca colide com uma NE de 2026).

`como_dataframe` devolve o mesmo esquema de colunas que
`src.bolsas_auxilios.ler_bolsas_auxilios` produzia (menos `tem_saldo`/`meses_de_saldo`/
`ocorrencias_tg` — confirmado sem uso em `app_pages/bolsas_auxilios.py`, grep no módulo) — o
resto do pipeline da página (`com_saldo_execucao`, Resumo Consolidado, Cobertura Orçamentária,
Relatório de Reforço) não sabe se os dados vieram de Excel ou do cadastro nativo. A coluna
adicional `valor_mensal_excepcional` preserva explicitamente valores financeiros informados
na origem que não sejam iguais a `qtd_efetiva * valor_unitario`; quando nula, a fórmula
continua sendo a fonte do valor mensal.

Migração única (`migrar_de_planilha`): lê a planilha antiga com `ler_bolsas_auxilios` e grava
cada linha como um registro nativo do exercício informado (2026, na migração feita para este
projeto) — depois disso a planilha não é mais lida pela página; existe só como o histórico de
onde o exercício 2026 partiu.

Contrato público:
    novo_programa(**campos) -> dict
    salvar_programa(ano, programa) -> Path
    atualizar_programa(ano, programa) -> Path
    excluir_programa(ano, id) -> None
    carregar_programas(ano) -> list[dict]
    como_dataframe(programas) -> pd.DataFrame
    anos_disponiveis() -> list[int]
    duplicar_exercicio(ano_origem, ano_destino) -> list[dict]
    migrar_de_planilha(caminho, ano, *, diretorio_base=None) -> list[dict]
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.bolsas_auxilios import ler_bolsas_auxilios
from src.cadastro_por_exercicio import (
    anos_disponiveis as _anos_disponiveis,
    atualizar as _atualizar,
    carregar_registros,
    duplicar_exercicio as _duplicar_exercicio,
    excluir as _excluir,
    excluir_exercicio as _excluir_exercicio,
    novo_registro,
    salvar as _salvar,
)
from src.necessidade_empenho import calcular_necessidade_empenho

DIRETORIO_PADRAO = Path("data/bolsas_auxilios")

#: copiados ao duplicar um exercício — classificação/identidade do programa, não execução.
CAMPOS_IDENTIDADE = [
    "processo", "programa_bolsa", "unidade_cod", "acao_cod", "ptres", "fonte_cod",
    "natureza_despesa_cod", "ugr_cod", "pi_cod", "meses_no_ano", "qtd_inicial",
    "qtd_efetiva", "valor_unitario", "valor_mensal_excepcional",
]

#: em branco/zerados no exercício novo — o vínculo com a Execução Anual se refaz quando o
#: usuário digitar o novo número de empenho (`ne_curta`) daquele exercício. `inicio_execucao_mes`
#: (1-12, opcional) é o mês do primeiro empenho daquela NE — auto-detectado a partir da base
#: mensal quando ausente (ver `src.tesouro_execucao_mensal.primeiro_mes_com_empenho_por_ne`),
#: editável pelo usuário se perceber um erro na detecção; usado só na sugestão inicial do
#: Relatório de Reforço (`src.necessidade_empenho.necessidade_ate_mes_vigente`).
CAMPOS_EXECUCAO_PADRAO = {
    "ne_curta": None,
    "valor_empenhado_tg": 0.0,
    "saldo_colado_planilha": 0.0,
    "situacao_tg": "SEM EMPENHO",
    "meses_empenhados": 0.0,
    "meses_liquidados": 0.0,
    "inicio_execucao_mes": None,
}

_COLUNAS_TEXTO = [
    "processo", "programa_bolsa", "unidade_cod", "acao_cod", "ptres", "fonte_cod",
    "natureza_despesa_cod", "ugr_cod", "pi_cod", "ne_curta", "situacao_tg",
]
_COLUNAS_NUMERICAS = [
    "meses_no_ano", "qtd_inicial", "qtd_efetiva", "valor_unitario",
    "valor_mensal_excepcional",
    "valor_empenhado_tg", "saldo_colado_planilha", "meses_empenhados", "meses_liquidados",
    "inicio_execucao_mes",
]
_COLUNAS_VAZIAS = [
    "id", *_COLUNAS_TEXTO, *_COLUNAS_NUMERICAS,
    "valor_mensal", "valor_anual", "meses_a_empenhar", "valor_a_empenhar",
]


def novo_programa(**campos: object) -> dict:
    """Monta um registro novo (ainda não gravado — ver `salvar_programa`). Campo de identidade
    não informado fica `None`; campo de execução não informado usa o padrão de exercício novo
    (`CAMPOS_EXECUCAO_PADRAO`, ex.: situação "SEM EMPENHO")."""

    base = {chave: None for chave in CAMPOS_IDENTIDADE}
    base.update(CAMPOS_EXECUCAO_PADRAO)
    base.update({chave: valor for chave, valor in campos.items() if chave in base})
    return novo_registro(**base)


def salvar_programa(ano: int, programa: dict) -> Path:
    return _salvar(DIRETORIO_PADRAO, ano, programa)


def atualizar_programa(ano: int, programa: dict) -> Path:
    return _atualizar(DIRETORIO_PADRAO, ano, programa)


def excluir_programa(ano: int, identificador: str) -> None:
    _excluir(DIRETORIO_PADRAO, ano, identificador)


def carregar_programas(ano: int) -> list[dict]:
    return carregar_registros(DIRETORIO_PADRAO, ano)


def anos_disponiveis() -> list[int]:
    return _anos_disponiveis(DIRETORIO_PADRAO)


def excluir_exercicio(ano: int) -> None:
    _excluir_exercicio(DIRETORIO_PADRAO, ano)


def como_dataframe(programas: list[dict]) -> pd.DataFrame:
    """Mesmo esquema de colunas de `src.bolsas_auxilios.ler_bolsas_auxilios` (ver docstring do
    módulo) — `valor_mensal` usa `valor_mensal_excepcional` quando informado e, nos demais
    registros, é derivado de quantidade efetiva e valor unitário. Os outros campos financeiros
    calculados continuam sempre derivados desse valor mensal efetivo."""

    if not programas:
        return pd.DataFrame(columns=_COLUNAS_VAZIAS)

    df = pd.DataFrame(programas)
    df["id"] = df["id"].astype("string")
    for coluna in _COLUNAS_TEXTO:
        if coluna not in df.columns:
            df[coluna] = pd.NA
        df[coluna] = df[coluna].astype("string")
    for coluna in _COLUNAS_NUMERICAS:
        if coluna not in df.columns:
            df[coluna] = pd.NA
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")

    valor_calculado = df["qtd_efetiva"] * df["valor_unitario"]
    df["valor_mensal"] = df["valor_mensal_excepcional"].fillna(valor_calculado)
    df["valor_anual"] = df["valor_mensal"] * df["meses_no_ano"]
    df["meses_a_empenhar"], df["valor_a_empenhar"] = calcular_necessidade_empenho(
        df["meses_empenhados"], df["meses_liquidados"], df["valor_mensal"]
    )
    return df


def duplicar_exercicio(ano_origem: int, ano_destino: int) -> list[dict]:
    registros_origem = carregar_programas(ano_origem)
    return _duplicar_exercicio(
        DIRETORIO_PADRAO, registros_origem, ano_destino, CAMPOS_IDENTIDADE, CAMPOS_EXECUCAO_PADRAO
    )


def _limpo(valor: object) -> object:
    if pd.isna(valor):
        return None
    if hasattr(valor, "item"):
        return valor.item()
    return valor


def _valor_mensal_excepcional(linha: pd.Series) -> float | None:
    """Preserva a divergência da origem sem alterar quantidade ou valor unitário."""

    informado = linha.get("valor_mensal")
    quantidade = linha.get("qtd_efetiva")
    unitario = linha.get("valor_unitario")
    if pd.isna(informado):
        return None
    if pd.isna(quantidade) or pd.isna(unitario):
        return float(informado)
    calculado = float(quantidade) * float(unitario)
    return float(informado) if abs(float(informado) - calculado) > 0.01 else None


def migrar_de_planilha(
    caminho: str | Path,
    ano: int,
    *,
    diretorio_base: str | Path | None = None,
) -> list[dict]:
    """Importação única: lê a planilha antiga (`ler_bolsas_auxilios`) e grava cada linha como
    um registro nativo do exercício `ano` — usada uma vez para migrar 2026 (pedido explícito de
    desvinculação da planilha); não é chamada pela página em uso normal."""

    dataframe = ler_bolsas_auxilios(caminho)
    destino = DIRETORIO_PADRAO if diretorio_base is None else Path(diretorio_base)
    criados = []
    for _, linha in dataframe.iterrows():
        campos = {chave: _limpo(linha.get(chave)) for chave in (*CAMPOS_IDENTIDADE, *CAMPOS_EXECUCAO_PADRAO)}
        campos["valor_mensal_excepcional"] = _valor_mensal_excepcional(linha)
        registro = novo_registro(**campos)
        _salvar(destino, ano, registro)
        criados.append(registro)
    return criados
