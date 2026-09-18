"""Migração segura das planilhas de trabalho para os cadastros nativos.

O fluxo sempre monta os dois cadastros em diretórios temporários e reconcilia contagens e
totais antes de qualquer promoção. A simulação é o padrão e não grava nos diretórios de
destino. A aplicação recusa qualquer exercício que já exista; não há opção de sobrescrita.
"""

from __future__ import annotations

import hashlib
import math
import tempfile
from contextlib import ExitStack
from pathlib import Path

import pandas as pd

import src.bolsas_auxilios_cadastro as bolsas_cadastro
import src.contratos_continuos_cadastro as contratos_cadastro
from src.cadastro_por_exercicio import carregar_registros
from src.bolsas_auxilios import ler_bolsas_auxilios
from src.contratos_continuos import ler_contratos_continuos


class ErroMigracaoCadastros(ValueError):
    """A migração não pode ser promovida sem risco de perda ou divergência."""


def _sha256(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _soma(dataframe: pd.DataFrame, coluna: str) -> float:
    return float(pd.to_numeric(dataframe[coluna], errors="coerce").sum())


def _exigir_igual(nome: str, origem: float, nativo: float) -> None:
    if not math.isclose(origem, nativo, rel_tol=0.0, abs_tol=0.01):
        raise ErroMigracaoCadastros(
            f"{nome} não reconciliou: origem={origem:.2f}; cadastro={nativo:.2f}."
        )


def _validar_bolsas(
    origem: pd.DataFrame,
    registros: list[dict],
) -> dict:
    nativo = bolsas_cadastro.como_dataframe(registros)
    if len(origem) != len(nativo):
        raise ErroMigracaoCadastros(
            f"Bolsas: {len(origem)} linhas na origem e {len(nativo)} registros no cadastro."
        )

    mensal_origem = _soma(origem, "valor_mensal")
    mensal_nativo = _soma(nativo, "valor_mensal")
    anual_origem = _soma(origem, "valor_anual")
    anual_nativo = _soma(nativo, "valor_anual")
    _exigir_igual("Bolsas - valor mensal", mensal_origem, mensal_nativo)
    _exigir_igual("Bolsas - valor anual", anual_origem, anual_nativo)

    return {
        "linhas_origem": len(origem),
        "registros": len(nativo),
        "valor_mensal_origem": mensal_origem,
        "valor_mensal_cadastro": mensal_nativo,
        "valor_anual_origem": anual_origem,
        "valor_anual_cadastro": anual_nativo,
        "valores_mensais_excepcionais": int(nativo["valor_mensal_excepcional"].notna().sum()),
    }


def _validar_contratos(
    origem: pd.DataFrame,
    registros: list[dict],
) -> dict:
    nativo = contratos_cadastro.como_dataframe(registros)
    chave = origem["ne_curta"].fillna(origem["contrato_numero"])
    grupos_esperados = int(chave.nunique(dropna=False))
    if grupos_esperados != len(nativo):
        raise ErroMigracaoCadastros(
            "Contratos: "
            f"{grupos_esperados} grupos esperados e {len(nativo)} registros no cadastro."
        )

    mensal_origem = _soma(origem, "despesa_mensal")
    mensal_nativo = _soma(nativo, "despesa_mensal")
    empenhado_origem = _soma(origem, "valor_empenhado")
    empenhado_nativo = _soma(nativo, "valor_empenhado")
    _exigir_igual("Contratos - despesa mensal", mensal_origem, mensal_nativo)
    _exigir_igual("Contratos - valor empenhado", empenhado_origem, empenhado_nativo)

    return {
        "linhas_origem": len(origem),
        "grupos_esperados": grupos_esperados,
        "registros": len(nativo),
        "despesa_mensal_origem": mensal_origem,
        "despesa_mensal_cadastro": mensal_nativo,
        "valor_empenhado_origem": empenhado_origem,
        "valor_empenhado_cadastro": empenhado_nativo,
    }


def migrar_cadastros_nativos(
    origem_bolsas: str | Path,
    origem_contratos: str | Path,
    ano: int,
    *,
    diretorio_bolsas: str | Path = bolsas_cadastro.DIRETORIO_PADRAO,
    diretorio_contratos: str | Path = contratos_cadastro.DIRETORIO_PADRAO,
    aplicar: bool = False,
) -> dict:
    """Valida os dois cadastros e, com ``aplicar=True``, promove-os sem sobrescrever.

    A promoção usa ``Path.replace`` no mesmo volume de cada destino. Se a segunda promoção
    falhar, a primeira é devolvida ao staging antes que o erro seja propagado.
    """

    origem_bolsas = Path(origem_bolsas)
    origem_contratos = Path(origem_contratos)
    diretorio_bolsas = Path(diretorio_bolsas)
    diretorio_contratos = Path(diretorio_contratos)
    ano = int(ano)

    for origem in (origem_bolsas, origem_contratos):
        if not origem.is_file():
            raise FileNotFoundError(origem)

    destino_bolsas = diretorio_bolsas / str(ano)
    destino_contratos = diretorio_contratos / str(ano)
    destinos_existentes = [
        str(destino) for destino in (destino_bolsas, destino_contratos) if destino.exists()
    ]
    if aplicar and destinos_existentes:
        raise ErroMigracaoCadastros(
            "Exercício já cadastrado; nada foi gravado: " + ", ".join(destinos_existentes)
        )

    hashes_antes = {
        "bolsas": _sha256(origem_bolsas),
        "contratos": _sha256(origem_contratos),
    }
    dataframe_bolsas = ler_bolsas_auxilios(origem_bolsas)
    dataframe_contratos = ler_contratos_continuos(origem_contratos)

    with ExitStack() as pilha:
        if aplicar:
            diretorio_bolsas.parent.mkdir(parents=True, exist_ok=True)
            diretorio_contratos.parent.mkdir(parents=True, exist_ok=True)
            tmp_bolsas = pilha.enter_context(
                tempfile.TemporaryDirectory(
                    prefix="budgetlab_bolsas_", dir=diretorio_bolsas.parent
                )
            )
            tmp_contratos = pilha.enter_context(
                tempfile.TemporaryDirectory(
                    prefix="budgetlab_contratos_", dir=diretorio_contratos.parent
                )
            )
        else:
            tmp_bolsas = pilha.enter_context(
                tempfile.TemporaryDirectory(prefix="budgetlab_bolsas_")
            )
            tmp_contratos = pilha.enter_context(
                tempfile.TemporaryDirectory(prefix="budgetlab_contratos_")
            )

        stage_bolsas = Path(tmp_bolsas) / "cadastro"
        stage_contratos = Path(tmp_contratos) / "cadastro"
        bolsas_cadastro.migrar_de_planilha(
            origem_bolsas, ano, diretorio_base=stage_bolsas
        )
        contratos_cadastro.migrar_de_planilha(
            origem_contratos, ano, diretorio_base=stage_contratos
        )
        registros_bolsas = carregar_registros(stage_bolsas, ano)
        registros_contratos = carregar_registros(stage_contratos, ano)
        resumo_bolsas = _validar_bolsas(dataframe_bolsas, registros_bolsas)
        resumo_contratos = _validar_contratos(dataframe_contratos, registros_contratos)

        hashes_depois = {
            "bolsas": _sha256(origem_bolsas),
            "contratos": _sha256(origem_contratos),
        }
        if hashes_depois != hashes_antes:
            raise ErroMigracaoCadastros("Uma planilha de origem mudou durante a migração.")

        if aplicar:
            diretorio_bolsas.mkdir(parents=True, exist_ok=True)
            diretorio_contratos.mkdir(parents=True, exist_ok=True)
            if destino_bolsas.exists() or destino_contratos.exists():
                raise ErroMigracaoCadastros(
                    "Um destino passou a existir durante a validação; nada foi sobrescrito."
                )

            movimentos: list[tuple[Path, Path]] = []
            try:
                origem_stage_bolsas = stage_bolsas / str(ano)
                origem_stage_bolsas.replace(destino_bolsas)
                movimentos.append((destino_bolsas, origem_stage_bolsas))

                origem_stage_contratos = stage_contratos / str(ano)
                origem_stage_contratos.replace(destino_contratos)
                movimentos.append((destino_contratos, origem_stage_contratos))
            except Exception:
                for destino, origem_stage in reversed(movimentos):
                    destino.replace(origem_stage)
                raise

    return {
        "modo": "aplicacao" if aplicar else "simulacao",
        "gravado": aplicar,
        "ano": ano,
        "aplicavel": not destinos_existentes,
        "destinos_existentes": destinos_existentes,
        "origens": {
            "bolsas": str(origem_bolsas),
            "contratos": str(origem_contratos),
        },
        "destinos": {
            "bolsas": str(destino_bolsas),
            "contratos": str(destino_contratos),
        },
        "hashes_sha256": hashes_antes,
        "bolsas": resumo_bolsas,
        "contratos": resumo_contratos,
    }
