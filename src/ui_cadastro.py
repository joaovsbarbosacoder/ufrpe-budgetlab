"""Componentes visuais compartilhados pelos cadastros de Contratos Contínuos e de Bolsas e Auxílios.

Camada: interface (HTML/CSS). Sem regra de negócio e sem leitura de dado: recebe valores já
calculados pelas páginas e só os formata. Funções puras (devolvem texto), exceto quando dito
o contrário, para serem testáveis sem Streamlit.

SEGUNDO PEDIDO (05/10/2026): "aplique o mesmo layout para a Cobertura Orçamentária por PTRES, EMPENHADO ×
LIQUIDADO e RESUMO CONSOLIDADO" — as três seções analíticas das duas páginas passam a usar o mesmo cartão
branco arredondado, título com destaque à direita e tabela de linhas limpas (`cartao_secao`/`tabela_html`).

PEDIDO (05/10/2026): "uma repaginação no layout dos cadastros de contratos e de bolsas — está
com muita cara de planilha", seguindo o layout de referência enviado (página de DEA): título com
ação principal à direita, cartão-resumo com faixa de destaque e grade de indicadores, e um
REGISTRO em tabela de linhas limpas — abas de situação com contagem, filtros, linha com título e
subtítulo, valores alinhados à direita, situação em "chip" colorido e ações por ícone. A edição
sai da grade de campos soltos e vai para uma janela (`st.dialog`) organizada em seções.

Valores: nulo ≠ zero. `formatar_brl` mostra "—" para nulo e "R$ 0,00" para zero (regra permanente
do projeto); negativo mantém o sinal.

Contrato público:
    TONS
    formatar_brl(valor) -> str
    chip(texto, tom) -> str
    celula_principal(titulo, subtitulo) -> str
    celula_categoria(texto) -> str
    celula_valor(valor, tom=None) -> str
    celula_suave(texto) -> str
    cartao_resumo(titulo, descricao, faixa, indicadores) -> str
    grade_indicadores(indicadores) -> str
    aviso_linha_do_tempo(nes, nes_com_tempo, base_disponivel) -> str | None
    tabela_html(colunas, linhas, proporcoes, rodape=None) -> str
    topo_secao(titulo, descricao, destaque, kicker=None) -> str
    cartao_secao(titulo, descricao, destaque, corpo_html, kicker=None) -> str
    celula_saldo(saldo, rotulo_positivo, rotulo_negativo, vazio) -> str
    cartao_cobertura_ptres(codigo, nome, grupo) -> str
    contagens_por_aba(mascaras) -> dict[str, int]
    ordenar_por(dataframe, coluna, crescente) -> pd.DataFrame
    css() -> str
"""

from __future__ import annotations

from collections.abc import Iterable
from html import escape

import pandas as pd

from src.design_tokens import (
    ACCENT,
    ACCENT_SOFT,
    BORDER,
    BORDER_SOFT,
    FONT_BODY,
    FONT_HEADING,
    NEGATIVE,
    NEGATIVE_SOFT,
    POSITIVE,
    POSITIVE_SOFT,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    TEXT_FAINT,
    TEXT_MUTED,
    WARNING,
    WARNING_SOFT,
)

#: tons semânticos de chip/faixa. `neutro` = sem juízo de valor (ex.: Suspenso); `info` = destaque azul.
TONS = ("ok", "warn", "bad", "neutro", "info")


def _eh_nulo(valor: object) -> bool:
    return valor is None or bool(pd.isna(valor))


def formatar_brl(valor: object) -> str:
    """"R$ 1.234,56" em pt-BR; nulo vira "—" (distinto de "R$ 0,00"); negativo mantém o sinal."""

    if _eh_nulo(valor):
        return "—"
    numero = float(valor)
    texto = f"{abs(numero):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"-R$ {texto}" if numero < 0 else f"R$ {texto}"


def _tom_valido(tom: str | None) -> str:
    return tom if tom in TONS else "neutro"


