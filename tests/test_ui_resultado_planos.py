"""Testes de `src/ui_resultado_planos.py` — HTML dos quadros do discricionário por Plano Orçamentário (29/10/2026)."""

from __future__ import annotations

from src.resultado_orcamentario_planos import LinhaAvulsa, PlanosDiscricionarios, QuadroPlano, SaldoFonte
from src.ui_resultado_planos import html_planos_discricionarios


def _plano(po="0001", acao="20RK", dotacao=1000.0, executado=400.0, projetado=300.0, fontes=(), po_descricao="PLANO UM",
           acao_descricao="FUNCIONAMENTO"):
    saldo = None if None in (dotacao, executado, projetado) else dotacao - executado - projetado
    return QuadroPlano(acao, acao_descricao, po, po_descricao, dotacao, executado, projetado, saldo, tuple(fontes))


def _resultado(planos, fora=LinhaAvulsa(0.0, 0.0), sem_celula=LinhaAvulsa(0.0, 0.0), diferenca=0.0):
    def soma(campo):
        valores = [getattr(p, campo) for p in planos]
        return None if any(v is None for v in valores) else float(sum(valores))

    dot, exe, prj = soma("dotacao"), soma("executado"), soma("projetado")
    saldo = None if None in (dot, exe, prj) else dot - exe - prj
    return PlanosDiscricionarios(planos, fora, sem_celula, dot, exe, prj, saldo, diferenca)


def test_um_quadro_por_plano_agrupado_sob_a_acao_com_os_valores_em_reais():
    html = html_planos_discricionarios(_resultado([_plano("0001"), _plano("0002", dotacao=500.0, executado=100.0, projetado=50.0)]))
    assert html.count('<article class="card"') == 2 and html.count('<div class="acao">') == 1
    assert "PO 0001" in html and "PLANO UM" in html and "FUNCIONAMENTO" in html
    assert "R&#36; 1.000,00" in html and "Folga R&#36; 300,00" in html and "Folga R&#36; 350,00" in html
    assert "Executado" in html and "Projetado até dez" in html and "Dotação" in html


def test_deficit_leva_a_pilula_vermelha_e_a_barra_acima_da_dotacao():
    html = html_planos_discricionarios(_resultado([_plano(dotacao=100.0, executado=80.0, projetado=60.0)]))
    assert "pill neg" in html and "Déficit R&#36; 40,00" in html and 'class="b-over"' in html


def test_dotacao_integral_e_sem_barra_vermelha_quando_cabe():
    html = html_planos_discricionarios(_resultado([_plano(dotacao=100.0, executado=60.0, projetado=40.0)]))
    assert "Dotação integral" in html and 'class="b-over"' not in html


def test_valor_nulo_vira_traco_e_pilula_incompleto_sem_barra_nem_zero():
    html = html_planos_discricionarios(_resultado([_plano(dotacao=1000.0, executado=None, projetado=None)]))
    assert "Incompleto" in html and "—" in html and 'class="b-exec"' not in html
    sem_dotacao = html_planos_discricionarios(_resultado([_plano(dotacao=None)]))
    assert "Sem dotação" in sem_dotacao


def test_fontes_so_aparecem_quando_ha_mais_de_uma_ou_receita():
    uma = SaldoFonte("1000000000", "TESOURO", 1000.0, 400.0, 300.0, 300.0)
    html1 = html_planos_discricionarios(_resultado([_plano(fontes=[uma])]))
    assert 'class="fontes"' not in html1
    duas = [uma, SaldoFonte("1050000000", "PROPRIOS LIVRES DA UO", 200.0, 0.0, 0.0, 200.0)]
    html2 = html_planos_discricionarios(_resultado([_plano(dotacao=1200.0, fontes=duas)]))
    assert 'class="fontes"' in html2 and "Fonte 1000000000" in html2
    assert "Fonte 1050000000 · PROPRIOS LIVRES DA UO" in html2  # a 1050 leva a descrição


def test_nota_da_arrecadacao_so_quando_ultrapassa_a_dotacao():
    passa = SaldoFonte("1050000000", "PROPRIOS", 415401.8, 0.0, 0.0, 415401.8, receita_limite=447514.78, receita_excedente=32112.98)
    html = html_planos_discricionarios(_resultado([_plano(dotacao=415401.8, executado=0.0, projetado=0.0, fontes=[passa])]))
    assert html.count("acima da dotação ficam fora") == 1 and "informado R&#36; 447.514,78" in html
    nao_passa = SaldoFonte("1050000000", "PROPRIOS", 415401.8, 0.0, 0.0, 415401.8, receita_limite=300000.0, receita_excedente=0.0)
    html2 = html_planos_discricionarios(_resultado([_plano(dotacao=415401.8, executado=0.0, projetado=0.0, fontes=[nao_passa])]))
    assert "acima da dotação" not in html2


def test_linhas_avulsas_so_aparecem_quando_ha_valor_e_a_conferencia_mostra_a_diferenca():
    sem = html_planos_discricionarios(_resultado([_plano()]))
    assert "Fora do discricionário" not in sem and "Sem célula" not in sem and "confere com o resultado" in sem
    com = html_planos_discricionarios(_resultado([_plano()], fora=LinhaAvulsa(10.0, 5.0), sem_celula=LinhaAvulsa(0.0, 337860.0)))
    assert "Fora do discricionário" in com and "Sem célula" in com and "R&#36; 337.860,00" in com
    quebrada = html_planos_discricionarios(_resultado([_plano()], diferenca=12.5))
    assert "não fecha com o resultado" in quebrada and "R&#36; 12,50" in quebrada


def test_texto_de_cadastro_e_escapado_e_vazio_avisa():
    html = html_planos_discricionarios(_resultado([_plano(po_descricao="<script>x</script>", acao_descricao="A & B")]))
    assert "<script>" not in html and "&lt;script&gt;" in html and "A &amp; B" in html
    assert "Nenhuma célula do discricionário" in html_planos_discricionarios(_resultado([]))


def test_recorte_filtrado_avisa_e_tira_avulsas_e_conferencia():
    from src.resultado_orcamentario_planos import filtrar_planos

    base = _resultado([_plano("0001"), _plano("0002", acao="4002")], fora=LinhaAvulsa(50.0, 10.0))
    html = html_planos_discricionarios(filtrar_planos(base, acoes=["20RK"]))
    assert "Filtrado: 1 de 2 Planos" in html and html.count('<article class="card"') == 1
    assert "Fora do discricionário" not in html and "confere com o resultado" not in html
    vazio = html_planos_discricionarios(filtrar_planos(base, acoes=["XXXX"]))
    assert "Nenhum Plano Orçamentário atende aos filtros" in vazio
    sem_filtro = html_planos_discricionarios(base)
    assert "Filtrado" not in sem_filtro and "Fora do discricionário" in sem_filtro
