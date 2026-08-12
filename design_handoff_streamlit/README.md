# Handoff adaptado ao seu stack: Streamlit + CSS em `ui_theme.py` + Plotly

Este pacote traduz o protótipo HTML do painel para o ambiente que você já usa. Nada aqui
depende de biblioteca de componentes nova.

## O que vem aqui

| Arquivo | Onde colocar | O que é |
| --- | --- | --- |
| `design_tokens.py` | `src/design_tokens.py` | Tokens de cor, tipografia, espaçamento e a grade da tabela — o "único lugar" que o Claude Code sugeriu consolidar. Inclui `PLOTLY_LAYOUT` para os gráficos das outras páginas. |
| `data_loader.py` | `src/data_loader.py` | Leitura da planilha com o forward fill obrigatório, devolvendo um DataFrame longo, mais uma função `conferir()` com os totais de referência. |
| `painel_acoes.py` | `pages/…_Painel_Acoes.py` (ou o nome que suas páginas usam) | A página completa: refino, totais e os cards por ação. |
| `painel-orcamentario.dc.html` | referência apenas | O protótipo original, para comparar visualmente. |
| `data.json` | referência/teste | A base já extraída, se você quiser testar sem o Excel. |

## Passo a passo no VS Code

1. Descompacte esta pasta na raiz do projeto.
2. Copie os três `.py` para os caminhos da tabela acima.
3. Ajuste `CAMINHO_BASE` em `painel_acoes.py` para o caminho real da planilha.
4. Faça `ui_theme.py` importar de `design_tokens` em vez de manter hexadecimais próprios,
   e alinhe `.streamlit/config.toml` (`backgroundColor`, `secondaryBackgroundColor`,
   `primaryColor`, `textColor`) com `BG`, `SURFACE`, `ACCENT`, `TEXT`.
5. Rode e confira: `conferir(df)` deve dar `True` nos sete anos.

Prompt sugerido para o Claude Code:

> Leia `design_handoff_streamlit/README.md` e integre os três módulos ao projeto:
> mova os tokens para `src/design_tokens.py`, refatore `src/ui_theme.py` para consumir
> esses tokens (sem hexadecimais soltos), e adicione a página de cards por ação de governo.
> Preserve os helpers existentes (`format_brl_compact`, `render_metric_grid`,
> `render_page_header`) e use-os onde equivalerem ao que o módulo novo faz.

## Decisões de tradução (e por quê)

- **Cards em HTML injetado.** A grade de 10 colunas com par nome/código em cada célula não
  existe em `st.dataframe` nem em `st.columns` sem virar uma grade frouxa. O card inteiro
  vai num `st.markdown(..., unsafe_allow_html=True)`; só os controles são nativos.
- **Tema claro do protótipo → seu tema escuro.** O protótipo nasceu num design system claro
  (steel sobre papel). Aqui os papéis foram remapeados: fundo `#0E1117`, card `#161B22`,
  hairline `#2A313A`, números em `#7FB0FF` (o `#4C8DFF` puro perde legibilidade em números
  grandes sobre fundo escuro), rótulos em `#8B949E`. Estrutura, colunas e tipografia idênticas.
- **Filtros cruzados.** Cada `selectbox` lista só os códigos que sobrevivem aos *outros*
  filtros ativos, evitando seleção que retorna vazio. Implementado em `passa(frame, ignorar=)`.
- **Expandir subdivisões.** `st.toggle` por ação, com `key=f"expandir_{codigo}"` — o estado
  fica no `session_state` e sobrevive ao rerun.
- **`st.metric` para os quatro totais**, sem `delta`: você não quer percentuais.
- **Nenhum gráfico nesta página.** Requisito explícito. `PLOTLY_LAYOUT` está nos tokens só
  para padronizar as outras páginas que já têm gráfico.
- **Formatação pt-BR à mão** (`brl`, `num`) porque `locale` no Streamlit Cloud é frágil.
  Se `format_brl_compact` já resolve, troque — mas mantenha `tabular-nums` no CSS.

## Especificação visual

Medidas, hierarquia de tipos, colunas e estados estão detalhados no README do pacote original
(`design_handoff_painel_orcamentario/README.md`) e já refletidos no CSS de `painel_acoes.py`.
Pontos que não podem mudar sem quebrar a leitura:

- Cabeçalho, linhas e rodapé da tabela usam **a mesma** `grid-template-columns`
  (`SUBDIV_COLUMNS`) — se alterar, altere em um lugar só.
- `overflow-x: auto` no `.po-scroll` com `min-width: 1200px` na grade: em tela estreita
  rola só a tabela, não a página.
- Valor zero renderiza `—`, nunca `0`.
- Dotação atualizada é a única coluna em destaque (peso 600 + acento).

## Riscos conhecidos

- `unsafe_allow_html=True` é necessário; o conteúdo vem da sua própria base, mas se algum
  campo puder conter `<` ou `&`, passe por `html.escape()` em `html_linha`.
- Streamlit reexecuta a página inteira a cada interação: com muitas ações na tela, mantenha
  `@st.cache_data` no carregamento (já está) e evite recomputar agregações fora de `main()`.
- Se o número de ações crescer muito, considere paginar os cards em vez de renderizar todos.