def chip(texto: object, tom: str = "neutro") -> str:
    """Rótulo de situação em forma de pílula, com bolinha — "Ativo", "Vencido"… O texto é escapado."""

    return f'<span class="cad-chip {_tom_valido(tom)}"><i></i>{escape(str(texto))}</span>'


def celula_principal(titulo: object, subtitulo: object = None) -> str:
    """Primeira coluna da linha: título em destaque e, abaixo, um subtítulo esmaecido. Textos escapados."""

    titulo_txt = "—" if _eh_nulo(titulo) or str(titulo).strip() == "" else str(titulo)
    sub = ""
    if not _eh_nulo(subtitulo) and str(subtitulo).strip():
        sub = f'<div class="cad-sub">{escape(str(subtitulo))}</div>'
    return f'<div class="cad-principal"><div class="cad-tit">{escape(titulo_txt)}</div>{sub}</div>'


def celula_categoria(texto: object) -> str:
    """Categoria com bolinha, como a coluna "CAT." da referência. Nulo vira "—"."""

    rotulo = "—" if _eh_nulo(texto) or str(texto).strip() == "" else str(texto)
    return f'<div class="cad-cat"><i></i>{escape(rotulo)}</div>'


def celula_valor(valor: object, tom: str | None = None, vazio: str | None = None) -> str:
    """Valor monetário alinhado à direita. `tom` opcional (`warn`/`bad`/`ok`) colore o número. `vazio`:
    texto para valor NULO (ex.: "sem NE", "sem dotação"), esmaecido; sem ele, nulo vira "—". Zero continua
    "R$ 0,00" — nulo e zero nunca se confundem."""

    if _eh_nulo(valor) and vazio is not None:
        return f'<div class="cad-valor vazio">{escape(vazio)}</div>'
    classe = f"cad-valor {tom}" if tom in TONS else "cad-valor"
    return f'<div class="{classe}">{escape(formatar_brl(valor))}</div>'


def celula_suave(texto: object) -> str:
    """Texto secundário esmaecido (data, processo…). Nulo vira "—"."""

    rotulo = "—" if _eh_nulo(texto) or str(texto).strip() == "" else str(texto)
    return f'<div class="cad-suave">{escape(rotulo)}</div>'


def cartao_resumo(
    titulo: str,
    descricao: str,
    faixa: dict[str, str],
    indicadores: list[tuple[str, str]],
) -> str:
    """Cartão-resumo do topo: título + descrição, faixa de destaque e grade de indicadores.

    `faixa`: `rotulo`, `valor`, `detalhe` (opcional, à direita) e `tom` (`ok`/`warn`/`bad`/`info`).
    `indicadores`: lista de (rótulo, valor já formatado). Todos os textos são escapados."""

    tom = _tom_valido(faixa.get("tom"))
    detalhe = faixa.get("detalhe") or ""
    detalhe_html = f'<div class="cad-faixa-detalhe">{escape(detalhe)}</div>' if detalhe else ""
    tiles = "".join(
        f'<div class="cad-tile"><div class="cad-tile-rotulo">{escape(rotulo)}</div>'
        f'<div class="cad-tile-valor">{escape(valor)}</div></div>'
        for rotulo, valor in indicadores
    )
    return (
        '<div class="cad-resumo">'
        f'<div class="cad-resumo-titulo">{escape(titulo)}</div>'
        f'<div class="cad-resumo-desc">{escape(descricao)}</div>'
        f'<div class="cad-faixa {tom}"><span class="cad-bola"></span>'
        f'<div><div class="cad-faixa-rotulo">{escape(faixa.get("rotulo", ""))}</div>'
        f'<div class="cad-faixa-valor">{escape(faixa.get("valor", ""))}</div></div>'
        f"{detalhe_html}</div>"
        f'<div class="cad-tiles">{tiles}</div>'
        "</div>"
    )


