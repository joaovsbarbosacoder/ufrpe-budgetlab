"""DDP do SIAPE × empenhos da folha (27/10/2026).

Lê os relatórios do SIAPE em PDF que o usuário envia na página Acompanhamento de Pessoal
— DDP (Demonstrativo de Despesa com Pessoal, GRCOFINDDP) e Crédito Bancário (GRCOCREBAN),
de servidor e de pensionista — e confronta a folha do mês com o saldo dos empenhos.
Tudo em memória: nenhum PDF nem resultado é gravado (AGENTS.md).

Correspondência validada com as DDPs DEFINITIVAS de set/2026 contra a Liquidada de
set/2026 da Execução Mensal (diferença total de R$ 6.971,93 em R$ 54,87 mi):

- a DDP do "MES/ANO SOLIC" X (paga no mês seguinte) é liquidada no próprio mês X;
- o código "3.3190.11.01" da DDP é a natureza detalhada SIAFI "31901101";
- valor da natureza = seção "DESPESAS CORRENTES ( 1 )" − seção "A ANULAR ( 2 )" (líquido: bate com a
  Liquidada em set/2026). **Em todo o sistema vale o BRUTO** (só a seção 1) — reforço, variação,
  confronto e painel —: as despesas a anular não reduzem o valor da folha (regra do usuário,
  28/10/2026). O líquido só aparece na conferência dos totais (bruto − descontos = líquido);
- conferência: BRUTO − DESCONTO = LÍQUIDO = total do Crédito Bancário; o DESCONTO é a
  seção (2) inteira (passivo + naturezas) mais o total de "CONSIGNACOES/DESCONTOS ( 3 )".

Reforço por empenho (regras desta versão, todas visíveis no quadro):

- empenhos da folha = notas cujo favorecido é a própria UG executora (exclui pagamentos
  diretos a operadoras, como a GEAP no per capita de saúde);
- saldo do item = Empenhado (deduplicado por bloco) − Liquidado de todo o exercício, por
  (NE, natureza detalhada). Se a folha do mês já estiver liquidada na base, o saldo já a
  desconta — `liquidado_no_mes` mostra quanto há; o reforço não tenta adivinhar;
- natureza da DDP com mais de um empenho da folha: repartida na proporção do Liquidado de
  cada um no mês anterior (a folha anterior); sem Liquidado no mês anterior, os empenhos
  viram uma linha só, com o saldo somado. A DDP de servidor não separa ativo × aposentado;
- natureza da DDP sem item em nenhum empenho: vai para o empenho da folha que já tem itens
  do mesmo elemento (natureza de despesa de 6 dígitos), se houver um só; senão fica em
  "sem empenho";
- reserva = o que o item ainda vai consumir depois do mês da DDP: projeção do painel da
  natureza (meses seguintes); se a natureza também tem empenhos fora da folha, a projeção
  os mistura e a reserva passa a ser DDP do mês × meses restantes;
- prática informada pelo usuário (não confirmada no SIAFI): o saldo é controlado por item
  da NE, e item com sobra é anulado para compor item sem saldo da mesma NE. Por isso a
  falta do mês é compensada só pela sobra livre (saldo − DDP − reserva) da mesma NE.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from src.despesas_pessoal import (
    ACAO_ASSISTENCIA_MEDICA, ACAO_ATIVO, ACAO_BENEFICIOS_OBRIGATORIOS, ACAO_INATIVO, ACAO_RPPS,
    GRUPO_ATIVO, GRUPO_INATIVO, GRUPO_OUTROS_BENEFICIOS, GRUPO_RPPS,
)
from src.tesouro_execucao_mensal import valor_empenhado_por_bloco

TIPO_DDP = "DDP"
TIPO_CREDITO = "CRED-BANC"
PUBLICO_SERVIDOR = "SERVIDOR"
PUBLICO_PENSIONISTA = "PENSIONISTA"
SECAO_DESPESA = "despesa"
SECAO_ANULAR = "anular"
SEM_EMPENHO = "(sem empenho)"

CRITERIO_UNICO = "único empenho"
CRITERIO_REPARTIDO = "repartido pelo liquidado do mês anterior"
CRITERIO_SOMADO = "empenhos somados"
CRITERIO_ELEMENTO = "sem item: empenho do mesmo elemento"
CRITERIO_SEM_EMPENHO = "sem empenho"

RESERVA_PROJECAO = "projeção do painel"
RESERVA_DDP = "DDP × meses restantes"

_MESES = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
          "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12}
_VALOR = r"(-?[\d.]+,\d{2})"
_NATUREZA = re.compile(r"^\s*(\d)\.(\d{4})\.(\d{2})\.(\d{2})\s+(.*?)\s+" + _VALOR + r"\s*$")
_AGREGADO = re.compile(r"^\s*(\d\.\d{4})\s+.*?\s+" + _VALOR + r"\s*$")
_CONSIGNACOES = re.compile(r"^\s*\*{6}\s+CONSIGNACOES/DESCONTOS\s+" + _VALOR + r"\s*$")
_TOTAL_DDP = re.compile(r"^\s*(99997|99998|99999)\s+\w+\s+" + _VALOR + r"\s*$")
_TOTAL_CREDITO = re.compile(r"^\s*TOTAIS DA UPAG\s+[\d.]+\s+" + _VALOR)
_MES_SOLIC = re.compile(r"MES/ANO SOLIC:\s*([A-Z]{3})(\d{4})")
_MES_PAGAMENTO = re.compile(r"MES PAGAMENTO\s*:\s*([A-Z]{3})(\d{4})")
_DATA = re.compile(r"DATA:\s*(\d{2})([A-Z]{3})(\d{4})")
_FOLHA = re.compile(r"\*\*\*\s*(?:DDP\s+)?(FOLHA\s+\w+)\s+-\s+NIVEL UNIDADE PAGADORA\s+-\s+(SERVIDOR|PENSIONISTA)\s*\*\*\*")
_RUBRICA = re.compile(r"^\s*(\d{5})\s+(.*?)\s+" + _VALOR + r"\s*$")
_TOTAIS_DDP = {"99997": "bruto", "99998": "desconto", "99999": "liquido"}


def _valor(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


def _ano_mes(mes: str, ano: str) -> int:
    if mes not in _MESES:
        raise ValueError(f"Mês não reconhecido no cabeçalho do SIAPE: {mes!r}.")
    return int(ano) * 100 + _MESES[mes]


# ---------------------------------------------------------------------------
# 1. Leitura dos PDFs
# ---------------------------------------------------------------------------

@dataclass
class RelatorioSiape:
    """Um PDF do SIAPE lido. `naturezas` só existe na DDP (colunas `secao`,
    `natureza_detalhada`, `descricao`, `valor`); `totais` traz o que o relatório declara:
    na DDP `bruto`, `desconto`, `liquido`, `despesas_correntes` (3.3000 da seção 1),
    `anular` (agregados de 1º nível da seção 2) e `consignacoes` (total da seção 3); no
    Crédito Bancário, `credito` (coluna do servidor/pensionista em "TOTAIS DA UPAG")."""

    nome: str
    tipo: str
    publico: str
    folha: str
    competencia: int
    mes_pagamento: int | None
    data_geracao: date | None
    totais: dict[str, float]
    naturezas: pd.DataFrame = field(default_factory=pd.DataFrame)
    #: rubricas da seção (3) CONSIGNACOES/DESCONTOS (colunas `codigo`, `descricao`, `valor`), só na DDP.
    rubricas: pd.DataFrame = field(default_factory=pd.DataFrame)


def _linhas_por_pagina(conteudo: bytes) -> list[list[str]]:
    import pymupdf  # importado aqui: só esta leitura depende dele

    with pymupdf.open(stream=conteudo, filetype="pdf") as documento:
        return [pagina.get_text().splitlines() for pagina in documento]


def ler_relatorio(conteudo: bytes, nome: str = "") -> RelatorioSiape:
    """Lê um PDF de DDP ou de Crédito Bancário do SIAPE. Levanta `ValueError` se o PDF não
    for um desses relatórios ou se faltar algum total — nada é completado com zero."""
    try:
        paginas = _linhas_por_pagina(conteudo)
    except Exception as erro:  # PDF corrompido ou não-PDF
        raise ValueError(f"{nome or 'Arquivo'}: não foi possível ler o PDF ({erro}).") from erro
    linhas = [linha for pagina in paginas for linha in pagina]
    cabecalho = "\n".join(linhas[:12])
    if "GRCOFINDDP" in cabecalho:
        tipo = TIPO_DDP
    elif "GRCOCREBAN" in cabecalho:
        tipo = TIPO_CREDITO
    else:
        raise ValueError(f"{nome or 'Arquivo'}: não é uma DDP nem um Crédito Bancário do SIAPE.")

    competencia = mes_pagamento = data_geracao = folha = publico = None
    for linha in linhas:
        if competencia is None and (m := _MES_SOLIC.search(linha)):
            competencia = _ano_mes(*m.groups())
        if mes_pagamento is None and (m := _MES_PAGAMENTO.search(linha)):
            mes_pagamento = _ano_mes(*m.groups())
        if data_geracao is None and (m := _DATA.search(linha)):
            dia, mes, ano = m.groups()
            data_geracao = date(int(ano), _MESES[mes], int(dia))
        if folha is None and (m := _FOLHA.search(linha)):
            folha, publico = m.group(1), m.group(2)
    if competencia is None or publico is None:
        raise ValueError(f"{nome or 'Arquivo'}: cabeçalho do SIAPE sem MES/ANO SOLIC ou sem o público da folha.")

    totais: dict[str, float] = {}
    naturezas = []
    rubricas = []
    if tipo == TIPO_CREDITO:
        for linha in linhas:
            if m := _TOTAL_CREDITO.match(linha):
                totais["credito"] = _valor(m.group(1))
        if "credito" not in totais:
            raise ValueError(f"{nome or 'Arquivo'}: Crédito Bancário sem a linha TOTAIS DA UPAG.")
    else:
        secao = None
        totais["anular"] = 0.0
        for linha in linhas:
            if "DESPESAS CORRENTES A ANULAR" in linha:
                secao = SECAO_ANULAR
                continue
            if "DESPESAS CORRENTES ( 1 )" in linha:
                secao = SECAO_DESPESA
                continue
            if "CONSIGNACOES/DESCONTOS ( 3 )" in linha:
                secao = "consignacoes"
                continue
            if "TOTAIS ( 5 )" in linha:
                secao = "totais"
                continue
            if secao in (SECAO_DESPESA, SECAO_ANULAR):
                if m := _NATUREZA.match(linha):
                    cat, gnd_mod, elem, sub, desc, valor = m.groups()
                    naturezas.append({"secao": secao, "natureza_detalhada": cat + gnd_mod[1:] + elem + sub,
                                      "descricao": desc.strip(), "valor": _valor(valor)})
                elif (m := _AGREGADO.match(linha)) and m.group(1).endswith("000"):
                    # agregados de 1º nível (3.3000, 2.1000): a seção (1) só tem 3.3000; a (2)
                    # tem também o passivo (reposição ao erário), que não é natureza.
                    chave = "despesas_correntes" if secao == SECAO_DESPESA else "anular"
                    totais[chave] = totais.get(chave, 0.0) + _valor(m.group(2))
            elif secao == "consignacoes" and (m := _CONSIGNACOES.match(linha)):
                totais["consignacoes"] = totais.get("consignacoes", 0.0) + _valor(m.group(1))
            elif secao == "consignacoes" and (m := _RUBRICA.match(linha)):
                rubricas.append({"codigo": m.group(1), "descricao": m.group(2).strip(), "valor": _valor(m.group(3))})
            elif secao == "totais" and (m := _TOTAL_DDP.match(linha)):
                totais[_TOTAIS_DDP[m.group(1)]] = _valor(m.group(2))
        faltando = [chave for chave in ("bruto", "desconto", "liquido") if chave not in totais]
        if faltando:
            raise ValueError(f"{nome or 'Arquivo'}: DDP sem os totais {', '.join(faltando)} (seção TOTAIS ( 5 )).")
        if not naturezas:
            raise ValueError(f"{nome or 'Arquivo'}: DDP sem nenhuma linha de natureza detalhada.")
    return RelatorioSiape(nome=nome, tipo=tipo, publico=publico, folha=folha, competencia=competencia,
                          mes_pagamento=mes_pagamento, data_geracao=data_geracao, totais=totais,
                          naturezas=pd.DataFrame(naturezas),
                          rubricas=pd.DataFrame(rubricas, columns=["codigo", "descricao", "valor"]))


def _competencia(ano_mes: int) -> str:
    return f"{ano_mes % 100:02d}/{ano_mes // 100}"


def validar_conjunto(relatorios: list[RelatorioSiape], competencias_com_ddp=()) -> list[str]:
    """Erros que impedem o confronto: mais de duas competências (a mais recente é a do
    reforço; a anterior, só comparação — 27/10/2026), relatório repetido para a mesma
    competência/tipo/público/folha, ou nenhuma DDP em alguma competência.
    `competencias_com_ddp`: competências que já têm DDP guardada — um envio só com Crédito
    Bancário delas não é erro."""
    erros = []
    competencias = sorted({r.competencia for r in relatorios})
    if len(competencias) > 2:
        erros.append("Envie no máximo duas competências (a do mês e a anterior, para comparar). Recebidas: "
                     + ", ".join(_competencia(c) for c in competencias) + ".")
    vistos: dict[tuple, str] = {}
    for r in relatorios:
        chave = (r.competencia, r.tipo, r.publico, r.folha)
        if chave in vistos:
            erros.append(f"{r.tipo} de {r.publico.lower()} ({r.folha.lower()}) de {_competencia(r.competencia)} "
                         f"enviado duas vezes: {vistos[chave]} e {r.nome}.")
        vistos[chave] = r.nome
    for c in competencias:
        if c not in competencias_com_ddp and not any(r.tipo == TIPO_DDP and r.competencia == c for r in relatorios):
            erros.append(f"Nenhuma DDP de {_competencia(c)} entre os PDFs enviados (só Crédito Bancário).")
    return erros


def separar_competencias(relatorios: list[RelatorioSiape]) -> tuple[list[RelatorioSiape], list[RelatorioSiape]]:
    """(atuais, anteriores): os relatórios da competência mais recente — base do reforço — e
    os da anterior, se enviada, usados só na comparação."""
    if not relatorios:
        return [], []
    atual = max(r.competencia for r in relatorios)
    return ([r for r in relatorios if r.competencia == atual], [r for r in relatorios if r.competencia != atual])


def variacao_por_natureza(atual: pd.DataFrame, anterior: pd.DataFrame) -> pd.DataFrame:
    """DDP bruta (seção 1, sem abater as despesas a anular) por natureza detalhada (servidor + pensionista) em duas competências, a
    partir de `ddp_por_natureza` de cada uma: `anterior`, `atual` (nulo quando a natureza não
    aparece naquela DDP — não é zero), `variacao` = atual − anterior (ausência conta como zero
    só aqui) e `situacao`: "nova", "saiu", "alta", "queda" ou "sem variação". Ordenada pelo
    tamanho da variação."""
    def por_natureza(tabela):
        soma = tabela.groupby("natureza_detalhada").agg(descricao=("descricao", "first"), valor=("despesa", "sum"))
        return soma.assign(valor=soma["valor"].round(2))  # servidor + pensionista, em centavos

    a, b = por_natureza(anterior), por_natureza(atual)
    tabela = pd.DataFrame({"anterior": a["valor"], "atual": b["valor"]})
    tabela["descricao"] = b["descricao"].combine_first(a["descricao"])
    tabela["variacao"] = (tabela["atual"].fillna(0.0) - tabela["anterior"].fillna(0.0)).round(2)
    tabela["situacao"] = [
        "nova" if pd.isna(ant) else "saiu" if pd.isna(atu) else "alta" if var > 0 else "queda" if var < 0 else "sem variação"
        for ant, atu, var in zip(tabela["anterior"], tabela["atual"], tabela["variacao"])
    ]
    tabela.index.name = "natureza_detalhada"
    tabela = tabela.reset_index()[["natureza_detalhada", "descricao", "anterior", "atual", "variacao", "situacao"]]
    tabela = tabela.assign(_tamanho=tabela["variacao"].abs())
    return (tabela.sort_values(["_tamanho", "natureza_detalhada"], ascending=[False, True])
            .drop(columns="_tamanho").reset_index(drop=True))


def conferencia(relatorios: list[RelatorioSiape]) -> pd.DataFrame:
    """Uma linha por (competência, público, folha) com os totais declarados e as
    conferências. Diferença nula quando falta o termo (ex.: Crédito Bancário não enviado) —
    nunca zero."""
    linhas = []
    chaves = sorted({(r.competencia, r.publico, r.folha) for r in relatorios if r.tipo == TIPO_DDP},
                    key=lambda c: (-c[0], c[1], c[2]))
    for competencia, publico, folha in chaves:
        mesmo = lambda r: (r.competencia, r.publico, r.folha) == (competencia, publico, folha)
        ddp = next(r for r in relatorios if r.tipo == TIPO_DDP and mesmo(r))
        credito = next((r for r in relatorios if r.tipo == TIPO_CREDITO and mesmo(r)), None)
        t = ddp.totais
        despesa = ddp.naturezas.loc[ddp.naturezas["secao"] == SECAO_DESPESA, "valor"].sum()
        desconto_calculado = t["anular"] + t["consignacoes"] if "consignacoes" in t else None
        linhas.append({
            "competencia": competencia, "publico": publico, "folha": folha,
            "bruto": t["bruto"], "desconto": t["desconto"], "liquido": t["liquido"],
            "dif_bruto_menos_desconto": round(t["bruto"] - t["desconto"] - t["liquido"], 2),
            "soma_naturezas_despesa": round(despesa, 2),
            "dif_naturezas_bruto": round(despesa - t["bruto"], 2),
            "desconto_calculado": None if desconto_calculado is None else round(desconto_calculado, 2),
            "dif_desconto": None if desconto_calculado is None else round(desconto_calculado - t["desconto"], 2),
            "credito_bancario": None if credito is None else credito.totais["credito"],
            "dif_credito": None if credito is None else round(credito.totais["credito"] - t["liquido"], 2),
        })
    return pd.DataFrame(linhas)


#: Patronal do RPPS (31911303) = (consignações de PSS) × 2, regra informada e confirmada pelo usuário em
#: 28/10/2026: "Consignações códigos: 98002, 98015, 98020, 98034, 98044, 98045 e 98046 = 2x". Servidor:
#: Ativo (98002, 98034, 98044, 98045) e Inativo (98015, "CONT P.SEGURIDADE SOCIAL AP"); pensionista:
#: 98020 e 98046 (DDP de pensionistas). Conferido com a Liquidada de mai–set/2026: a fórmula só dos
#: servidores (98015 incluída) fica entre +0,17% e +0,59% do liquidado; com os pensionistas, entre
#: +3,2% e +3,7% (o usuário confirmou que esta é a regra). Rubrica ausente na DDP não é zero: não
#: entra na soma e não é listada (98034 nunca apareceu nas DDPs de mai–out/2026).
RUBRICAS_PSS = {
    PUBLICO_SERVIDOR: {"98002": "Ativo", "98034": "Ativo", "98044": "Ativo", "98045": "Ativo", "98015": "Inativo"},
    PUBLICO_PENSIONISTA: {"98020": "Pensionista", "98046": "Pensionista"},
}
FATOR_PATRONAL_PSS = 2


def patronal_por_pss(relatorios: list[RelatorioSiape]) -> pd.DataFrame | None:
    """Rubricas de PSS da DDP (servidores e pensionistas) usadas no patronal (colunas `codigo`,
    `descricao`, `parte` — Ativo/Inativo/Pensionista —, `valor`), ou `None` se não há DDP de
    servidores com a 98002 (sem base para a regra: o patronal segue pela projeção). O patronal é
    `valor.sum() × FATOR_PATRONAL_PSS`."""
    partes = []
    for r in relatorios:
        if r.tipo != TIPO_DDP or not len(r.rubricas) or r.publico not in RUBRICAS_PSS:
            continue
        validas = r.rubricas.loc[r.rubricas["codigo"].isin(RUBRICAS_PSS[r.publico])]
        partes.append(validas.assign(parte=validas["codigo"].map(RUBRICAS_PSS[r.publico])))
    if not partes:
        return None
    rubricas = pd.concat(partes, ignore_index=True)
    servidor = {r.publico for r in relatorios if r.tipo == TIPO_DDP and r.publico == PUBLICO_SERVIDOR and len(r.rubricas)}
    if "98002" not in set(rubricas["codigo"]) or not servidor:
        return None
    tabela = rubricas.groupby("codigo", as_index=False).agg(descricao=("descricao", "first"), parte=("parte", "first"), valor=("valor", "sum"))
    tabela["valor"] = tabela["valor"].round(2)
    return tabela[["codigo", "descricao", "parte", "valor"]]


def ddp_por_natureza(relatorios: list[RelatorioSiape]) -> pd.DataFrame:
    """Uma linha por (natureza detalhada, público): `despesa` (seção 1), `anular`
    (seção 2) e `liquido` = despesa − anular, com a descrição da DDP."""
    partes = [r.naturezas.assign(publico=r.publico) for r in relatorios if r.tipo == TIPO_DDP]
    if not partes:
        return pd.DataFrame(columns=["natureza_detalhada", "publico", "descricao", "despesa", "anular", "liquido"])
    linhas = pd.concat(partes, ignore_index=True)
    tabela = linhas.pivot_table(index=["natureza_detalhada", "publico"], columns="secao", values="valor",
                                aggfunc="sum", fill_value=0.0)
    for secao in (SECAO_DESPESA, SECAO_ANULAR):
        if secao not in tabela:
            tabela[secao] = 0.0
    tabela = tabela.rename(columns={SECAO_DESPESA: "despesa", SECAO_ANULAR: "anular"})[["despesa", "anular"]]
    tabela["liquido"] = (tabela["despesa"] - tabela["anular"]).round(2)
    tabela["descricao"] = linhas.groupby(["natureza_detalhada", "publico"])["descricao"].first()
    tabela.columns.name = None
    return tabela.reset_index()[["natureza_detalhada", "publico", "descricao", "despesa", "anular", "liquido"]]


# ---------------------------------------------------------------------------
# 2. Empenhos da folha
# ---------------------------------------------------------------------------

def itens_de_empenho(mensal_df: pd.DataFrame, ano: int, ano_mes_ddp: int) -> pd.DataFrame:
    """Uma linha por (NE, natureza detalhada) do exercício: `empenhada` (deduplicada por
    bloco), `liquidada` (todo o exercício), `saldo`, `liquidado_mes_anterior` e
    `liquidado_no_mes` (mês da DDP), `folha` (favorecido = a própria UG executora),
    `natureza_despesa_cod` e `acao_cod`. Nulo de Liquidado é tratado como sem movimento."""
    base = mensal_df.loc[mensal_df["ano"] == ano]
    colunas = ["ne_ccor", "natureza_detalhada_cod"]
    blocos = valor_empenhado_por_bloco(base)
    empenhada = blocos.groupby(colunas)["empenhada"].sum(min_count=1)
    itens = base.loc[base["tipo_linha"] == "item_execucao"]
    liquidada = itens.groupby(colunas)["liquidada"].sum(min_count=1)
    mes_anterior = ano_mes_ddp - 1 if ano_mes_ddp % 100 > 1 else None
    anterior = itens.loc[itens["ano_mes"] == mes_anterior].groupby(colunas)["liquidada"].sum(min_count=1)
    no_mes = itens.loc[itens["ano_mes"] == ano_mes_ddp].groupby(colunas)["liquidada"].sum(min_count=1)
    resultado = pd.concat({"empenhada": empenhada, "liquidada": liquidada,
                           "liquidado_mes_anterior": anterior, "liquidado_no_mes": no_mes}, axis=1)
    resultado = resultado.fillna(0.0).reset_index()
    resultado["saldo"] = resultado["empenhada"] - resultado["liquidada"]

    atributos = base.loc[base["ne_ccor"].notna()].drop_duplicates("ne_ccor").set_index("ne_ccor")
    folha = atributos["ne_favorecido"].astype("string").str.strip() == atributos["ug_executora_desc"].astype("string").str.strip()
    resultado["folha"] = resultado["ne_ccor"].map(folha).fillna(False).astype(bool)
    resultado["acao_cod"] = resultado["ne_ccor"].map(atributos["acao_cod"])
    descricoes = base.dropna(subset=["natureza_detalhada_cod"]).drop_duplicates("natureza_detalhada_cod")
    resultado["natureza_detalhada_desc"] = resultado["natureza_detalhada_cod"].map(
        descricoes.set_index("natureza_detalhada_cod")["natureza_detalhada_desc"])
    resultado["natureza_despesa_cod"] = resultado["natureza_detalhada_cod"].astype("string").str[:6]
    return resultado


def reserva_projetada(grade_linhas: pd.DataFrame, mes_ddp: int) -> dict[str, float]:
    """Soma, por natureza detalhada, da projeção do painel (`grade_mensal(...).linhas`)
    nos meses DEPOIS do mês da DDP. Mês nulo na grade conta como sem consumo."""
    reserva: dict[str, float] = {}
    for linha in grade_linhas.itertuples(index=False):
        valores = [v for v in list(linha.meses)[mes_ddp:12] if v is not None and not pd.isna(v)]
        chave = str(linha.natureza_detalhada_cod)
        reserva[chave] = reserva.get(chave, 0.0) + float(sum(valores))
    return reserva


def _rotulo(nes) -> str:
    return " + ".join(sorted(str(n)[-8:] for n in nes))


# ---------------------------------------------------------------------------
# 3. Reforço por item e por empenho
# ---------------------------------------------------------------------------

def quadro_reforco(ddp_natureza: pd.DataFrame, mensal_df: pd.DataFrame, ano_mes_ddp: int,
                   reserva_por_natureza: dict[str, float], somente_folha: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(itens, por_empenho). `itens`: uma linha por (empenho, natureza detalhada) dos
    empenhos da folha que têm alguma natureza da DDP, com `empenhada`, `liquidada`, `saldo`,
    `ddp` (valor BRUTO do mês — seção 1 da DDP, sem abater as despesas a anular), `falta` = máx(0, ddp − saldo), `reserva`, `sobra_livre` =
    máx(0, saldo − ddp − reserva), `saldo_apos_ano` = saldo − ddp − reserva e os critérios
    usados. `por_empenho`: soma por empenho, `compensa` = mín(falta, sobra livre),
    `reforco_mes` = falta − compensa e `reforco_ate_dezembro` = máx(0, −saldo_apos_ano). Ver as
    regras no docstring do módulo. `somente_folha=False` (RPPS patronal, ver
    `quadro_sem_ddp`) considera qualquer empenho do exercício, e a reserva vem sempre da projeção."""
    ano, mes = divmod(ano_mes_ddp, 100)
    meses_restantes = 12 - mes
    itens = itens_de_empenho(mensal_df, ano, ano_mes_ddp)
    # valor BRUTO (seção 1, despesas correntes): as despesas a anular (seção 2) não reduzem a
    # necessidade de reforço do empenho — regra do usuário, 28/10/2026
    ddp = ddp_natureza.groupby("natureza_detalhada")["despesa"].sum()
    descricoes = ddp_natureza.groupby("natureza_detalhada")["descricao"].first()

    folha = itens.loc[itens["folha"]] if somente_folha else itens
    alvo = set(folha.loc[folha["natureza_detalhada_cod"].isin(ddp.index), "ne_ccor"])
    # natureza sem item: empenho da folha que já tem o mesmo elemento (único), senão "sem empenho"
    destino_sem_item: dict[str, str | None] = {}
    for natureza in ddp.index.difference(folha["natureza_detalhada_cod"]):
        candidatos = folha.loc[folha["natureza_despesa_cod"] == natureza[:6], "ne_ccor"].unique()
        destino_sem_item[natureza] = candidatos[0] if len(candidatos) == 1 else None
        if len(candidatos) == 1:
            alvo.add(candidatos[0])
    fora_da_folha = set(itens.loc[~itens["folha"], "natureza_detalhada_cod"]) if somente_folha else set()
    alvo_itens = folha.loc[folha["ne_ccor"].isin(alvo)]

    linhas = []
    for natureza, grupo in alvo_itens.groupby("natureza_detalhada_cod"):
        valor_ddp = float(ddp.get(natureza, 0.0))
        reserva_natureza = (valor_ddp * meses_restantes if natureza in fora_da_folha
                            else float(reserva_por_natureza.get(natureza, 0.0)))
        tipo_reserva = RESERVA_DDP if natureza in fora_da_folha else RESERVA_PROJECAO
        anterior = grupo["liquidado_mes_anterior"].clip(lower=0)
        positivo = grupo["saldo"].clip(lower=0)
        if len(grupo) == 1:
            partes = [(grupo, 1.0, CRITERIO_UNICO)]
        elif anterior.sum() > 0:
            partes = [(grupo.loc[[i]], float(anterior[i] / anterior.sum()), CRITERIO_REPARTIDO) for i in grupo.index]
        elif natureza not in ddp.index:
            # item fora da DDP em vários empenhos: cada um fica no seu (a sobra compensa a própria NE);
            # a reserva, se houver, é repartida pelo saldo positivo
            partes = [(grupo.loc[[i]], float(positivo[i] / positivo.sum()) if positivo.sum() > 0 else 1.0 / len(grupo),
                       CRITERIO_UNICO) for i in grupo.index]
        else:
            partes = [(grupo, 1.0, CRITERIO_SOMADO)]
        for parte, fracao, criterio in partes:
            linhas.append({
                "empenho": _rotulo(parte["ne_ccor"]), "nes": tuple(sorted(parte["ne_ccor"])),
                "natureza_detalhada": natureza, "acao_cod": parte["acao_cod"].iloc[0],
                # descrição da DDP; item fora da DDP usa a da base
                "descricao": descricoes.get(natureza, parte["natureza_detalhada_desc"].iloc[0]),
                "empenhada": float(parte["empenhada"].sum()), "liquidada": float(parte["liquidada"].sum()),
                "saldo": float(parte["saldo"].sum()),
                "ddp": valor_ddp * fracao, "reserva": reserva_natureza * fracao, "fracao": fracao,
                "criterio": criterio if natureza in ddp.index else "fora da DDP", "tipo_reserva": tipo_reserva,
                "liquidado_no_mes": float(parte["liquidado_no_mes"].sum()),
            })
    for natureza, destino in destino_sem_item.items():
        valor_ddp = float(ddp[natureza])
        linhas.append({
            "empenho": _rotulo([destino]) if destino else SEM_EMPENHO, "nes": (destino,) if destino else (),
            "natureza_detalhada": natureza, "acao_cod": None, "descricao": descricoes.get(natureza),
            "empenhada": 0.0, "liquidada": 0.0, "saldo": 0.0, "ddp": valor_ddp,
            "reserva": valor_ddp * meses_restantes if natureza in fora_da_folha else float(reserva_por_natureza.get(natureza, 0.0)),
            "fracao": 1.0, "criterio": CRITERIO_ELEMENTO if destino else CRITERIO_SEM_EMPENHO,
            "tipo_reserva": RESERVA_DDP if natureza in fora_da_folha else RESERVA_PROJECAO, "liquidado_no_mes": 0.0,
        })

    colunas = ["empenho", "nes", "natureza_detalhada", "acao_cod", "descricao", "empenhada", "liquidada", "saldo",
               "ddp", "falta", "reserva",
               "sobra_livre", "saldo_apos_ano", "fracao", "criterio", "tipo_reserva", "liquidado_no_mes"]
    tabela = pd.DataFrame(linhas, columns=[c for c in colunas if c not in ("falta", "sobra_livre", "saldo_apos_ano")])
    tabela["falta"] = (tabela["ddp"] - tabela["saldo"]).clip(lower=0)
    tabela["sobra_livre"] = (tabela["saldo"] - tabela["ddp"] - tabela["reserva"]).clip(lower=0)
    tabela["saldo_apos_ano"] = tabela["saldo"] - tabela["ddp"] - tabela["reserva"]
    # item fora da DDP, sem saldo, sem reserva: não tem o que mostrar
    vazio = (tabela["ddp"] == 0) & (tabela["saldo"].abs() < 0.005) & (tabela["reserva"] == 0)
    tabela = tabela.loc[~vazio, colunas].sort_values(["empenho", "natureza_detalhada"]).reset_index(drop=True)

    por_empenho = tabela.groupby("empenho").agg(
        acao_cod=("acao_cod", "first"), saldo=("saldo", "sum"), ddp=("ddp", "sum"), falta=("falta", "sum"),
        sobra_livre=("sobra_livre", "sum"), reserva=("reserva", "sum"), saldo_apos_ano=("saldo_apos_ano", "sum"),
        liquidado_no_mes=("liquidado_no_mes", "sum"),
    )
    por_empenho["compensa"] = por_empenho[["falta", "sobra_livre"]].min(axis=1)
    por_empenho["reforco_mes"] = por_empenho["falta"] - por_empenho["compensa"]
    por_empenho["reforco_ate_dezembro"] = (-por_empenho["saldo_apos_ano"]).clip(lower=0)
    por_empenho = por_empenho.sort_values(["reforco_mes", "reforco_ate_dezembro"], ascending=False).reset_index()
    return tabela, por_empenho


