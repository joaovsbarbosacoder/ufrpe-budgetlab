"""Relatório de liquidação mensal das NEs marcadas na Consulta de Empenhos (PDF e Excel).

Camada: regra de relatório — recebe da página `app_pages/consulta_empenhos.py` as NEs marcadas
(caixinhas da lista) e as duas séries de Liquidado já agregadas por (NE, mês):

  * por COMPETÊNCIA (mês de referência — `src.liquidacao_competencia.liquidado_por_ne_e_mes`);
  * por DATA DE LIQUIDAÇÃO (mês de lançamento — `src.tesouro_execucao_mensal.liquidado_por_ne_e_mes`).

Não lê planilha: só escolhe a base de cada NE, monta as tabelas e formata.

PEDIDO (30/09/2026): "algo parecido com o relatório de execução retardada", só com a
liquidação, evidenciando por competência todas as NEs selecionadas; quando não for possível,
mostrar pelo período em que foi liquidado, com aviso. Objetivo declarado: observar o
comportamento das despesas ao longo do ano e comparar exercícios — por isso a tabela principal
tem uma linha por (NE, ano do mês) e colunas Jan…Dez, deixando os anos de uma mesma NE (ou de
NEs de exercícios diferentes) um embaixo do outro.

REGRA DA BASE, POR NE (não por mês — nunca mistura as duas bases na série de uma mesma NE):
  1. NE com ao menos uma linha na base de competência -> série por competência
     (`BASE_COMPETENCIA`).
  2. Caso contrário -> série da Execução Mensal por mês de lançamento (`BASE_LANCAMENTO`), com
     aviso no relatório listando essas NEs. Também é o caso de TODAS as NEs quando a base de
     competência não está disponível (`competencia=None`) — aviso geral.
  3. Sem liquidação em nenhuma das duas -> `BASE_SEM_DADO`: uma linha sem valores (nulo, não
     zero) — a NE não é descartada do relatório.

Reconciliação ("Resumo por NE"): total da série escolhida × total liquidado da NE na Execução
Mensal (NE inteira, independente dos filtros de linha da página — a base de competência não tem
classificação orçamentária, então as duas comparações só fazem sentido no nível da NE). A
diferença evidencia competência parcial/defasada; é nula quando falta um dos dois lados. NEs
por competência com diferença também entram nos avisos — na extração de referência há NE com
R$ 13 mil por competência contra R$ 102 mi liquidados; sem o aviso a série subnotificaria em
silêncio.

Valores: mês sem linha fica vazio (nulo), distinto de zero; estornos entram com o sinal; meses
de referência fora do exercício da NE (restos a pagar, competência atrasada ou até anos
"estranhos" vindos da origem) aparecem como vieram, na linha do ano correspondente.

PDF x EXCEL (pedido explícito posterior, 30/09/2026): o PDF não traz o "Resumo por NE" — em
seu lugar vai a "Consolidação Orçamentária do Grupo" da tela (Elemento de Despesa, Grupo de
Despesa, Ação de Governo, UGR), calculada por `consolidar_por_dimensao` (a mesma função que a
página usa, para tela e PDF nunca divergirem). Os valores dessa consolidação são da Execução
Mensal (Liquidado por data de liquidação, sobre o recorte de linhas dos filtros), e o PDF diz
isso no título do quadro. O Excel continua com o "Resumo por NE" (reconciliação) e ganhou a
mesma consolidação na aba "Consolidação" (formato longo, coluna "Dimensão").

ORDEM (pedido explícito posterior): NEs em ordem alfabética da descrição (depois favorecido,
depois NE; sem acento/caixa; descrição nula por último) no PDF e nas abas "Liquidação mensal" e
"Resumo por NE" do Excel — agrupa a mesma despesa de exercícios diferentes.

Contrato público:
    BASE_COMPETENCIA, BASE_LANCAMENTO, BASE_SEM_DADO
    ContextoRelatorioLiquidacao (dataclass)
    RelatorioLiquidacao (dataclass: resumo, mensal, serie)
    montar_relatorio(nes, lancamento, competencia) -> RelatorioLiquidacao
    consolidar_por_dimensao(grupo, coluna_cod, coluna_desc) -> pd.DataFrame
    gerar_pdf(relatorio, contexto, consolidacao=()) -> bytes
    gerar_xlsx(relatorio, contexto, consolidacao=()) -> bytes
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import unicodedata
from io import BytesIO
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.execucao_ne_utils import ne_curta

TITULO = "LIQUIDAÇÃO MENSAL POR EMPENHO"

BASE_COMPETENCIA = "Competência"
BASE_LANCAMENTO = "Data de liquidação"
BASE_SEM_DADO = "Sem dado"

NOTA_BASES = (
    "Competência = mês de referência da despesa (base Liquidação por Competência, Tesouro "
    "Gerencial). Data de liquidação = mês em que a liquidação foi lançada (Execução Mensal, BI "
    "CPOC). Cada NE usa uma única base; a coluna Base indica qual."
)

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


@dataclass(frozen=True)
class ContextoRelatorioLiquidacao:
    """Procedência impressa no cabeçalho do PDF e na aba "Parâmetros" do Excel."""

    data_extracao: str
    hash_manifesto: str
    data_emissao: str
    #: descrição da base de competência usada (arquivo + data de modificação), ou `None`
    #: quando ela não estava disponível.
    origem_competencia: str | None


@dataclass(frozen=True)
class RelatorioLiquidacao:
    #: uma linha por NE: ne_ccor, ano, ne_favorecido, ne_descricao, base, total_base,
    #: liquidado_execucao_mensal, diferenca.
    resumo: pd.DataFrame
    #: uma linha por (NE, ano do mês): ne_ccor, ano_ne, ne_favorecido, ne_descricao, base, ano,
    #: 1..12, total.
    mensal: pd.DataFrame
    #: formato longo: ne_ccor, base, ano_mes, valor.
    serie: pd.DataFrame

    @property
    def nes_por_lancamento(self) -> list[str]:
        return self.resumo.loc[self.resumo["base"] == BASE_LANCAMENTO, "ne_ccor"].tolist()

    @property
    def nes_competencia_divergente(self) -> list[str]:
        """NEs por competência cujo total difere do liquidado da Execução Mensal (mais de meio
        centavo) — competência parcial ou defasada; o leitor precisa saber que a série não
        cobre todo o liquidado da NE."""

        divergente = (self.resumo["base"] == BASE_COMPETENCIA) & (self.resumo["diferenca"].abs() > 0.005)
        return self.resumo.loc[divergente, "ne_ccor"].tolist()

    @property
    def nes_sem_dado(self) -> list[str]:
        return self.resumo.loc[self.resumo["base"] == BASE_SEM_DADO, "ne_ccor"].tolist()


def _soma(serie: pd.Series) -> float | None:
    """`min_count=1`: só nulos (ou vazia) soma nulo, não zero."""

    total = serie.sum(min_count=1)
    return None if pd.isna(total) else float(total)


def _chave_alfabetica(valor: object) -> str:
    """Chave de ordenação sem acento e sem caixa ("Ação" e "ACAO" empatam)."""

    if valor is None or pd.isna(valor):
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode("ascii")
    return sem_acento.casefold().strip()


def montar_relatorio(
    nes: pd.DataFrame, lancamento: pd.DataFrame, competencia: pd.DataFrame | None
) -> RelatorioLiquidacao:
    """`nes`: uma linha por NE marcada (`ne_ccor`, `ano`, `ne_favorecido`, `ne_descricao`). `lancamento` e
    `competencia`: (`ne_ccor`, `ano_mes`, `valor`), a segunda `None` quando a base de
    competência não está disponível. Não altera nenhuma das entradas."""

    nes = nes[["ne_ccor", "ano", "ne_favorecido", "ne_descricao"]].drop_duplicates("ne_ccor")
    # ordem alfabética (pedido explícito): descrição, depois favorecido, depois NE — sem
    # diferenciar maiúsculas/acentos; descrição nula vai para o fim. Agrupa despesas iguais de
    # exercícios diferentes (ex. "DIARIAS NO PAIS" de 2024, 2025 e 2026 lado a lado).
    nes = nes.assign(
        _k_desc=nes["ne_descricao"].map(_chave_alfabetica),
        _k_fav=nes["ne_favorecido"].map(_chave_alfabetica),
        _k_nulo=nes["ne_descricao"].isna(),
    ).sort_values(["_k_nulo", "_k_desc", "_k_fav", "ne_ccor"])[["ne_ccor", "ano", "ne_favorecido", "ne_descricao"]]
    ordem_ne = {ne: posicao for posicao, ne in enumerate(nes["ne_ccor"])}
    alvo = set(nes["ne_ccor"])
    lanc = lancamento.loc[lancamento["ne_ccor"].isin(alvo), ["ne_ccor", "ano_mes", "valor"]]
    if competencia is not None:
        comp = competencia.loc[competencia["ne_ccor"].isin(alvo), ["ne_ccor", "ano_mes", "valor"]]
    else:
        comp = pd.DataFrame(columns=["ne_ccor", "ano_mes", "valor"])
    com_competencia = set(comp["ne_ccor"])
    com_lancamento = set(lanc["ne_ccor"])

    def _base(ne: str) -> str:
        if ne in com_competencia:
            return BASE_COMPETENCIA
        if ne in com_lancamento:
            return BASE_LANCAMENTO
        return BASE_SEM_DADO

    bases = {ne: _base(ne) for ne in nes["ne_ccor"]}

    partes = [
        comp[comp["ne_ccor"].map(bases) == BASE_COMPETENCIA],
        lanc[lanc["ne_ccor"].map(bases) == BASE_LANCAMENTO],
    ]
    serie = pd.concat(partes, ignore_index=True)
    serie = serie.assign(
        base=serie["ne_ccor"].map(bases),
        ano_mes=serie["ano_mes"].astype("int64"),
        valor=serie["valor"].astype("float64"),
    )[["ne_ccor", "base", "ano_mes", "valor"]].sort_values(["ne_ccor", "ano_mes"]).reset_index(drop=True)

    # ---- resumo por NE (reconciliação)
    total_base = serie.groupby("ne_ccor")["valor"].sum(min_count=1)
    total_lanc = lanc.groupby("ne_ccor")["valor"].sum(min_count=1)
    resumo = nes.copy()
    resumo["base"] = resumo["ne_ccor"].map(bases)
    resumo["total_base"] = resumo["ne_ccor"].map(total_base).astype("float64")
    resumo["liquidado_execucao_mensal"] = resumo["ne_ccor"].map(total_lanc).astype("float64")
    resumo["diferenca"] = resumo["total_base"] - resumo["liquidado_execucao_mensal"]
    resumo = resumo.reset_index(drop=True)

    # ---- tabela mensal: (NE, ano do mês) x Jan..Dez
    trabalho = serie.assign(ano=serie["ano_mes"] // 100, mes=serie["ano_mes"] % 100)
    largo = (
        trabalho.groupby(["ne_ccor", "ano", "mes"])["valor"]
        .sum(min_count=1)
        .unstack("mes")
        .reindex(columns=range(1, 13))
        .reset_index()
    )
    largo.columns.name = None
    largo["total"] = largo[list(range(1, 13))].sum(axis=1, min_count=1)
    sem_dado = [ne for ne, base in bases.items() if base == BASE_SEM_DADO]
    if sem_dado:
        largo = pd.concat([largo, pd.DataFrame({"ne_ccor": sem_dado})], ignore_index=True)
    info = nes.rename(columns={"ano": "ano_ne"}).set_index("ne_ccor")
    largo["ano_ne"] = largo["ne_ccor"].map(info["ano_ne"])
    largo["ne_favorecido"] = largo["ne_ccor"].map(info["ne_favorecido"])
    largo["ne_descricao"] = largo["ne_ccor"].map(info["ne_descricao"])
    largo["base"] = largo["ne_ccor"].map(bases)
    largo["ano"] = largo["ano"].astype("Int64")
    for mes in range(1, 13):
        largo[mes] = largo[mes].astype("float64")
    largo["total"] = largo["total"].astype("float64")
    mensal = largo[["ne_ccor", "ano_ne", "ne_favorecido", "ne_descricao", "base", "ano", *range(1, 13), "total"]]
    mensal = (
        mensal.assign(_ordem=mensal["ne_ccor"].map(ordem_ne))
        .sort_values(["_ordem", "ano"], na_position="last")
        .drop(columns="_ordem")
        .reset_index(drop=True)
    )

    return RelatorioLiquidacao(resumo=resumo, mensal=mensal, serie=serie)


def consolidar_por_dimensao(grupo: pd.DataFrame, coluna_cod: str, coluna_desc: str | None) -> pd.DataFrame:
    """Consolidação das NEs do grupo por uma dimensão orçamentária — uma linha por código
    (`nome`, `codigo`, `qtd`, `emp`, `liq`, `pag`, `saldo`), ordenada por Empenhado decrescente.
    `grupo`: uma linha por NE (saída de `agregar_por_ne`, com `empenhada`/`liquidada`/`paga`).
    Somas com `min_count=1` (grupo só com nulos soma nulo, não zero); `saldo` = Empenhado −
    Liquidado (Liquidado nulo conta como 0, mesma regra do quadro da tela). Código nulo vira o
    grupo "(não informado)" — nunca descartado. Não altera `grupo`."""

    colunas_grupo = [coluna_cod] if coluna_desc is None else [coluna_cod, coluna_desc]
    agrupado = (
        grupo.groupby(colunas_grupo, dropna=False)
        .agg(
            qtd=("ne_ccor", "count"),
            emp=("empenhada", lambda s: s.sum(min_count=1)),
            liq=("liquidada", lambda s: s.sum(min_count=1)),
            pag=("paga", lambda s: s.sum(min_count=1)),
        )
        .reset_index()
    )
    agrupado["saldo"] = agrupado["emp"] - agrupado["liq"].fillna(0.0)

    def _nome(linha: pd.Series) -> str:
        if pd.isna(linha[coluna_cod]):
            return "(não informado)"
        if coluna_desc and pd.notna(linha[coluna_desc]):
            return str(linha[coluna_desc])
        return str(linha[coluna_cod])

    agrupado["nome"] = agrupado.apply(_nome, axis=1) if not agrupado.empty else pd.Series(dtype=object)
    agrupado["codigo"] = agrupado[coluna_cod]
    return (
        agrupado[["nome", "codigo", "qtd", "emp", "liq", "pag", "saldo"]]
        .sort_values("emp", ascending=False, na_position="last")
        .reset_index(drop=True)
    )


# ------------------------------------------------------------------------------ comum
def _formatar_brl(valor: object) -> str:
    """Pontuação pt-BR com centavos; nulo vira "—" (distinto de "0,00")."""

    if valor is None or pd.isna(valor):
        return "—"
    return f"{float(valor):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _texto(valor: object) -> str | None:
    if valor is None or pd.isna(valor):
        return None
    return str(valor)


def _ne_curta(valor: object) -> str:
    return "—" if valor is None or pd.isna(valor) else ne_curta(str(valor))


def _avisos(relatorio: RelatorioLiquidacao, contexto: ContextoRelatorioLiquidacao) -> list[str]:
    avisos = []
    if contexto.origem_competencia is None:
        avisos.append(
            "A base de Liquidação por Competência não está disponível: TODAS as NEs estão por "
            "data de liquidação (mês de lançamento), não por competência."
        )
    elif relatorio.nes_por_lancamento:
        avisos.append(
            "NEs sem registro na base de competência — exibidas por DATA DE LIQUIDAÇÃO (mês de "
            "lançamento), não por competência: "
            + ", ".join(_ne_curta(ne) for ne in relatorio.nes_por_lancamento)
            + "."
        )
    if relatorio.nes_competencia_divergente:
        avisos.append(
            "NEs cujo liquidado por competência difere do total liquidado na Execução Mensal "
            "(competência parcial ou defasada — ver Diferença no Resumo por NE do Excel): "
            + ", ".join(_ne_curta(ne) for ne in relatorio.nes_competencia_divergente)
            + "."
        )
    if relatorio.nes_sem_dado:
        avisos.append(
            "NEs sem liquidação em nenhuma das bases (Sem dado): "
            + ", ".join(_ne_curta(ne) for ne in relatorio.nes_sem_dado)
            + "."
        )
    return avisos


def _linhas_parametros(relatorio: RelatorioLiquidacao, contexto: ContextoRelatorioLiquidacao) -> list[tuple[str, str]]:
    resumo = relatorio.resumo
    contagem = resumo["base"].value_counts()
    return [
        ("Empenhos no relatório", str(len(resumo))),
        ("Por competência", str(int(contagem.get(BASE_COMPETENCIA, 0)))),
        ("Por data de liquidação", str(int(contagem.get(BASE_LANCAMENTO, 0)))),
        ("Sem dado", str(int(contagem.get(BASE_SEM_DADO, 0)))),
        ("Bases", NOTA_BASES),
        ("Execução Mensal", f"extração de {contexto.data_extracao} · hash {contexto.hash_manifesto}"),
        ("Liquidação por Competência", contexto.origem_competencia or "indisponível"),
        ("Emitido em", contexto.data_emissao),
    ]


# ------------------------------------------------------------------------------ Excel
def _texto_objeto(serie: pd.Series) -> pd.Series:
    return serie.map(_texto).astype(object)


NOTA_CONSOLIDACAO = (
    "Valores da Execução Mensal (Liquidado por data de liquidação, não por competência), sobre o "
    "recorte dos filtros aplicados na tela — mesmo quadro da Consulta de Empenhos."
)


def gerar_xlsx(
    relatorio: RelatorioLiquidacao,
    contexto: ContextoRelatorioLiquidacao,
    consolidacao: Sequence[tuple[str, pd.DataFrame]] = (),
) -> bytes:
    """`consolidacao`: mesmo parâmetro de `gerar_pdf` — vira a aba "Consolidação" (uma linha por
    dimensão × grupo, sem linhas de total no meio, para continuar filtrável). Vazio: sem a aba."""

    mensal = relatorio.mensal
    aba_mensal = pd.DataFrame(
        {
            "NE": mensal["ne_ccor"].map(_ne_curta).astype(object),
            "NE (código completo)": _texto_objeto(mensal["ne_ccor"]),
            "Exercício da NE": mensal["ano_ne"].astype("Int64"),
            "Favorecido": _texto_objeto(mensal["ne_favorecido"]),
            "Descrição": _texto_objeto(mensal["ne_descricao"]),
            "Base": _texto_objeto(mensal["base"]),
            "Ano": mensal["ano"].astype("Int64"),
        }
    )
    for numero, nome in enumerate(MESES, start=1):
        aba_mensal[nome] = mensal[numero].astype("float64")
    aba_mensal["Total"] = mensal["total"].astype("float64")

    resumo = relatorio.resumo
    aba_resumo = pd.DataFrame(
        {
            "NE": resumo["ne_ccor"].map(_ne_curta).astype(object),
            "NE (código completo)": _texto_objeto(resumo["ne_ccor"]),
            "Exercício da NE": resumo["ano"].astype("Int64"),
            "Favorecido": _texto_objeto(resumo["ne_favorecido"]),
            "Descrição": _texto_objeto(resumo["ne_descricao"]),
            "Base": _texto_objeto(resumo["base"]),
            "Liquidado na base": resumo["total_base"],
            "Liquidado total (Execução Mensal)": resumo["liquidado_execucao_mensal"],
            "Diferença": resumo["diferenca"],
        }
    )

    serie = relatorio.serie
    aba_serie = pd.DataFrame(
        {
            "NE (código completo)": _texto_objeto(serie["ne_ccor"]),
            "Base": _texto_objeto(serie["base"]),
            "Ano": (serie["ano_mes"] // 100).astype("Int64"),
            "Mês": (serie["ano_mes"] % 100).astype("Int64"),
            "Liquidado": serie["valor"].astype("float64"),
        }
    )

    aba_consolidacao = None
    if consolidacao:
        aba_consolidacao = pd.concat(
            [
                pd.DataFrame(
                    {
                        "Dimensão": rotulo,
                        "Grupo": _texto_objeto(tabela["nome"]),
                        "Código": _texto_objeto(tabela["codigo"]),
                        "NEs": tabela["qtd"].astype("Int64"),
                        "Empenhado": tabela["emp"].astype("float64"),
                        "Liquidado (data de liquidação)": tabela["liq"].astype("float64"),
                        "Pago": tabela["pag"].astype("float64"),
                        "Saldo": tabela["saldo"].astype("float64"),
                    }
                )
                for rotulo, tabela in consolidacao
            ],
            ignore_index=True,
        )

    parametros = [("Avisos", aviso) for aviso in _avisos(relatorio, contexto)] + _linhas_parametros(relatorio, contexto)
    if aba_consolidacao is not None:
        parametros.append(("Consolidação", NOTA_CONSOLIDACAO))

    colunas_valor = set(MESES) | {
        "Total", "Liquidado na base", "Liquidado total (Execução Mensal)", "Diferença", "Liquidado",
        "Empenhado", "Liquidado (data de liquidação)", "Pago", "Saldo",
    }
    colunas_inteiras = {"Exercício da NE", "Ano", "Mês", "NEs"}

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        abas = {"Liquidação mensal": aba_mensal, "Resumo por NE": aba_resumo, "Série": aba_serie}
        if aba_consolidacao is not None:
            abas["Consolidação"] = aba_consolidacao
        for nome, dados in abas.items():
            dados.to_excel(writer, sheet_name=nome, index=False)
            planilha = writer.sheets[nome]
            for indice, cabecalho in enumerate(dados.columns, start=1):
                letra = planilha.cell(row=1, column=indice).column_letter
                if cabecalho in colunas_valor:
                    formato = "#,##0.00"
                elif cabecalho in colunas_inteiras:
                    formato = None
                else:
                    formato = "@"
                if formato:
                    for celula in planilha[letra][1:]:
                        celula.number_format = formato
                planilha.column_dimensions[letra].width = min(max(len(cabecalho), 12) + 2, 45)
            planilha.freeze_panes = "B2"
        pd.DataFrame(parametros, columns=["Parâmetro", "Valor"]).to_excel(writer, sheet_name="Parâmetros", index=False)
        writer.sheets["Parâmetros"].column_dimensions["A"].width = 28
        writer.sheets["Parâmetros"].column_dimensions["B"].width = 120
    return buffer.getvalue()


# -------------------------------------------------------------------------------- PDF
#: landscape(A4) com 10mm de margem (~785pt úteis).
_CABECALHO_MENSAL_PDF = ["NE", "ANO", "BASE", *[m.upper() for m in MESES], "TOTAL"]
_LARGURAS_MENSAL_PDF = [62, 26, 52] + [51] * 12 + [58]
_CABECALHO_CONSOLIDACAO_PDF = ["GRUPO", "CÓDIGO", "NEs", "EMPENHADO (R$)", "LIQUIDADO (R$)", "PAGO (R$)", "SALDO (R$)"]
_LARGURAS_CONSOLIDACAO_PDF = [305, 70, 40, 92, 92, 92, 92]
_COR_TITULO_NE = colors.HexColor("#E8EEF7")


def _estilo_tabela(colunas_valor_inicio: int, com_total: bool, zebra: bool = True) -> TableStyle:
    comandos = [
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDDDDD")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (colunas_valor_inicio, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if zebra:
        comandos.append(("ROWBACKGROUNDS", (0, 1), (-1, -2 if com_total else -1), [colors.white, colors.HexColor("#F5F5F5")]))
    if com_total:
        comandos.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
    return TableStyle(comandos)


def gerar_pdf(
    relatorio: RelatorioLiquidacao,
    contexto: ContextoRelatorioLiquidacao,
    consolidacao: Sequence[tuple[str, pd.DataFrame]] = (),
) -> bytes:
    """`consolidacao`: (rótulo da dimensão, saída de `consolidar_por_dimensao`), na ordem em que
    os quadros devem aparecer — a "Consolidação Orçamentária do Grupo" da tela."""

    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
        title=TITULO,
    )
    estilos = getSampleStyleSheet()
    estilo_parametro = estilos["Normal"].clone("parametro_liquidacao")
    estilo_parametro.fontSize = 8
    estilo_parametro.leading = 10
    estilo_aviso = estilo_parametro.clone("aviso_liquidacao")
    estilo_aviso.textColor = colors.HexColor("#8A4B00")
    estilo_celula = estilos["Normal"].clone("celula_liquidacao")
    estilo_celula.fontSize = 6.5
    estilo_celula.leading = 7.5

    elementos: list = [Paragraph(TITULO, estilos["Heading3"])]
    for aviso in _avisos(relatorio, contexto):
        elementos.append(Paragraph(f"<b>ATENÇÃO:</b> {escape(aviso)}", estilo_aviso))
    for rotulo, valor in _linhas_parametros(relatorio, contexto):
        elementos.append(Paragraph(f"<b>{escape(rotulo)}:</b> {escape(valor)}", estilo_parametro))
    elementos.append(Spacer(1, 8))

    # título de seção nunca fica sozinho no pé da página, separado da tabela
    estilo_secao = estilos["Heading4"].clone("secao_liquidacao")
    estilo_secao.keepWithNext = 1
    estilo_nota_secao = estilo_parametro.clone("nota_secao_liquidacao")
    estilo_subsecao = estilo_parametro.clone("subsecao_liquidacao")
    estilo_subsecao.fontName = "Helvetica-Bold"
    estilo_titulo_ne = estilo_celula.clone("titulo_ne_liquidacao")
    estilo_titulo_ne.fontSize = 7
    estilo_titulo_ne.leading = 8.5

    # ---- tabela mensal: cada NE abre com uma linha de título de largura total (NE —
    # favorecido — descrição); as 16 colunas de valor não comportam mais duas colunas de texto.
    mensal = relatorio.mensal
    dados: list[list[object]] = [_CABECALHO_MENSAL_PDF]
    comandos_titulo: list[tuple] = []
    ne_anterior = None
    for _, linha in mensal.iterrows():
        if linha["ne_ccor"] != ne_anterior:
            ne_anterior = linha["ne_ccor"]
            titulo = (
                f"<b>{escape(_ne_curta(linha['ne_ccor']))}</b> — "
                f"{escape(_texto(linha['ne_favorecido']) or '(sem favorecido)')} — "
                f"{escape(_texto(linha['ne_descricao']) or '(sem descrição)')}"
            )
            indice = len(dados)
            dados.append([Paragraph(titulo, estilo_titulo_ne)] + [""] * (len(_CABECALHO_MENSAL_PDF) - 1))
            comandos_titulo += [
                ("SPAN", (0, indice), (-1, indice)),
                ("BACKGROUND", (0, indice), (-1, indice), _COR_TITULO_NE),
            ]
        dados.append(
            [
                _ne_curta(linha["ne_ccor"]),
                "—" if pd.isna(linha["ano"]) else str(int(linha["ano"])),
                Paragraph(escape(str(linha["base"])), estilo_celula),
                *[_formatar_brl(linha[m]) for m in range(1, 13)],
                _formatar_brl(linha["total"]),
            ]
        )
    tabela = Table(dados, colWidths=_LARGURAS_MENSAL_PDF, repeatRows=1)
    estilo_mensal = _estilo_tabela(3, com_total=False, zebra=False)
    for comando in comandos_titulo:
        estilo_mensal.add(*comando)
    tabela.setStyle(estilo_mensal)
    elementos.append(Paragraph("Liquidação mensal (uma linha por NE e ano do mês)", estilo_secao))
    elementos.append(tabela)
    elementos.append(Spacer(1, 10))

    # ---- consolidação orçamentária do grupo (mesmo quadro da tela)
    if consolidacao:
        # título + nota + cada quadro ficam num `KeepTogether`: título nunca sozinho no pé da
        # página, quadro de dimensão nunca partido do seu rótulo.
        cabecalho_secao = [
            Paragraph("Consolidação Orçamentária do Grupo", estilo_secao),
            Paragraph(escape(NOTA_CONSOLIDACAO), estilo_nota_secao),
        ]
        for posicao, (rotulo, tabela_dim) in enumerate(consolidacao):
            dados_dim: list[list[object]] = [_CABECALHO_CONSOLIDACAO_PDF]
            for _, linha in tabela_dim.iterrows():
                dados_dim.append(
                    [
                        Paragraph(escape(str(linha["nome"])), estilo_celula),
                        _texto(linha["codigo"]) or "—",
                        str(int(linha["qtd"])),
                        _formatar_brl(linha["emp"]),
                        _formatar_brl(linha["liq"]),
                        _formatar_brl(linha["pag"]),
                        _formatar_brl(linha["saldo"]),
                    ]
                )
            dados_dim.append(
                [
                    "TOTAL", "",
                    str(int(tabela_dim["qtd"].sum())),
                    _formatar_brl(_soma(tabela_dim["emp"])),
                    _formatar_brl(_soma(tabela_dim["liq"])),
                    _formatar_brl(_soma(tabela_dim["pag"])),
                    _formatar_brl(_soma(tabela_dim["saldo"])),
                ]
            )
            tabela_pdf = Table(dados_dim, colWidths=_LARGURAS_CONSOLIDACAO_PDF, repeatRows=1)
            tabela_pdf.setStyle(_estilo_tabela(2, com_total=True))
            bloco = [Spacer(1, 4), Paragraph(escape(rotulo), estilo_subsecao), tabela_pdf]
            elementos.append(KeepTogether((cabecalho_secao if posicao == 0 else []) + bloco))

    documento.build(elementos)
    return buffer.getvalue()
