"""Quadros do discricionário por Plano Orçamentário (pedido do usuário, 29/10/2026).

Regra pura, só leitura e em memória: não importa Streamlit, não lê arquivo e não altera `calcular_resultado`. Para cada Plano
Orçamentário (PO) de cada Ação do **discricionário** (Resultado Primário 2) devolve a dotação, o executado, o projetado a
realizar e o saldo, na mesma conta do Resultado Orçamentário:

  * o escopo é **toda** célula do RP2, independentemente das células marcadas na página — o resultado de `res` deve ter sido
    calculado com `selecao_discricionaria(celulas)`;
  * a repartição de executado e projetado por célula é a do detalhamento por GND e Ação (`_acumular` de
    `resultado_orcamentario_detalhe`), só que agrupada por (Ação, PO), e depois por (Ação, PO, Fonte) para o detalhe de fontes;
  * a célula da fonte 1050 da 20RK já vem limitada pela arrecadação própria, como no resultado;
  * o que não tem Plano entra em duas linhas à parte, para o total fechar com o resultado: "Fora do discricionário" (parte de
    NE com empenho em célula que não é RP2, que entra inteira na conta) e "Sem célula" (despesas previstas sem célula e
    contratos ativos sem NE).

Filtros da página (30/10/2026): `filtrar_planos` recorta os quadros já calculados por Ação, Plano, Fonte e Situação; só exibição.

Nulo continua nulo: um valor indisponível deixa nulo o plano que ele alimenta (e o total), nunca vira zero. "Faixa histórica" e
"pior caso" (existem em Despesas de Pessoal) não se aplicam: não há série definida para o discricionário.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd

from src.resultado_orcamentario import TOLERANCIA_CONFERENCIA, ResultadoOrcamentario, soma_ou_nulo
from src.resultado_orcamentario_cadastro import CHAVE_CELULA, CelulaChave, DespesaManual
from src.resultado_orcamentario_detalhe import TIPO_CELULA, TIPO_FORA, TIPO_SEM_CELULA, _acumular

RESULTADO_PRIMARIO_DISCRICIONARIO = "2"

_IDX_RP = CHAVE_CELULA.index("resultado_primario_codigo")
_IDX_ACAO = CHAVE_CELULA.index("acao_codigo")
_IDX_PO = CHAVE_CELULA.index("plano_orcamentario_codigo")
_IDX_FONTE = CHAVE_CELULA.index("fonte_recursos_detalhada_codigo")


@dataclass(frozen=True)
class SaldoFonte:
    fonte: str | None
    fonte_descricao: str | None
    dotacao: float | None
    executado: float | None
    projetado: float | None
    saldo: float | None
    #: arrecadação própria informada e o que passa da dotação (só na célula da fonte 1050 da 20RK, com limite ativo)
    receita_limite: float | None = None
    receita_excedente: float = 0.0


@dataclass(frozen=True)
class QuadroPlano:
    acao: str
    acao_descricao: str | None
    po: str
    po_descricao: str | None
    dotacao: float | None
    executado: float | None
    projetado: float | None
    saldo: float | None
    fontes: tuple[SaldoFonte, ...] = ()


@dataclass(frozen=True)
class LinhaAvulsa:
    """Valores que não pertencem a um Plano do RP2 ("Fora do discricionário", "Sem célula")."""

    executado: float | None
    projetado: float | None

    @property
    def vazia(self) -> bool:
        return not (self.executado or self.projetado) and self.executado is not None and self.projetado is not None


@dataclass
class PlanosDiscricionarios:
    planos: list[QuadroPlano]
    fora: LinhaAvulsa
    sem_celula: LinhaAvulsa
    dotacao: float | None
    executado: float | None
    projetado: float | None
    saldo: float | None
    #: maior diferença absoluta entre estes totais e os do `ResultadoOrcamentario` (0,0 quando fecham)
    diferenca_conferencia: float
    avisos: list[str] = field(default_factory=list)
    #: recorte de `filtrar_planos`: totais só dos planos visíveis, sem linhas avulsas nem conferência com o resultado
    filtrado: bool = False
    #: quantos planos o discricionário tem sem filtro (só preenchido quando `filtrado`)
    planos_no_total: int | None = None

    @property
    def fecha(self) -> bool:
        return self.diferenca_conferencia < TOLERANCIA_CONFERENCIA


def selecao_discricionaria(celulas: pd.DataFrame) -> list[CelulaChave]:
    """Chaves de todas as células do Resultado Primário 2 (discricionário), na ordem da base. Sem fonte (`None`) não entra,
    como em `calcular_resultado`."""

    if not len(celulas):
        return []
    return [
        chave for chave in celulas["chave"]
        if chave[_IDX_RP] == RESULTADO_PRIMARIO_DISCRICIONARIO and chave[-1] is not None
    ]


def _descricoes(celulas: pd.DataFrame, colunas_chave: tuple[str, ...], coluna_descricao: str) -> dict[tuple, str]:
    if coluna_descricao not in celulas.columns or any(c not in celulas.columns for c in colunas_chave):
        return {}
    base = celulas.dropna(subset=[*colunas_chave, coluna_descricao])
    return {
        tuple(str(v) for v in valores): str(d)
        for *valores, d in zip(*(base[c] for c in colunas_chave), base[coluna_descricao])
    }


def _finais(balde, indisponivel: bool) -> tuple[float | None, float | None, float | None, float | None]:
    dotacao, executado, projetado = balde.final("dotacao"), balde.final("executado"), balde.final("projetado")
    if indisponivel:
        executado = projetado = None
    saldo = None if None in (dotacao, executado, projetado) else dotacao - executado - projetado
    return dotacao, executado, projetado, saldo


def planos_discricionarios(
    res: ResultadoOrcamentario,
    celulas: pd.DataFrame,
    empenhado: pd.DataFrame,
    despesas_manuais: list[DespesaManual],
    ativos_sem_ne: pd.DataFrame | None = None,
) -> PlanosDiscricionarios:
    """`res` precisa ter sido calculado com `selecao_discricionaria(celulas)`; os demais argumentos são os mesmos de
    `calcular_resultado` / `detalhar_por_gnd_acao`."""

    selecao = selecao_discricionaria(celulas)
    por_plano, avisos, indisponivel = _acumular(
        res, celulas, empenhado, selecao, despesas_manuais, ativos_sem_ne, lambda c: (c[_IDX_ACAO], c[_IDX_PO])
    )
    por_fonte, _, _ = _acumular(
        res, celulas, empenhado, selecao, despesas_manuais, ativos_sem_ne,
        lambda c: (c[_IDX_ACAO], c[_IDX_PO], c[_IDX_FONTE]),
    )
    # nomes só das células do RP2: a mesma Ação/Plano em outro resultado primário não pode emprestar a descrição
    do_rp2 = celulas.loc[celulas["chave"].isin(set(selecao))] if len(celulas) else celulas
    nome_acao = {k[0]: v for k, v in _descricoes(do_rp2, ("acao_codigo",), "acao_descricao").items()}
    nome_po = _descricoes(do_rp2, ("acao_codigo", "plano_orcamentario_codigo"), "plano_orcamentario_descricao")
    nome_fonte = {
        k[0]: v for k, v in _descricoes(do_rp2, ("fonte_recursos_detalhada_codigo",), "fonte_recursos_detalhada_descricao").items()
    }

    fontes_do_plano: dict[tuple, list[SaldoFonte]] = {}
    for chave_balde, b in por_fonte.items():
        if chave_balde[0] != TIPO_CELULA:
            continue
        _, acao, po, fonte = chave_balde
        dotacao, executado, projetado, saldo = _finais(b, indisponivel)
        fontes_do_plano.setdefault((acao, po), []).append(
            SaldoFonte(
                fonte=fonte, fonte_descricao=nome_fonte.get(str(fonte)), dotacao=dotacao, executado=executado,
                projetado=projetado, saldo=saldo, receita_limite=b.receita_limite, receita_excedente=b.receita_excedente,
            )
        )

    planos: list[QuadroPlano] = []
    for chave_balde, b in por_plano.items():
        if chave_balde[0] != TIPO_CELULA:
            continue
        _, acao, po = chave_balde
        dotacao, executado, projetado, saldo = _finais(b, indisponivel)
        planos.append(QuadroPlano(
            acao=acao, acao_descricao=nome_acao.get(str(acao)), po=po, po_descricao=nome_po.get((str(acao), str(po))),
            dotacao=dotacao, executado=executado, projetado=projetado, saldo=saldo,
            fontes=tuple(sorted(fontes_do_plano.get((acao, po), []), key=lambda f: str(f.fonte))),
        ))
    # Ações da maior para a menor dotação; dentro da Ação, planos da maior para a menor (nulo por último)
    dotacao_da_acao = {
        acao: soma_ou_nulo(pd.Series([p.dotacao for p in planos if p.acao == acao], dtype="float64")) or 0.0
        for acao in {p.acao for p in planos}
    }
    planos.sort(key=lambda p: (-dotacao_da_acao[p.acao], str(p.acao), -(p.dotacao if p.dotacao is not None else float("-inf")), str(p.po)))

    def _avulsa(chave_balde: tuple) -> LinhaAvulsa:
        b = por_plano.get(chave_balde)
        if b is None:
            return LinhaAvulsa(0.0, 0.0)
        _, executado, projetado, _ = _finais(b, indisponivel)
        return LinhaAvulsa(executado, projetado)

    fora, sem_celula = _avulsa((TIPO_FORA,)), _avulsa((TIPO_SEM_CELULA,))

    def _total(valores: list[float | None]) -> float | None:
        return soma_ou_nulo(pd.Series(valores, dtype="float64")) if valores else 0.0

    dotacao_total = _total([p.dotacao for p in planos])
    executado_total = _total([p.executado for p in planos] + [fora.executado, sem_celula.executado])
    projetado_total = _total([p.projetado for p in planos] + [fora.projetado, sem_celula.projetado])
    saldo_total = (
        None if res.resultado is None or None in (dotacao_total, executado_total, projetado_total)
        else dotacao_total - executado_total - projetado_total
    )
    diferencas = [
        abs(quadro - cartao)
        for quadro, cartao in (
            (dotacao_total, res.dotacao), (executado_total, res.executado_total),
            (projetado_total, res.projetado_total), (saldo_total, res.resultado),
        )
        if quadro is not None and cartao is not None
    ]
    resultado = PlanosDiscricionarios(
        planos=planos, fora=fora, sem_celula=sem_celula, dotacao=dotacao_total, executado=executado_total,
        projetado=projetado_total, saldo=saldo_total, diferenca_conferencia=max(diferencas, default=0.0), avisos=list(avisos),
    )
    if not resultado.fecha:
        resultado.avisos.append(
            f"Os quadros por Plano Orçamentário não fecham com o resultado do discricionário: diferença de "
            f"R$ {resultado.diferenca_conferencia:,.2f}."
        )
    return resultado


# ---------------------------------------------------------------------------------------- filtros
# Filtros da página (pedido do usuário, 30/10/2026). Só escolhem o que aparece: a conta acima não muda (sempre sobre todo o RP2).
SITUACAO_DEFICIT = "Déficit"
SITUACAO_FOLGA = "Folga"
SITUACAO_INTEGRAL = "Dotação integral"
SITUACAO_SEM_SALDO = "Sem saldo calculável"
SITUACOES = (SITUACAO_DEFICIT, SITUACAO_FOLGA, SITUACAO_INTEGRAL, SITUACAO_SEM_SALDO)
#: mesma tolerância da pílula do quadro (`ui_resultado_planos`): |saldo| até ela é "dotação integral"
TOLERANCIA_SITUACAO = 0.004


def situacao(saldo: float | None) -> str:
    if saldo is None:
        return SITUACAO_SEM_SALDO
    if saldo < -TOLERANCIA_SITUACAO:
        return SITUACAO_DEFICIT
    if abs(saldo) <= TOLERANCIA_SITUACAO:
        return SITUACAO_INTEGRAL
    return SITUACAO_FOLGA


def chave_plano(p: QuadroPlano) -> str:
    """Identificador do plano para o filtro: o código do PO se repete entre Ações (0000, 0001...), então leva a Ação."""

    return f"{p.acao}|{p.po}"


def opcoes_filtros(
    r: PlanosDiscricionarios, acoes: list[str] | None = None, planos: list[str] | None = None
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """(Ações, Planos, Fontes) oferecidos nos filtros, como {valor: rótulo}, na ordem dos quadros. Planos só das Ações escolhidas;
    fontes só dos planos que sobram depois de Ação e Plano (vazio = todos)."""

    opcoes_acao: dict[str, str] = {}
    for p in r.planos:
        opcoes_acao.setdefault(str(p.acao), f"{p.acao} — {p.acao_descricao}" if p.acao_descricao else str(p.acao))
    da_acao = [p for p in r.planos if not acoes or str(p.acao) in acoes]
    opcoes_plano = {
        chave_plano(p): f"{p.acao} · PO {p.po} — {p.po_descricao}" if p.po_descricao else f"{p.acao} · PO {p.po}"
        for p in da_acao
    }
    visiveis = [p for p in da_acao if not planos or chave_plano(p) in planos]
    opcoes_fonte: dict[str, str] = {}
    for p in visiveis:
        for f in p.fontes:
            if f.fonte is not None:
                opcoes_fonte.setdefault(str(f.fonte), f"{f.fonte} — {f.fonte_descricao}" if f.fonte_descricao else str(f.fonte))
    return opcoes_acao, opcoes_plano, dict(sorted(opcoes_fonte.items()))


def _so_das_fontes(p: QuadroPlano, fontes: set[str]) -> QuadroPlano | None:
    """O plano refeito só com as fontes escolhidas (soma das linhas de fonte; nulo em qualquer uma deixa o total nulo). Sem
    nenhuma das fontes, `None` (o plano sai)."""

    escolhidas = tuple(f for f in p.fontes if f.fonte is not None and str(f.fonte) in fontes)
    if not escolhidas:
        return None

    def soma(campo: str) -> float | None:
        return soma_ou_nulo(pd.Series([getattr(f, campo) for f in escolhidas], dtype="float64"))

    dotacao, executado, projetado = soma("dotacao"), soma("executado"), soma("projetado")
    saldo = None if None in (dotacao, executado, projetado) else dotacao - executado - projetado
    return replace(p, dotacao=dotacao, executado=executado, projetado=projetado, saldo=saldo, fontes=escolhidas)


def filtrar_planos(
    r: PlanosDiscricionarios,
    *,
    acoes: list[str] | None = None,
    planos: list[str] | None = None,
    fontes: list[str] | None = None,
    situacoes: list[str] | None = None,
) -> PlanosDiscricionarios:
    """Recorte dos quadros para exibição. Lista vazia ou `None` = sem filtro naquele campo; sem nenhum filtro devolve `r` como está.

    Ordem: Ação, Plano, Fonte (o plano passa a mostrar só as fontes escolhidas, com dotação, executado, projetado e saldo
    somados delas) e, por último, Situação (sobre o saldo já recortado). Os totais passam a ser a soma dos planos visíveis, com
    nulo propagando; as linhas avulsas ("Fora do discricionário", "Sem célula") e a conferência com o resultado não valem para
    um recorte e ficam de fora (`filtrado=True`). Não altera `r`."""

    if not (acoes or planos or fontes or situacoes):
        return r
    visiveis = [p for p in r.planos if (not acoes or str(p.acao) in acoes) and (not planos or chave_plano(p) in planos)]
    if fontes:
        visiveis = [q for q in (_so_das_fontes(p, set(fontes)) for p in visiveis) if q is not None]
    if situacoes:
        visiveis = [p for p in visiveis if situacao(p.saldo) in situacoes]

    def total(campo: str) -> float | None:
        return soma_ou_nulo(pd.Series([getattr(p, campo) for p in visiveis], dtype="float64"))

    dotacao, executado, projetado = total("dotacao"), total("executado"), total("projetado")
    saldo = None if None in (dotacao, executado, projetado) else dotacao - executado - projetado
    return PlanosDiscricionarios(
        planos=visiveis, fora=LinhaAvulsa(0.0, 0.0), sem_celula=LinhaAvulsa(0.0, 0.0), dotacao=dotacao, executado=executado,
        projetado=projetado, saldo=saldo, diferenca_conferencia=0.0, avisos=list(r.avisos), filtrado=True,
        planos_no_total=len(r.planos),
    )
