"""Relatório do Resultado Orçamentário (pedido do usuário, 22/10/2026): um HTML de uma folha A4, pronto para imprimir ou salvar em PDF.

Protótipo aprovado: `docs/superpowers/specs/2026-10-22-resultado-orcamentario-relatorio-mockup.html`. Seções: 1 Resumo, 2 Composição,
3 Detalhamento por GND, Ação e Fonte, 4 Receitas próprias arrecadadas, 5 Outras despesas previstas e, quando informada, 6 Discricionário
(RP2) por Plano Orçamentário (29/10/2026). Avisos, lista de células e
rastreabilidade das extrações ficaram de fora por decisão do usuário.

Camada: apresentação pura. Recebe o `ResultadoOrcamentario`, o `DetalheGndAcao` e os cadastros já carregados; não lê arquivo, não
importa Streamlit e não recalcula regra — só repete os números que a página mostra, para o relatório e a tela fecharem entre si. Nulo
continua "—" (nunca R$ 0,00) e todo texto vindo de cadastro é escapado.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from src import design_tokens as dt
from src.resultado_orcamentario import (
    ORIGENS_CONSUMO,
    ORIGENS_EMPENHADO,
    OUTRAS_DESPESAS,
    ROTULO_CELULA_RECEITA,
    ResultadoOrcamentario,
)
from src.resultado_orcamentario_cadastro import CHAVE_CELULA, DespesaManual, ReceitaPropria
from src.resultado_orcamentario_detalhe import TIPO_CELULA, TIPO_FORA, TIPO_SEM_CELULA, DetalheGndAcao
from src.resultado_orcamentario_planos import LinhaAvulsa, PlanosDiscricionarios, QuadroPlano
from src.ui_resultado_orcamentario import _txt, brl, percentual, situacao_resultado

_IDX_ACAO = CHAVE_CELULA.index("acao_codigo")
_IDX_GND = CHAVE_CELULA.index("grupo_despesa_codigo")
_IDX_FONTE = CHAVE_CELULA.index("fonte_recursos_detalhada_codigo")
_TOLERANCIA_EXCEDENTE = 0.004
_CLASSE_FORA = ' class="extra"'  # lançamento desconsiderado: linha em itálico

ESTILO = f"""
<style>
:root{{--bg:#E9EEF5;--paper:#fff;--alt:{dt.SURFACE_ALT};--border:{dt.BORDER};--text:{dt.TEXT};--muted:{dt.TEXT_MUTED};
  --faint:{dt.TEXT_FAINT};--accent:{dt.ACCENT};--accent-soft:{dt.ACCENT_SOFT};--pos:{dt.POSITIVE};--neg:{dt.NEGATIVE};
  --pos-soft:{dt.POSITIVE_SOFT};--neg-soft:{dt.NEGATIVE_SOFT};--mono:ui-monospace,"Cascadia Mono",Consolas,monospace}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:"Inter","Segoe UI",system-ui,sans-serif;font-size:12.5px;
  line-height:1.45;padding:20px 12px 48px}}
