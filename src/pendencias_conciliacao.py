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
    meses_analisados(cid, ne, faturas, empenhos_gov, relatorio) -> list[dict]     # todos os meses com dado
    consolidar_exercicio(contratos, faturas, empenhos_gov, relatorio, ano) -> list[dict]   # visão de todos os contratos
    tabela_inconsistencias(contratos, faturas, empenhos_gov, relatorio) -> DataFrame   # relatório para o gov
    excel_inconsistencias(tabela) -> bytes
    gerar_relatorio_inconsistencias(fotografia, referencia, a_partir_do_ano=None) -> bytes
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.decisoes_conciliacao import aplicar_decisao, assinatura_mes, carregar_eventos, reconstruir_decisoes
from src.conciliacao_competencia_gov import (
    CLASSES,
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


COLUNAS_INCONSISTENCIAS = [
    "Contrato", "Competência", "Causa", "NEs", "Notas", "Valor nas notas", "Valor no relatório", "Diferença", "Ação sugerida",
]


def _acao_sugerida(classe: str, causas: list, ajuste, visto) -> str:
    if classe == "deslocamento":
        c = next(c for c in causas if c.tipo == "deslocamento")
        par = f"{c.par % 100:02d}/{c.par // 100}"
        return f"Corrigir a competência da nota no Contratos.gov (ou confirmar o lançamento no SIAFI): o valor está em {par} no outro lado."
    if classe == "nota_pendente":
        c = next(c for c in causas if c.tipo == "nota_pendente")
        return f"Concluir a liquidação/apropriação da(s) nota(s) {', '.join(c.notas)} no SIAFI (pendente ou com erro)."
    if classe == "cancelamento":
        notas = ", ".join(visto.itens[i].nota for i in ajuste.retiradas)
        return f"Verificar se a(s) nota(s) {notas} foi(ram) cancelada(s)/substituída(s) e registrar o cancelamento no Contratos.gov."
    if classe == "ambiguo":
        return "Identificar qual nota foi cancelada/substituída (mais de uma combinação fecha o valor) e registrar no Contratos.gov."
    if classe == "so_relatorio":
        return "Registrar no Contratos.gov o instrumento de cobrança (nota) desta competência: o Tesouro tem liquidação e o gov não tem nota."
    if classe == "so_notas":
        return "Conferir: NE sem competência no relatório (ex.: DEA) ou liquidação ausente no Tesouro para a nota."
    return "Conferir a nota e o lançamento no Tesouro: diferença sem causa identificada."


def meses_analisados(
    cid: object, ne_cadastro: object, faturas: pd.DataFrame | None, empenhos_gov: pd.DataFrame | None,
    relatorio: pd.DataFrame | None, numero: str | None = None, decisoes: dict | None = None,
) -> list[dict]:
    """TODOS os meses com dado do contrato (filtro padrão: NEs da 20RK), cada um com a classe, os valores nas duas
    fontes, as NEs, as notas e a ação sugerida. Contrato sem id no gov usa só o relatório da NE do cadastro. Com `numero` e
    `decisoes` (ver `src/decisoes_conciliacao.py`), uma decisão ATIVA do usuário muda a classe do mês para "confirmada"
    (resolvido) ou "rejeitada" (continua pendente); a `assinatura` de cada mês acompanha o resultado."""

    tem_gov = not (cid is None or (isinstance(cid, float) and pd.isna(cid)))
    cid = str(cid) if tem_gov else None
    empenhos = empenhos_do_contrato(empenhos_gov if tem_gov else None, cid, ne_cadastro)
    naturezas = {ne: info.natureza for ne, info in empenhos.items()}
    tabela = None if faturas is None or not tem_gov else faturas[faturas["contrato_id"].astype(str) == cid]
    itens, _ = itens_das_notas(tabela, naturezas)
    pendentes, _ = itens_das_notas(tabela, naturezas, liquidadas=False)
    contexto = construir_contexto(relatorio, itens, pendentes, naturezas)
    linhas: list[dict] = []
    for ano in exercicios_disponiveis(relatorio, itens, naturezas):
        for completo in conciliar_exercicio(ano, relatorio, itens, naturezas):
            if not nes_do_mes(completo):
                continue
            escolhidas = padrao_do_mes(completo, empenhos)
            visto = filtrar_mes(completo, escolhidas)
            causas = causas_do_mes(contexto, ano, completo.mes, escolhidas)
            explicadas = {c.ne for c in causas if c.tipo == "deslocamento"}
            ajuste = ajustar_mes(visto, explicadas)
            classe = classificar_mes(visto, ajuste, causas)
            assinatura = assinatura_mes(classe, escolhidas, [i.nota for i in visto.itens], visto.notas, visto.relatorio)
            if decisoes and numero is not None:
                classe = aplicar_decisao(classe, decisoes.get((str(numero), ano * 100 + completo.mes)), assinatura)
            linhas.append({
                "assinatura": assinatura, "classe": classe, "ano_mes": ano * 100 + completo.mes, "nes": sorted(escolhidas),
                "notas": sorted({i.nota for i in visto.itens}), "valor_notas": visto.notas, "valor_relatorio": visto.relatorio,
                "acao": _acao_sugerida(classe, causas, ajuste, visto) if classe not in CLASSES_OK else "",
            })
    return linhas


def detalhar_contrato(
    cid: object, ne_cadastro: object, faturas: pd.DataFrame | None, empenhos_gov: pd.DataFrame | None,
    relatorio: pd.DataFrame | None, numero: str | None = None, decisoes: dict | None = None,
) -> list[dict]:
    """Os meses PENDENTES do contrato (classe fora de `CLASSES_OK`), com valores, notas, causa e ação sugerida."""

    if cid is None or (isinstance(cid, float) and pd.isna(cid)):
        return []
    return [
        l for l in meses_analisados(cid, ne_cadastro, faturas, empenhos_gov, relatorio, numero, decisoes)
        if l["classe"] not in CLASSES_OK
    ]


def consolidar_exercicio(
    contratos: list[tuple], faturas: pd.DataFrame | None, empenhos_gov: pd.DataFrame | None, relatorio: pd.DataFrame | None,
    ano: int, decisoes: dict | None = None,
) -> list[dict]:
    """Visão consolidada de todos os contratos no exercício `ano`: por contrato, os 12 meses com o valor do relatório, o das
    notas e a classe, e os totais (None = sem nenhum valor). Contrato sem ligação ao gov entra pelo relatório da NE do
    cadastro."""

    resultado = []
    for numero, cid, ne in contratos:
        por_mes = {
            l["ano_mes"]: l for l in meses_analisados(cid, ne, faturas, empenhos_gov, relatorio, str(numero), decisoes)
            if l["ano_mes"] // 100 == ano
        }
        meses = []
        for mes in range(1, 13):
            l = por_mes.get(ano * 100 + mes)
            meses.append(
                {"mes": mes, "relatorio": l["valor_relatorio"], "notas": l["valor_notas"], "classe": l["classe"],
                 "acao": l["acao"], "assinatura": l["assinatura"]} if l else
                {"mes": mes, "relatorio": None, "notas": None, "classe": "sem_registro", "acao": "", "assinatura": ""}
            )
        def total(campo):
            valores = [m[campo] for m in meses if m[campo] is not None]
            return round(sum(valores), 2) if valores else None
        resultado.append({"contrato": str(numero), "meses": meses, "total_relatorio": total("relatorio"), "total_notas": total("notas")})
    return resultado


def _pendencias_do_contrato(
    cid: object, ne_cadastro: object, faturas: pd.DataFrame | None, empenhos_gov: pd.DataFrame | None,
    relatorio: pd.DataFrame | None, numero: str | None = None, decisoes: dict | None = None,
) -> set[tuple[int, str]]:
    return {
        (l["ano_mes"], l["classe"])
        for l in detalhar_contrato(cid, ne_cadastro, faturas, empenhos_gov, relatorio, numero, decisoes)
    }


def tabela_inconsistencias(
    contratos: list[tuple], faturas: pd.DataFrame | None, empenhos_gov: pd.DataFrame | None, relatorio: pd.DataFrame | None,
    a_partir_do_ano: int | None = None, decisoes: dict | None = None,
) -> pd.DataFrame:
    """Relatório de inconsistências para quem alimenta o Contratos.gov: uma linha por contrato e mês pendente, com a causa
    (rótulo de `CLASSES`), os valores nas duas fontes, a diferença e a ação sugerida. Ordenado por contrato e competência.
    `a_partir_do_ano`: só competências desse ano em diante (antes de 2025 as notas do gov são incompletas — ruído)."""

    linhas = []
    for numero, cid, ne in contratos:
        for l in detalhar_contrato(cid, ne, faturas, empenhos_gov, relatorio, str(numero), decisoes):
            if a_partir_do_ano is not None and l["ano_mes"] // 100 < a_partir_do_ano:
                continue
            nota, rel = l["valor_notas"], l["valor_relatorio"]
            linhas.append({
                "Contrato": str(numero), "Competência": f"{l['ano_mes'] % 100:02d}/{l['ano_mes'] // 100}",
                "Causa": CLASSES[l["classe"]], "NEs": ", ".join(l["nes"]), "Notas": ", ".join(l["notas"]) or "—",
                "Valor nas notas": nota, "Valor no relatório": rel,
                "Diferença": None if nota is None or rel is None else round(nota - rel, 2),
                "Ação sugerida": l["acao"], "_ordem": l["ano_mes"],
            })
    if not linhas:
        return pd.DataFrame(columns=COLUNAS_INCONSISTENCIAS)
    return pd.DataFrame(linhas).sort_values(["Contrato", "_ordem"]).drop(columns="_ordem").reset_index(drop=True)[COLUNAS_INCONSISTENCIAS]


def excel_inconsistencias(tabela: pd.DataFrame) -> bytes:
    """Excel com a aba "Resumo por causa" e a aba "Pendências"."""

    from io import BytesIO

    resumo = (
        tabela.groupby("Causa").agg(Meses=("Contrato", "size"), Contratos=("Contrato", "nunique")).reset_index()
        .sort_values("Meses", ascending=False) if not tabela.empty else pd.DataFrame(columns=["Causa", "Meses", "Contratos"])
    )
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
        resumo.to_excel(escritor, sheet_name="Resumo por causa", index=False)
        tabela.to_excel(escritor, sheet_name="Pendências", index=False)
        for aba in escritor.book.worksheets:
            for coluna in aba.columns:
                aba.column_dimensions[coluna[0].column_letter].width = min(
                    60, max(12, *(len(str(c.value)) for c in coluna if c.value is not None))
                )
    return buffer.getvalue()


def calcular_pendencias(
    contratos: list[tuple], faturas: pd.DataFrame | None, empenhos_gov: pd.DataFrame | None, relatorio: pd.DataFrame | None,
    decisoes: dict | None = None,
) -> dict[str, set[tuple[int, str]]]:
    """Pendências por contrato: `contratos` = [(número, id no Contratos.gov ou None, NE do cadastro ou None)]. Mês
    pendente = qualquer classe que não seja "batem"/"sem registro" (ver `CLASSES_OK`), com o filtro padrão do mês."""

    return {
        str(numero): _pendencias_do_contrato(cid, ne, faturas, empenhos_gov, relatorio, str(numero), decisoes)
        for numero, cid, ne in contratos
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
            # delta da última atualização (baseline antigo não tinha: vem vazio)
            "novas": {(c, int(am), classe) for c, am, classe in bruto.get("novas", [])},
            "resolvidas": {(c, int(am), classe) for c, am, classe in bruto.get("resolvidas", [])},
        }
    except (OSError, ValueError, KeyError, TypeError) as erro:
        raise ErroBaseline(f"Não foi possível ler {caminho}: {erro}") from erro


def salvar_baseline(
    pendencias: dict, fotografia: str, diretorio: Path | None = None, novas=(), resolvidas=(),
) -> Path:
    caminho = _caminho(diretorio)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {
        "versao_schema": VERSAO_SCHEMA, "fotografia": fotografia, "gerado_em": datetime.now().replace(microsecond=0).isoformat(),
        "pendencias": {c: sorted([am, classe] for am, classe in pares) for c, pares in pendencias.items()},
        "novas": sorted([c, am, classe] for c, am, classe in novas),
        "resolvidas": sorted([c, am, classe] for c, am, classe in resolvidas),
    }
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(json.dumps(conteudo, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temporario, caminho)
    return caminho


def contratos_ligados(tabela: pd.DataFrame, consultados: set) -> list[tuple]:
    """[(número, id no Contratos.gov ou None, NE do cadastro ou None)] de um cadastro de Contínuos já ligado ao gov
    (`com_contratosgov`); o id só vale se as notas do contrato foram consultadas (`consultados`)."""

    ligados = []
    for _, linha in tabela.drop_duplicates("contrato_numero").iterrows():
        cid = linha.get("contratosgov_id")
        cid = None if pd.isna(cid) or str(cid) not in consultados else str(cid)
        ne = linha.get("ne_curta")
        ligados.append((linha["contrato_numero"], cid, None if pd.isna(ne) else str(ne)))
    return ligados


def entradas_da_conciliacao(fotografia: dict, referencia) -> tuple[list, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Lê o cadastro de Contínuos (exercício mais recente) e a Liquidação por Competência em `data/raw` e monta as
    entradas do cálculo com a `fotografia` dada: (contratos ligados, faturas, empenhos do gov, relatório por mês).
    Falha de leitura levanta exceção."""

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
    return contratos_ligados(tabela, contratos_com_faturas(fotografia)), faturas, empenhos, relatorio


def gerar_relatorio_inconsistencias(fotografia: dict, referencia, a_partir_do_ano: int | None = None) -> bytes:
    """Excel de inconsistências (para o pessoal que alimenta o Contratos.gov) com a fotografia dada."""

    ligados, faturas, empenhos, relatorio = entradas_da_conciliacao(fotografia, referencia)
    decisoes = reconstruir_decisoes(carregar_eventos())  # confirmadas saem do relatório; rejeitadas ficam
    return excel_inconsistencias(tabela_inconsistencias(ligados, faturas, empenhos, relatorio, a_partir_do_ano, decisoes))


def atualizar_apos_gravacao(fotografia: dict, referencia, diretorio: Path | None = None) -> str:
    """Chamada logo depois de gravar uma fotografia nova do Contratos.gov: calcula as pendências de todos os contratos do
    cadastro de Contínuos com a fotografia NOVA, compara com a atualização anterior, grava a nova referência e devolve a
    mensagem para o usuário. Qualquer falha de leitura levanta exceção — o chamador mostra o aviso sem desfazer a
    gravação da fotografia."""

    ligados, faturas, empenhos, relatorio = entradas_da_conciliacao(fotografia, referencia)
    atual = calcular_pendencias(ligados, faturas, empenhos, relatorio, reconstruir_decisoes(carregar_eventos()))
    anterior = carregar_baseline(diretorio)
    novas, resolvidas = comparar(None if anterior is None else anterior["pendencias"], atual)
    salvar_baseline(
        atual, fotografia=str(fotografia.get("_sha256", ""))[:12], diretorio=diretorio, novas=novas, resolvidas=resolvidas
    )
    total = sum(len(pares) for pares in atual.values())
    if anterior is None:
        return f"Conciliação por competência: primeira referência registrada ({total} pendência(s) em {len(atual)} contrato(s))."
    return mensagem_delta(novas, resolvidas, total)
