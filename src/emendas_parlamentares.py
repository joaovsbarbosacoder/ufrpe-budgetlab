"""Emendas Parlamentares — cadastro, vínculo por PTRES e reconciliação.

O relatório específico de Emendas é lido por
``src.tesouro_emendas_acompanhamento`` e fornece a identidade da indicação:
exercício, número, parlamentar e um ou mais PTRES. A Execução Anual fornece os
movimentos financeiros, agregados por ``(exercício, RP, PTRES)``.

Política aprovada:

* exercícios anteriores a 2026 permanecem como fotografia estática do
  relatório de Emendas;
* em 2026 e exercícios posteriores, empenhado/liquidado/pago vêm da Execução
  Anual quando o PTRES está vinculado;
* execução sem emenda identificada e PTRES cadastrado sem execução permanecem
  explícitos — nenhum valor é atribuído ou descartado silenciosamente;
* uma emenda pode ter vários PTRES, mas um mesmo ``(ano, RP, PTRES)`` não pode
  ser atribuído automaticamente a números de emenda diferentes.

As funções e a persistência legadas do painel atual continuam disponíveis até
a etapa de substituição da interface, sem quebrar o formulário existente.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from src.tesouro_emendas_acompanhamento import COLUNAS_SAIDA

DIRETORIO_EMENDAS = Path("data/emendas")
ANO_INICIO_ATUALIZACAO = 2026

#: Resultado Primário que identifica emenda parlamentar na Execução Anual (confirmado nos
#: dados reais — ver docstring acima) — não existe em nenhuma outra base deste projeto como
#: um conceito de "emenda", só como este código de Resultado Primário.
RPS_EMENDA = {
    "6": "Emenda Individual",
    "7": "Emenda de Bancada",
    "8": "Emenda de Comissão Mista",
}

SITUACOES = ("Não iniciada", "Empenho parcial", "Em execução", "Concluída")
ESTAGIOS = ("SIOP", "TED", "Empenho", "Licitação", "Execução")

_CHAVE_PTRES = ["ano", "resultado_primario_cod", "ptres"]
_MEDIDAS_EXECUCAO = ["empenhada", "liquidada", "paga"]
_MEDIDAS_RELATORIO = [
    "empenhada_relatorio",
    "liquidada_relatorio",
    "paga_relatorio",
]


class ErroPoliticaImportacao(ValueError):
    """O relatório contém exercícios protegidos pela política histórica."""


class ErroVinculoEmenda(ValueError):
    """Um vínculo não pode ser resolvido automaticamente sem ambiguidade."""


@dataclass
class ResultadoVinculoEmendas:
    """Visões reconciliadas preservando cadastro, execução e lacunas."""

    emendas: pd.DataFrame
    vinculos: pd.DataFrame
    execucao_sem_vinculo: pd.DataFrame
    ptres_sem_execucao: pd.DataFrame


@dataclass
class ResultadoComposicaoCadastros:
    """Relatório acrescido dos cadastros manuais e sobreposições explícitas."""

    relatorio: pd.DataFrame
    sobreposicoes: pd.DataFrame


def validar_anos_importaveis(
    relatorio: pd.DataFrame,
    ano_minimo: int = ANO_INICIO_ATUALIZACAO,
) -> None:
    """Bloqueia por inteiro uploads que tentem alterar exercícios históricos.

    A base inicial pode conter anos anteriores; esta validação é destinada às
    atualizações posteriores. Linhas antigas nunca são ignoradas silenciosamente.
    """

    if "ano" not in relatorio.columns:
        raise ErroPoliticaImportacao("O relatório não possui a coluna 'ano'.")
    if relatorio.empty:
        raise ErroPoliticaImportacao("O relatório de atualização está vazio.")

    anos = pd.to_numeric(relatorio["ano"], errors="coerce")
    invalidos = relatorio["ano"].notna() & anos.isna()
    if relatorio["ano"].isna().any() or invalidos.any():
        raise ErroPoliticaImportacao("Há exercícios nulos ou inválidos no relatório.")
    if (anos % 1 != 0).any():
        raise ErroPoliticaImportacao("Há exercícios não inteiros no relatório.")

    protegidos = sorted(int(ano) for ano in anos[anos < ano_minimo].unique())
    if protegidos:
        raise ErroPoliticaImportacao(
            "O upload contém exercícios históricos protegidos: "
            f"{protegidos}. Somente exercícios a partir de {ano_minimo} podem "
            "ser atualizados."
        )


def compor_relatorio_com_cadastros(
    relatorio: pd.DataFrame,
    cadastros: list[dict],
) -> ResultadoComposicaoCadastros:
    """Acrescenta cadastros manuais sem duplicar linhas já presentes no relatório.

    Quando a mesma chave ``(ano, RP, emenda, PTRES, GND)`` já existe no relatório,
    a linha oficial do relatório prevalece e o cadastro permanece listado em
    ``sobreposicoes``. Isso evita dupla contagem sem apagar o JSON manual.
    """

    faltando = [coluna for coluna in COLUNAS_SAIDA if coluna not in relatorio.columns]
    if faltando:
        raise ErroVinculoEmenda(
            f"Relatório de Emendas sem as colunas obrigatórias: {faltando}."
        )

    base = relatorio.copy(deep=True)
    base["origem_cadastro"] = "relatorio"
    base["id_cadastro_manual"] = pd.NA
    manuais = cadastros_manuais_para_relatorio(cadastros)
    if manuais.empty:
        return ResultadoComposicaoCadastros(
            relatorio=base,
            sobreposicoes=manuais,
        )

    chave = [
        "ano",
        "resultado_primario_cod",
        "emenda_numero",
        "ptres",
        "gnd_cod",
    ]
    duplicadas_manuais = manuais.duplicated(subset=chave, keep=False)
    if duplicadas_manuais.any():
        ids = sorted(
            str(value)
            for value in manuais.loc[
                duplicadas_manuais, "id_cadastro_manual"
            ].dropna().unique()
        )
        raise ErroVinculoEmenda(
            "Cadastros manuais repetem a mesma chave ano × RP × emenda × "
            f"PTRES × GND: {ids}."
        )

    chaves_relatorio = base[chave].drop_duplicates().assign(_no_relatorio=True)
    classificados = manuais.merge(
        chaves_relatorio,
        on=chave,
        how="left",
        validate="many_to_one",
    )
    sobreposicoes = classificados.loc[
        classificados["_no_relatorio"].fillna(False)
    ].drop(columns="_no_relatorio")
    novos = classificados.loc[
        ~classificados["_no_relatorio"].fillna(False)
    ].drop(columns="_no_relatorio")

    combinado = pd.concat([base, novos], ignore_index=True, sort=False)
    return ResultadoComposicaoCadastros(
        relatorio=combinado,
        sobreposicoes=sobreposicoes.reset_index(drop=True),
    )


def cadastros_manuais_para_relatorio(cadastros: list[dict]) -> pd.DataFrame:
    """Converte JSONs manuais para a granularidade emenda × PTRES × GND."""

    registros: list[dict[str, object]] = []
    for cadastro in cadastros:
        # Cadastros criados a partir de uma pendência funcionam como identidade
        # da emenda. Seu PTRES é aplicado exclusivamente pelo log reversível de
        # vínculos, evitando que um desfazimento precise alterar ou apagar o JSON.
        if cadastro.get("gerenciada_por_vinculo_id"):
            continue
        identificador = str(cadastro.get("id") or "sem-id")
        ano = cadastro.get("exercicio")
        if ano is None:
            raise ErroVinculoEmenda(
                f"Cadastro manual {identificador!r} não informa o exercício."
            )
        try:
            ano_inteiro = int(ano)
        except (TypeError, ValueError) as error:
            raise ErroVinculoEmenda(
                f"Cadastro manual {identificador!r} possui exercício inválido: {ano!r}."
            ) from error
        if ano_inteiro < ANO_INICIO_ATUALIZACAO:
            raise ErroPoliticaImportacao(
                f"Cadastro manual {identificador!r} tenta alterar o exercício "
                f"histórico {ano_inteiro}."
            )

        rp = str(cadastro.get("rp") or "").upper().removeprefix("RP").strip()
        numero = str(cadastro.get("numero") or "").strip()
        parlamentar = str(cadastro.get("parlamentar") or "").strip()
        autor = str(cadastro.get("autor_emenda") or parlamentar).strip()
        gnd = _codigo_ou_na(
            cadastro.get("gnd_codigo", cadastro.get("gnd_cod"))
        )
        ptres = _normalizar_lista_ptres(cadastro.get("ptres"))
        if rp not in RPS_EMENDA or not numero or not parlamentar or gnd is pd.NA:
            raise ErroVinculoEmenda(
                f"Cadastro manual {identificador!r} não possui RP, número, "
                "parlamentar ou GND válido."
            )
        if not ptres:
            raise ErroVinculoEmenda(
                f"Cadastro manual {identificador!r} não possui PTRES."
            )

        dotacao = cadastro.get("dotacao_atualizada", pd.NA)
        if dotacao is None:
            dotacao = pd.NA
        for codigo_ptres in ptres:
            registros.append(
                {
                    "arquivo_origem": f"data/emendas/{identificador}.json",
                    "aba_origem": pd.NA,
                    "linha_origem": pd.NA,
                    "resultado_primario_cod": rp,
                    "ptres": codigo_ptres,
                    "emenda_numero": numero,
                    "autor_emenda": autor,
                    "parlamentar": parlamentar,
                    "gnd_cod": str(gnd),
                    "ano": ano_inteiro,
                    "dotacao_atualizada": dotacao,
                    "empenhada_relatorio": pd.NA,
                    "liquidada_relatorio": pd.NA,
                    "paga_relatorio": pd.NA,
                    "origem_cadastro": "manual",
                    "id_cadastro_manual": identificador,
                }
            )

    colunas = [*COLUNAS_SAIDA, "origem_cadastro", "id_cadastro_manual"]
    return pd.DataFrame.from_records(registros, columns=colunas)


def agregar_execucao_por_ptres(execucao: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por ``(ano, RP, PTRES)``, somando todas as linhas da Execução.

    A Execução mistura linhas de empenho e de item de execução; por isso cada
    medida é somada sobre todas as linhas com ``min_count=1``, conforme o
    contrato de ``src.execucao_anual``.
    """

    obrigatorias = [*_CHAVE_PTRES, *_MEDIDAS_EXECUCAO]
    _exigir_colunas(execucao, obrigatorias, "Execução Anual")
    df = execucao[obrigatorias].copy()

    df["ano"] = _serie_ano_estrita(df["ano"], "Execução Anual")
    for coluna in ["resultado_primario_cod", "ptres"]:
        df[coluna] = df[coluna].map(_codigo_ou_na).astype("string")
    for coluna in _MEDIDAS_EXECUCAO:
        df[coluna] = _serie_numerica_estrita(df[coluna], coluna)

    sem_chave = df[_CHAVE_PTRES].isna().any(axis=1)
    if sem_chave.any():
        linhas = df.index[sem_chave].tolist()
        raise ErroVinculoEmenda(
            "A Execução possui linhas sem ano, RP ou PTRES; não é seguro "
            f"descartá-las no vínculo. Índices: {linhas[:20]}."
        )

    df = df[df["resultado_primario_cod"].isin(RPS_EMENDA)].copy()
    agregado = (
        df.groupby(_CHAVE_PTRES, dropna=False, sort=True)[_MEDIDAS_EXECUCAO]
        .sum(min_count=1)
        .reset_index()
        .rename(
            columns={
                "empenhada": "empenhada_execucao",
                "liquidada": "liquidada_execucao",
                "paga": "paga_execucao",
            }
        )
    )
    for coluna in [
        "empenhada_execucao",
        "liquidada_execucao",
        "paga_execucao",
    ]:
        agregado[coluna] = pd.array(agregado[coluna], dtype="Float64")
    return agregado


