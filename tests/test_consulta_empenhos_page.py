"""Testes da página Consulta de Empenhos (leitura pelo manifesto atual da Execução Anual).

Espelha `test_execucao_orcamentaria_page.py`: usa a extração real apontada pelo manifesto
atual, sem fixtures sintéticas — pulado se esse manifesto não existir.

A lista "Empenhos no escopo" é uma grade de cartões HTML com revelação progressiva (8 cartões
de início, +8 a cada clique em "Ver mais"), não `st.dataframe` — cada cartão tem um
`st.button("Ver")` de seleção (única, para o painel de detalhe) e um `st.checkbox` de marcação
(múltipla, para o cartão "Resumo do grupo selecionado"). Diferente de `st.dataframe` (cuja
seleção de linha é somente leitura em `AppTest`), botão e caixa aqui SÃO simuláveis via clique
real. Os testes cobrem seleção padrão, troca de seleção por clique, revelação progressiva e
marcação de grupo.

Os filtros são dropdowns de valor único com "Todos" (fiéis ao design do handoff), não o
multi-seleção "estilo Excel" usado nas demais páginas da Execução Anual — os testes usam
`st.selectbox`, não `st.multiselect`. A faixa de KPIs do topo é HTML puro (grade com hairlines,
não `st.metric`), então é verificada via `app.markdown`; só o painel de detalhe usa `st.metric`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.importacao_execucao import Manifesto

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFESTO_ATUAL = Path("data/manifestos/execucao_anual_atual.json")


@unittest.skipUnless(MANIFESTO_ATUAL.exists(), f"Manifesto ausente em {MANIFESTO_ATUAL}")
class ConsultaEmpenhosPageTests(unittest.TestCase):
    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        app.switch_page("app_pages/consulta_empenhos.py")
        app.run(timeout=60)
        return app

    def _kpis_html(self, app: AppTest) -> str:
        return " ".join(item.value for item in app.markdown if "ce-kpi" in item.value)

    def _cartoes_lista(self, app: AppTest):
        """Botões-cartão da lista, na ordem em que aparecem — um por NE visível. Desde que o
        botão "Ver" foi removido (pedido explícito), cada cartão É o próprio `st.button`
        (rótulo "NE — objeto", `type="primary"` quando selecionado), não mais um
        `st.markdown` com classe `ce-list-row` (ver docstring do módulo)."""

        return [b for b in app.button if b.key and b.key.startswith("consulta_empenhos_ver_")]

    def _ne_do_cartao(self, cartao) -> str:
        """NE curta (ex. "2026NE000036") a partir do rótulo do botão-cartão ("NE — objeto")."""
        return cartao.label.split(" — ", 1)[0]

    def _qtd_grupos_consolidacao(self, app: AppTest) -> int:
        # ao contrário dos cartões da lista (um `st.markdown` por linha), a consolidação
        # renderiza cabeçalho + todas as linhas visíveis num único `st.markdown` — por isso
        # conta ocorrências da classe dentro do texto, não itens de `app.markdown`.
        return sum(item.value.count('class="ce-cons-row"') for item in app.markdown)

    def test_renders_page_from_current_manifest(self) -> None:
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Consulta de Empenhos")

        kpis = self._kpis_html(app)
        self.assertIn("Empenhos", kpis)
        self.assertIn("3742", kpis)
        self.assertIn("Saldo de empenho", kpis)
        self.assertIn("A pagar", kpis)

    def test_shows_procedencia_footer_with_manifest_hash(self) -> None:
        app = self._open_page()
        manifesto = Manifesto.atual()

        self.assertTrue(any(f"hash {manifesto.sha256[:8]}" in item.value for item in app.caption))

    def _total_empenhos_no_recorte(self, app: AppTest) -> int:
        # lido do KPI "Empenhos" em vez de hardcoded: a base real (sem fixture congelada,
        # reimportada de vez em quando) já tem 4 outros testes deste arquivo que quebram por
        # depender de um total fixo (ver docstring do módulo) — não repete esse problema aqui.
        kpis = self._kpis_html(app)
        match = re.search(r'ce-kpi-label">Empenhos</div><div class="ce-kpi-value">(\d+)<', kpis)
        return int(match.group(1))

    def test_lista_mostra_ate_o_teto_direto_sem_precisar_clicar(self) -> None:
        # Pedido explícito: rolagem em vez de "Ver mais" clicado repetidamente — até
        # QTD_INICIAL_LISTA (200) cartões aparecem de uma vez, dentro da caixa rolável
        # (`.st-key-ce_list_scroll`); só acima desse teto (a base real tem milhares de NEs sem
        # filtro) que "Ver mais" ainda aparece, como rede de segurança (ver docstring do
        # módulo e `_render_cartoes_lista`).
        app = self._open_page()
        total = self._total_empenhos_no_recorte(app)

        cartoes = self._cartoes_lista(app)
        self.assertEqual(len(cartoes), min(200, total))
        self.assertTrue(
            any(f"Mostrando {min(200, total)} de {total} notas" in item.value for item in app.markdown)
            or any(f"Mostrando todas as {total} notas" in item.value for item in app.markdown)
        )
        self.assertEqual(any(b.label == "Ver mais" for b in app.button), total > 200)

    def test_clicar_ver_mais_revela_mais_cartoes(self) -> None:
        app = self._open_page()
        total = self._total_empenhos_no_recorte(app)
        if total <= 200:
            self.skipTest("Recorte atual tem 200 NEs ou menos — 'Ver mais' nem aparece.")

        ver_mais = next(b for b in app.button if b.label == "Ver mais")
        ver_mais.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        cartoes = self._cartoes_lista(app)
        esperado = min(400, total)  # QTD_INICIAL_LISTA + QTD_INCREMENTO_LISTA
        self.assertEqual(len(cartoes), esperado)
        self.assertTrue(
            any(f"Mostrando {esperado} de {total} notas" in item.value for item in app.markdown)
        )

    def test_grupo_selecionado_mostra_instrucao_sem_marcacoes(self) -> None:
        app = self._open_page()
        self.assertTrue(any("Marque a caixinha" in item.value for item in app.caption))

    def test_marcar_um_cartao_preenche_o_resumo_do_grupo(self) -> None:
        app = self._open_page()
        cartoes = self._cartoes_lista(app)
        ne_primeira = self._ne_do_cartao(cartoes[0])

        caixa = next(c for c in app.checkbox if c.key.endswith(ne_primeira))
        caixa.set_value(True)
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(
            any("Selecionados" in item.value and ">1<" in item.value for item in app.markdown)
        )
        self.assertTrue(any(f"NEs no grupo: {ne_primeira}" in item.value for item in app.caption))

        limpar = next(b for b in app.button if b.label == "Limpar seleção do grupo")
        limpar.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("Marque a caixinha" in item.value for item in app.caption))

    def test_selecionar_todos_marca_todos_os_cartoes_visiveis(self) -> None:
        app = self._open_page()

        botao = next(b for b in app.button if b.label == "Selecionar todos")
        botao.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(all(c.value for c in app.checkbox))
        self.assertTrue(any(b.label == "Desmarcar todos" for b in app.button))

    def test_desmarcar_todos_desmarca_todos_os_cartoes_visiveis(self) -> None:
        app = self._open_page()

        selecionar = next(b for b in app.button if b.label == "Selecionar todos")
        selecionar.click()
        app.run(timeout=60)

        desmarcar = next(b for b in app.button if b.label == "Desmarcar todos")
        desmarcar.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(all(not c.value for c in app.checkbox))
        self.assertTrue(any(b.label == "Selecionar todos" for b in app.button))

    def test_selecionar_todos_preserva_marcacao_apos_ver_mais(self) -> None:
        # "Selecionar todos" marca só o que está EXIBIDO no momento do clique — revelar mais
        # cartões depois (via "Ver mais") não marca os novos automaticamente, nem desmarca os
        # já marcados.
        app = self._open_page()

        selecionar = next(b for b in app.button if b.label == "Selecionar todos")
        selecionar.click()
        app.run(timeout=60)
        marcados_antes = sum(1 for c in app.checkbox if c.value)

        vermais = next(b for b in app.button if b.label == "Ver mais")
        vermais.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(sum(1 for c in app.checkbox if c.value), marcados_antes)
        self.assertGreater(len(app.checkbox), marcados_antes)
        self.assertTrue(any(b.label == "Selecionar todos" for b in app.button))

    def test_consolidacao_do_grupo_pede_marcacao_quando_vazia(self) -> None:
        app = self._open_page()

        self.assertTrue(any(h.value == "Consolidação Orçamentária do Grupo" for h in app.subheader))
        self.assertTrue(
            any("Marque a caixinha ao lado de um ou mais empenhos" in item.value for item in app.caption)
        )

    def test_consolidacao_do_grupo_mostra_os_4_blocos_apos_marcar(self) -> None:
        app = self._open_page()
        cartoes = self._cartoes_lista(app)
        ne_primeira = self._ne_do_cartao(cartoes[0])

        caixa = next(c for c in app.checkbox if c.key.endswith(ne_primeira))
        caixa.set_value(True)
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        rotulos_blocos = {"Elemento de Despesa", "Grupo de Despesa", "Ação de Governo", "UGR - Gestão"}
        self.assertTrue(rotulos_blocos.issubset({e.label for e in app.expander}))

    def test_bloco_elemento_de_despesa_mostra_o_grupo_marcado_nao_o_escopo_inteiro(self) -> None:
        app = self._open_page()
        cartoes = self._cartoes_lista(app)
        ne_primeira = self._ne_do_cartao(cartoes[0])

        caixa = next(c for c in app.checkbox if c.key.endswith(ne_primeira))
        caixa.set_value(True)
        app.run(timeout=60)

        bloco = next(e for e in app.expander if e.label == "Elemento de Despesa")
        # "NEs" (coluna de contagem) do bloco tem que bater com o tamanho do grupo marcado
        # (1), não com as milhares de NEs do recorte de filtros inteiro.
        html = bloco.markdown[0].value
        self.assertIn('class="ce-cons-val">1<', html)

    def test_consolidacao_comeca_enxuta_com_botao_ver_mais(self) -> None:
        app = self._open_page()

        # "Ação de Governo" tem mais de 8 grupos na base real — garante que o teste
        # exercite o caso com "Ver mais" visível, não uma dimensão que já cabe inteira.
        self.assertLessEqual(self._qtd_grupos_consolidacao(app), 8)
        vermais = [b for b in app.button if b.label == "Ver mais"]
        self.assertGreaterEqual(len(vermais), 1)

    def test_clicar_ver_mais_da_consolidacao_revela_mais_grupos(self) -> None:
        app = self._open_page()
        antes = self._qtd_grupos_consolidacao(app)

        vermais_cons = next(
            b for b in app.button if b.label == "Ver mais" and "_cons_vermais_" in b.key
        )
        vermais_cons.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        depois = self._qtd_grupos_consolidacao(app)
        self.assertGreater(depois, antes)

    def test_quick_filters_include_exercicio_acao_ugr_grupo_despesa_in_order(self) -> None:
        app = self._open_page()
        # os quatro primeiros multiselects da página são os filtros rápidos, nesta ordem
        # (filtro combinado: multiselect, não mais selectbox — pedido explícito posterior).
        rapidos = [m.label for m in app.multiselect[:4]]
        self.assertEqual(rapidos, ["Exercício", "Ação de Governo", "UGR - Gestão", "Grupo de Despesa"])

    def test_filtering_by_exercicio_narrows_scope(self) -> None:
        app = self._open_page()
        filtro_ano = next(m for m in app.multiselect if m.label == "Exercício")
        primeira_opcao = filtro_ano.options[0]  # nenhuma seleção = "Todos"
        filtro_ano.set_value([primeira_opcao])
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        kpis = self._kpis_html(app)
        self.assertNotIn(">3742<", kpis)

    def test_filtering_by_acao_narrows_scope(self) -> None:
        app = self._open_page()
        acao_filter = next(m for m in app.multiselect if m.label == "Ação de Governo")
        primeira_opcao = acao_filter.options[0]
        acao_filter.set_value([primeira_opcao])
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        kpis = self._kpis_html(app)
        self.assertNotIn(">3742<", kpis)

    def _empenhos_no_kpi(self, app: AppTest) -> int:
        match = re.search(
            r'<div class="ce-kpi-label">Empenhos</div><div class="ce-kpi-value">(\d+)</div>',
            self._kpis_html(app),
        )
        return int(match.group(1))

    def test_filtering_by_acao_com_dois_valores_combina_com_ou(self) -> None:
        # filtro combinado (pedido explícito): selecionar 2 valores no mesmo campo devolve a
        # união dos dois, não a interseção (impossível, já que é o mesmo campo) nem só um deles.
        app = self._open_page()
        acao_filter = next(m for m in app.multiselect if m.label == "Ação de Governo")
        duas_opcoes = acao_filter.options[:2]
        acao_filter.set_value([duas_opcoes[0]])
        app.run(timeout=60)
        empenhos_um = self._empenhos_no_kpi(app)

        acao_filter = next(m for m in app.multiselect if m.label == "Ação de Governo")
        acao_filter.set_value(duas_opcoes)
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        empenhos_dois = self._empenhos_no_kpi(app)
        self.assertGreaterEqual(empenhos_dois, empenhos_um)

    def test_limpar_filtros_reseta_para_todos(self) -> None:
        app = self._open_page()
        acao_filter = next(m for m in app.multiselect if m.label == "Ação de Governo")
        acao_filter.set_value([acao_filter.options[0]])
        app.run(timeout=60)
        self.assertEqual(
            next(m for m in app.multiselect if m.label == "Ação de Governo").value,
            [acao_filter.options[0]],
        )

        limpar = next(b for b in app.button if b.label == "Limpar filtros")
        limpar.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(next(m for m in app.multiselect if m.label == "Ação de Governo").value, [])
        kpis = self._kpis_html(app)
        self.assertIn(">3742<", kpis)

    def test_busca_livre_narrows_scope(self) -> None:
        app = self._open_page()
        busca = next(t for t in app.text_input if t.label == "Busca livre")
        busca.set_value("UFRPE")
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        kpis = self._kpis_html(app)
        self.assertIn("Empenhos", kpis)

    def test_busca_sem_correspondencia_mostra_lista_vazia(self) -> None:
        app = self._open_page()
        busca = next(t for t in app.text_input if t.label == "Busca livre")
        busca.set_value("texto que nao existe em nenhum empenho xyz123")
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(
            any("Nenhum empenho encontrado com os filtros informados." in item.value for item in app.warning)
        )

    def test_busca_livre_restringe_opcoes_dos_filtros_rapidos(self) -> None:
        # bug relatado: os filtros ofereciam atributos de NEs fora da busca (opções do
        # dataset inteiro, não do recorte já reduzido pela busca livre). "informatica" bate
        # nos campos de sempre da NE em 7 "Ação de Governo" distintas — bem menos que as 54 do
        # dataset inteiro; "ADMINISTRACAO DA UNIDADE" (ação 2000) não é uma delas. Desde que a
        # busca por item (base mensal, 2026+) foi ligada, uma 8ª ação aparece também: NE
        # 153165152392026NE000490 (ação "Manutenção e Operação da Infraestrutura de TI") não
        # tem "informatica" em nenhum campo da própria NE, só no item empenhado dentro dela —
        # é exatamente o caso que a busca por item deveria capturar, não uma regressão.
        app = self._open_page()
        busca = next(t for t in app.text_input if t.label == "Busca livre")
        busca.set_value("informatica")
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        acao_filter = next(m for m in app.multiselect if m.label == "Ação de Governo")
        self.assertEqual(len(acao_filter.options), 8)
        self.assertFalse(any("ADMINISTRACAO DA UNIDADE" in opcao for opcao in acao_filter.options))
        self.assertTrue(any("INFRAESTRUTURA DE TECNOLOGIA" in opcao for opcao in acao_filter.options))

    def test_default_selection_matches_sort_order(self) -> None:
        # Padrão: "Maior saldo de empenho" — o cartão selecionado (marcado nativamente por
        # `type="primary"`, não uma classe CSS própria — ver docstring do módulo) deve ser o
        # primeiro da página 1, e sua NE deve ser a exibida no painel de detalhamento.
        app = self._open_page()
        cartoes = self._cartoes_lista(app)
        selecionado = next(c for c in cartoes if c.proto.type == "primary")
        self.assertEqual(selecionado.key, cartoes[0].key)

        ne_selecionada = self._ne_do_cartao(selecionado)
        self.assertTrue(
            any(f'class="ce-ne">{ne_selecionada}' in item.value for item in app.markdown)
        )

    def test_clicar_no_cartao_troca_a_ne_selecionada(self) -> None:
        # botão "Ver" foi removido (pedido explícito) — cada cartão É o próprio `st.button`
        # (ver docstring do módulo e `_render_cartoes_lista`); clicar nele troca a seleção.
        app = self._open_page()
        cartoes = self._cartoes_lista(app)
        ne_segunda = self._ne_do_cartao(cartoes[1])

        cartoes[1].click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(
            any(f'class="ce-ne">{ne_segunda}' in item.value for item in app.markdown)
        )
        cartoes_apos = self._cartoes_lista(app)
        selecionado_apos = next(c for c in cartoes_apos if c.proto.type == "primary")
        self.assertEqual(self._ne_do_cartao(selecionado_apos), ne_segunda)

    def test_explains_when_no_manifest_available(self) -> None:
        with patch.object(Manifesto, "atual", return_value=None):
            app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(
            any("Nenhuma base de Execução Anual foi importada" in item.value for item in app.info)
        )


if __name__ == "__main__":
    unittest.main()
