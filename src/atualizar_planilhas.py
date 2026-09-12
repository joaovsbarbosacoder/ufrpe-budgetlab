"""Atualização das planilhas de trabalho sem reimportação versionada (Contratos Contínuos,
Bolsas e Auxílios, Contratos — Vigência, Contratos — Pagamentos, Execução Mensal, Liquidação
por Competência) — ver AGENTS.md, seção "Fixtures de teste vs. dados de trabalho".

Camada: regra específica desta funcionalidade, não leitor de base (reaproveita o `ler_*` de
cada base só para validar layout, nunca reimplementa a leitura), não interface (não importa
Streamlit — ver `app_pages/atualizar_planilhas.py` para a UI).

Diferente de `src/importacao_versionada.py`/`src/ui_reimportacao.py` (Dotação/Execução
Anual): essas 6 bases não têm manifesto nem detecção de delta/retroatividade — são planilhas
de trabalho mantidas manualmente, substituídas inteiras a cada atualização, sem aviso prévio
de layout (ver AGENTS.md). `substituir_planilha` só faz duas coisas: valida o arquivo novo
com o leitor da própria base antes de aceitar (nunca adivinha um layout novo — se o leitor
rejeitar, a exceção original propaga sem tocar em nada), e preserva o arquivo atual num
backup com carimbo de data/hora antes de sobrescrever — nunca apaga a versão anterior.

Contrato público:
    ESPECIFICACOES: dict[str, EspecificacaoBase]
    substituir_planilha(spec, arquivo_novo) -> ResultadoSubstituicao
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.bolsas_auxilios import ler_bolsas_auxilios
from src.contratos_continuos import ler_contratos_continuos
from src.contratos_pagamentos import ler_pagamentos
from src.contratos_vigencia import ler_contratos_vigencia
from src.liquidacao_competencia import ler_liquidacao_competencia
from src.tesouro_execucao_mensal import ler_execucao_mensal

DIRETORIO_DADOS_BRUTOS = Path("data/raw")


@dataclass(frozen=True)
class EspecificacaoBase:
    chave: str
    nome: str
    caminho: Path
    extensao: str  # sem ponto, ex. "xlsx"/"xlsm" — usado no filtro do uploader
    validar: Callable[[Path], pd.DataFrame]


#: as 6 planilhas de trabalho sem reimportação versionada (ver docstring do módulo).
#: "Contratos — Pagamentos" não tem página de análise no menu hoje (tirada por pedido
#: explícito, ver app.py), mas continua entrando aqui — ainda alimenta "Meses Pagos" em
#: Contratos Contínuos, então precisa poder ser atualizada mesmo sem tela própria.
ESPECIFICACOES: dict[str, EspecificacaoBase] = {
    "contratos_continuos": EspecificacaoBase(
        chave="contratos_continuos",
        nome="Contratos Contínuos",
        caminho=DIRETORIO_DADOS_BRUTOS / "SERVIÇOS CONTÍNUOS - 2026 - AGO A DEZ.xlsm",
        extensao="xlsm",
        validar=ler_contratos_continuos,
    ),
    "bolsas_auxilios": EspecificacaoBase(
        chave="bolsas_auxilios",
        nome="Bolsas e Auxílios",
        caminho=DIRETORIO_DADOS_BRUTOS / "BOLSAS E AUXÍLIOS 2026 - AGO A DEZ.xlsx",
        extensao="xlsx",
        validar=ler_bolsas_auxilios,
    ),
    "contratos_vigencia": EspecificacaoBase(
        chave="contratos_vigencia",
        nome="Contratos — Vigência",
        caminho=DIRETORIO_DADOS_BRUTOS / "CONTRATOS UFRPE - BASE_CONTRATOS.xlsx",
        extensao="xlsx",
        validar=ler_contratos_vigencia,
    ),
    "contratos_pagamentos": EspecificacaoBase(
        chave="contratos_pagamentos",
        nome="Contratos — Pagamentos",
        caminho=DIRETORIO_DADOS_BRUTOS / "CONTRATOS - CONTROLE 2020 - Pagamentos.xlsx",
        extensao="xlsx",
        validar=ler_pagamentos,
    ),
    "execucao_mensal": EspecificacaoBase(
        chave="execucao_mensal",
        nome="Execução Mensal",
        # mesmo caminho fixo referenciado por app_pages/execucao_mensal.py e
        # app_pages/consulta_empenhos.py (CAMINHO_EXECUCAO_MENSAL) — atualizar aqui já
        # alimenta as duas telas, sem precisar duplicar a constante.
        caminho=DIRETORIO_DADOS_BRUTOS / "BI CPOC - EXEC. DESPESAS - Mensal.xlsx",
        extensao="xlsx",
        validar=ler_execucao_mensal,
    ),
    "liquidacao_competencia": EspecificacaoBase(
        chave="liquidacao_competencia",
        nome="Liquidação por Competência",
        # mesmo caminho fixo referenciado por app_pages/consulta_empenhos.py
        # (CAMINHO_LIQUIDACAO_COMPETENCIA) — usada hoje só na Linha do Tempo Mensal daquela
        # página (ver src/liquidacao_competencia.py sobre o escopo reduzido desta base).
        caminho=DIRETORIO_DADOS_BRUTOS / "Liquidação por Competência.xlsx",
        extensao="xlsx",
        validar=ler_liquidacao_competencia,
    ),
}


@dataclass(frozen=True)
class ResultadoSubstituicao:
    linhas_lidas: int
    caminho_backup: Path | None  # None quando não havia arquivo anterior pra guardar


def _caminho_backup(spec: EspecificacaoBase, agora: datetime) -> Path:
    carimbo = agora.strftime("%Y-%m-%d-%Hh%M")
    nome = f"{spec.caminho.stem}__substituida-{carimbo}{spec.caminho.suffix}"
    # backup ao lado do próprio arquivo, não num diretório fixo em data/raw/ — assim um spec
    # de teste apontando pra um diretório temporário nunca escreve em data/raw/ de verdade.
    return spec.caminho.parent / "_backup" / nome


def substituir_planilha(
    spec: EspecificacaoBase, arquivo_novo: str | Path, agora: datetime | None = None
) -> ResultadoSubstituicao:
    """Valida `arquivo_novo` com o leitor da própria base (`spec.validar`) e, só se passar,
    substitui o arquivo em `spec.caminho`. Se já existir um arquivo ali, ele é movido pra um
    backup com carimbo de data/hora antes da substituição — nunca apagado. Se a validação
    falhar, a exceção do leitor (ex. `ErroLayoutBase`) propaga sem que nada no disco mude.
    """
    lido = spec.validar(Path(arquivo_novo))

    agora = agora or datetime.now()
    caminho_backup = None
    if spec.caminho.exists():
        caminho_backup = _caminho_backup(spec, agora)
        caminho_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(spec.caminho), str(caminho_backup))

    spec.caminho.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(arquivo_novo, spec.caminho)

    return ResultadoSubstituicao(linhas_lidas=len(lido), caminho_backup=caminho_backup)