def construir_vinculos_relatorio(relatorio: pd.DataFrame) -> pd.DataFrame:
    """Consolida GNDs, preservando uma linha por emenda × PTRES."""

    obrigatorias = [
        "ano",
        "resultado_primario_cod",
        "emenda_numero",
        "autor_emenda",
        "parlamentar",
        "ptres",
        "gnd_cod",
        "linha_origem",
        "dotacao_atualizada",
        *_MEDIDAS_RELATORIO,
    ]
    _exigir_colunas(relatorio, obrigatorias, "Relatório de Emendas")
    df = relatorio.copy(deep=True)
    if "origem_cadastro" not in df.columns:
        df["origem_cadastro"] = "relatorio"
    if "arquivo_origem" not in df.columns:
        df["arquivo_origem"] = "dados_em_memoria"
    if "aba_origem" not in df.columns:
        df["aba_origem"] = pd.NA
    df = df[
        [
            *obrigatorias,
            "origem_cadastro",
            "arquivo_origem",
            "aba_origem",
        ]
    ].copy()
    df["ano"] = _serie_ano_estrita(df["ano"], "Relatório de Emendas")
    for coluna in [
        "resultado_primario_cod",
        "emenda_numero",
        "autor_emenda",
        "parlamentar",
        "ptres",
        "gnd_cod",
    ]:
        df[coluna] = df[coluna].map(_codigo_ou_na).astype("string")
    for coluna in ["dotacao_atualizada", *_MEDIDAS_RELATORIO]:
        df[coluna] = _serie_numerica_estrita(df[coluna], coluna)

    obrigatorias_nao_nulas = [
        "ano",
        "resultado_primario_cod",
        "emenda_numero",
        "autor_emenda",
        "parlamentar",
        "ptres",
    ]
    sem_chave = df[obrigatorias_nao_nulas].isna().any(axis=1)
    if sem_chave.any():
        linhas = df.loc[sem_chave, "linha_origem"].tolist()
        raise ErroVinculoEmenda(
            "O relatório possui linhas sem identificadores obrigatórios: "
            f"{linhas[:20]}."
        )

    # A Execução Anual não informa GND na chave conciliada. Portanto, um
    # vínculo manual com emenda já existente pode ter GND nulo; qualquer outra
    # origem continua obrigada a informá-lo, preservando o contrato do relatório.
    gnd_nulo_invalido = df["gnd_cod"].isna() & ~df["origem_cadastro"].eq(
        "vinculo_manual"
    )
    if gnd_nulo_invalido.any():
        linhas = df.loc[gnd_nulo_invalido, "linha_origem"].tolist()
        raise ErroVinculoEmenda(
            "O relatório possui linhas sem GND fora de vínculos manuais; "
            f"linhas de origem: {linhas[:20]}."
        )

    chave_linha = [
        "ano",
        "resultado_primario_cod",
        "emenda_numero",
        "ptres",
        "gnd_cod",
    ]
    duplicadas = df.duplicated(subset=chave_linha, keep=False)
    if duplicadas.any():
        linhas = df.loc[duplicadas, "linha_origem"].tolist()
        raise ErroVinculoEmenda(
            "O relatório consolidado repete a chave ano × RP × emenda × "
            f"PTRES × GND; linhas de origem: {linhas[:20]}."
        )

    df["referencia_origem"] = df.apply(_referencia_origem, axis=1)

    chave_emenda = ["ano", "resultado_primario_cod", "emenda_numero"]
    autores = df.groupby(chave_emenda, dropna=False)["autor_emenda"].nunique()
    autores_conflitantes = autores[autores > 1]
    if not autores_conflitantes.empty:
        raise ErroVinculoEmenda(
            "Uma mesma emenda aparece com autores diferentes: "
            f"{list(autores_conflitantes.index)}."
        )

    chave_vinculo = [
        *chave_emenda,
        "autor_emenda",
        "parlamentar",
        "ptres",
    ]
    vinculos = (
        df.groupby(chave_vinculo, dropna=False, sort=True)
        .agg(
            gnds=("gnd_cod", _tupla_unica),
            linhas_origem=("linha_origem", _tupla_inteiros),
            referencias_origem=("referencia_origem", _tupla_unica),
            origens_cadastro=("origem_cadastro", _tupla_unica),
            dotacao_atualizada=("dotacao_atualizada", _soma_min_count),
            empenhada_relatorio=("empenhada_relatorio", _soma_min_count),
            liquidada_relatorio=("liquidada_relatorio", _soma_min_count),
            paga_relatorio=("paga_relatorio", _soma_min_count),
        )
        .reset_index()
    )
    for coluna in ["dotacao_atualizada", *_MEDIDAS_RELATORIO]:
        vinculos[coluna] = pd.array(vinculos[coluna], dtype="Float64")

    ambiguos = (
        vinculos.groupby(_CHAVE_PTRES, dropna=False)["emenda_numero"]
        .nunique()
        .loc[lambda serie: serie > 1]
    )
    if not ambiguos.empty:
        raise ErroVinculoEmenda(
            "O mesmo (ano, RP, PTRES) foi atribuído a emendas diferentes: "
            f"{list(ambiguos.index)}. Resolva o conflito manualmente."
        )
    return vinculos