def grade_indicadores(indicadores: list[tuple[str, str]]) -> str:
    """Só a grade de indicadores (sem título nem faixa) — usada no topo das janelas de edição."""

    tiles = "".join(
        f'<div class="cad-tile"><div class="cad-tile-rotulo">{escape(rotulo)}</div>'
        f'<div class="cad-tile-valor">{escape(valor)}</div></div>'
        for rotulo, valor in indicadores
    )
    return f'<div class="cad-tiles">{tiles}</div>'


def aviso_linha_do_tempo(
    nes: Iterable[object], nes_com_tempo: set[str], base_disponivel: bool = True
) -> str | None:
    """Aviso do Resumo Consolidado quando NENHUMA linha abre a "Linha do tempo mensal" (pedido de
    05/10/2026: no exercício 2027 de Bolsas as linhas viram texto simples e parecia defeito). A linha
    só é clicável quando a NE tem dado na base mensal (Execução Mensal). Devolve `None` se pelo menos
    uma NE do recorte é clicável (nada a explicar). `base_disponivel=False`: a base mensal nem foi
    carregada, e o texto diz isso em vez de culpar as NEs."""

    if any(not _eh_nulo(ne) and ne in nes_com_tempo for ne in nes):
        return None
    if not base_disponivel:
        return "A linha do tempo mensal não pôde ser carregada (Execução Mensal indisponível); por isso nenhuma linha abre."
    return (
        "Nenhuma NE deste recorte foi encontrada na Execução Mensal — a linha do tempo mensal só abre para "
        "NEs com dado nessa base (programas e contratos sem NE aparecem como texto simples)."
    )


def tabela_html(
    colunas: list[tuple[str, bool]],
    linhas: list[list[str]],
    proporcoes: list[float],
    rodape: list[str] | None = None,
    rolagem: bool = False,
) -> str:
    """Tabela de linhas limpas em grade CSS (`.cad-tabela`): cabeçalho em caixa-alta esmaecida, uma linha por
    item, rodapé de total opcional. `colunas`: (rótulo, alinhar_à_direita); `proporcoes`: largura relativa de
    cada coluna (frações); `linhas`/`rodape`: listas de células JÁ em HTML (use `celula_*`, que escapam o
    texto). Rótulos são escapados aqui. Uma única linha de texto por linha (sem indentação): o Markdown do
    Streamlit trata 4+ espaços no começo de linha como bloco de código. `rolagem=True` põe só as linhas numa
    caixa de altura máxima com barra de rolagem (`.cad-tabela-rolagem`); cabeçalho e rodapé ficam fora dela."""

    if len(colunas) != len(proporcoes):
        raise ValueError("colunas e proporcoes precisam ter o mesmo tamanho")
    grade = " ".join(f"minmax(0,{proporcao}fr)" for proporcao in proporcoes)
    cabecalho = "".join(
        f'<span class="cad-tabela-rotulo{" direita" if direita else ""}">{escape(rotulo)}</span>'
        for rotulo, direita in colunas
    )
    # célula vazia ("") ocuparia ZERO elementos na grade e deslocaria as seguintes: vira um `<span>` vazio
    def _preenche(celulas: list[str]) -> str:
        return "".join(celula if celula else "<span></span>" for celula in celulas)

    corpo = "".join(f'<div class="cad-tabela-linha">{_preenche(celulas)}</div>' for celulas in linhas)
    if rolagem:
        corpo = f'<div class="cad-tabela-rolagem">{corpo}</div>'
    total = f'<div class="cad-tabela-rodape">{_preenche(rodape)}</div>' if rodape else ""
    return (
        f'<div class="cad-tabela" style="--cad-cols:{grade}">'
        f'<div class="cad-tabela-cab">{cabecalho}</div>{corpo}{total}</div>'
    )


