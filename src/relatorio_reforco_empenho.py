"""
Relatório de Reforço de Empenho (Bolsas e Auxílios / Contratos Contínuos).

Camada: regra de negócio de relatório — monta a tabela no formato usado pela PROPLAD para
pedidos de reforço de empenho (Processo, Item de Despesa, Unidade, Ação, PTRES, Fonte, ND,
UGR, PI, Empenho, Empenhar (R$), ver histórico da conversa para os PDFs de referência) e
gera o PDF correspondente. Não lê planilha, não é interface — recebe o DataFrame já
normalizado de `ler_bolsas_auxilios`/`ler_contratos_continuos` (com `meses_a_empenhar` já
calculado por `necessidade_empenho.py`).

"Meses a empenhar" é editável por linha (personalizado por empenho, pedido explícito) — o
valor sugerido inicial vem de `meses_a_empenhar`, mas cada linha pode ser ajustada livremente
antes de gerar o relatório (a edição em si mora em `st.session_state`, na página, não aqui).
"Empenhar (R$)" é sempre DERIVADO (meses × valor mensal da linha), nunca um campo editado
diretamente — um único controle por linha evita os dois campos saírem de sincronia.

Contrato público:
    EspecificacaoRelatorio (dataclass) — BOLSAS_AUXILIOS / CONTRATOS_CONTINUOS, prontas
    linhas_para_processo(df, spec, processo) -> pd.DataFrame
    gerar_pdf(spec, processo, linhas) -> bytes
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
_LARGURAS_COLUNA = [66, 199, 42, 38, 42, 34, 38, 38, 62, 62, 62]


def _celula_texto(texto: str, estilo) -> Paragraph:
    return Paragraph(str(texto), estilo)


def gerar_pdf(spec: EspecificacaoRelatorio, processo: str, linhas: pd.DataFrame) -> bytes:
    """PDF no layout do modelo da PROPLAD — cabeçalho com título/base, tabela paisagem com
    uma linha por item e o total ao final. `linhas` já traz a coluna `empenhar` final (após
    edição por linha na página) — esta função só formata e desenha, não recalcula nada."""

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

    tabela = Table(dados, colWidths=_LARGURAS_COLUNA, repeatRows=1)
    tabela.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDDDDD")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F5F5")]),
            ]
        )
    )
    elementos.append(tabela)
    documento.build(elementos)
    return buffer.getvalue()