def quadro_sem_ddp(mensal_df: pd.DataFrame, ano_mes: int, grade_linhas: pd.DataFrame,
                   grupo: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reforço de um grupo que não está na DDP — a contribuição patronal ao RPPS (27/10/2026)
    —, pelo mesmo `quadro_reforco`, mas com o valor do mês tirado da projeção do painel
    (`grade_mensal(...).linhas` do `grupo`) no lugar da DDP. Considera qualquer empenho do
    exercício com a natureza (o do RPPS não tem a UG como favorecida) e a reserva é a projeção
    dos meses seguintes (com o 13º de novembro). Mês nulo na grade conta como zero. Não há
    documento do SIAPE para conferir o valor do mês."""
    mes = ano_mes % 100
    linhas = grade_linhas.loc[grade_linhas["grupo"] == grupo]
    previsto = pd.DataFrame([{
        "natureza_detalhada": str(l.natureza_detalhada_cod), "publico": "projeção", "descricao": l.natureza_detalhada_desc,
        "despesa": float(l.meses[mes - 1]) if l.meses[mes - 1] is not None and not pd.isna(l.meses[mes - 1]) else 0.0,
    } for l in linhas.itertuples(index=False)], columns=["natureza_detalhada", "publico", "descricao", "despesa"])
    return quadro_reforco(previsto, mensal_df, ano_mes, reserva_projetada(linhas, mes), somente_folha=False)


def conciliacao_sem_ddp(itens: pd.DataFrame, grade_linhas: pd.DataFrame, grupo: str, ano_mes: int,
                        dotacao: float | None) -> dict[str, float | None]:
    """Fecha o reforço até dezembro do grupo com o painel: reforço = déficit de dotação
    (total do ano projetado − dotação) + dotação ainda não empenhada (dotação − empenhado) +
    `diferenca_meses_anteriores` (Liquidado já lançado na base − executado/projetado da grade
    nos meses antes do mês do quadro; zero quando a base e a grade coincidem). Sem dotação,
    os termos que dependem dela ficam nulos."""
    mes = ano_mes % 100
    linhas = grade_linhas.loc[grade_linhas["grupo"] == grupo]
    soma = lambda valores: sum(float(v) for v in valores if v is not None and not pd.isna(v))
    total_ano = soma(v for l in linhas.itertuples(index=False) for v in l.meses)
    meses_anteriores = soma(v for l in linhas.itertuples(index=False) for v in list(l.meses)[:mes - 1])
    empenhado, liquidado = float(itens["empenhada"].sum()), float(itens["liquidada"].sum())
    reforco = max(0.0, -float(itens["saldo_apos_ano"].sum()))
    sem_dotacao = dotacao is None or pd.isna(dotacao)
    return {
        "total_ano": total_ano, "empenhado": empenhado, "liquidado": liquidado, "reforco_ate_dezembro": reforco,
        "dotacao": None if sem_dotacao else float(dotacao),
        "deficit_dotacao": None if sem_dotacao else total_ano - float(dotacao),
        "dotacao_nao_empenhada": None if sem_dotacao else float(dotacao) - empenhado,
        "diferenca_meses_anteriores": liquidado - meses_anteriores,
    }


SEM_ACAO = "(sem ação única)"


def acoes_dos_quadros(quadros: list[tuple[pd.DataFrame, pd.DataFrame]], mensal_df: pd.DataFrame, ano: int) -> set[str]:
    """Ações dos empenhos que aparecem nos quadros — para buscar só a dotação necessária."""
    base = mensal_df.loc[mensal_df["ano"] == ano]
    nes = {ne for itens, _ in quadros for tupla in itens["nes"] for ne in tupla}
    return set(base.loc[base["ne_ccor"].isin(nes), "acao_cod"].dropna().astype(str))


def _acao_po_dos_empenhos(itens: pd.DataFrame, blocos: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """(Ação, PO) de cada empenho do quadro, pela NE; NEs com Ação/PO diferentes ou sem NE → `SEM_ACAO`."""
    ne_acao_po = blocos.groupby("ne_ccor")[["acao_cod", "po_cod"]].first()
    resultado = {}
    for empenho, nes in itens.groupby("empenho")["nes"].first().items():
        combinacoes = {tuple(ne_acao_po.loc[ne]) for ne in nes if ne in ne_acao_po.index}
        acao, po = next(iter(combinacoes)) if len(combinacoes) == 1 else (SEM_ACAO, "")
        resultado[empenho] = (str(acao), str(po))
    return resultado


def reforco_por_acao_po(quadros: list[tuple[pd.DataFrame, pd.DataFrame]], mensal_df: pd.DataFrame, ano: int,
                        dotacao_por_acao_po: pd.Series) -> pd.DataFrame:
    """O reforço cabe na dotação? (27/10/2026). `quadros`: os pares (itens, por_empenho) de
    `quadro_reforco` (DDP) e `quadro_sem_ddp` (RPPS). Cada empenho vai para a (Ação, PO) da
    sua NE; empenho agrupado com NEs de Ação/PO diferentes, ou sem empenho, vai para
    `SEM_ACAO`. Por (Ação, PO): `dotacao` (Atualizada), `empenhado` (todos os empenhos do
    exercício na Ação/PO, deduplicado por bloco), `disponivel` = dotação − empenhado,
    `reforco_mes`, `reforco_ate_dezembro`, `sobra_empenhos` (o que sobraria em dezembro nos
    empenhos do quadro, anulável) e `saldo_apos_reforco` = disponível − reforço até dezembro
    (negativo = o reforço não cabe). Dotação ausente fica nula, não zero. Só os empenhos dos
    quadros: outras despesas da mesma ação que ainda precisem de empenho não entram."""
    base = mensal_df.loc[mensal_df["ano"] == ano]
    blocos = valor_empenhado_por_bloco(base)
    empenhado = blocos.groupby(["acao_cod", "po_cod"])["empenhada"].sum(min_count=1)

    linhas = []
    for itens, por_empenho in quadros:
        acao_po = _acao_po_dos_empenhos(itens, blocos)
        for r in por_empenho.itertuples(index=False):
            acao, po = acao_po[r.empenho]
            linhas.append({"acao_cod": str(acao), "po_cod": str(po), "empenho": r.empenho, "reforco_mes": r.reforco_mes,
                           "reforco_ate_dezembro": r.reforco_ate_dezembro,
                           "sobra_empenhos": max(0.0, float(r.saldo_apos_ano))})
    colunas = ["acao_cod", "po_cod", "dotacao", "empenhado", "disponivel", "reforco_mes", "reforco_ate_dezembro",
               "sobra_empenhos", "saldo_apos_reforco", "empenhos"]
    if not linhas:
        return pd.DataFrame(columns=colunas)
    tabela = pd.DataFrame(linhas)
    com_reforco = tabela.loc[tabela["reforco_ate_dezembro"] > 0.004]
    resumo = tabela.groupby(["acao_cod", "po_cod"]).agg(
        reforco_mes=("reforco_mes", "sum"), reforco_ate_dezembro=("reforco_ate_dezembro", "sum"),
        sobra_empenhos=("sobra_empenhos", "sum"),
    )
    resumo["empenhos"] = com_reforco.groupby(["acao_cod", "po_cod"])["empenho"].agg(lambda e: ", ".join(sorted(e)))
    resumo["empenhos"] = resumo["empenhos"].fillna("")
    chave = lambda serie: {(str(a), str(p)): v for (a, p), v in serie.items()}
    dotacao, emp = chave(dotacao_por_acao_po), chave(empenhado)
    resumo["dotacao"] = [dotacao.get(k) if k[0] != SEM_ACAO else None for k in resumo.index]
    resumo["empenhado"] = [emp.get(k) if k[0] != SEM_ACAO else None for k in resumo.index]
    resumo["dotacao"] = pd.to_numeric(resumo["dotacao"], errors="coerce")
    resumo["empenhado"] = pd.to_numeric(resumo["empenhado"], errors="coerce")
    resumo["disponivel"] = resumo["dotacao"] - resumo["empenhado"].fillna(0.0)
    resumo["saldo_apos_reforco"] = resumo["disponivel"] - resumo["reforco_ate_dezembro"]
    return resumo.reset_index()[colunas].sort_values(["saldo_apos_reforco", "acao_cod", "po_cod"], na_position="first").reset_index(drop=True)


_ACAO_DO_GRUPO = {GRUPO_ATIVO: ACAO_ATIVO, GRUPO_INATIVO: ACAO_INATIVO, GRUPO_RPPS: ACAO_RPPS}
_GRUPO_DA_ACAO = {ACAO_ATIVO: GRUPO_ATIVO, ACAO_INATIVO: GRUPO_INATIVO, ACAO_RPPS: GRUPO_RPPS,
                  ACAO_ASSISTENCIA_MEDICA: GRUPO_OUTROS_BENEFICIOS, ACAO_BENEFICIOS_OBRIGATORIOS: GRUPO_OUTROS_BENEFICIOS}


def _acao_da_linha_da_grade(grupo: str, natureza: str, acao_por_natureza: dict[str, str | None]) -> str | None:
    if grupo == GRUPO_OUTROS_BENEFICIOS:
        return acao_por_natureza.get(natureza)  # 2004 ou 212B, pela execução do exercício
    return _ACAO_DO_GRUPO.get(grupo)


def conciliacao_por_acao(quadros: list[tuple[pd.DataFrame, pd.DataFrame]], mensal_df: pd.DataFrame, ano_mes: int,
                         grade_linhas: pd.DataFrame, dotacao_por_acao_po: pd.Series) -> pd.DataFrame:
    """Ponte entre o saldo do quadro por ação (`reforco_por_acao_po`, somado por ação) e o
    saldo do painel (dotação − total do ano projetado), para as ações do escopo de pessoal
    (27/10/2026). Identidade exata, parcela a parcela:

    saldo no quadro = saldo do painel
        + `projecao_fora`: projeção do painel do mês do quadro em diante − (DDP/projeção do mês
          + reserva) atribuídas aos empenhos do quadro (naturezas sem empenho de folha,
          pagamentos diretos, diferença entre a DDP e a projeção do mês);
        + `executado_fora`: executado do painel antes do mês − Liquidado nos empenhos do quadro
          (o que foi liquidado em outras notas da ação);
        − `empenhado_fora`: empenhado em notas da ação que não estão nos quadros;
        − `sobras`: o que sobraria em dezembro nos empenhos do quadro com folga (não anulado);
        + `diferenca` (resíduo; zero salvo arredondamento).

    Outros Benefícios é aberto por ação (2004/212B) pela ação em que cada natureza é executada
    no exercício; natureza em mais de uma ação fica fora (contada em `naturezas_sem_acao`).
    A projeção é a padrão (sem as edições manuais do painel). Dotação nula deixa os saldos nulos."""
    ano, mes = divmod(ano_mes, 100)
    base = mensal_df.loc[mensal_df["ano"] == ano]
    blocos = valor_empenhado_por_bloco(base)
    acoes_escopo = sorted(_GRUPO_DA_ACAO)
    beneficios = base.loc[base["acao_cod"].isin([ACAO_ASSISTENCIA_MEDICA, ACAO_BENEFICIOS_OBRIGATORIOS])]
    unicas = beneficios.groupby("natureza_detalhada_cod")["acao_cod"].agg(lambda a: set(a.dropna().astype(str)))
    acao_por_natureza = {str(n): next(iter(a)) if len(a) == 1 else None for n, a in unicas.items()}

    soma = lambda valores: sum(float(v) for v in valores if v is not None and not pd.isna(v))
    projecao = {a: {"anterior": 0.0, "futuro": 0.0} for a in acoes_escopo}
    sem_acao = 0
    for l in grade_linhas.itertuples(index=False):
        acao = _acao_da_linha_da_grade(l.grupo, str(l.natureza_detalhada_cod), acao_por_natureza)
        if acao not in projecao:
            sem_acao += 1
            continue
        projecao[acao]["anterior"] += soma(list(l.meses)[:mes - 1])
        projecao[acao]["futuro"] += soma(list(l.meses)[mes - 1:])

    quadro = {a: dict(empenhada=0.0, liquidada=0.0, ddp=0.0, reserva=0.0, sobras=0.0, reforco=0.0) for a in acoes_escopo}
    for itens, por_empenho in quadros:
        acao_po = _acao_po_dos_empenhos(itens, blocos)
        for empenho, grupo in itens.groupby("empenho"):
            acao = acao_po[empenho][0]
            if acao not in quadro:
                continue
            q = quadro[acao]
            for coluna in ("empenhada", "liquidada", "ddp", "reserva"):
                q[coluna] += float(grupo[coluna].sum())
            saldo_apos = float(grupo["saldo_apos_ano"].sum())
            q["sobras"] += max(0.0, saldo_apos)
            q["reforco"] += max(0.0, -saldo_apos)

    dotacao = {}
    for (acao, _po), valor in dotacao_por_acao_po.items():
        if valor is not None and not pd.isna(valor):
            dotacao[str(acao)] = dotacao.get(str(acao), 0.0) + float(valor)
    empenhado = blocos.groupby("acao_cod")["empenhada"].sum(min_count=1)

    linhas = []
    for acao in acoes_escopo:
        t_ant, t_fut, q = projecao[acao]["anterior"], projecao[acao]["futuro"], quadro[acao]
        emp_total = float(empenhado.get(acao, 0.0) or 0.0)
        dot = dotacao.get(acao)
        saldo_painel = None if dot is None else dot - (t_ant + t_fut)
        saldo_quadro = None if dot is None else dot - emp_total - q["reforco"]
        parcelas = {
            "projecao_fora": t_fut - q["ddp"] - q["reserva"],
            "executado_fora": t_ant - q["liquidada"],
            "empenhado_fora": emp_total - q["empenhada"],
            "sobras": q["sobras"],
        }
        explicado = parcelas["projecao_fora"] + parcelas["executado_fora"] - parcelas["empenhado_fora"] - parcelas["sobras"]
        linhas.append({
            "acao_cod": acao, "grupo": _GRUPO_DA_ACAO[acao], "dotacao": dot, "total_painel": t_ant + t_fut,
            "saldo_painel": saldo_painel, "reforco_quadro": q["reforco"], "saldo_quadro": saldo_quadro, **parcelas,
            "diferenca": None if dot is None else round(saldo_quadro - saldo_painel - explicado, 2),
        })
    tabela = pd.DataFrame(linhas)
    tabela.attrs["naturezas_sem_acao"] = sem_acao
    return tabela


OPERACAO_REMANEJAR = "anular e reforçar no mesmo empenho"
OPERACAO_REFORCO = "reforço novo"


def plano_operacoes(itens: pd.DataFrame) -> pd.DataFrame:
    """Operações por item que cobrem a falta do mês, a partir de `quadro_reforco(...)[0]`.
    Em cada empenho, os itens com falta (maior primeiro) recebem a sobra livre dos outros
    itens (maior sobra primeiro); o que a sobra não cobre vira reforço novo. Uma linha por
    operação: `empenho`, `operacao`, `item_origem` (nulo no reforço novo), `item_destino`
    e `valor`. Contas em centavos: a soma das anulações de um empenho é a sua compensação,
    e nenhum item cede mais que a sobra livre — fica sempre com a reserva dos meses seguintes."""
    linhas = []
    for empenho, grupo in itens.groupby("empenho", sort=True):
        faltas = [(n, round(f * 100)) for n, f in zip(grupo["natureza_detalhada"], grupo["falta"]) if round(f * 100) > 0]
        # sobra arredondada para baixo: o item nunca cede meio centavo além da sobra livre
        sobras = [[n, math.floor(s * 100 + 1e-6)] for n, s in zip(grupo["natureza_detalhada"], grupo["sobra_livre"])
                  if math.floor(s * 100 + 1e-6) > 0]
        faltas.sort(key=lambda par: (-par[1], par[0]))
        sobras.sort(key=lambda par: (-par[1], par[0]))
        for destino, falta in faltas:
            for origem in sobras:
                if falta == 0:
                    break
                parcela = min(falta, origem[1])
                if parcela:
                    linhas.append({"empenho": empenho, "operacao": OPERACAO_REMANEJAR, "item_origem": origem[0],
                                   "item_destino": destino, "valor": parcela / 100})
                    origem[1] -= parcela
                    falta -= parcela
            if falta:
                linhas.append({"empenho": empenho, "operacao": OPERACAO_REFORCO, "item_origem": None,
                               "item_destino": destino, "valor": falta / 100})
    return pd.DataFrame(linhas, columns=["empenho", "operacao", "item_origem", "item_destino", "valor"])


def somente_reforco(itens: pd.DataFrame) -> pd.DataFrame:
    """Cenário sem anulação agora (27/10/2026: a anulação será feita, mas talvez não no momento):
    cada item com falta recebe reforço do valor inteiro, sem usar a sobra de outro item. Uma linha
    por item com falta no mês ou até dezembro: `reforco_mes` = falta do item e
    `reforco_ate_dezembro` = máx(0, −saldo depois de dezembro) do próprio item."""
    tabela = itens.assign(reforco_mes=itens["falta"], reforco_ate_dezembro=(-itens["saldo_apos_ano"]).clip(lower=0))
    tabela = tabela.loc[(tabela["reforco_mes"] > 0.004) | (tabela["reforco_ate_dezembro"] > 0.004)]
    return tabela[["empenho", "nes", "natureza_detalhada", "descricao", "acao_cod", "saldo", "ddp", "reserva",
                   "reforco_mes", "reforco_ate_dezembro"]].reset_index(drop=True)


def por_empenho_somente_reforco(itens: pd.DataFrame) -> pd.DataFrame:
    """`somente_reforco` somado por empenho, no formato de `quadro_reforco(...)[1]` (para
    `reforco_por_acao_po`): `saldo_apos_ano` passa a ser só a sobra que ficaria parada em
    dezembro nos itens com folga — sem anulação ela continua empenhada."""
    base = itens.assign(reforco_mes=itens["falta"], reforco_ate_dezembro=(-itens["saldo_apos_ano"]).clip(lower=0),
                        sobra_parada=itens["saldo_apos_ano"].clip(lower=0))
    tabela = base.groupby("empenho").agg(acao_cod=("acao_cod", "first"), saldo=("saldo", "sum"), ddp=("ddp", "sum"),
                                         reforco_mes=("reforco_mes", "sum"), reforco_ate_dezembro=("reforco_ate_dezembro", "sum"),
                                         sobra_parada=("sobra_parada", "sum"))
    tabela["saldo_apos_ano"] = tabela["sobra_parada"]
    return tabela.sort_values(["reforco_mes", "reforco_ate_dezembro"], ascending=False).reset_index()


def sugestoes_anulacao(itens: pd.DataFrame, plano: pd.DataFrame) -> pd.DataFrame:
    """Itens que podem ser anulados sem faltar nos meses seguintes: `pode_anular` = sobra livre
    (saldo − folha do mês − reserva de nov/dez); `usado_no_plano` = quanto o plano de anulação +
    reforço tira do item para cobrir faltas da mesma NE; `restante` = o que ainda sobraria."""
    usado = (plano.loc[plano["operacao"] == OPERACAO_REMANEJAR].groupby(["empenho", "item_origem"])["valor"].sum()
             if len(plano) else pd.Series(dtype=float))
    tabela = itens.loc[itens["sobra_livre"] > 0.004, ["empenho", "nes", "natureza_detalhada", "descricao", "acao_cod",
                                                      "saldo", "ddp", "reserva", "sobra_livre"]].copy()
    tabela["usado_no_plano"] = [float(usado.get((e, n), 0.0)) for e, n in zip(tabela["empenho"], tabela["natureza_detalhada"])]
    tabela["restante"] = tabela["sobra_livre"] - tabela["usado_no_plano"]
    return tabela.rename(columns={"sobra_livre": "pode_anular"}).sort_values("pode_anular", ascending=False).reset_index(drop=True)


def confronto_liquidado(ddp_natureza: pd.DataFrame, mensal_df: pd.DataFrame, ano_mes: int) -> pd.DataFrame:
    """DDP bruta × Liquidada da base no mês da DDP, por natureza detalhada, só nos
    empenhos da folha. Com a folha já liquidada, as diferenças são o que a liquidação não
    reproduziu (ex.: reposição ao erário nas pensões, cota-parte na creche); antes dela,
    a coluna da base mostra só o que já entrou no mês."""
    ano = ano_mes // 100
    itens = itens_de_empenho(mensal_df, ano, ano_mes)
    liquidado = itens.loc[itens["folha"]].groupby("natureza_detalhada_cod")["liquidado_no_mes"].sum()
    ddp = ddp_natureza.groupby("natureza_detalhada").agg(descricao=("descricao", "first"), ddp=("despesa", "sum"))
    # só as naturezas da DDP: os empenhos com a UG como favorecida incluem também diárias, bolsas etc.
    tabela = ddp.join(liquidado.rename("liquidado_no_mes"), how="left").fillna({"liquidado_no_mes": 0.0})
    tabela.index.name = "natureza_detalhada"
    tabela = tabela.reset_index()
    tabela["diferenca"] = tabela["liquidado_no_mes"] - tabela["ddp"]
    return tabela.sort_values("natureza_detalhada").reset_index(drop=True)