def topo_secao(
    titulo: str,
    descricao: str | None,
    destaque: dict[str, str] | None,
    kicker: str | None = None,
) -> str:
    """Só o TOPO de um cartão de seção (kicker, título, descrição e destaque à direita), sem a caixa nem o
    corpo — para os cartões que contêm botões do Streamlit (Resumo Consolidado), em que a caixa é o
    `st.container(border=True, key="cad_secao_...")` e as linhas são widgets. `destaque`: `rotulo`, `valor`,
    `detalhe` opcional e `tom`. Textos escapados."""

    kicker_html = f'<div class="cad-cartao-kicker">{escape(kicker)}</div>' if kicker else ""
    desc_html = f'<div class="cad-cartao-desc">{escape(descricao)}</div>' if descricao else ""
    destaque_html = ""
    if destaque:
        detalhe = f'<div class="cad-cartao-detalhe">{escape(destaque["detalhe"])}</div>' if destaque.get("detalhe") else ""
        destaque_html = (
            '<div class="cad-cartao-destaque">'
            f'<div class="cad-cartao-rotulo">{escape(destaque.get("rotulo", ""))}</div>'
            f'<div class="cad-cartao-valor {_tom_valido(destaque.get("tom"))}">{escape(destaque.get("valor", ""))}</div>'
            f"{detalhe}</div>"
        )
    return (
        f'<div class="cad-cartao-topo"><div class="cad-cartao-texto">{kicker_html}'
        f'<div class="cad-cartao-titulo">{escape(titulo)}</div>{desc_html}</div>{destaque_html}</div>'
    )


def cartao_secao(
    titulo: str,
    descricao: str | None,
    destaque: dict[str, str] | None,
    corpo_html: str,
    kicker: str | None = None,
) -> str:
    """Cartão branco arredondado de uma seção analítica: `topo_secao` + o corpo (normalmente `tabela_html`).
    Textos do topo escapados; `corpo_html` entra como está."""

    return f'<div class="cad-cartao">{topo_secao(titulo, descricao, destaque, kicker)}{corpo_html}</div>'


def celula_saldo(
    saldo: object,
    rotulo_positivo: str = "Sobra",
    rotulo_negativo: str = "Insuficiência",
    vazio: str = "sem NE",
) -> str:
    """Saldo com o valor colorido e, embaixo, o chip do que ele significa: "Sobra" (saldo ≥ 0: ainda há espaço
    no empenho) ou "Insuficiência" (saldo < 0: o liquidado passou do empenhado). Nulo mostra `vazio` (ex.:
    contrato sem NE), nunca "Sobra"; zero é "Sobra" com R$ 0,00."""

    if _eh_nulo(saldo):
        return celula_valor(None, vazio=vazio)
    positivo = float(saldo) >= 0
    return (
        '<div class="cad-saldo">'
        f'{celula_valor(saldo, "ok" if positivo else "bad")}'
        f'{chip(rotulo_positivo if positivo else rotulo_negativo, "ok" if positivo else "bad")}'
        "</div>"
    )


def _tom_do_saldo(saldo: object) -> str | None:
    return None if _eh_nulo(saldo) else ("ok" if float(saldo) >= 0 else "bad")


