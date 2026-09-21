"""Especificações de reimportação (`src/ui_reimportacao.py::EspecificacaoReimportacao`) das
bases com importação versionada — Execução Anual, Dotação Anual e Execução Mensal.

Extraído de `app_pages/execucao_orcamentaria.py`/`app_pages/dotacao_orcamentaria.py` (onde a
seção "Reimportar base" vivia antes) para `app_pages/atualizar_planilhas.py`, o único lugar do
app que recebe planilha nova agora (pedido explícito: um só menu para toda atualização de
dado, versionada ou não) — poder importar essas specs sem executar o script inteiro da
página de análise (`app_pages/*.py` roda como script Streamlit, não é seguro importar como
biblioteca) é exatamente o motivo deste módulo existir.

Execução Mensal (21/09/2026, pedido explícito do usuário): migrou de "planilha de trabalho"
sem manifesto (`src/atualizar_planilhas.py`) para este mesmo padrão versionado — ver docstring
de `src/importacao_execucao_mensal.py` para o que isso muda no armazenamento do arquivo bruto.

Contrato público:
    ESPECIFICACAO_EXECUCAO_ANUAL: EspecificacaoReimportacao
    ESPECIFICACAO_DOTACAO_ANUAL: EspecificacaoReimportacao
    ESPECIFICACAO_EXECUCAO_MENSAL: EspecificacaoReimportacao
"""

from __future__ import annotations

from pathlib import Path

from src.execucao_anual import MEDIDAS as MEDIDAS_EXECUCAO
from src.importacao_dotacao import (
    DIRETORIO_MANIFESTOS_PADRAO as DIRETORIO_MANIFESTOS_DOTACAO,
    MEDIDAS as MEDIDAS_DOTACAO,
    ROTULOS_MEDIDAS,
)
from src.importacao_dotacao import Manifesto as ManifestoDotacao
from src.importacao_dotacao import importar as importar_dotacao
from src.importacao_execucao import DIRETORIO_MANIFESTOS_PADRAO as DIRETORIO_MANIFESTOS_EXECUCAO
from src.importacao_execucao import Manifesto as ManifestoExecucao
from src.importacao_execucao import importar as importar_execucao
from src.importacao_execucao_mensal import DIRETORIO_MANIFESTOS_PADRAO as DIRETORIO_MANIFESTOS_EXECUCAO_MENSAL
from src.importacao_execucao_mensal import Manifesto as ManifestoExecucaoMensal
from src.importacao_execucao_mensal import importar as importar_execucao_mensal
from src.tesouro_execucao_mensal import MEDIDAS as MEDIDAS_EXECUCAO_MENSAL
from src.ui_reimportacao import EspecificacaoReimportacao

# nota: importacao_dotacao/importacao_execucao/importacao_execucao_mensal são importados em
# blocos separados de propósito (Manifesto/importar têm o mesmo nome nos três módulos —
# precisam de alias, e misturar aliased/não-aliased no mesmo `from ... import (...)` fica
# menos legível que só repetir o `from`).

DIRETORIO_DADOS_BRUTOS = Path("data/raw")


def _linhas_resumo_execucao(manifesto: ManifestoExecucao) -> str:
    return (
        f"{manifesto.linhas} linhas · {manifesto.linhas_empenho} de empenho · "
        f"{manifesto.linhas_item_execucao} de item de execução · "
        f"{manifesto.notas_empenho_distintas} NEs distintas · "
        f"exercícios {', '.join(map(str, manifesto.anos))}"
    )


def _linhas_resumo_execucao_mensal(manifesto: ManifestoExecucaoMensal) -> str:
    contagens = manifesto.contagens
    return (
        f"{contagens.get('linhas_originais')} linhas brutas · "
        f"{contagens.get('notas_empenho_distintas')} NEs distintas · "
        f"exercícios {', '.join(map(str, manifesto.anos))}"
    )


def _linhas_resumo_dotacao(manifesto: ManifestoDotacao) -> str:
    contagens = manifesto.contagens
    return (
        f"{contagens.get('abas_reconhecidas')} aba(s) reconhecida(s) · "
        f"{contagens.get('linhas_normalizadas')} linhas normalizadas · "
        f"{contagens.get('nulos')} nulos · {contagens.get('zeros')} zeros · "
        f"{contagens.get('negativos')} negativos · "
        f"exercícios {', '.join(map(str, manifesto.anos))}"
    )


ESPECIFICACAO_EXECUCAO_ANUAL = EspecificacaoReimportacao(
    prefixo_estado="execucao_anual_reimport",
    diretorio_dados_brutos=DIRETORIO_DADOS_BRUTOS,
    diretorio_manifestos=DIRETORIO_MANIFESTOS_EXECUCAO,
    medidas=MEDIDAS_EXECUCAO,
    importar=importar_execucao,
    linhas_resumo=_linhas_resumo_execucao,
)

ESPECIFICACAO_DOTACAO_ANUAL = EspecificacaoReimportacao(
    prefixo_estado="dotacao_anual_reimport",
    diretorio_dados_brutos=DIRETORIO_DADOS_BRUTOS,
    diretorio_manifestos=DIRETORIO_MANIFESTOS_DOTACAO,
    medidas=MEDIDAS_DOTACAO,
    importar=importar_dotacao,
    linhas_resumo=_linhas_resumo_dotacao,
    formatar_medida=lambda medida: ROTULOS_MEDIDAS[medida],
)

ESPECIFICACAO_EXECUCAO_MENSAL = EspecificacaoReimportacao(
    prefixo_estado="execucao_mensal_reimport",
    diretorio_dados_brutos=DIRETORIO_DADOS_BRUTOS,
    diretorio_manifestos=DIRETORIO_MANIFESTOS_EXECUCAO_MENSAL,
    medidas=MEDIDAS_EXECUCAO_MENSAL,
    importar=importar_execucao_mensal,
    linhas_resumo=_linhas_resumo_execucao_mensal,
)
