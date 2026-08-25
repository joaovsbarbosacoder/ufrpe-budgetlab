"""
Relatório de Reforço de Empenho (Bolsas e Auxílios / Contratos Contínuos).

Camada: regra de negócio de relatório — monta a tabela no formato usado pela PROPLAD para
pedidos de reforço de empenho e gera os DOIS modelos de PDF em uso (ver histórico da
conversa para os PDFs de referência — dois modelos distintos, os dois precisam ser emitidos):

  * "Detalhado" (`gerar_pdf_detalhado`) — Processo, Item de Despesa, Unidade, Ação, PTRES,
    Fonte, ND, UGR, PI, Empenho, Empenhar (R$); Processo/Unidade/Empenho repetidos em toda
    linha.
  * "Resumido" (`gerar_pdf_resumido`) — Item de Despesa, Ação, PTRES, Fonte, ND, PI, UGR,
    Empenhar (R$); sem Unidade/Empenho, Processo aparece uma vez só no cabeçalho da página
    (não repetido linha a linha) — layout de Tabela Dinâmica do Excel impresso, PI antes de
    UGR (ordem invertida em relação ao modelo detalhado).

Não lê planilha, não é interface — recebe o DataFrame já normalizado de
`ler_bolsas_auxilios`/`ler_contratos_continuos` (com `meses_a_empenhar` já calculado por
`necessidade_empenho.py`).

"Meses a empenhar" E "Empenhar (R$)" são editáveis por linha, os dois (pedido explícito) — o
valor sugerido inicial vem de `meses_a_empenhar`, mas cada linha pode ser ajustada livremente
antes de gerar o relatório (a edição em si mora em `st.session_state`, na página, não aqui).
Editar "Meses a Empenhar" recalcula "Empenhar (R$)" (= meses × valor mensal) e sempre vence
sobre um valor digitado direto antes; editar "Empenhar (R$)" direto fica valendo como está até
a próxima edição de "Meses a Empenhar" na mesma linha.

Contrato público:
    EspecificacaoRelatorio (dataclass) — BOLSAS_AUXILIOS / CONTRATOS_CONTINUOS, prontas
    linhas_para_processo(df, spec, processo) -> pd.DataFrame
    excluir_linhas_zeradas(linhas) -> pd.DataFrame
    gerar_pdf_detalhado(spec, processo, linhas) -> bytes
    gerar_pdf_resumido(spec, processo, linhas) -> bytes
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet


@dataclass(frozen=True)
class EspecificacaoRelatorio:
    """O que varia entre Bolsas e Contratos Contínuos para este relatório — o resto do
    esquema (unidade/ação/PTRES/fonte/ND/UGR/PI/empenho) já tem o mesmo nome de coluna nas
    duas bases (ver `COLUNAS_ORIGEM` de cada leitor)."""

    titulo_orgao: str
    titulo_base: str
    #: coluna que vira "PROCESSO" — o processo administrativo que agrupa vários itens de
    #: reforço num mesmo pedido (não o processo de contratação, ver histórico da conversa).
    coluna_processo: str
    #: coluna que vira "ITEM DE DESPESA" — o texto que identifica a linha para quem lê o
    #: relatório (nome do programa de bolsa, ou fornecedor do contrato).
    coluna_item_despesa: str
    coluna_valor_mensal: str


BOLSAS_AUXILIOS = EspecificacaoRelatorio(
    titulo_orgao="PRÓ-REITORIA DE ADMINISTRAÇÃO - PROPLAD",
    titulo_base="BOLSAS, AUXÍLIOS FINANCEIROS E GECC",
    coluna_processo="processo",
    coluna_item_despesa="programa_bolsa",
    coluna_valor_mensal="valor_mensal",
)

CONTRATOS_CONTINUOS = EspecificacaoRelatorio(
    titulo_orgao="PRÓ-REITORIA DE ADMINISTRAÇÃO - PROPLAD",
    titulo_base="CONTRATOS CONTÍNUOS",
    coluna_processo="processo_empenho",
    coluna_item_despesa="fornecedor",
    coluna_valor_mensal="despesa_mensal",
)

#: colunas do esquema comum do relatório, já com o nome final de exibição — nesta ordem.
_CABECALHO = [
    "PROCESSO", "ITEM DE DESPESA", "UNIDADE", "AÇÃO", "PTRES", "FONTE", "ND", "UGR", "PI",
    "EMPENHO", "EMPENHAR (R$)",
]


def processos_disponiveis(df: pd.DataFrame, spec: EspecificacaoRelatorio) -> list[str]:
    """Processos distintos da base, com NE reconhecível (sem NE não há o que reforçar) —
    para popular o seletor da página, ordenados do mais frequente para o menos frequente
    (processo que agrupa mais itens de reforço primeiro, atalho útil no dia a dia)."""

    com_ne = df[df["ne_curta"].notna() & df[spec.coluna_processo].notna()]
    return com_ne[spec.coluna_processo].value_counts().index.tolist()


def linhas_para_processo(df: pd.DataFrame, spec: EspecificacaoRelatorio, processo: str) -> pd.DataFrame:
    """Linhas do processo escolhido, no esquema comum do relatório (independente da base de
    origem) — `meses_sugeridos` vem de `meses_a_empenhar` (já calculado na leitura da base),
    ponto de partida para a edição por linha na página, não o valor final. Linhas sem NE
    reconhecível ficam de fora — não há empenho para reforçar (a bolsa/contrato ainda não foi
    empenhado), mesmo critério de `processos_disponiveis`."""

    filtrado = df[(df[spec.coluna_processo] == processo) & df["ne_curta"].notna()]
    resultado = pd.DataFrame(
        {
            "processo": filtrado[spec.coluna_processo],
            "item_despesa": filtrado[spec.coluna_item_despesa],
            "unidade_cod": filtrado["unidade_cod"],
            "acao_cod": filtrado["acao_cod"],
            "ptres": filtrado["ptres"],
            "fonte_cod": filtrado["fonte_cod"],
            "natureza_despesa_cod": filtrado["natureza_despesa_cod"],
            "ugr_cod": filtrado["ugr_cod"],
            "pi_cod": filtrado["pi_cod"],
            "ne_curta": filtrado["ne_curta"],
            "valor_mensal": filtrado[spec.coluna_valor_mensal],
            "meses_sugeridos": filtrado["meses_a_empenhar"],
        }
    )
    return resultado.reset_index(drop=True)


def excluir_linhas_zeradas(linhas: pd.DataFrame) -> pd.DataFrame:
    """Remove linhas com `meses` OU `empenhar` igual a zero (pedido explícito) — zero não é
    "sem dado" (`NaN`, que continua na saída — ver `_formatar_valor`), é "não há o que
    reforçar aqui", então não deve entrar no PDF final. A tela de edição continua mostrando
    essas linhas (a exclusão é só para gerar o relatório, ver `render_botao_relatorio`)."""

    return linhas[(linhas["meses"] != 0) & (linhas["empenhar"] != 0)]


def _formatar_valor(valor: float) -> str:
    # NaN acontece quando "Meses a Empenhar" fica sem preencher (linha cujo cálculo de
    # necessidade não deu um número — dado incompleto na origem, ver `meses_a_empenhar` em
    # `necessidade_empenho.py`) — "—" em vez de "nan" no PDF, mesmo critério de nulo ≠ zero
    # do resto do projeto.
    if pd.isna(valor):
        return "—"
    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


#: larguras de coluna (pt) calibradas para landscape(A4) com margem de 15mm dos dois lados
#: (~756pt úteis) — soma abaixo fica dentro desse limite. Sem largura explícita, o reportlab
#: dimensiona cada coluna pelo conteúdo mais largo (a descrição do item de despesa, em geral
#: bem mais longa que as demais colunas), empurrando "EMPENHAR (R$)" para fora da página —
#: por isso "Item de Despesa" (e "Processo", mais curto mas por segurança) usam `Paragraph`
#: em vez de string simples, para quebrar linha dentro da largura fixa, não estourá-la.
_LARGURAS_COLUNA_DETALHADO = [66, 199, 42, 38, 42, 34, 38, 38, 62, 62, 62]

#: Modelo "resumido" (ver `gerar_pdf_resumido`): sem Unidade/Empenho, Item de Despesa ganha o
#: espaço que sobra.
_CABECALHO_RESUMIDO = ["ITEM DE DESPESA", "AÇÃO", "PTRES", "FONTE", "ND", "PI", "UGR", "EMPENHAR (R$)"]
_LARGURAS_COLUNA_RESUMIDO = [300, 42, 46, 38, 46, 62, 46, 70]


def _celula_texto(texto: str, estilo) -> Paragraph:
    return Paragraph(str(texto), estilo)


def _novo_documento(spec: EspecificacaoRelatorio, processo: str) -> tuple[BytesIO, SimpleDocTemplate, list, object]:
    """Base comum aos dois modelos de PDF — página paisagem, cabeçalho com título/base, e o
    estilo de célula usado nas colunas de texto livre (quebra de linha dentro da largura fixa
    da coluna, ver `_LARGURAS_COLUNA_*`)."""

    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
    )
    estilos = getSampleStyleSheet()
    estilo_celula = estilos["Normal"].clone("celula")
    estilo_celula.fontSize = 7
    estilo_celula.leading = 8.5

    elementos = [
        Paragraph(spec.titulo_orgao, estilos["Heading3"]),
        Paragraph(spec.titulo_base, estilos["Heading3"]),
        Paragraph(f"Processo: {processo}", estilos["Normal"]),
        Spacer(1, 8),
    ]
    return buffer, documento, elementos, estilo_celula


def _estilo_tabela(indice_inicio_alinhamento_direita: int) -> TableStyle:
    return TableStyle(
        [
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDDDDD")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (indice_inicio_alinhamento_direita, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F5F5")]),
        ]
    )


def gerar_pdf_detalhado(spec: EspecificacaoRelatorio, processo: str, linhas: pd.DataFrame) -> bytes:
    """PDF "modelo detalhado" da PROPLAD — uma linha por item, com Processo/Unidade/Empenho
    repetidos em cada linha. `linhas` já traz a coluna `empenhar` final (após edição por
    linha na página) — esta função só formata e desenha, não recalcula nada."""

    buffer, documento, elementos, estilo_celula = _novo_documento(spec, processo)

    dados = [_CABECALHO]
    for linha in linhas.itertuples():
        dados.append(
            [
                _celula_texto(linha.processo, estilo_celula),
                _celula_texto(linha.item_despesa, estilo_celula),
                str(linha.unidade_cod), str(linha.acao_cod), str(linha.ptres),
                str(linha.fonte_cod), str(linha.natureza_despesa_cod), str(linha.ugr_cod),
                str(linha.pi_cod), str(linha.ne_curta), _formatar_valor(float(linha.empenhar)),
            ]
        )
    total = float(linhas["empenhar"].sum())
    dados.append(["", "", "", "", "", "", "", "", "", "TOTAL", _formatar_valor(total)])

    tabela = Table(dados, colWidths=_LARGURAS_COLUNA_DETALHADO, repeatRows=1)
    tabela.setStyle(_estilo_tabela(indice_inicio_alinhamento_direita=2))
    elementos.append(tabela)
    documento.build(elementos)
    return buffer.getvalue()


def gerar_pdf_resumido(spec: EspecificacaoRelatorio, processo: str, linhas: pd.DataFrame) -> bytes:
    """PDF "modelo resumido" da PROPLAD — Processo aparece uma vez só (no cabeçalho da
    página, não repetido linha a linha) e as colunas Unidade/Empenho (NE) ficam de fora
    (pedido explícito, layout de referência sem essas duas colunas). `linhas` já traz a
    coluna `empenhar` final — esta função só formata e desenha, não recalcula nada."""

    buffer, documento, elementos, estilo_celula = _novo_documento(spec, processo)

    dados = [_CABECALHO_RESUMIDO]
    for linha in linhas.itertuples():
        dados.append(
            [
                _celula_texto(linha.item_despesa, estilo_celula),
                str(linha.acao_cod), str(linha.ptres), str(linha.fonte_cod),
                str(linha.natureza_despesa_cod), str(linha.pi_cod), str(linha.ugr_cod),
                _formatar_valor(float(linha.empenhar)),
            ]
        )
    total = float(linhas["empenhar"].sum())
    dados.append(["", "", "", "", "", "", "TOTAL", _formatar_valor(total)])

    tabela = Table(dados, colWidths=_LARGURAS_COLUNA_RESUMIDO, repeatRows=1)
    tabela.setStyle(_estilo_tabela(indice_inicio_alinhamento_direita=1))
    elementos.append(tabela)
    documento.build(elementos)
    return buffer.getvalue()
