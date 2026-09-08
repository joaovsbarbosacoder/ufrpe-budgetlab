"""Importação versionada do relatório Emendas — Acompanhamento.

A carga inicial é uma fotografia histórica e pode conter qualquer exercício.
Depois dela, toda atualização é validada pela política de
``src.emendas_parlamentares`` e só pode trazer exercícios a partir de 2026.
A composição por ano do núcleo versionado mantém os anos históricos da carga
inicial e substitui somente os exercícios presentes nas atualizações.

Os arquivos brutos são imutáveis e recebem um nome com o hash da extração.
Assim, dois uploads com o mesmo nome não sobrescrevem versões anteriores.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.emendas_parlamentares import (
    ANO_INICIO_ATUALIZACAO,
    ErroPoliticaImportacao,
    validar_anos_importaveis,
)
from src.importacao_versionada import (
    DIRETORIO_MANIFESTOS_PADRAO,
    Delta,
    Manifesto as _ManifestoGenerico,
    ResultadoImportacao,
    comparar as _comparar_generico,
    historico as _historico_generico,
    historico_como_tabela as _historico_como_tabela_generico,
    importar as _importar_generico,
    manifestos_por_ano,
    nome_ponteiro,
)
from src.tesouro_emendas_acompanhamento import (
    COLUNAS_FINANCEIRAS,
    ler_emendas_acompanhamento,
    reconciliar_emendas_acompanhamento,
)


BASE = "emendas_acompanhamento"
NOME_PONTEIRO = nome_ponteiro(BASE)
DIRETORIO_DADOS_BRUTOS_PADRAO = Path("data/raw")
MEDIDAS: tuple[str, ...] = tuple(COLUNAS_FINANCEIRAS)
ROTULOS_MEDIDAS = {
    "dotacao_atualizada": "Dotação atualizada",
    "empenhada_relatorio": "Empenhada no relatório",
    "liquidada_relatorio": "Liquidada no relatório",
    "paga_relatorio": "Paga no relatório",
}


class Manifesto(_ManifestoGenerico):
    """Manifesto com a base de Emendas já fixada."""

    BASE = BASE


@dataclass
class RelatorioValidacao:
    erros: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.erros


def validar_atualizacao(df: pd.DataFrame) -> RelatorioValidacao:
    """Valida um upload posterior; histórico anterior a 2026 é bloqueado."""

    relatorio = RelatorioValidacao()
    try:
        validar_anos_importaveis(df)
    except ErroPoliticaImportacao as error:
        relatorio.erros.append(str(error))
    return relatorio


def validar_carga_inicial(df: pd.DataFrame) -> RelatorioValidacao:
    """A carga inicial pode conter o histórico completo observado."""

    relatorio = RelatorioValidacao()
    anos = sorted(int(ano) for ano in df["ano"].dropna().unique())
    if not anos:
        relatorio.erros.append("A carga inicial não possui exercícios.")
    elif max(anos) < ANO_INICIO_ATUALIZACAO:
        relatorio.alertas.append(
            f"A carga inicial não contém exercício a partir de {ANO_INICIO_ATUALIZACAO}."
        )
    return relatorio


def gerar_manifesto(
    df: pd.DataFrame,
    caminho: Path,
    *,
    carga_inicial: bool = False,
) -> Manifesto:
    resultado = _importar(
        caminho,
        carga_inicial=carga_inicial,
        registrar=False,
    )
    return resultado.manifesto


def comparar(anterior: Manifesto | None, novo: Manifesto) -> Delta:
    return _comparar_generico(anterior, novo, medidas=MEDIDAS)


def importar(
    caminho: str | Path,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
    registrar: bool = True,
) -> ResultadoImportacao:
    """Importa uma atualização que contenha exclusivamente exercícios 2026+."""

    return _importar(
        caminho,
        carga_inicial=False,
        diretorio_manifestos=diretorio_manifestos,
        registrar=registrar,
    )


def importar_carga_inicial(
    caminho: str | Path,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
    registrar: bool = True,
) -> ResultadoImportacao:
    """Importa explicitamente a fotografia histórica inicial."""

    diretorio_manifestos = Path(diretorio_manifestos)
    anterior = Manifesto.atual(diretorio_manifestos)
    if anterior is not None:
        raise ErroPoliticaImportacao(
            "A carga inicial de Emendas já foi registrada. Use a atualização 2026+."
        )
    resultado = _importar(
        caminho,
        carga_inicial=True,
        diretorio_manifestos=diretorio_manifestos,
        registrar=False,
    )
    if registrar:
        if Path(caminho).name != resultado.manifesto.arquivo:
            raise ErroPoliticaImportacao(
                "Para registrar e copiar uma carga inicial externa, use "
                "instalar_carga_inicial()."
            )
        if resultado.ok and not resultado.delta.mesma_extracao:
            resultado.caminho_manifesto = resultado.manifesto.salvar(
                Path(diretorio_manifestos)
            )
    return resultado


def instalar_carga_inicial(
    caminho_origem: str | Path,
    diretorio_dados_brutos: str | Path = DIRETORIO_DADOS_BRUTOS_PADRAO,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
) -> ResultadoImportacao:
    """Copia e registra a base inicial sem modificar o arquivo recebido.

    A operação é recusada se já houver um manifesto desta base. O arquivo é
    primeiro validado em sua localização original e só depois copiado para
    ``data/raw`` com nome versionado pelo hash.
    """

    caminho_origem = Path(caminho_origem)
    diretorio_dados_brutos = Path(diretorio_dados_brutos)
    diretorio_manifestos = Path(diretorio_manifestos)
    if Manifesto.atual(diretorio_manifestos) is not None:
        raise ErroPoliticaImportacao(
            "A carga inicial de Emendas já foi registrada. Use a atualização 2026+."
        )

    resultado = _importar(
        caminho_origem,
        carga_inicial=True,
        diretorio_manifestos=diretorio_manifestos,
        registrar=False,
    )
    if not resultado.ok:
        raise ErroPoliticaImportacao("; ".join(resultado.validacao.erros))

    diretorio_dados_brutos.mkdir(parents=True, exist_ok=True)
    destino = diretorio_dados_brutos / resultado.manifesto.arquivo
    temporario = destino.with_suffix(destino.suffix + ".tmp")
    shutil.copy2(caminho_origem, temporario)
    temporario.replace(destino)
    resultado.manifesto.salvar(diretorio_manifestos)
    resultado.caminho_manifesto = (
        diretorio_manifestos
        / f"{BASE}_{resultado.manifesto.rotulo}.json"
    )
    return resultado


def carregar_atual(
    diretorio_dados_brutos: str | Path = DIRETORIO_DADOS_BRUTOS_PADRAO,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
) -> pd.DataFrame | None:
    """Monta a base por ano, preservando o histórico da carga inicial."""

    por_ano = manifestos_por_ano(BASE, diretorio_manifestos)
    if not por_ano:
        return None

    anos_por_sha: dict[str, list[int]] = {}
    manifesto_por_sha: dict[str, Manifesto] = {}
    for ano, manifesto in por_ano.items():
        anos_por_sha.setdefault(manifesto.sha256, []).append(ano)
        manifesto_por_sha[manifesto.sha256] = manifesto

    diretorio_dados_brutos = Path(diretorio_dados_brutos)
    partes: list[pd.DataFrame] = []
    for sha, anos in sorted(anos_por_sha.items(), key=lambda item: min(item[1])):
        manifesto = manifesto_por_sha[sha]
        df = ler_emendas_acompanhamento(diretorio_dados_brutos / manifesto.arquivo)
        partes.append(df[df["ano"].isin(anos)].copy())
    return partes[0] if len(partes) == 1 else pd.concat(partes, ignore_index=True)


def historico(
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
) -> list[Manifesto]:
    return _historico_generico(BASE, diretorio_manifestos)


def historico_como_tabela(
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
) -> pd.DataFrame:
    return _historico_como_tabela_generico(
        BASE,
        MEDIDAS,
        diretorio_manifestos,
        contagem_destaque="linhas",
    )


def _importar(
    caminho: str | Path,
    *,
    carga_inicial: bool,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
    registrar: bool,
) -> ResultadoImportacao:
    caminho = Path(caminho)
    validar = validar_carga_inicial if carga_inicial else validar_atualizacao
    resultado = _importar_generico(
        caminho,
        base=BASE,
        ler=ler_emendas_acompanhamento,
        reconciliar=reconciliar_emendas_acompanhamento,
        validar=validar,
        medidas=MEDIDAS,
        diretorio_manifestos=diretorio_manifestos,
        registrar=False,
    )
    resultado.manifesto = Manifesto(**resultado.manifesto.to_dict())
    resultado.manifesto.arquivo = _nome_versionado(
        caminho.name,
        resultado.manifesto.sha256,
    )

    if registrar and resultado.ok and not resultado.delta.mesma_extracao:
        resultado.caminho_manifesto = resultado.manifesto.salvar(
            Path(diretorio_manifestos)
        )
    return resultado


def _nome_versionado(nome_original: str, sha256: str) -> str:
    caminho = Path(nome_original)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", caminho.stem).strip("._-")
    stem = stem or "emendas_acompanhamento"
    sufixo_hash = f"_{sha256[:8]}"
    if not stem.lower().endswith(sufixo_hash.lower()):
        stem += sufixo_hash
    return f"{stem}.xlsx"


def sha256_arquivo(caminho: str | Path) -> str:
    """Hash público usado por testes e rotinas de instalação."""

    digest = hashlib.sha256()
    with Path(caminho).open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            digest.update(bloco)
    return digest.hexdigest()