def cartao_cobertura_ptres(codigo: object, nome: object, grupo: pd.DataFrame) -> str:
    """Cartão de UMA Ação de Governo na "Cobertura Orçamentária por PTRES": uma linha por Plano
    Orçamentário/PTRES (dotação atualizada × despesa estimada anual do cadastro) e o saldo (dotação −
    despesa) em destaque — verde se sobra, vermelho se falta. `grupo`: `plano_orcamentario_descricao`,
    `plano_orcamentario_codigo`, `ptres_codigo`, `dotacao_atualizada`, `despesa_estimada` e `saldo`. PTRES
    sem dotação encontrada mostra "sem dotação" (nulo, não zero) e fica fora da soma do saldo. As linhas
    saem das mais deficitárias para as mais folgadas, como no quadro anterior."""

    linhas = []
    for _, linha in grupo.sort_values("saldo", ascending=True).iterrows():
        descricao = "(não informado)" if _eh_nulo(linha["plano_orcamentario_descricao"]) else linha["plano_orcamentario_descricao"]
        codigo_po = "—" if _eh_nulo(linha["plano_orcamentario_codigo"]) else linha["plano_orcamentario_codigo"]
        linhas.append([
            celula_principal(descricao, f"PO {codigo_po}"),
            celula_suave(linha["ptres_codigo"]),
            celula_valor(linha["dotacao_atualizada"], vazio="sem dotação"),
            celula_valor(linha["despesa_estimada"]),
            celula_valor(linha["saldo"], _tom_do_saldo(linha["saldo"])),
        ])

    dotacao_total = grupo["dotacao_atualizada"].sum(min_count=1)
    despesa_total = grupo["despesa_estimada"].sum()
    saldo_total = grupo["saldo"].sum(min_count=1)
    tom_total = _tom_do_saldo(saldo_total)
    rodape = [
        '<div class="cad-total-rotulo">Total da ação</div>', "",
        celula_valor(dotacao_total, vazio="sem dotação"), celula_valor(despesa_total),
        celula_valor(saldo_total, tom_total, vazio="sem dotação"),
    ]
    tabela = tabela_html(
        [("Plano orçamentário", False), ("PTRES", False), ("Dotação atualizada", True), ("Despesa estimada", True), ("Saldo", True)],
        linhas, [3.0, 0.9, 1.3, 1.3, 1.3], rodape,
    )
    return cartao_secao(
        "—" if _eh_nulo(nome) else str(nome),
        None,
        {
            "rotulo": "Saldo (Dotação − Despesa estimada)",
            "valor": "sem dotação" if _eh_nulo(saldo_total) else formatar_brl(saldo_total),
            "detalhe": f"{len(grupo)} PTRES",
            "tom": tom_total or "neutro",
        },
        tabela,
        kicker=f"AÇÃO DE GOVERNO {'—' if _eh_nulo(codigo) else codigo}",
    )


def contagens_por_aba(mascaras: dict[str, pd.Series]) -> dict[str, int]:
    """Quantos registros cada aba de situação tem (uma máscara booleana por aba; abas podem se
    sobrepor, como "Ativo" e "Necessita reforço")."""

    return {rotulo: int(mascara.fillna(False).astype(bool).sum()) for rotulo, mascara in mascaras.items()}


def ordenar_por(dataframe: pd.DataFrame, coluna: str, crescente: bool = True) -> pd.DataFrame:
    """Ordena sem alterar a entrada: texto sem diferenciar maiúsculas, nulo sempre por último, ordem
    estável. Coluna ausente devolve o DataFrame como veio."""

    if coluna not in dataframe.columns or dataframe.empty:
        return dataframe
    serie = dataframe[coluna]
    if pd.api.types.is_numeric_dtype(serie):
        chave = serie
    else:
        chave = serie.map(lambda v: None if _eh_nulo(v) else str(v).casefold())
    return dataframe.assign(_chave_ordem=chave).sort_values(
        "_chave_ordem", ascending=crescente, na_position="last", kind="stable"
    ).drop(columns="_chave_ordem")


