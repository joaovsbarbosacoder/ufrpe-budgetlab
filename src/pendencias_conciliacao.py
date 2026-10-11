"""
Pendências de conciliação (relatório de competência × notas do Contratos.gov) por atualização do gov (11/10/2026).

Camada: regra pura + persistência mínima. A cada atualização do Contratos.gov, calcula as pendências de cada contrato
(com o filtro padrão — NEs da 20RK —, as mesmas causas da seção do cadastro) e compara com as da atualização anterior:
"N pendência(s) nova(s), M resolvida(s)". É o que impede o acúmulo silencioso de divergências.

PERSISTÊNCIA (autorizada pelo usuário em 11/10/2026): um único arquivo `data/conciliacao_pendencias/ultima.json`
(versao_schema 1, gravação atômica tmp+replace) com as pendências da última atualização. Arquivo ilegível levanta
`ErroBaseline` — nunca vira "sem baseline" em silêncio. Não é lido nem alterado por nenhuma outra parte do sistema.

Contrato público:
    calcular_pendencias(contratos, faturas, empenhos_gov, relatorio) -> {contrato: {(ano_mes, classe)}}
    comparar(anterior, atual) -> (novas, resolvidas)       # conjuntos de (contrato, ano_mes, classe)
    mensagem_delta(novas, resolvidas, total) -> str
    carregar_baseline(diretorio=None) -> {"fotografia", "gerado_em", "pendencias"} | None
    salvar_baseline(pendencias, fotografia, diretorio=None) -> Path
    atualizar_apos_gravacao(fotografia, referencia, diretorio=None) -> str     # orquestra tudo e devolve a mensagem
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.conciliacao_competencia_gov import (
    CLASSES_OK,
    ajustar_mes,
    causas_do_mes,
    classificar_mes,
    conciliar_exercicio,
    empenhos_do_contrato,
    exercicios_disponiveis,
    filtrar_mes,
    itens_das_notas,
    nes_do_mes,
    padrao_do_mes,
    construir_contexto,
)

DIRETORIO_PADRAO = Path("data/conciliacao_pendencias")
VERSAO_SCHEMA = 1


class ErroBaseline(RuntimeError):
    """O arquivo de pendências da atualização anterior existe mas não pôde ser lido."""


def _pendencias_do_contrato(
    cid: object, ne_cadastro: object, faturas: pd.DataFrame | None, empenhos_gov: pd.DataFrame | None,
    relatorio: pd.DataFrame | None,
) -> set[tuple[int, str]]:
    if cid is None or (isinstance(cid, float) and pd.isna(cid)):
        return set()
    cid = str(cid)
    empenhos = empenhos_do_contrato(empenhos_gov, cid, ne_cadastro)
    naturezas = {ne: info.natureza for ne, info in empenhos.items()}
    tabela = None if faturas is None else faturas[faturas["contrato_id"].astype(str) == cid]
    itens, _ = itens_das_notas(tabela, naturezas)
    pendentes, _ = itens_das_notas(tabela, naturezas, liquidadas=False)
    contexto = construir_contexto(relatorio, itens, pendentes, naturezas)
    resultado: set[tuple[int, str]] = set()
    for ano in exercicios_disponiveis(relatorio, itens, naturezas):
        for completo in conciliar_exercicio(ano, relatorio, itens, naturezas):
            if not nes_do_mes(completo):
                continue
            escolhidas = padrao_do_mes(completo, empenhos)
            visto = filtrar_mes(completo, escolhidas)
            causas = causas_do_mes(contexto, ano, completo.mes, escolhidas)
            explicadas = {c.ne for c in causas if c.tipo == "deslocamento"}
            classe = classificar_mes(visto, ajustar_mes(visto, explicadas), causas)
            if classe not in CLASSES_OK:
                resultado.add((ano * 100 + completo.mes, classe))
    return resultado


def calcular_pendencias(
    contratos: list[tuple], faturas: pd.DataFrame | None, empenhos_gov: pd.DataFrame | None, relatorio: pd.DataFrame | None,
) -> dict[str, set[tuple[int, str]]]:
    """Pendências por contrato: `contratos` = [(número, id no Contratos.gov ou None, NE do cadastro ou None)]. Mês
    pendente = qualquer classe que não seja "batem"/"sem registro" (ver `CLASSES_OK`), com o filtro padrão do mês."""

    return {
        str(numero): _pendencias_do_contrato(cid, ne, faturas, empenhos_gov, relatorio) for numero, cid, ne in contratos
    }


def comparar(anterior: dict | None, atual: dict) -> tuple[set, set]:
    """Pendências novas e resolvidas desde a atualização anterior. Sem baseline (primeira vez) nada é "novo": só se registra."""

    if anterior is None:
        return set(), set()

    def achatar(d: dict) -> set:
        return {(contrato, am, classe) for contrato, pares in d.items() for am, classe in pares}

    antes, depois = achatar(anterior), achatar(atual)
    return depois - antes, antes - depois


def mensagem_delta(novas: set, resolvidas: set, total: int) -> str:
    if not novas and not resolvidas:
        return f"Conciliação por competência: nenhuma mudança nas pendências desde a atualização anterior ({total} pendência(s) no total)."
    partes = []
    if novas:
        partes.append(f"{len(novas)} pendência(s) nova(s)")
    if resolvidas:
        partes.append(f"{len(resolvidas)} resolvida(s)")
    return f"Conciliação por competência desde a atualização anterior: {', '.join(partes)} ({total} pendência(s) no total)."


def _caminho(diretorio: Path | None) -> Path:
    return Path(diretorio if diretorio is not None else DIRETORIO_PADRAO) / "ultima.json"


def carregar_baseline(diretorio: Path | None = None) -> dict | None:
    caminho = _caminho(diretorio)
    if not caminho.exists():
        return None
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
        return {
            "fotografia": bruto["fotografia"], "gerado_em": bruto["gerado_em"],
            "pendencias": {c: {(int(am), classe) for am, classe in pares} for c, pares in bruto["pendencias"].items()},
        }
    except (OSError, ValueError, KeyError, TypeError) as erro:
        raise ErroBaseline(f"Não foi possível ler {caminho}: {erro}") from erro


def salvar_baseline(pendencias: dict, fotografia: str, diretorio: Path | None = None) -> Path:
    caminho = _caminho(diretorio)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {
        "versao_schema": VERSAO_SCHEMA, "fotografia": fotografia, "gerado_em": datetime.now().replace(microsecond=0).isoformat(),
        "pendencias": {c: sorted([am, classe] for am, classe in pares) for c, pares in pendencias.items()},
    }
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(json.dumps(conteudo, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temporario, caminho)
    return caminho


def atualizar_apos_gravacao(fotografia: dict, referencia, diretorio: Path | None = None) -> str:
    """Chamada logo depois de gravar uma fotografia nova do Contratos.gov: calcula as pendências de todos os contratos do
    cadastro de Contínuos (exercício mais recente) com a fotografia NOVA e a Liquidação por Competência em
    `data/raw`, compara com a atualização anterior, grava a nova referência e devolve a mensagem para o usuário.
    Qualquer falha de leitura levanta exceção — o chamador mostra o aviso sem desfazer a gravação da fotografia."""

    from src.contratos_cadastro import (  # importações tardias: este módulo é puro e leve sem elas
        contratos_com_faturas,
        montar_contratos,
        montar_empenhos,
        montar_faturas,
        montar_termos,
    )
    from src.contratos_continuos import com_contratosgov
    from src.contratos_continuos_cadastro import anos_disponiveis, carregar_contratos, como_dataframe
    from src.execucao_ne_utils import ne_curta
    from src.liquidacao_competencia import ler_liquidacao_competencia, liquidado_por_ne_e_mes

    caminho_relatorio = Path("data/raw") / "Liquidação por Competência.xlsx"
    if not caminho_relatorio.exists():
        raise FileNotFoundError(f"{caminho_relatorio} não encontrado: sem o relatório de competência não há o que conciliar.")
    anos = anos_disponiveis()
    if not anos:
        raise ValueError("Nenhum contrato cadastrado em Contratos Contínuos.")
    relatorio = liquidado_por_ne_e_mes(ler_liquidacao_competencia(caminho_relatorio))
    relatorio["ne_curta"] = relatorio["ne_ccor"].apply(ne_curta)

    contratos_gov, termos, empenhos = montar_contratos(fotografia, referencia), montar_termos(fotografia), montar_empenhos(fotografia)
    faturas = montar_faturas(fotografia)
    ano = max(anos)
    tabela = com_contratosgov(como_dataframe(carregar_contratos(ano), ano), contratos_gov, termos, empenhos)
    consultados = contratos_com_faturas(fotografia)
    ligados = []
    for _, linha in tabela.drop_duplicates("contrato_numero").iterrows():
        cid = linha.get("contratosgov_id")
        cid = None if pd.isna(cid) or str(cid) not in consultados else str(cid)
        ne = linha.get("ne_curta")
        ligados.append((linha["contrato_numero"], cid, None if pd.isna(ne) else str(ne)))

    atual = calcular_pendencias(ligados, faturas, empenhos, relatorio)
    anterior = carregar_baseline(diretorio)
    novas, resolvidas = comparar(None if anterior is None else anterior["pendencias"], atual)
    salvar_baseline(atual, fotografia=str(fotografia.get("_sha256", ""))[:12], diretorio=diretorio)
    total = sum(len(pares) for pares in atual.values())
    if anterior is None:
        return f"Conciliação por competência: primeira referência registrada ({total} pendência(s) em {len(atual)} contrato(s))."
    return mensagem_delta(novas, resolvidas, total)