def vincular_execucao_emendas(
    relatorio: pd.DataFrame,
    execucao: pd.DataFrame,
    ano_inicio_atualizacao: int = ANO_INICIO_ATUALIZACAO,
) -> ResultadoVinculoEmendas:
    """Aplica a política estática/dinâmica e devolve as lacunas do vínculo."""

    vinculos = construir_vinculos_relatorio(relatorio)
    execucao_ptres = agregar_execucao_por_ptres(execucao)

    cruzado = vinculos.merge(
        execucao_ptres,
        on=_CHAVE_PTRES,
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    cruzado["tem_execucao"] = cruzado["_merge"].eq("both")
    dinamico = cruzado["ano"].ge(ano_inicio_atualizacao)
    cruzado["origem_valores"] = pd.Series(
        "relatorio_estatico", index=cruzado.index, dtype="string"
    )
    cruzado.loc[dinamico & cruzado["tem_execucao"], "origem_valores"] = (
        "execucao_anual"
    )
    cruzado.loc[dinamico & ~cruzado["tem_execucao"], "origem_valores"] = (
        "sem_execucao"
    )

    for medida in _MEDIDAS_EXECUCAO:
        relatorio_col = f"{medida}_relatorio"
        execucao_col = f"{medida}_execucao"
        efetivo = cruzado[relatorio_col].copy()
        efetivo.loc[dinamico] = cruzado.loc[dinamico, execucao_col]
        cruzado[medida] = pd.array(efetivo, dtype="Float64")
        tem_ambos = cruzado[relatorio_col].notna() & cruzado[execucao_col].notna()
        cruzado[f"diferenca_{medida}"] = pd.array(
            (cruzado[execucao_col] - cruzado[relatorio_col]).where(tem_ambos),
            dtype="Float64",
        )

    ptres_sem_execucao = cruzado.loc[
        dinamico & ~cruzado["tem_execucao"]
    ].drop(columns="_merge").reset_index(drop=True)

    chaves_cadastradas = vinculos[_CHAVE_PTRES].drop_duplicates()
    execucao_dinamica = execucao_ptres[
        execucao_ptres["ano"].ge(ano_inicio_atualizacao)
    ].copy()
    execucao_sem_vinculo = execucao_dinamica.merge(
        chaves_cadastradas,
        on=_CHAVE_PTRES,
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    execucao_sem_vinculo = (
        execucao_sem_vinculo.loc[execucao_sem_vinculo["_merge"].eq("left_only")]
        .drop(columns="_merge")
        .reset_index(drop=True)
    )

    cruzado = cruzado.drop(columns="_merge")
    emendas = _resumir_emendas_vinculadas(cruzado)
    return ResultadoVinculoEmendas(
        emendas=emendas,
        vinculos=cruzado.reset_index(drop=True),
        execucao_sem_vinculo=execucao_sem_vinculo,
        ptres_sem_execucao=ptres_sem_execucao,
    )


def _resumir_emendas_vinculadas(vinculos: pd.DataFrame) -> pd.DataFrame:
    chave = [
        "ano",
        "resultado_primario_cod",
        "emenda_numero",
        "autor_emenda",
        "parlamentar",
    ]
    resumo = (
        vinculos.groupby(chave, dropna=False, sort=True)
        .agg(
            ptres=("ptres", _tupla_unica),
            gnds=("gnds", _unir_tuplas),
            referencias_origem=("referencias_origem", _unir_tuplas),
            origens_cadastro=("origens_cadastro", _unir_tuplas),
            ptres_total=("ptres", "size"),
            ptres_com_execucao=("tem_execucao", "sum"),
            dotacao_atualizada=("dotacao_atualizada", _soma_min_count),
            empenhada_relatorio=("empenhada_relatorio", _soma_min_count),
            liquidada_relatorio=("liquidada_relatorio", _soma_min_count),
            paga_relatorio=("paga_relatorio", _soma_min_count),
            empenhada_execucao=("empenhada_execucao", _soma_min_count),
            liquidada_execucao=("liquidada_execucao", _soma_min_count),
            paga_execucao=("paga_execucao", _soma_min_count),
            empenhada=("empenhada", _soma_min_count),
            liquidada=("liquidada", _soma_min_count),
            paga=("paga", _soma_min_count),
            origem_valores=("origem_valores", "first"),
        )
        .reset_index()
    )
    historico = resumo["origem_valores"].eq("relatorio_estatico")
    parcial = (
        ~historico
        & resumo["ptres_com_execucao"].gt(0)
        & resumo["ptres_com_execucao"].lt(resumo["ptres_total"])
    )
    completo = ~historico & resumo["ptres_com_execucao"].eq(resumo["ptres_total"])
    resumo.loc[~historico, "origem_valores"] = "sem_execucao"
    resumo.loc[parcial, "origem_valores"] = "execucao_anual_parcial"
    resumo.loc[completo, "origem_valores"] = "execucao_anual"
    return resumo


def _exigir_colunas(
    df: pd.DataFrame,
    colunas: list[str],
    nome_base: str,
) -> None:
    faltando = [coluna for coluna in colunas if coluna not in df.columns]
    if faltando:
        raise ErroVinculoEmenda(
            f"{nome_base} sem as colunas obrigatórias: {faltando}."
        )


def _serie_ano_estrita(series: pd.Series, nome_base: str) -> pd.Series:
    convertida = pd.to_numeric(series, errors="coerce")
    invalidos = series.notna() & convertida.isna()
    if invalidos.any() or convertida.isna().any():
        raise ErroVinculoEmenda(f"{nome_base} possui exercício nulo ou inválido.")
    if (convertida % 1 != 0).any():
        raise ErroVinculoEmenda(f"{nome_base} possui exercício não inteiro.")
    return pd.array(convertida, dtype="Int64")


def _serie_numerica_estrita(series: pd.Series, coluna: str) -> pd.Series:
    convertida = pd.to_numeric(series, errors="coerce")
    invalidos = series.notna() & convertida.isna()
    if invalidos.any():
        indices = series.index[invalidos].tolist()
        raise ErroVinculoEmenda(
            f"Valores inválidos em {coluna!r}; índices {indices[:20]}."
        )
    return pd.Series(pd.array(convertida, dtype="Float64"), index=series.index)


def _codigo_ou_na(value: object) -> object:
    if value is None or value is pd.NA:
        return pd.NA
    try:
        if pd.isna(value):
            return pd.NA
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    text = str(value).strip()
    return text or pd.NA


def _soma_min_count(series: pd.Series) -> object:
    soma = series.sum(min_count=1)
    return pd.NA if pd.isna(soma) else float(soma)


def _tupla_unica(series: pd.Series) -> tuple[str, ...]:
    return tuple(sorted(str(value) for value in series.dropna().unique()))


def _tupla_inteiros(series: pd.Series) -> tuple[int, ...]:
    return tuple(sorted(int(value) for value in series.dropna().unique()))


def _unir_tuplas(series: pd.Series) -> tuple[str, ...]:
    valores = {
        str(value)
        for grupo in series.dropna()
        for value in grupo
    }
    return tuple(sorted(valores))


def _referencia_origem(row: pd.Series) -> str:
    arquivo_valor = row.get("arquivo_origem")
    arquivo = (
        "origem_desconhecida"
        if arquivo_valor is None or pd.isna(arquivo_valor)
        else str(arquivo_valor)
    )
    aba = row.get("aba_origem")
    linha = row.get("linha_origem")
    if row.get("origem_cadastro") == "manual":
        return arquivo
    partes = [arquivo]
    if aba is not None and not pd.isna(aba):
        partes.append(str(aba))
    if linha is not None and not pd.isna(linha):
        partes.append(f"linha {int(linha)}")
    return " · ".join(partes)


def _normalizar_lista_ptres(
    ptres: str | Iterable[str] | None,
) -> list[str]:
    if ptres is None:
        return []
    valores = [ptres] if isinstance(ptres, str) else list(ptres)
    normalizados: list[str] = []
    for value in valores:
        codigo = _codigo_ou_na(value)
        if codigo is pd.NA:
            continue
        texto = str(codigo)
        if texto not in normalizados:
            normalizados.append(texto)
    return normalizados


def normalizar_ptres_texto(texto: str) -> list[str]:
    """Separa PTRES por vírgula, ponto e vírgula ou quebra de linha."""

    return _normalizar_lista_ptres(
        parte
        for parte in re.split(r"[,;\r\n]+", texto)
        if parte.strip()
    )


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def combinacoes_orcamentarias_validas(
    dotacao: pd.DataFrame, execucao: pd.DataFrame
) -> pd.DataFrame:
    """(rp_codigo, rp_descricao, acao_codigo, acao_descricao, po_codigo, po_descricao, origem)
    — união de combinações reais vindas de Dotação Anual e Execução Anual, para alimentar os
    seletores em cascata do formulário de cadastro. `origem` diz de qual base cada linha veio
    ("Dotação"/"Execução") — mostrado no formulário pra deixar claro que nenhuma opção é
    inventada."""

    da_dotacao = (
        dotacao[
            [
                "resultado_primario_codigo", "resultado_primario_descricao",
                "acao_codigo", "acao_descricao",
                "plano_orcamentario_codigo", "plano_orcamentario_descricao",
            ]
        ]
        .drop_duplicates()
        .dropna(subset=["resultado_primario_codigo", "acao_codigo"])
        .rename(
            columns={
                "resultado_primario_codigo": "rp_codigo",
                "resultado_primario_descricao": "rp_descricao",
                "acao_codigo": "acao_codigo",
                "acao_descricao": "acao_descricao",
                "plano_orcamentario_codigo": "po_codigo",
                "plano_orcamentario_descricao": "po_descricao",
            }
        )
    )
    da_dotacao["origem"] = "Dotação"

    da_execucao = (
        execucao[["resultado_primario_cod", "resultado_primario_desc", "acao_cod", "acao_desc", "po_cod", "po_desc"]]
        .drop_duplicates()
        .dropna(subset=["resultado_primario_cod", "acao_cod"])
        .rename(
            columns={
                "resultado_primario_cod": "rp_codigo",
                "resultado_primario_desc": "rp_descricao",
                "acao_cod": "acao_codigo",
                "acao_desc": "acao_descricao",
                "po_cod": "po_codigo",
                "po_desc": "po_descricao",
            }
        )
    )
    da_execucao["origem"] = "Execução"

    combinado = pd.concat([da_dotacao, da_execucao], ignore_index=True)
    # só as combinações de RP que interessam a esta página (emenda parlamentar) — sem isso, o
    # seletor de RP ofereceria todo Resultado Primário da Dotação/Execução (obrigatório,
    # discricionário, financeiro etc.), não só os de emenda.
    combinado = combinado[combinado["rp_codigo"].isin(RPS_EMENDA)]
    return combinado.drop_duplicates(subset=["rp_codigo", "acao_codigo", "po_codigo", "origem"]).reset_index(drop=True)


def emendas_representadas_em_dotacao(emendas: list[dict], dotacao: pd.DataFrame) -> list[dict]:
    """Só as emendas cuja combinação (RP, Ação) tem pelo menos uma linha real na Dotação Anual
    — pedido explícito. Nas que sobram, zera Indicado/Empenhado/Liquidado/Pago: são valores
    fictícios de cadastro, e mostrar um número fictício ao lado de uma classificação
    orçamentária real seria mais enganoso do que mostrar zero (nenhuma base liga um empenho a
    um número de emenda específico — ver docstring do módulo)."""

    rp_por_codigo_emenda = {"RP6": "6", "RP7": "7", "RP8": "8"}
    combos_validos = set(
        zip(dotacao["resultado_primario_codigo"].astype(str), dotacao["acao_codigo"].astype(str))
    )

    representadas = []
    for emenda in emendas:
        rp_codigo = rp_por_codigo_emenda.get(emenda["rp"])
        acao_codigo = emenda["acao"].split(" — ")[0].strip()
        if (rp_codigo, acao_codigo) not in combos_validos:
            continue
        emenda_zerada = dict(emenda)
        emenda_zerada["indicado"] = 0
        emenda_zerada["empenhado"] = 0
        emenda_zerada["liquidado"] = 0
        emenda_zerada["pago"] = 0
        emenda_zerada["dias_parado"] = 0
        representadas.append(emenda_zerada)
    return representadas


def nova_emenda(
    *,
    parlamentar: str,
    numero: str,
    rp_codigo: str,
    rp_descricao: str,
    acao_codigo: str,
    acao_descricao: str,
    po_codigo: str | None,
    po_descricao: str | None,
    objeto: str,
    responsavel: str,
    situacao: str,
    proximo: str,
    indicado: float,
    exercicio: int | None = None,
    ptres: str | Iterable[str] | None = None,
    gnd_codigo: str | None = None,
    dotacao_atualizada: float | None = None,
    autor_emenda: str | None = None,
) -> dict:
    """Uma emenda recém-cadastrada começa com Empenhado/Liquidado/Pago em zero de propósito:
    não é um placeholder — é o estado real de uma emenda que acabou de ser indicada, ainda sem
    nenhuma execução."""

    if exercicio is not None and exercicio < ANO_INICIO_ATUALIZACAO:
        raise ErroPoliticaImportacao(
            f"Cadastros manuais só podem alterar exercícios a partir de "
            f"{ANO_INICIO_ATUALIZACAO}."
        )

    ptres_normalizados = _normalizar_lista_ptres(ptres)
    gnd_normalizado = _codigo_ou_na(gnd_codigo)
    return {
        "id": str(uuid.uuid4()),
        "exercicio": exercicio,
        "parlamentar": parlamentar.strip(),
        "autor_emenda": (autor_emenda or parlamentar).strip(),
        "numero": numero.strip(),
        "ptres": ptres_normalizados,
        "gnd_codigo": None if gnd_normalizado is pd.NA else str(gnd_normalizado),
        "dotacao_atualizada": dotacao_atualizada,
        "rp": f"RP{rp_codigo}",
        "rp_descricao": rp_descricao,
        "acao": f"{acao_codigo} — {acao_descricao}",
        "po": f"{po_codigo} — {po_descricao}" if po_codigo else None,
        "objeto": objeto,
        "indicado": indicado,
        "empenhado": 0,
        "liquidado": 0,
        "pago": 0,
        "situacao": situacao,
        "responsavel": responsavel,
        "proximo": proximo,
        "dias_parado": 0,
        "criado_em": _agora_iso(),
        "cadastro_manual": True,
        "origem_cadastro": "manual",
    }


def nova_emenda_acompanhamento(
    *,
    exercicio: int,
    parlamentar: str,
    numero: str,
    rp_codigo: str,
    ptres: str | Iterable[str],
    gnd_codigo: str,
    dotacao_atualizada: float | None,
    objeto: str = "",
    responsavel: str = "",
) -> dict:
    """Cria o cadastro manual usado pela nova interface de acompanhamento."""

    try:
        ano = int(exercicio)
    except (TypeError, ValueError) as error:
        raise ErroPoliticaImportacao(
            f"Exercício inválido para cadastro manual: {exercicio!r}."
        ) from error
    if ano < ANO_INICIO_ATUALIZACAO:
        raise ErroPoliticaImportacao(
            f"Cadastros manuais só podem alterar exercícios a partir de "
            f"{ANO_INICIO_ATUALIZACAO}."
        )

    parlamentar = parlamentar.strip()
    numero = numero.strip()
    rp_codigo = str(rp_codigo).upper().removeprefix("RP").strip()
    gnd_codigo = str(gnd_codigo).strip()
    ptres_normalizados = _normalizar_lista_ptres(ptres)
    if not parlamentar or not numero:
        raise ErroVinculoEmenda("Informe o parlamentar e o número da emenda.")
    if rp_codigo not in RPS_EMENDA:
        raise ErroVinculoEmenda("O Resultado Primário deve ser 6, 7 ou 8.")
    if not ptres_normalizados:
        raise ErroVinculoEmenda("Informe ao menos um PTRES.")
    if not gnd_codigo:
        raise ErroVinculoEmenda("Informe o código do GND.")
    if isinstance(dotacao_atualizada, bool):
        raise ErroVinculoEmenda("Dotação atualizada não pode ser booleana.")
    if dotacao_atualizada is not None:
        try:
            dotacao_atualizada = float(dotacao_atualizada)
        except (TypeError, ValueError) as error:
            raise ErroVinculoEmenda("Dotação atualizada inválida.") from error

    return nova_emenda(
        parlamentar=parlamentar,
        autor_emenda=parlamentar,
        numero=numero,
        rp_codigo=rp_codigo,
        rp_descricao=RPS_EMENDA[rp_codigo],
        acao_codigo="",
        acao_descricao="",
        po_codigo=None,
        po_descricao=None,
        objeto=objeto.strip(),
        responsavel=responsavel.strip(),
        situacao="Não iniciada",
        proximo="Empenho",
        indicado=0.0,
        exercicio=ano,
        ptres=ptres_normalizados,
        gnd_codigo=gnd_codigo,
        dotacao_atualizada=dotacao_atualizada,
    )


def salvar(
    emenda: dict,
    diretorio: str | Path = DIRETORIO_EMENDAS,
) -> Path:
    """Grava um cadastro manual atomicamente, sem sobrescrever outro ID."""

    identificador = str(emenda.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", identificador):
        raise ValueError("O identificador da emenda é inválido para persistência.")
    diretorio = Path(diretorio)
    diretorio.mkdir(parents=True, exist_ok=True)
    caminho = diretorio / f"{identificador}.json"
    if caminho.exists():
        raise FileExistsError(f"Já existe um cadastro com o ID {identificador}.")
    temporario = diretorio / f".{identificador}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(
            json.dumps(emenda, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()
    return caminho


def carregar_emendas_cadastradas(
    diretorio: str | Path = DIRETORIO_EMENDAS,
) -> list[dict]:
    diretorio = Path(diretorio)
    if not diretorio.exists():
        return []
    return [
        json.loads(caminho.read_text(encoding="utf-8"))
        for caminho in sorted(diretorio.glob("*.json"))
    ]