def css() -> str:
    """Folha de estilo (`<style>`) dos componentes `cad-*`, com os tokens do sistema. As linhas do
    registro são `st.container(key="cad_linha_…")`; o cartão do registro é `key="cad_registro"`."""

    return f"""
<style>
.cad-resumo {{ background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 24px;
    padding: 26px 30px 24px; margin: 6px 0 22px; box-shadow: 0 1px 2px rgba(11,53,87,0.04); }}
.cad-resumo-titulo {{ font-family: {FONT_HEADING}; font-size: 20px; font-weight: 600; color: {TEXT}; }}
.cad-resumo-desc {{ font-size: 13.5px; color: {TEXT_FAINT}; margin: 2px 0 18px; }}
.cad-faixa {{ display: flex; align-items: center; gap: 16px; border-radius: 16px; padding: 18px 22px;
    margin-bottom: 16px; border: 2px solid transparent; }}
.cad-faixa.warn {{ background: {WARNING_SOFT}; border-color: rgba(201,106,0,0.35); color: {WARNING}; }}
.cad-faixa.bad {{ background: {NEGATIVE_SOFT}; border-color: rgba(210,10,22,0.35); color: {NEGATIVE}; }}
.cad-faixa.ok {{ background: {POSITIVE_SOFT}; border-color: rgba(10,143,61,0.35); color: {POSITIVE}; }}
.cad-faixa.info, .cad-faixa.neutro {{ background: {ACCENT_SOFT}; border-color: rgba(9,105,218,0.30); color: {ACCENT}; }}
.cad-bola {{ width: 34px; height: 34px; border-radius: 50%; flex: 0 0 34px; background: currentColor;
    box-shadow: inset -4px -5px 8px rgba(0,0,0,0.18); }}
.cad-faixa-rotulo {{ font-size: 15px; font-weight: 600; }}
.cad-faixa-valor {{ font-family: {FONT_HEADING}; font-size: 30px; font-weight: 700; line-height: 1.2;
    font-variant-numeric: tabular-nums; }}
.cad-faixa-detalhe {{ margin-left: auto; text-align: right; font-size: 13.5px; max-width: 46%; }}
.cad-tiles {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }}
.cad-tile {{ border: 1px solid {BORDER_SOFT}; border-radius: 16px; padding: 14px 18px; background: {SURFACE}; }}
.cad-tile-rotulo {{ font-size: 13.5px; color: {TEXT_FAINT}; }}
.cad-tile-valor {{ font-family: {FONT_HEADING}; font-size: 19px; font-weight: 700; color: {TEXT};
    margin-top: 4px; font-variant-numeric: tabular-nums; }}
@media (max-width: 900px) {{ .cad-tiles {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .cad-faixa {{ flex-wrap: wrap; }} .cad-faixa-detalhe {{ max-width: 100%; margin-left: 0; text-align: left; }} }}
@media (max-width: 560px) {{ .cad-tiles {{ grid-template-columns: 1fr; }} }}

.cad-secao-titulo {{ font-family: {FONT_HEADING}; font-size: 22px; font-weight: 600; color: {TEXT}; margin: 18px 0 4px; }}
.cad-secao-desc {{ font-size: 13.5px; color: {TEXT_FAINT}; margin: 0 0 10px; }}
.st-key-cad_registro, [class*="st-key-cad_secao_"] {{ background: {SURFACE}; border: 1px solid {BORDER_SOFT} !important; border-radius: 22px !important;
    padding: 14px 18px 10px !important; box-shadow: 0 1px 2px rgba(11,53,87,0.04); }}
.cad-contagem {{ text-align: right; font-size: 13.5px; color: {TEXT_FAINT}; padding-top: 8px; font-variant-numeric: tabular-nums; }}
.cad-cabecalho {{ font-size: 11.5px; letter-spacing: 0.08em; text-transform: uppercase; color: {TEXT_MUTED};
    font-weight: 600; padding: 4px 0 8px; }}
.cad-cabecalho.direita {{ text-align: right; }}
[class*="st-key-cad_linha_"] {{ border-top: 1px solid {BORDER_SOFT}; padding: 12px 0; }}
[class*="st-key-cad_linha_"]:hover {{ background: {SURFACE_ALT}; }}
[class*="st-key-cad_linha_"] [data-testid="stHorizontalBlock"] {{ align-items: center; }}
.cad-principal {{ min-width: 0; }}
.cad-tit {{ font-size: 15.5px; font-weight: 600; color: {TEXT}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.cad-sub {{ font-size: 13px; color: {TEXT_FAINT}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.cad-cat {{ display: flex; align-items: center; gap: 8px; font-size: 14px; color: {TEXT_MUTED}; }}
.cad-cat i {{ width: 9px; height: 9px; border-radius: 50%; background: {TEXT_FAINT}; flex: 0 0 9px; }}
.cad-valor {{ text-align: right; font-size: 15px; font-weight: 700; color: {TEXT}; font-variant-numeric: tabular-nums; }}
.cad-valor.warn {{ color: {WARNING}; }} .cad-valor.bad {{ color: {NEGATIVE}; }} .cad-valor.ok {{ color: {POSITIVE}; }}
.cad-suave {{ font-size: 14px; color: {TEXT_MUTED}; font-variant-numeric: tabular-nums; }}
.cad-chip {{ display: inline-flex; align-items: center; gap: 7px; border-radius: 999px; padding: 4px 12px 4px 10px;
    font-size: 13.5px; font-weight: 600; font-family: {FONT_BODY}; }}
.cad-chip i {{ width: 8px; height: 8px; border-radius: 50%; background: currentColor; }}
.cad-chip.ok {{ background: {POSITIVE_SOFT}; color: {POSITIVE} !important; }}
.cad-chip.warn {{ background: {WARNING_SOFT}; color: {WARNING} !important; }}
.cad-chip.bad {{ background: {NEGATIVE_SOFT}; color: {NEGATIVE} !important; }}
.cad-chip.info {{ background: {ACCENT_SOFT}; color: {ACCENT} !important; }}
.cad-chip.neutro {{ background: rgba(82,101,132,0.12); color: {TEXT_MUTED} !important; }}
[class*="st-key-cad_acoes_"] button {{ border-radius: 10px; min-height: 34px; padding: 0 8px; }}
.st-key-cad_novo button {{ border-radius: 14px; font-weight: 600; min-height: 46px; }}
/* Abas de situação (`st.segmented_control` com key `cad_abas_*`): o tema global deixa todas as opções iguais
   (comentário em `src/ui_theme.py`); nesta versão do Streamlit cada opção expõe `aria-checked`, o que permite
   destacar a ATIVA — fundo escuro e texto branco, como na referência. */
[class*="st-key-cad_abas"] [data-testid="stButtonGroup"] {{ background: {SURFACE_ALT} !important; border: 1px solid {BORDER_SOFT} !important;
    border-radius: 14px !important; padding: 3px; gap: 2px; }}
[class*="st-key-cad_abas"] [data-testid="stButtonGroup"] button {{ background: transparent !important; border: 0 !important;
    border-radius: 11px !important; padding: 6px 14px; font-weight: 600; }}
[class*="st-key-cad_abas"] [data-testid="stButtonGroup"] button[aria-checked="true"] {{ background: {TEXT} !important; }}
[class*="st-key-cad_abas"] [data-testid="stButtonGroup"] button[aria-checked="true"] * {{ color: #FFFFFF !important; }}
/* o tema uniformiza os rótulos de texto/número/seleção, mas não os de data: dentro das janelas, todos iguais */
[data-testid="stDialog"] [data-testid="stDateInput"] [data-testid="stWidgetLabel"] p {{ color: {TEXT_MUTED} !important;
    font-size: 0.68rem; font-weight: 750; letter-spacing: 0.045em; text-transform: uppercase; }}
.cad-chip {{ white-space: nowrap; }}
/* a bolinha herda `color`, que o tema sobrescreve dentro das janelas: cor explícita por tom */
.cad-chip.ok i {{ background: {POSITIVE} !important; }} .cad-chip.warn i {{ background: {WARNING} !important; }}
.cad-chip.bad i {{ background: {NEGATIVE} !important; }} .cad-chip.info i {{ background: {ACCENT} !important; }}
.cad-chip.neutro i {{ background: {TEXT_MUTED} !important; }}
/* Seções analíticas (Resumo Consolidado, Empenhado × Liquidado, Cobertura por PTRES): cartão + tabela */
.cad-cartao {{ background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 22px; padding: 20px 24px 14px;
    margin: 6px 0 18px; box-shadow: 0 1px 2px rgba(11,53,87,0.04); }}
.cad-cartao-topo {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; margin-bottom: 10px; }}
.cad-cartao-texto {{ min-width: 0; }}
.cad-cartao-kicker {{ font-size: 11.5px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 700; color: {ACCENT}; }}
.cad-cartao-titulo {{ font-family: {FONT_HEADING}; font-size: 20px; font-weight: 600; color: {TEXT}; line-height: 1.25; }}
.cad-cartao-desc {{ font-size: 13.5px; color: {TEXT_FAINT}; margin-top: 2px; }}
.cad-cartao-destaque {{ text-align: right; flex: 0 0 auto; }}
.cad-cartao-rotulo {{ font-size: 13px; color: {TEXT_FAINT}; }}
.cad-cartao-valor {{ font-family: {FONT_HEADING}; font-size: 26px; font-weight: 700; line-height: 1.2; font-variant-numeric: tabular-nums; color: {TEXT}; }}
.cad-cartao-valor.ok {{ color: {POSITIVE}; }} .cad-cartao-valor.bad {{ color: {NEGATIVE}; }} .cad-cartao-valor.warn {{ color: {WARNING}; }}
.cad-cartao-valor.info {{ color: {ACCENT}; }}
.cad-cartao-detalhe {{ font-size: 13px; color: {TEXT_FAINT}; margin-top: 2px; }}
.cad-tabela {{ overflow-x: auto; }}
.cad-tabela-cab, .cad-tabela-linha, .cad-tabela-rodape {{ display: grid; grid-template-columns: var(--cad-cols); gap: 14px;
    align-items: center; min-width: 640px; }}
.cad-tabela-cab {{ padding: 6px 4px 8px; }}
.cad-tabela-rotulo {{ font-size: 11.5px; letter-spacing: 0.08em; text-transform: uppercase; color: {TEXT_MUTED}; font-weight: 600; }}
.cad-tabela-rotulo.direita {{ text-align: right; }}
.cad-tabela-linha {{ border-top: 1px solid {BORDER_SOFT}; padding: 11px 4px; }}
.cad-tabela-linha:hover {{ background: {SURFACE_ALT}; }}
.cad-tabela-rodape {{ border-top: 2px solid {BORDER}; padding: 12px 4px 4px; }}
.cad-total-rotulo {{ font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED}; font-weight: 700; }}
.cad-valor.vazio {{ font-weight: 500; color: {TEXT_FAINT}; }}
.cad-saldo {{ display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }}
/* Resumo Consolidado: linhas com botão (`st.columns`) — linha de total e caixa com rolagem da Bolsas */
[class*="st-key-cad_total_"] {{ border-top: 2px solid {BORDER}; padding: 12px 0 4px; }}
[class*="st-key-cad_total_"] [data-testid="stHorizontalBlock"] {{ align-items: center; }}
.st-key-bls_resumo_scroll, .st-key-cc_resumo_scroll {{ max-height: 380px; overflow-y: auto; padding-right: 8px; }}
/* mesma largura mínima das linhas: no celular a tabela inteira rola para o lado junto, não só o corpo */
.cad-tabela-rolagem {{ max-height: 380px; overflow-y: auto; min-width: 640px; }}
.st-key-cc_registro_scroll, .st-key-bls_registro_scroll {{ max-height: 640px; overflow-y: auto; padding-right: 8px; }}
.cad-vazio {{ text-align: center; color: {TEXT_FAINT}; padding: 28px 0; border-top: 1px solid {BORDER_SOFT}; }}

.cad-secao-dialogo {{ font-family: {FONT_HEADING}; font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase;
    color: {TEXT_MUTED}; font-weight: 700; margin: 18px 0 6px; border-bottom: 1px solid {BORDER}; padding-bottom: 5px; }}
</style>
"""