.barra{{max-width:210mm;margin:0 auto 12px;display:flex;justify-content:space-between;align-items:center;gap:12px;color:var(--muted);font-size:12px}}
.barra button{{font:inherit;font-weight:600;color:#fff;background:var(--accent);border:0;border-radius:8px;padding:7px 14px;cursor:pointer}}
.folha{{max-width:210mm;margin:0 auto;background:var(--paper);box-shadow:0 2px 14px rgba(7,19,61,.14);padding:16mm 15mm 14mm}}
header.rel{{display:flex;justify-content:space-between;gap:16px;border-bottom:3px solid var(--accent);padding-bottom:10px;margin-bottom:14px}}
header.rel h1{{font-size:19px;margin:0 0 2px}} header.rel .sub{{color:var(--muted);font-size:12px}}
header.rel .meta{{text-align:right;font-size:11.5px;color:var(--muted);white-space:nowrap}} header.rel .meta b{{color:var(--text)}}
h2{{font-size:13.5px;margin:18px 0 6px;padding-bottom:3px;border-bottom:1px solid var(--border);display:flex;gap:8px;align-items:baseline}}
h2 .n{{color:var(--accent);font-family:var(--mono);font-size:12px}}
p.nota{{color:var(--muted);font-size:11.5px;margin:2px 0 8px}}
.cartoes{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}
.card{{border:1px solid var(--border);border-radius:10px;padding:9px 11px;background:var(--paper)}}
.card .l{{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}}
.card .v{{font-family:var(--mono);font-size:15px;font-weight:700;margin:3px 0 2px;white-space:nowrap}}
.card .f{{font-size:10.5px;color:var(--faint)}}
.card.res.pos{{border-color:var(--pos);background:var(--pos-soft)}} .card.res.pos .v{{color:var(--pos)}}
.card.res.neg{{border-color:var(--neg);background:var(--neg-soft)}} .card.res.neg .v{{color:var(--neg)}}
.selo{{font-size:10px;font-weight:700;color:#fff;border-radius:5px;padding:0 6px;margin-left:4px;vertical-align:middle;background:var(--faint)}}
.selo.pos{{background:var(--pos)}} .selo.neg{{background:var(--neg)}}
.formula{{margin-top:8px;padding:7px 11px;background:var(--alt);border-radius:8px;font-family:var(--mono);font-size:11.5px;color:var(--muted)}}
.duas{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
table{{width:100%;border-collapse:collapse;font-size:11.5px}}
th{{background:var(--alt);color:var(--muted);font-weight:600;text-align:left;padding:5px 7px;border-bottom:1px solid var(--border)}}
td{{padding:4px 7px;border-bottom:1px solid #E7EEF6;vertical-align:top}}
th.n,td.n{{text-align:right;font-family:var(--mono);white-space:nowrap}}
tr.grupo td{{font-weight:700;background:#FAFCFE}} tr.sub td:first-child{{padding-left:20px}}
tr.alvo td{{background:var(--accent-soft)}} tr.extra td{{font-style:italic;color:var(--muted)}}
tr.tot td{{font-weight:700;border-top:2px solid var(--border);border-bottom:0;background:var(--alt)}}
.cod{{font-family:var(--mono);font-size:10.5px;color:var(--muted);margin-right:6px}}
.fonte{{display:inline-block;margin-left:6px;padding:0 6px;border-radius:5px;font-size:10px;font-weight:600;background:var(--alt);
  border:1px solid var(--border);color:var(--muted);white-space:nowrap}}
.fonte.f1050{{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}}
.rec{{display:block;font-size:10px;font-weight:400;color:var(--accent);line-height:1.3;margin-top:3px;white-space:normal}}
table.det{{table-layout:fixed}} table.det td:first-child{{overflow-wrap:anywhere}}
table.det th,table.det td{{padding:4px 4px}} table.det td.n,table.det th.n{{font-size:10px}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
.selo.pos,.selo.neg{{color:#fff}}
.bar{{display:inline-block;width:44px;height:5px;border-radius:3px;background:var(--alt);position:relative;overflow:hidden;vertical-align:middle;margin-right:5px}}
.bar i{{position:absolute;left:0;top:0;bottom:0;background:var(--accent)}} .bar i.acima{{background:var(--neg)}}
.ok{{color:var(--pos);font-size:11px;margin-top:5px}} .erro{{color:var(--neg);font-size:11px;margin-top:5px}}
footer.rel{{margin-top:18px;padding-top:8px;border-top:1px solid var(--border);display:flex;justify-content:space-between;color:var(--faint);font-size:10.5px}}
@media screen and (max-width:760px){{.cartoes{{grid-template-columns:1fr 1fr}}.duas{{grid-template-columns:1fr}}.folha{{padding:12px}}
  header.rel{{flex-direction:column}}header.rel .meta{{text-align:left}}table{{display:block;overflow-x:auto}}}}
@media print{{*{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
  body{{background:#fff;padding:0;font-size:10.5px}}.barra{{display:none}}.folha{{box-shadow:none;max-width:none;width:100%;padding:0}}
  @page{{size:A4;margin:12mm 10mm}}tr{{page-break-inside:avoid}}h2{{page-break-after:avoid}}.quebra{{page-break-before:always}}
  table{{font-size:9.5px}}th,td{{padding:3px 4px}}td.n,th.n{{font-size:9px}}table.det td.n,table.det th.n{{font-size:8.5px}}.card .v{{font-size:12.5px}}.card{{padding:7px 8px}}
  .cartoes{{gap:6px}}.duas{{gap:10px}}}}
</style>
"""


def _valor(v: object) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def _soma(serie: pd.Series) -> float | None:
    """Soma que mantém nulo (nulo não vira zero); série vazia = 0."""

    valores = serie.astype("float64")
    return None if valores.isna().any() else float(valores.sum())


def _classe_valor(v: float | None) -> str:
    return "" if v is None or v == 0 else (" pos" if v > 0 else " neg")


def _celula(v: object, classe: str = "n") -> str:
    return f'<td class="{classe}">{brl(_valor(v))}</td>'


def _resultado_celula(v: float | None) -> str:
    return f'<td class="n{_classe_valor(v)}">{brl(v)}</td>'


def _consumo(executado: float | None, projetado: float | None, dotacao: float | None) -> str:
    if executado is None or projetado is None or dotacao is None:
        return "<td>—</td>"
    usado = (executado + projetado) / dotacao * 100 if dotacao else None
    barra = (
        f'<span class="bar"><i class="{"acima" if usado > 100 else ""}" style="width:{min(max(usado, 0), 100):.1f}%"></i></span>'
        if usado is not None else ""
    )
    return f"<td>{barra}{_txt(percentual(executado + projetado, dotacao))}</td>"


def _rotulo_celula(chave: tuple | None) -> str:
    if not chave:
        return "—"
    partes = [str(chave[_IDX_ACAO]), f"GND {chave[_IDX_GND]}"]
    if chave[_IDX_FONTE] is not None:
        partes.append(f"fonte {chave[_IDX_FONTE]}")
    return " · ".join(partes)


# --------------------------------------------------------------------------------- seções
def _secao_resumo(res: ResultadoOrcamentario, qtd_marcadas: int, qtd_celulas: int, nota_dotacao: str) -> str:
    classe, selo = situacao_resultado(res.resultado)
    pct = percentual(res.resultado, res.dotacao) if res.resultado is not None else "—"
    rodape = f"{pct} da dotação selecionada" if res.resultado is not None else "Resultado incompleto"
    cartoes = [
        ("Dotação atualizada", res.dotacao, f"{qtd_marcadas} de {qtd_celulas} células{nota_dotacao}"),
        ("(−) Executado nas células", res.executado_total, "Contratos e Bolsas: liquidado · demais: empenhado"),
        ("(−) Projetado a realizar", res.projetado_total, "Contratos + Bolsas + outras previstas"),
    ]
    partes = [
        f'<div class="card"><div class="l">{_txt(r)}</div><div class="v">{brl(v)}</div><div class="f">{_txt(f)}</div></div>'
        for r, v, f in cartoes
    ]
    partes.append(
        f'<div class="card res {classe}"><div class="l">Resultado <span class="selo {classe}">{_txt(selo)}</span></div>'
        f'<div class="v">{brl(res.resultado)}</div><div class="f">{_txt(rodape)}</div></div>'
    )
    return (
        '<h2><span class="n">1</span>Resumo</h2><div class="cartoes">' + "".join(partes) + "</div>"
        '<div class="formula">Resultado = Dotação (a da fonte 1050/20RK limitada pela arrecadação própria) − Executado − '
        "Projetado a realizar</div>"
    )


def _tabela_composicao(titulo: str, linhas: list[tuple[str, float | None]], total: float | None, rotulo_total: str) -> str:
    corpo = "".join(
        f'<tr><td>{_txt(rotulo)}</td><td class="n">{brl(valor)}</td><td class="n">{_txt(percentual(valor, total))}</td></tr>'
        for rotulo, valor in linhas
    )
    return (
        f'<table><thead><tr><th>{_txt(titulo)}</th><th class="n">Valor</th><th class="n">%</th></tr></thead><tbody>{corpo}'
        f'<tr class="tot"><td>{_txt(rotulo_total)}</td><td class="n">{brl(total)}</td><td class="n">'
        f'{"100%" if total else "—"}</td></tr></tbody></table>'
    )


def _secao_composicao(res: ResultadoOrcamentario) -> str:
    executado = [
        (origem, res.executado.get(origem) if origem in ORIGENS_CONSUMO else res.empenhado.get(origem))
        for origem in ORIGENS_EMPENHADO
    ]
    projetado = list(res.projetado.items())
    return (
        '<h2><span class="n">2</span>Composição</h2><div class="duas">'
        + _tabela_composicao("Executado nas células", executado, res.executado_total, "Total executado")
        + _tabela_composicao("Projetado a realizar até dezembro", projetado, res.projetado_total, "Total projetado")
        + "</div>"
    )


def _nota_excedente(linha: pd.Series) -> str:
    limite, excedente = _valor(linha.get("receita_limite")), _valor(linha.get("receita_excedente"))
    if limite is None or excedente is None or excedente <= _TOLERANCIA_EXCEDENTE:
        return ""
    return (
        f'<span class="rec">limitada pela arrecadação própria: informado {brl(limite)} · {brl(excedente)} acima da '
        "dotação ficam fora</span>"
    )


def _secao_detalhamento(detalhe: DetalheGndAcao) -> str:
    linhas = detalhe.linhas
    celulas = linhas.loc[linhas["tipo"] == TIPO_CELULA]
    corpo: list[str] = []
    for gnd, grupo in celulas.groupby("gnd", sort=True):
        dot, exe, prj = _soma(grupo["dotacao"]), _soma(grupo["executado"]), _soma(grupo["projetado"])
        res_grupo = None if dot is None or exe is None or prj is None else dot - exe - prj
        descricao = grupo.iloc[0].get("gnd_descricao")
        corpo.append(
            f'<tr class="grupo"><td><span class="cod">GND {_txt(gnd)}</span>{_txt("" if pd.isna(descricao) else descricao)}</td>'
            f'{_celula(dot)}{_celula(exe)}{_celula(prj)}{_resultado_celula(res_grupo)}{_consumo(exe, prj, dot)}</tr>'
        )
        for _, r in grupo.sort_values(["acao", "fonte"]).iterrows():
            fonte = r.get("fonte")
            e1050 = fonte is not None and not pd.isna(fonte) and str(fonte).startswith("1050")
            desc_fonte = r.get("fonte_descricao")
            texto_fonte = f"Fonte {fonte}" + (f" · {desc_fonte}" if e1050 and desc_fonte and not pd.isna(desc_fonte) else "")
            etiqueta = (
                f'<span class="fonte{" f1050" if e1050 else ""}">{_txt(texto_fonte)}</span>'
                if fonte is not None and not pd.isna(fonte) else ""
            )
            desc_acao = r.get("acao_descricao")
            dot_r, exe_r, prj_r = _valor(r["dotacao"]), _valor(r["executado"]), _valor(r["projetado"])
            corpo.append(
                f'<tr class="sub{" alvo" if e1050 else ""}"><td><span class="cod">{_txt(r["acao"])}</span>'
                f'{_txt("" if desc_acao is None or pd.isna(desc_acao) else desc_acao)}{etiqueta}{_nota_excedente(r)}</td>'
                f'<td class="n">{brl(dot_r)}</td>{_celula(exe_r)}{_celula(prj_r)}'
                f'{_resultado_celula(_valor(r["resultado"]))}{_consumo(exe_r, prj_r, dot_r)}</tr>'
            )
    for tipo, rotulo in (
        (TIPO_FORA, "Fora das células marcadas (parte de NE em célula não marcada)"),
        (TIPO_SEM_CELULA, "Sem célula (outras despesas previstas e contratos ativos sem NE)"),
    ):
        for _, r in linhas.loc[linhas["tipo"] == tipo].iterrows():
            corpo.append(
                f'<tr class="extra"><td>{_txt(rotulo)}</td>{_celula(r["dotacao"])}{_celula(r["executado"])}'
                f'{_celula(r["projetado"])}{_resultado_celula(_valor(r["resultado"]))}<td>—</td></tr>'
            )
    corpo.append(
        f'<tr class="tot"><td>Total do bolsão</td>{_celula(detalhe.dotacao)}{_celula(detalhe.executado)}{_celula(detalhe.projetado)}'
        f'{_resultado_celula(detalhe.resultado)}{_consumo(detalhe.executado, detalhe.projetado, detalhe.dotacao)}</tr>'
    )
    if not len(linhas):
        corpo.insert(0, '<tr class="extra"><td colspan="6">Nenhuma célula marcada.</td></tr>')
    conferencia = (
        f'<div class="ok">✓ A soma das linhas confere com os cartões · diferença {brl(round(detalhe.diferenca_conferencia, 2) + 0.0)}</div>'
        if detalhe.fecha else
        f'<div class="erro">✗ A soma das linhas não fecha com os cartões · diferença {brl(round(detalhe.diferenca_conferencia, 2) + 0.0)}</div>'
    )
    return (
        '<h2><span class="n">3</span>Detalhamento por GND, Ação e Fonte</h2>'
        '<p class="nota">Cada linha indica a sua fonte; a fonte 1050 aparece em linha própria.</p>'
        '<table class="det"><colgroup><col style="width:25%"><col style="width:16%"><col style="width:16%"><col style="width:16%">'
        '<col style="width:16%"><col style="width:11%"></colgroup>'
        '<thead><tr><th>Grupo</th><th class="n">Dotação atualizada</th><th class="n">Executado</th>'
        '<th class="n">Projetado</th><th class="n">Resultado</th><th>Consumo</th></tr></thead><tbody>'
        + "".join(corpo) + "</tbody></table>" + conferencia
    )


def _secao_receitas(res: ResultadoOrcamentario, receitas: list[ReceitaPropria]) -> str:
    cabecalho = (
        '<h2 class="quebra"><span class="n">4</span>Receitas próprias arrecadadas</h2>'
        f'<p class="nota">Informadas à mão. A soma dos lançamentos considerados limita a dotação da célula {_txt(ROTULO_CELULA_RECEITA)} '
        "(o menor entre a dotação e a arrecadação); não soma dotação por fora.</p>"
    )
    if not receitas:
        return cabecalho + '<p class="nota">Nenhuma receita própria cadastrada para este exercício.</p>'
    linhas = "".join(
        f'<tr{_CLASSE_FORA if not r.considerada else ""}><td>{_txt(r.descricao)}</td><td>{_txt(r.observacao or "—")}</td>'
        f'<td>{"Considerada" if r.considerada else "Desconsiderada"}</td><td class="n">{brl(r.valor)}</td></tr>'
        for r in receitas
    )
    if res.receita_limite is None:
        efeito = "Nenhum lançamento considerado: a célula da fonte 1050 conta pela dotação integral."
        resumo = ""
    else:
        efeito = None
        sem_efeito = res.receita_aplicada == 0 and res.receita_excedente == 0
        resumo = (
            '<table style="margin-top:8px"><tbody>'
            + (
                f'<tr><td>A célula {_txt(ROTULO_CELULA_RECEITA)} não está marcada: a arrecadação não tem efeito no resultado.</td></tr>'
                if sem_efeito else
                f'<tr><td>Dotação com que a célula conta (menor entre a dotação e a arrecadação)</td><td class="n">{brl(res.receita_aplicada)}</td></tr>'
                f'<tr><td>Arrecadação acima da dotação (fica fora)</td><td class="n">{brl(res.receita_excedente)}</td></tr>'
            )
            + "</tbody></table>"
        )
    return (
        cabecalho
        + '<table><thead><tr><th>Descrição</th><th>Observação</th><th>Situação</th><th class="n">Valor</th></tr></thead><tbody>'
        + linhas
        + f'<tr class="tot"><td colspan="3">Arrecadação considerada (limite)</td><td class="n">{brl(res.receita_limite)}</td></tr>'
        + "</tbody></table>"
        + (f'<p class="nota">{_txt(efeito)}</p>' if efeito else "")
        + resumo
    )


def _secao_outras_despesas(res: ResultadoOrcamentario, despesas: list[DespesaManual]) -> str:
    cabecalho = (
        f'<h2><span class="n">5</span>{_txt(OUTRAS_DESPESAS)}</h2>'
        '<p class="nota">Despesas fora de Contratos e Bolsas que ainda serão empenhadas no exercício, cadastradas à mão. '
        "Só as consideradas entram no projetado do resultado; a célula é informativa.</p>"
    )
    if not despesas:
        return cabecalho + '<p class="nota">Nenhuma despesa prevista cadastrada para este exercício.</p>'
    linhas = "".join(
        f'<tr{_CLASSE_FORA if not d.considerada else ""}><td>{_txt(d.descricao)}</td><td>{_txt(d.observacao or "—")}</td>'
        f'<td>{_txt(_rotulo_celula(d.celula))}</td><td>{"Considerada" if d.considerada else "Desconsiderada"}</td>'
        f'<td class="n">{brl(d.valor)}</td></tr>'
        for d in despesas
    )
    cadastrado = float(sum(d.valor for d in despesas))
    fora = float(sum(d.valor for d in despesas if not d.considerada))
    return (
        cabecalho
        + '<table><thead><tr><th>Descrição</th><th>Observação</th><th>Célula (informativa)</th><th>Situação</th>'
        '<th class="n">Valor</th></tr></thead><tbody>' + linhas
        + f'<tr class="tot"><td colspan="4">Considerado no resultado (projetado)</td><td class="n">{brl(res.projetado.get(OUTRAS_DESPESAS))}</td></tr>'
        "</tbody></table>"
        '<table style="margin-top:8px"><tbody>'
        f'<tr><td>Total cadastrado</td><td class="n">{brl(cadastrado)}</td></tr>'
        f'<tr><td>Desconsiderado (fora da conta do resultado)</td><td class="n">{brl(fora)}</td></tr></tbody></table>'
    )


def _soma_ou_nulo(valores: list[float | None]) -> float | None:
    return None if any(v is None for v in valores) else float(sum(valores))


def _nota_fontes(p: QuadroPlano) -> str:
    """Fontes do plano quando ele tem mais de uma (ou quando a 1050 foi limitada pela arrecadação), com o saldo de cada uma; a nota
    da arrecadação só aparece quando o valor informado ultrapassa a dotação da célula."""

    if len(p.fontes) <= 1 and not any(f.receita_limite is not None for f in p.fontes):
        return ""
    linhas = []
    for f in p.fontes:
        e1050 = f.fonte is not None and str(f.fonte).startswith("1050")
        rotulo = f"Fonte {f.fonte}" + (f" · {f.fonte_descricao}" if e1050 and f.fonte_descricao else "")
        sinal = "" if f.saldo is None else ("+" if f.saldo >= 0 else "−")
        saldo = "—" if f.saldo is None else sinal + brl(abs(f.saldo))
        extra = ""
        if f.receita_limite is not None and f.receita_excedente > _TOLERANCIA_EXCEDENTE:
            extra = (
                f" — limitada pela arrecadação própria: informado {brl(f.receita_limite)} · {brl(f.receita_excedente)} acima da "
                "dotação ficam fora"
            )
        linhas.append(f"{_txt(rotulo)}: {saldo}{extra}")
    return '<span class="rec">' + "<br>".join(linhas) + "</span>"


def _linha_avulsa_plano(rotulo: str, linha: LinhaAvulsa) -> str:
    if linha.vazia:
        return ""
    saldo = None if linha.executado is None or linha.projetado is None else -(linha.executado + linha.projetado)
    return (
        f'<tr class="extra"><td>{_txt(rotulo)}</td>{_celula(0.0)}{_celula(linha.executado)}{_celula(linha.projetado)}'
        f"{_resultado_celula(saldo)}<td>—</td></tr>"
    )


def _secao_planos(planos: PlanosDiscricionarios) -> str:
    cabecalho = (
        '<h2 class="quebra"><span class="n">6</span>Discricionário (RP2) por Plano Orçamentário</h2>'
        '<p class="nota">Todas as células do Resultado Primário 2, marcadas ou não, com a mesma conta do resultado. Ações da maior '
        "para a menor dotação; planos com mais de uma fonte trazem o saldo de cada uma.</p>"
    )
    if not planos.planos:
        return cabecalho + '<p class="nota">Nenhuma célula do discricionário neste exercício.</p>'
    acoes: dict[str, list[QuadroPlano]] = {}
    for p in planos.planos:
        acoes.setdefault(p.acao, []).append(p)
    corpo: list[str] = []
    for acao, itens in acoes.items():
        dot = _soma_ou_nulo([p.dotacao for p in itens])
        exe = _soma_ou_nulo([p.executado for p in itens])
        prj = _soma_ou_nulo([p.projetado for p in itens])
        saldo = None if None in (dot, exe, prj) else dot - exe - prj
        descricao = next((p.acao_descricao for p in itens if p.acao_descricao), "")
        corpo.append(
            f'<tr class="grupo"><td><span class="cod">{_txt(acao)}</span>{_txt(descricao)}</td>{_celula(dot)}{_celula(exe)}'
            f"{_celula(prj)}{_resultado_celula(saldo)}{_consumo(exe, prj, dot)}</tr>"
        )
        for p in itens:
            destaque = " alvo" if any(f.receita_limite is not None for f in p.fontes) else ""
            corpo.append(
                f'<tr class="sub{destaque}"><td><span class="cod">PO {_txt(p.po)}</span>{_txt(p.po_descricao or "")}'
                f"{_nota_fontes(p)}</td>{_celula(p.dotacao)}{_celula(p.executado)}{_celula(p.projetado)}"
                f"{_resultado_celula(p.saldo)}{_consumo(p.executado, p.projetado, p.dotacao)}</tr>"
            )
    corpo.append(_linha_avulsa_plano("Fora do discricionário (parte de NE com empenho em célula que não é RP2)", planos.fora))
    corpo.append(_linha_avulsa_plano("Sem célula (outras despesas previstas e contratos ativos sem NE)", planos.sem_celula))
    corpo.append(
        f'<tr class="tot"><td>Total do discricionário</td>{_celula(planos.dotacao)}{_celula(planos.executado)}'
        f"{_celula(planos.projetado)}{_resultado_celula(planos.saldo)}{_consumo(planos.executado, planos.projetado, planos.dotacao)}</tr>"
    )
    diferenca = brl(round(planos.diferenca_conferencia, 2) + 0.0)
    conferencia = (
        f'<div class="ok">✓ A soma confere com o resultado do discricionário · diferença {diferenca}</div>' if planos.fecha
        else f'<div class="erro">✗ A soma não fecha com o resultado do discricionário · diferença {diferenca}</div>'
    )
    return (
        cabecalho
        + '<table class="det"><colgroup><col style="width:34%"><col style="width:15%"><col style="width:14%"><col style="width:14%">'
        '<col style="width:14%"><col style="width:9%"></colgroup>'
        '<thead><tr><th>Ação / Plano Orçamentário</th><th class="n">Dotação atualizada</th><th class="n">Executado</th>'
        '<th class="n">Projetado</th><th class="n">Saldo</th><th>Consumo</th></tr></thead><tbody>'
        + "".join(corpo) + "</tbody></table>" + conferencia
    )


def html_relatorio(
    res: ResultadoOrcamentario,
    detalhe: DetalheGndAcao,
    despesas: list[DespesaManual],
    receitas: list[ReceitaPropria],
    exercicio: int,
    qtd_marcadas: int,
    qtd_celulas: int,
    emitido_em: datetime,
    nota_dotacao: str = "",
    planos: PlanosDiscricionarios | None = None,
) -> str:
    """Documento HTML completo (com botão "Imprimir / PDF" que some na impressão). `nota_dotacao`: complemento do rodapé do
    cartão de dotação (ex.: fonte 1050 limitada), igual ao da tela. `planos`: quadros do discricionário por Plano Orçamentário; quando
    informado, entra a seção 6 (sem ele o relatório fica com as 5 seções)."""

    cabecalho = (
        '<header class="rel"><div><h1>Resultado Orçamentário — ' + _txt(exercicio) + '</h1><div class="sub">A dotação das '
        "células selecionadas cobre o que ainda falta executar até dezembro?</div></div>"
        f'<div class="meta"><div>Emitido em <b>{emitido_em:%d/%m/%Y %H:%M}</b></div>'
        f"<div>UFRPE BudgetLab · exercício <b>{_txt(exercicio)}</b></div>"
        f"<div><b>{qtd_marcadas}</b> de {qtd_celulas} células selecionadas</div></div></header>"
    )
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Resultado Orçamentário {_txt(exercicio)}</title>{ESTILO}</head><body>"
        '<div class="barra"><span>Folha A4 · imprima ou salve em PDF</span>'
        '<button onclick="window.print()">Imprimir / PDF</button></div><div class="folha">'
        + cabecalho
        + _secao_resumo(res, qtd_marcadas, qtd_celulas, nota_dotacao)
        + _secao_composicao(res)
        + _secao_detalhamento(detalhe)
        + _secao_receitas(res, receitas)
        + _secao_outras_despesas(res, despesas)
        + (_secao_planos(planos) if planos is not None else "")
        + f'<footer class="rel"><span>UFRPE BudgetLab · Resultado Orçamentário {_txt(exercicio)}</span>'
        "<span>valores em R$</span></footer></div></body></html>"
    )
