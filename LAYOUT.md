# LAYOUT.md — UFRPE BudgetLab

Documentação do layout real da aplicação (Streamlit), gerada a partir do código-fonte em
26/08/2026, para uso de um designer. Não é um documento de especificação — descreve o que
**existe hoje**, incluindo inconsistências entre páginas (ex.: nem toda página tem CSS
próprio; os prefixos de classe variam por página).

---

## 1. Estrutura de páginas

Navegação lateral (`st.navigation`, `position="sidebar"`, definida em `app.py`), em modo
"trilho de ícones": recolhida por padrão (só ícones, ~72px), expande ao passar o mouse
(~336px). Duas seções nomeadas viram cabeçalhos de grupo; a seção sem nome não tem cabeçalho.

| # | Página (título no menu) | Arquivo | Grupo | Ícone (Material) |
|---|---|---|---|---|
| 1 | Início | `app_pages/home.py` | *(sem grupo)* | `home` |
| 2 | Dotação Orçamentária | `app_pages/dotacao_orcamentaria.py` | *(sem grupo)* | `monitoring` |
| 3 | Painel por Ação | `app_pages/painel_acoes.py` | *(sem grupo)* | `grid_view` |
| 4 | Execução Orçamentária | `app_pages/execucao_orcamentaria.py` | *(sem grupo)* | `payments` |
| 5 | Consulta de Empenhos | `app_pages/consulta_empenhos.py` | *(sem grupo)* | `receipt_long` |
| 6 | Empenhos com Execução Retardada | `app_pages/empenhos_execucao_retardada.py` | *(sem grupo)* | `schedule` |
| 7 | Bolsas e Auxílios | `app_pages/bolsas_auxilios.py` | *(sem grupo)* | `school` |
| 8 | Contratos Contínuos | `app_pages/contratos_continuos.py` | **Contratos** | `handshake` |
| 9 | Contratos — Vigência | `app_pages/contratos_vigencia.py` | **Contratos** | `event_upcoming` |
| 10 | Atualizar Planilhas | `app_pages/atualizar_planilhas.py` | **Administração** | `upload_file` |

**Página existente mas fora do menu** (código mantido, `st.Page` comentado em `app.py`,
reativável a qualquer momento):
- Contratos — Pagamentos — `app_pages/contratos_pagamentos.py`

Todas as páginas são scripts diretos executados pelo `st.navigation` (sem `def main()`, sem
`st.set_page_config` próprio — isso é chamado uma única vez em `app.py`).

---

## 2. Árvore de componentes por página

Ordem vertical de renderização. "N cols" indica quantas colunas a linha usa. Blocos
`st.container(border=True)` aparecem como "cartão"; grades HTML customizadas (não
`st.dataframe`) aparecem como "grade HTML".

### 2.1 Início (`home.py`)
- Header (`render_page_header`): título + subtítulo + badge de contexto
- Cartão — "Visão geral" (subheader + parágrafo)
- Cartão — "Módulos disponíveis" (subheader + lista com marcadores)
- Caption (rodapé, texto único)

### 2.2 Dotação Orçamentária (`dotacao_orcamentaria.py`)
- Header (título + subtítulo + badge "Dotação")
- **Sidebar** (`st.sidebar`, único caso na aplicação): "Filtros" (subheader) + 8
  `st.multiselect` empilhados verticalmente (Ano, Ação Governo, PTRES, Plano Orçamentário,
  Grupo de Despesa, Fonte de Recursos Detalhada, IDUSO, Resultado Primário)
- Alerta de sucesso (`render_alert`, faixa horizontal verde) — "Base carregada"
- Caption — "Anos: ..."
- Faixa de KPIs (`render_metric_grid`, 4 colunas): Dotação Atualizada, Inicial, Suplementar,
  Cancelada/Remanejada
- Cartão — "Evolução por Ano"
  - `st.segmented_control` (4 opções: os 4 indicadores)
  - Gráfico Plotly (linha/área, `plotly_chart`)
- Caption (rodapé): procedência (data extração + hash do manifesto)

### 2.3 Painel por Ação (`painel_acoes.py`)
- Header (título + subtítulo + badge "Dotação")
- CSS próprio (`_inject_css`, prefixo `.po-*`)
- Alerta de sucesso — "Base carregada"
- Linha de filtros (2 linhas × 4 colunas = 8 campos): row1 = Ano (`st.selectbox`) + 3
  `st.multiselect`; row2 = 4 `st.multiselect`
- Caption — contagem de ações/subdivisões no recorte
- Aviso condicional (⚠ exercício em andamento)
- **Lista de cartões** (um por Ação de Governo, ordenados por saldo):
  - Cartão (`.po-card`, HTML puro):
    - Cabeçalho: kicker (código da ação) + título (nome da ação) + tags (`.po-tag`, chips)
    - Métrica em destaque (`.po-metric`): Dotação Atualizada Total
    - Grade HTML rolável (`.po-scroll` → `.po-head`/`.po-row`×N/`.po-foot`), 10 colunas
      (Plano Orçamentário, Fonte, GND, Res. Primário, Iduso, PTRES, Inicial, Suplem.,
      Canc./Remanej., Atualizada)
- Caption (rodapé): procedência

### 2.4 Execução Orçamentária (`execucao_orcamentaria.py`)
- Header (título + subtítulo + badge "Execução")
- Alerta de sucesso — "Base carregada"
- Linha de filtros inline (`st.columns(5)`, 1 linha): Exercício, GND, Fonte, Resultado
  Primário, UGR — cada `st.multiselect`
- Faixa de KPIs (HTML custom via `render_metric_grid`-like, 5 colunas): Empenhado, Liquidado,
  Pago, % Liquidado/Empenhado, % Pago/Liquidado
- Caption condicional (⚠ exercício em andamento no recorte)
- Cartão — "Série histórica"
  - Gráfico Plotly (barras agrupadas Empenhado × Liquidado × Pago por ano, textura listrada
    no exercício em andamento)
- Cartão — "Composição"
  - `st.selectbox` "Dimensão" (11 opções)
  - `st.dataframe` (ranking, até 15 linhas + "outros")
  - Caption condicional ("X categorias ficaram fora do ranking")
- Cartão — "Rastreabilidade"
  - `st.selectbox` "Nota de Empenho (NE)" (busca)
  - `st.dataframe` (linhas de origem da NE selecionada, com `linha_origem`)
- Caption (rodapé): "Última extração" + hash + nota de composição por ano

### 2.5 Consulta de Empenhos (`consulta_empenhos.py`)
- Header em `st.columns([5, 1])`: título à esquerda, botão utilitário à direita
- CSS próprio (`_inject_css`, prefixo `.ce-*`)
- Linha de busca (`st.columns([2,1,1,1,1])`): campo de texto livre + 4 filtros rápidos
  (`st.multiselect`)
- `st.expander` — "Filtros por atributo" (12 campos cruzados, `st.multiselect` em grade)
- Faixa de KPIs (grade HTML `.ce-kpis`, 6 colunas): Empenhos, Empenhado, Liquidado, Pago,
  Saldo de empenho, A pagar
- **Duas colunas** (`st.columns([2, 1], gap="medium")`):
  - **Coluna principal (2/3)**:
    - "Empenhos no escopo": título + `st.selectbox` "Ordenar" + botão "Selecionar
      todos"/"Desmarcar todos"
    - Lista de cartões HTML (`.ce-list-row`, revelação progressiva 8+8), cada um com
      `st.checkbox` (marcação de grupo) + `st.button("Ver")` (seleção de detalhe)
    - Botão "Ver mais" (paginação)
    - "Consolidação do escopo" (grade HTML `.ce-cons-row`, agrupada por dimensão
      selecionável, revelação progressiva 8+8)
  - **Coluna de detalhe (1/3)**:
    - Cabeçalho do detalhe (`.ce-detail-head`): NE + favorecido
    - `st.metric` × N (`st-key-ce_detail_metrics`)
    - Texto/caption com dados da NE selecionada
- **Full-width, abaixo das duas colunas**: "Consolidação Orçamentária do Grupo"
  - Um `st.expander` por dimensão (4 dimensões: Elemento de Despesa, Grupo de Despesa, Ação
    de Governo, UGR), cada um com grade HTML `.ce-cons-row`
- Caption (rodapé): procedência

### 2.6 Empenhos com Execução Retardada (`empenhos_execucao_retardada.py`)
- Fonte de dados: Execução Mensal (`src/tesouro_execucao_mensal.py`, BI CPOC), desde 22/09/2026
  — antes lia da Execução Anual; migrada para replicar os mesmos filtros de Consulta de
  Empenhos (só cobre 2024 em diante)
- Header
- Linha de ação (`st.columns([1,4])`): botão "Limpar filtros"
- Linha de busca (`st.columns([2,1,1,1,1])`): mesmo padrão de Consulta de Empenhos (campo
  compartilhado `src/ui_filtros_execucao.py`)
- `st.expander` — "Filtros por atributo" (15 campos: 13 compartilhados com Consulta de
  Empenhos + 2 exclusivos da Execução Mensal — NE - Informação Complementar, Unidade
  Orçamentária)
- Dois cortes de sensibilidade (`st.columns(2)`), cada um `st.columns([3,1], vertical_alignment="bottom")`:
  valor mínimo (R$) + toggle de percentual mínimo
- Faixa de KPIs (`st.columns(4)`, `st.metric`)
- Cabeçalho de tabela (`st.columns([1.3,2,1.2,1.2,1.2,0.9,0.8])`, 7 colunas)
- Lista de linhas (mesma grade de 7 colunas), cada uma clicável
- `@st.dialog("Detalhe do empenho", width="large")`:
  - `st.columns(4)` de métricas
  - `st.expander` — "Linhas de origem (rastreabilidade)" (`st.dataframe`)

### 2.7 Bolsas e Auxílios (`bolsas_auxilios.py`)
- Header em `st.columns([4, 1.4, 1])`: título | botão relatório | botão "+ Novo programa"
  (`st.popover`)
- CSS próprio (`_inject_css`, prefixo `.bls-*`)
- Faixa de KPIs (`render_metric_grid`, 4 colunas): Despesa Anual Total, Valor Mensal,
  Necessidade de Reforço, Programas, Saldo via Execução Anual
- Cartão "Resumo Consolidado — por Bolsa" (grade HTML `.bls-resumo-row`, "Ver mais"/"Ver
  menos" se >5 linhas)
- Cartão "Cobertura Orçamentária por PTRES" (um cartão `.bls-dotacao-card` por Ação de
  Governo, condicional — só se Dotação Anual disponível)
- Lista "Programas, bolsas e auxílios": um `st.expander` por programa
  (`_render_card`), com dentro:
  - Linha 1: `st.text_input` (Item de Despesa) + `st.selectbox` (Situação TG)
  - Linhas 2–4: campos editáveis em grade de 4/5 colunas (Processo, Unidade, Ação, PTRES,
    Fonte, ND, UGR, PI, NE, Meses/Ano, Qtd. Inicial, Qtd. Efetiva, Valor Unit., Empenhado,
    Meses Empenhados/Liquidados — ou exibição "(Execução Anual)" quando a NE já foi
    localizada — Saldo)
  - Linha de métricas calculadas: Valor Mensal, Meses de Saldo, Empenhar
  - Linha de status: `saldo_execucao`/`valor_empenhado_execucao` (Execução Anual) + tags de
    situação
  - Botão "Remover" (ocultar nesta sessão)
  - "Ver mais"/"Ver menos" se a lista tiver mais de 5 itens
- Diálogo de relatório (`@st.dialog`, `render_botao_relatorio`): tabela editável
  (`st.data_editor`, 4 colunas) + 2 `st.download_button` (PDF detalhado / resumido)

### 2.8 Contratos Contínuos (`contratos_continuos.py`)
- Header em `st.columns([4, 1.4, 1])`: título | botão relatório | botão "+ Novo contrato"
- CSS próprio (`_inject_css`, prefixo `.cc-*`)
- Faixa de KPIs (`render_metric_grid`, 4 colunas): Despesa Anual Total, Despesa Mensal,
  Número de Contratos, Necessidade de Empenho Total
- Cartão "Resumo Consolidado — por NE" (grade HTML `.cc-resumo-row`, "Ver mais"/"Ver menos")
- Cartão "Empenhado × Liquidado" ("Sobra ou Insuficiência no Empenho, por NE", mesma grade)
- Cartão "Cobertura Orçamentária por PTRES" (condicional, mesmo padrão de Bolsas)
- "Carteira de contratos" (subheader): legenda de bolinhas de status (Ativo/Necessita
  reforço/Vencido) + lista de `st.expander` (um por contrato × item de licitação), minimizada
  por padrão (3 cartões, "Ver mais"/"Ver menos"), cada cartão com a mesma estrutura de campo
  editável em grade que Bolsas (mais "Meses Pagos (Pagamentos)")
- Diálogo de relatório (mesmo componente de Bolsas)

### 2.9 Contratos — Vigência (`contratos_vigencia.py`)
- Header
- CSS próprio (`_inject_css`, prefixo `.ct-*`)
- Linha `st.columns([3,1])`: espaço + "Atualizado em ..." + botão "Atualizar dados"
- Banner de defasagem condicional (`.ct-banner`, se dados com ≥2 dias)
- `st.checkbox` — "Mostrar todos os contratos"
- "Filtros" (subheader): `st.columns(4)` (Contrato, Contratado, Término, Dias) +
  `st.columns(3)` (Criticidade, Mensal vigente, Pendências)
- Faixa de KPIs (`st.columns(6)`, `st.metric`): Contratos vigentes, Vencem em 30d, Vencem
  31–120d, Sem termo final, Projeção do exercício, Com pendências
- "Vencimentos por faixa" (subheader): 7 linhas `st.columns([2,6,1])` com `st.progress`
  (rótulo | barra | contagem)
- "Contratos" (subheader) + `st.columns([3,1])` (contagem | `st.selectbox` "Ordenar")
- Tabela em grade HTML/widgets (`st.columns([1.4,2,1.2,1,1,1.2,1.3,0.6])`, 8 colunas:
  Contrato, Contratado, Término, Dias, Criticidade, Mensal vigente, Pendências, botão "Ver")
- "Ver mais" (paginação 20+20)
- "Vigência × Contratos Contínuos" (subheader): grade HTML de 8 colunas comparando as duas
  bases
- `@st.dialog("Detalhe do contrato", width="large")`:
  - Título + badges (situação, criticidade, pendências)
  - `st.columns(4)` de métricas
  - `st.tabs` (6 abas): Visão geral, Linha do tempo, Financeiro, Empenhos, Documentos e
    responsáveis, Auditoria — cada uma com campos editáveis/tabelas próprias

### 2.10 Contratos — Pagamentos (`contratos_pagamentos.py`, fora do menu)
- Header
- CSS próprio (`_inject_css`, prefixo `.pg-*`)
- Faixa de KPIs (`st.columns(5)`): Valor publicado, Pagamentos principais, Contratos
  distintos, Fornecedores distintos, Valor bloqueado
- Linha de filtros (`st.columns([3,1,1,1.2])`): busca + Mês + Qualidade + Ano de referência
- `st.checkbox` condicional — "Somente empenhos relacionados a Contratos Contínuos"
- Lista de cartões por fornecedor (`.pg-*`, `st.container(border=True)`): cabeçalho
  (nome/CNPJ/total) + badges de status + sub-blocos por contrato (mini-tabela Mês
  pagamento/Mês competência/Valor/Empenho/Status)
- "Conciliação com Execução Anual" (subheader): grade HTML de 4 colunas (NE, soma
  planilha, valor pago Execução, diferença)
- "Medição à referência de empenho" (subheader): `st.columns(2)` (Contrato + Competência) →
  cartão com `st.columns(4)` de métricas + badge de status
- Caption (rodapé)

### 2.11 Atualizar Planilhas (`atualizar_planilhas.py`)
Sem CSS próprio — só widgets nativos do Streamlit.
- Header (`st.title` + `st.caption`)
- Subheader "Bases com reimportação versionada" + caption
- 2 cartões (`st.container(border=True)`, um por base: Execução Anual, Dotação Anual):
  - Subheader (nome) + caption (extração atual)
  - `st.expander` "Pasta de entrada" (detecção automática)
  - `st.file_uploader` (upload manual) + fluxo de prévia/confirmação (`st.checkbox` +
    `st.button`)
- Subheader "Planilhas de trabalho" + caption
- 4 cartões (um por base: Contratos Contínuos, Bolsas, Vigência, Pagamentos):
  - Subheader (nome) + caption (arquivo atual/última atualização)
  - `st.file_uploader` + `st.button` "Substituir planilha"

---

## 3. Tokens visuais (conteúdo integral)

### 3.1 `.streamlit/config.toml`

```toml
[server]
fileWatcherType = "none"

[theme]
base = "dark"
primaryColor = "#4C8DFF"
backgroundColor = "#0B1220"
secondaryBackgroundColor = "#121B2D"
textColor = "#E7ECF5"
borderColor = "#232E45"
blueColor = "#4C8DFF"
greenColor = "#22C55E"
yellowColor = "#F5A524"
redColor = "#F0576B"
font = "sans serif"
baseFontSize = 15
baseFontWeight = 400
headingFontSizes = ["32px", "24px", "20px", "16px", "14px", "12px"]
headingFontWeights = [600, 600, 600, 600, 600, 600]
baseRadius = "large"
buttonRadius = "medium"
showWidgetBorder = true
linkUnderline = false

[theme.sidebar]
backgroundColor = "#0E1626"
secondaryBackgroundColor = "#121B2D"
textColor = "#E7ECF5"
borderColor = "#232E45"
```

### 3.2 `src/design_tokens.py` (fonte única de tokens — íntegra)

```python
# --- Cor (tema escuro, acento azul alinhado ao .streamlit/config.toml) ----
BG = "#0B1220"                          # fundo da página (Streamlit base)
BG_GRADIENT_EDGE = "#101A2E"            # realce sutil do gradiente radial de fundo
SIDEBAR_BG = "#0E1626"                  # fundo da sidebar
SURFACE = "#121B2D"                     # fundo de card / expander
SURFACE_ALT = "#1C2537"                 # linha zebrada / hover
BORDER = "#232E45"                      # hairline de card e cabeçalho de tabela
BORDER_SOFT = "rgba(255,255,255,0.07)"  # separador entre linhas da tabela

TEXT = "#E7ECF5"          # texto principal
TEXT_MUTED = "#93A1B8"    # rótulos, códigos, metadados
TEXT_FAINT = "#6E7994"    # placeholders, "—"

ACCENT = "#4C8DFF"                     # acento (= primaryColor)
ACCENT_STRONG = "#7FB0FF"              # números de destaque sobre fundo escuro
ACCENT_SOFT = "rgba(76,141,255,0.14)"  # fills e hovers tintados
ACCENT_LINE = "rgba(76,141,255,0.35)"  # borda de tag

POSITIVE = "#22C55E"   # suplementação
NEGATIVE = "#F0576B"   # cancelamento / remanejamento negativo
WARNING = "#F5A524"

# --- Tipografia ------------------------------------------------------------
FONT_BODY = '"Segoe UI", system-ui, sans-serif'
FONT_HEADING = '"Segoe UI Semibold", "Segoe UI", system-ui, sans-serif'
FONT_MONO_NUM = "font-variant-numeric: tabular-nums;"

SIZE = {
    "micro": "10px", "code": "10.5px", "label": "11px", "meta": "11.5px",
    "small": "12.5px", "body": "13.5px", "value": "13px", "value_strong": "14px",
    "card_title": "23px", "metric": "29px", "brand": "21px",
}
TRACK = {"tight": "0.06em", "label": "0.12em", "kicker": "0.16em"}

# --- Espaçamento / forma ----------------------------------------------------
SPACE = {"xs": "6px", "sm": "10px", "md": "14px", "lg": "18px", "xl": "22px", "xxl": "32px"}
RADIUS = "14px"       # raio dos cartões do app
RADIUS_SM = "10px"
CARD_PAD = "18px 20px 16px"

TABLE_MIN_WIDTH = "1000px"

# --- Grade da tabela de subdivisões (Painel por Ação) ----------------------
SUBDIV_COLUMNS = (
    "minmax(150px, 1.4fr) minmax(110px, 1fr) "
    "minmax(110px, 0.8fr) minmax(100px, 0.7fr) 46px 64px 92px 88px 96px 104px"
)
SUBDIV_GAP = "6px"

# --- Plotly ------------------------------------------------------------------
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family=FONT_BODY, color=TEXT, size=12),
    colorway=[ACCENT, ACCENT_STRONG, POSITIVE, NEGATIVE, TEXT_MUTED],
    xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
    yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
    margin=dict(l=8, r=8, t=28, b=8),
)
```

### 3.3 `src/ui_theme.py` — CSS global (`_THEME_CSS`, aplicado em toda página via `apply_theme()`)

```css
[data-testid="stAppViewContainer"] {
    background: radial-gradient(circle at top left, #101A2E 0%, #0B1220 55%);
}
[data-testid="stHeader"] {
    background: transparent;
    position: static !important;
}
.block-container { max-width: 1480px; padding-top: 1rem; padding-bottom: 3.25rem; }
[data-testid="stMetric"] {
    background: transparent;
    border: 0;
    border-radius: 0;
    padding: 0.15rem 0;
    box-shadow: none;
}
[data-testid="stMetricValue"] { font-weight: 650; letter-spacing: -0.02em; color: #E7ECF5; }
[data-testid="stMetricLabel"] { color: #93A1B8; font-weight: 600; }
[data-testid="stDataFrame"] { border: 1px solid #232E45; border-radius: 14px; overflow: hidden; }

/* Barra lateral em modo "trilho de ícones": 4.5rem por padrão, 21rem no hover */
[data-testid="stSidebar"] {
    background: #0E1626;
    border-right: 1px solid #232E45;
    min-width: 4.5rem !important;
    width: 4.5rem !important;
    transition: width 0.18s ease, min-width 0.18s ease;
}
[data-testid="stSidebar"]:hover {
    min-width: 21rem !important;
    width: 21rem !important;
}
[data-testid="stSidebarContent"] { overflow-x: hidden; }
[data-testid="stSidebarNavLink"] { border-radius: 10px; }
[data-testid="stSidebarNavLink"][aria-current="page"] {
    background: rgba(76,141,255,0.14);
    color: #4C8DFF;
}
[data-testid="stSidebarNavLink"] span[label] {
    display: inline-block;
    max-width: 0;
    opacity: 0;
    overflow: hidden;
    white-space: nowrap;
    transition: max-width 0.18s ease, opacity 0.12s ease;
}
[data-testid="stSidebarNavLink"] span[label] p {
    white-space: nowrap;
    overflow: visible;
    text-overflow: clip;
}
[data-testid="stNavSectionHeader"] {
    opacity: 0;
    max-height: 0;
    overflow: hidden;
    white-space: nowrap;
    transition: opacity 0.12s ease, max-height 0.18s ease;
}
[data-testid="stSidebar"]:hover [data-testid="stSidebarNavLink"] span[label] {
    max-width: 16rem;
    opacity: 1;
}
[data-testid="stSidebar"]:hover [data-testid="stNavSectionHeader"] {
    opacity: 1;
    max-height: 2.5rem;
}

[data-testid="stAlert"] { border-radius: 14px; border-width: 1px; }
[data-testid="stExpander"] {
    background: #121B2D;
    border: 1px solid #232E45;
    border-radius: 14px;
}
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #121B2D;
    border: 1px solid #232E45;
    border-radius: 16px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}
[data-testid="stTabs"] button[role="tab"] { color: #93A1B8; }
[data-testid="stTabs"] button[aria-selected="true"] { color: #4C8DFF; }
[data-testid="stMultiSelectTagsContainer"] { flex-wrap: wrap; row-gap: 0.35rem; }

* { scrollbar-color: #4C8DFF transparent; scrollbar-width: auto; }
::-webkit-scrollbar { width: 40px; height: 40px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background-color: #4C8DFF;
    border-radius: 999px;
    border: 10px solid #0B1220;
    background-clip: padding-box;
    min-height: 96px;
}
::-webkit-scrollbar-thumb:hover {
    background-color: #7FB0FF;
    background-clip: padding-box;
}
```

Funções auxiliares no mesmo arquivo (`src/ui_theme.py`), usadas por quase toda página:
- `render_page_header(title, subtitle=None, context=None)` — `st.title` + `st.caption` +
  `st.badge` (ícone `account_balance`, cor azul).
- `render_alert(message, status="info")` — `st.error`/`st.warning`/`st.success`/`st.info` com
  ícone Material fixo por status.
- `render_metric_grid(metrics, columns=4)` — `st.columns` com `border=True` + `st.metric`,
  no máximo `columns` por linha.
- `format_brl_compact(value)` — ex. `"R$ 3,25 bi"`, `"R$ 762,5 mi"`.
- `format_brl_full(value)` — ex. `"R$ 3.252.795.607,12"`.
- `currency_column(label)` — `st.column_config.NumberColumn` padrão para colunas monetárias.

### 3.4 CSS por página (prefixo de classe próprio, injetado via `st.markdown(unsafe_allow_html=True)`)

| Página | Prefixo | Função |
|---|---|---|
| Painel por Ação | `.po-*` | `_inject_css()` em `painel_acoes.py` |
| Bolsas e Auxílios | `.bls-*` | `_inject_css()` em `bolsas_auxilios.py` |
| Contratos Contínuos | `.cc-*` | `_inject_css()` em `contratos_continuos.py` (mesma estrutura de `.bls-*`) |
| Consulta de Empenhos | `.ce-*` | `_inject_css()` em `consulta_empenhos.py` |
| Contratos — Vigência | `.ct-*` | `_inject_css()` em `contratos_vigencia.py` |
| Contratos — Pagamentos | `.pg-*` | `_inject_css()` em `contratos_pagamentos.py` |
| Dotação, Execução, Empenhos Retardada, Início, Atualizar Planilhas | — | sem CSS próprio, só `_THEME_CSS` + widgets nativos |

**Painel por Ação (`.po-*`)** — cartão de Ação de Governo + grade de subdivisões:

```css
.po-card {
    border: 1px solid #232E45; border-radius: 14px;
    background: #121B2D; padding: 18px 20px 16px;
    margin-bottom: 22px;
}
.po-card-head {
    display: grid; grid-template-columns: minmax(0,1fr) auto;
    gap: 24px; align-items: start; margin-bottom: 14px;
}
.po-kicker { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 13px; letter-spacing: 0.16em; color: #4C8DFF; text-transform: uppercase; }
.po-title {
    margin: 3px 0 8px; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-weight: 600;
    font-size: 23px; line-height: 1.12; color: #E7ECF5;
    text-transform: uppercase; text-wrap: pretty;
}
.po-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.po-tag {
    font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10.5px;
    letter-spacing: 0.1em; text-transform: uppercase; color: #93A1B8;
    border: 1px solid rgba(76,141,255,0.35); border-radius: 14px;
    padding: 2px 7px; background: rgba(76,141,255,0.14);
}
.po-metric-label { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: #93A1B8; }
.po-metric { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 29px; line-height: 1.1; color: #7FB0FF; font-variant-numeric: tabular-nums; }
.po-scroll { overflow-x: auto; padding-bottom: 2px; }
.po-row, .po-head, .po-foot {
    display: grid;
    grid-template-columns: minmax(150px, 1.4fr) minmax(110px, 1fr) minmax(110px, 0.8fr) minmax(100px, 0.7fr) 46px 64px 92px 88px 96px 104px;
    gap: 6px; min-width: 1000px;
}
.po-head { padding-bottom: 6px; border-bottom: 1px solid #232E45; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #93A1B8; }
.po-row { padding: 9px 0; border-bottom: 1px solid rgba(255,255,255,0.07); align-items: baseline; }
.po-foot { padding-top: 9px; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; align-items: baseline; }
.po-name { font-family: "Segoe UI", system-ui, sans-serif; font-size: 13.5px; line-height: 1.25; color: #E7ECF5; overflow-wrap: normal; word-break: normal; }
.po-name-sm { font-family: "Segoe UI", system-ui, sans-serif; font-size: 12.5px; line-height: 1.25; color: #E7ECF5; overflow-wrap: normal; word-break: normal; }
.po-code { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10.5px; letter-spacing: 0.12em; color: #93A1B8; white-space: nowrap; }
.po-flat { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 12.5px; letter-spacing: 0.08em; color: #93A1B8; white-space: nowrap; }
.po-val { text-align: right; font-family: "Segoe UI", system-ui, sans-serif; font-size: 13px; font-variant-numeric: tabular-nums; color: #93A1B8; white-space: nowrap; }
.po-val-strong { text-align: right; font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; color: #7FB0FF; white-space: nowrap; }
.po-foot-label { grid-column: span 6; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: #93A1B8; }
.po-foot-val { text-align: right; font-size: 13.5px; font-variant-numeric: tabular-nums; color: #E7ECF5; white-space: nowrap; }
.po-foot-total { text-align: right; font-size: 15px; font-variant-numeric: tabular-nums; color: #7FB0FF; white-space: nowrap; }
.po-empty { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 16px; letter-spacing: 0.1em; text-transform: uppercase; color: #93A1B8; padding: 40px 0; }
```

**Consulta de Empenhos (`.ce-*`)** — KPIs, cartão de detalhe, listas e consolidação:

```css
.ce-kpis {
    display: grid; grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 1px; background: #232E45; border: 1px solid #232E45;
    margin: 4px 0 18px 0;
}
.ce-kpi { background: #121B2D; padding: 11px 14px 12px 14px; }
.ce-kpi-label { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: #93A1B8; }
.ce-kpi-value { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 24px; line-height: 1.1; font-variant-numeric: tabular-nums; color: #7FB0FF; }
.ce-detail-head { padding: 15px 18px 14px 18px; background: #121B2D; border-bottom: 1px solid #232E45; }
.ce-kicker { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: 0.16em; text-transform: uppercase; color: #93A1B8; }
.ce-ne { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 17px; letter-spacing: 0.01em; color: #E7ECF5; line-height: 1.25; overflow-wrap: anywhere; }
.ce-favorecido { font-size: 12px; color: #93A1B8; margin-top: 3px; overflow-wrap: anywhere; }
.st-key-ce_detail_metrics [data-testid="stMetricValue"] { font-size: 18px; line-height: 1.2; overflow-wrap: anywhere; }
.st-key-ce_detail_metrics [data-testid="stMetricLabel"] { font-size: 10.5px; }
.ce-section-title { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase; color: #93A1B8; padding-bottom: 6px; border-bottom: 1px solid #232E45; margin-top: 12px; }
.ce-cons-head, .ce-cons-row {
    display: grid;
    grid-template-columns: minmax(140px, 2fr) 42px minmax(0, 88px) minmax(0, 88px) minmax(0, 88px) minmax(0, 96px);
    gap: 6px; align-items: baseline;
}
.ce-cons-head { padding-bottom: 6px; border-bottom: 1px solid #232E45; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #93A1B8; }
.ce-cons-row { padding: 9px 0; border-bottom: 1px solid rgba(255,255,255,0.07); }
.ce-cons-name { font-family: "Segoe UI", system-ui, sans-serif; font-size: 13.5px; line-height: 1.25; color: #E7ECF5; }
.ce-cons-code { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10.5px; letter-spacing: 0.12em; color: #93A1B8; }
.ce-cons-val { text-align: right; font-family: "Segoe UI", system-ui, sans-serif; font-size: 13px; font-variant-numeric: tabular-nums; color: #93A1B8; }
.ce-cons-val-strong { text-align: right; font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; color: #7FB0FF; }
.ce-list-head, .ce-list-row {
    display: grid;
    grid-template-columns: minmax(220px, 3fr) 110px 110px 120px;
    gap: 10px; align-items: center;
}
.ce-list-head { padding-bottom: 6px; border-bottom: 1px solid #232E45; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #93A1B8; }
.ce-list-row { padding: 8px 0 8px 8px; border-bottom: 1px solid rgba(255,255,255,0.07); border-left: 3px solid transparent; }
.ce-list-row.is-selected { background: rgba(76,141,255,0.14); border-left-color: #4C8DFF; }
.ce-list-ne { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 13.5px; letter-spacing: 0.06em; color: #E7ECF5; }
.ce-list-obj { font-family: "Segoe UI", system-ui, sans-serif; font-size: 12.5px; color: #93A1B8; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ce-list-fav { font-family: "Segoe UI", system-ui, sans-serif; font-size: 10.5px; color: #6E7994; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ce-list-val { text-align: right; font-family: "Segoe UI", system-ui, sans-serif; font-size: 13px; font-variant-numeric: tabular-nums; color: #93A1B8; }
.ce-list-val-strong { text-align: right; font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; color: #7FB0FF; }
.ce-list-pager { text-align: center; margin-bottom: 6px; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: #93A1B8; }
.st-key-ce_list_mais, .st-key-ce_cons_mais { text-align: center; margin-top: 6px; }
.st-key-ce_list_mais button, .st-key-ce_cons_mais button { padding: 2px 16px; min-height: 0; font-size: 12px; color: #93A1B8; }
.st-key-ce_list_select button { padding: 0px 9px; min-height: 0; height: 26px; font-size: 11px; color: #93A1B8; border-color: #232E45; }
.st-key-ce_list_select button:hover { color: #4C8DFF; border-color: #4C8DFF; }
.st-key-ce_list_select [data-testid="stCheckbox"] { padding-top: 0; }
```

**Bolsas e Auxílios (`.bls-*`) / Contratos Contínuos (`.cc-*`)** — mesma estrutura nas duas
páginas (Contratos Contínuos reaproveita o padrão de Bolsas, só troca o prefixo `bls-`→`cc-`):

```css
.bls-label { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 9.5px; letter-spacing: 0.08em; text-transform: uppercase; color: #93A1B8; margin-bottom: -6px; }
.bls-calc { font-size: 13px; font-variant-numeric: tabular-nums; padding: 8px 0 2px; }
.bls-calc.strong { font-weight: 600; color: #7FB0FF; }
.bls-tag { display: inline-block; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 9.5px; letter-spacing: 0.06em; text-transform: uppercase; padding: 3px 8px; border-radius: 3px; margin: 1px 4px 1px 0; }
.bls-tag.ok { background: rgba(34,197,94,0.12); color: #22C55E; }
.bls-tag.warn { background: rgba(245,165,36,0.12); color: #F5A524; }
.bls-tag.bad { background: rgba(240,87,107,0.12); color: #F0576B; }
.bls-exec { font-size: 11px; color: #93A1B8; }

/* Card "Resumo Consolidado" — mesmo padrão de grade de .po-* */
.bls-resumo-card { border: 1px solid #232E45; border-radius: 14px; background: #121B2D; padding: 18px 20px 16px; margin-bottom: 22px; }
.bls-resumo-head { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 24px; align-items: start; margin-bottom: 14px; }
.bls-resumo-kicker { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 13px; letter-spacing: 0.16em; color: #4C8DFF; text-transform: uppercase; }
.bls-resumo-title { margin: 3px 0 0; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-weight: 600; font-size: 23px; line-height: 1.12; color: #E7ECF5; }
.bls-resumo-metric-label { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: #93A1B8; }
.bls-resumo-metric { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 29px; line-height: 1.1; color: #7FB0FF; font-variant-numeric: tabular-nums; }
.bls-resumo-scroll { overflow-x: auto; padding-bottom: 2px; }
.bls-resumo-row, .bls-resumo-head-row, .bls-resumo-foot { display: grid; grid-template-columns: minmax(200px,2fr) 120px 120px 150px; gap: 10px; min-width: 560px; }
.bls-resumo-head-row { padding-bottom: 6px; border-bottom: 1px solid #232E45; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #93A1B8; }
.bls-resumo-row { padding: 9px 0; border-bottom: 1px solid rgba(255,255,255,0.07); align-items: baseline; }
.bls-resumo-foot { padding-top: 9px; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; align-items: baseline; }
.bls-resumo-name { font-family: "Segoe UI", system-ui, sans-serif; font-size: 13.5px; line-height: 1.25; color: #E7ECF5; }
.bls-resumo-code { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10.5px; letter-spacing: 0.12em; color: #93A1B8; }
.bls-resumo-val { text-align: right; font-family: "Segoe UI", system-ui, sans-serif; font-size: 13px; font-variant-numeric: tabular-nums; color: #93A1B8; }
.bls-resumo-val-strong { text-align: right; font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; color: #7FB0FF; }
.bls-resumo-foot-label { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: #93A1B8; }

/* Card "Cobertura Orçamentária por PTRES" — 5 colunas (Plano Orç., PTRES, Dotação, Despesa, Saldo) */
.bls-dotacao-card { border: 1px solid #232E45; border-radius: 14px; background: #121B2D; padding: 18px 20px 16px; margin-bottom: 18px; }
.bls-dotacao-card-head { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 24px; align-items: start; margin-bottom: 14px; }
.bls-dotacao-kicker { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 13px; letter-spacing: 0.16em; color: #4C8DFF; text-transform: uppercase; }
.bls-dotacao-title { margin: 3px 0 0; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-weight: 600; font-size: 23px; line-height: 1.12; color: #E7ECF5; text-transform: uppercase; text-wrap: pretty; }
.bls-dotacao-metric-label { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: #93A1B8; }
.bls-dotacao-metric { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 29px; line-height: 1.1; font-variant-numeric: tabular-nums; }
.bls-dotacao-scroll { overflow-x: auto; padding-bottom: 2px; }
.bls-dotacao-row, .bls-dotacao-head-row, .bls-dotacao-foot { display: grid; grid-template-columns: minmax(200px,2fr) 90px 130px 130px 130px; gap: 10px; min-width: 700px; }
.bls-dotacao-head-row { padding-bottom: 6px; border-bottom: 1px solid #232E45; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #93A1B8; }
.bls-dotacao-row { padding: 9px 0; border-bottom: 1px solid rgba(255,255,255,0.07); align-items: baseline; }
.bls-dotacao-foot { padding-top: 9px; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; align-items: baseline; }
.bls-dotacao-name { font-family: "Segoe UI", system-ui, sans-serif; font-size: 12.5px; line-height: 1.25; color: #E7ECF5; }
.bls-dotacao-code { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10.5px; letter-spacing: 0.12em; color: #93A1B8; }
.bls-dotacao-flat { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 12.5px; letter-spacing: 0.08em; color: #93A1B8; }
.bls-dotacao-val { text-align: right; font-family: "Segoe UI", system-ui, sans-serif; font-size: 13px; font-variant-numeric: tabular-nums; color: #93A1B8; }
.bls-dotacao-val-strong { text-align: right; font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
.bls-dotacao-foot-label { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: #93A1B8; }
```

**Contratos — Vigência (`.ct-*`)**:

```css
.ct-kicker { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: #93A1B8; }
.ct-label { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 9px; letter-spacing: .08em; text-transform: uppercase; color: #93A1B8; }
.ct-badge { display: inline-block; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 9.5px; letter-spacing: .04em; text-transform: uppercase; padding: 2px 7px; border-radius: 3px; margin: 0 4px 4px 0; }
.ct-banner { padding: 9px 14px; border: 1px solid #F5A524; background: #F5A5241A; color: #F5A524; font-size: 12.5px; border-radius: 4px; }
.st-key-cv_tabela div[data-testid="stVerticalBlockBorderWrapper"] { border: 1px solid #232E45 !important; border-radius: 4px; background: #121B2D; }
.st-key-cv_comparacao div[data-testid="stVerticalBlockBorderWrapper"] { border: 1px solid #232E45 !important; border-radius: 4px; background: #121B2D; }
```

**Contratos — Pagamentos (`.pg-*`)**:

```css
.pg-kicker { font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 10px; letter-spacing: .16em; text-transform: uppercase; color: #93A1B8; }
.pg-badge { display: inline-block; font-family: "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif; font-size: 9.5px; letter-spacing: .05em; text-transform: uppercase; padding: 2px 8px; border-radius: 3px; margin: 2px 4px 0 0; }
.pg-col-label { font-size: 9.5px; color: #93A1B8; }
.st-key-pg_cards div[data-testid="stVerticalBlockBorderWrapper"] { border: 1px solid #232E45 !important; border-radius: 8px; background: #121B2D; }
```

---

## 4. Componentes recorrentes

### 4.1 Cartão de KPI (`render_metric_grid`, `src/ui_theme.py`)
- **Onde é definido**: função única, reaproveitada por Dotação, Painel por Ação, Execução (via HTML próprio — ver 4.7), Bolsas, Contratos Contínuos.
- **Variação**: número de colunas (`columns`, padrão 4); `subtitle` opcional abaixo do valor.
- **Estado único** — não tem variação visual por status; usa `st.metric` nativo dentro de
  `st.columns(border=True)`. Cor do valor: `TEXT` (#E7ECF5), cor do rótulo: `TEXT_MUTED`
  (#93A1B8).

### 4.2 Badge/tag de status (`_badge`, padrão repetido — não uma função compartilhada, cada
página reimplementa)
- **Onde**: `contratos_vigencia.py::_badge`, `contratos_pagamentos.py::_badge`, classes
  `.bls-tag`/`.cc-tag`/`.ct-badge`/`.pg-badge`.
- **Padrão visual**: `<span>` com `background: {cor}22` (opacidade ~13%) + `color: {cor}`
  sólida — nunca preenchimento sólido.
- **Variações por significado** (ver seção 5 para o mapeamento completo de cor):
  - Positivo/OK/Bate: `POSITIVE` (#22C55E)
  - Atenção/Alerta: `WARNING` (#F5A524) ou `ACCENT_STRONG` (#7FB0FF, usado como "Alerta" em Pagamentos)
  - Negativo/Vencido/Diverge/Bloqueado: `NEGATIVE` (#F0576B)
  - Neutro/Indeterminado/Duplicado: `TEXT_MUTED` (#93A1B8)

### 4.3 "Ver mais" / "Ver menos" (paginação incremental)
- **Onde**: Consulta de Empenhos (lista + consolidação), Empenhos Retardada, Contratos —
  Vigência, Resumo Consolidado (Bolsas/Contratos Contínuos), lista de programas/contratos
  (Bolsas/Contratos Contínuos).
- **Padrão**: `st.session_state` guarda a quantidade visível (`QTD_INICIAL_*`); "Ver mais"
  soma `QTD_INCREMENTO_*`; "Ver menos" (onde existe) volta para `QTD_INICIAL_*`. Botão
  `st.button`, sem estilo de link.
- **Variação**: nem toda lista tem "Ver menos" (só onde foi pedido explicitamente:
  Resumo Consolidado, listas de Bolsas/Contratos Contínuos/Contratos — Vigência).

### 4.4 Cabeçalho de grupo expansível (`st.expander`)
- **Onde**: cartão por contrato/bolsa (Bolsas, Contratos Contínuos), "Pasta de entrada"
  (Atualizar Planilhas), "Filtros por atributo" (Consulta de Empenhos, Empenhos Retardada),
  "Linhas de origem" (Empenhos Retardada).
- **Estilo**: `[data-testid="stExpander"]` global — fundo `SURFACE`, borda `BORDER`, raio
  `RADIUS` (14px). Rótulo do expander (cartão de contrato/bolsa) é gerado dinamicamente com
  emoji de status: 🟢 ativo sem reforço, 🟡 necessita reforço, 🔴 vencido/sem empenho.

### 4.5 Diálogo modal (`@st.dialog`)
- **Onde**: Contratos — Vigência (`_abrir_detalhe`, `width="large"`), Empenhos Retardada
  (detalhe do empenho, `width="large"`), Relatório de Reforço de Empenho (Bolsas/Contratos
  Contínuos, `width="large"`).
- **Padrão**: título + badges de status no topo → `st.columns` de métricas → conteúdo
  principal (abas `st.tabs` no caso de Vigência; tabela editável no caso do relatório).

### 4.6 Linha de tabela em grade CSS (não `st.dataframe`)
- **Onde**: praticamente toda tabela "de negócio" do app (Painel por Ação, Resumo
  Consolidado, Consulta de Empenhos, Contratos — Vigência, Contratos — Pagamentos) — decisão
  deliberada documentada no código: `st.dataframe` "lia como planilha" (grid do
  glide-data-grid, fora do alcance do CSS do app).
- **Padrão**: `display: grid` com `grid-template-columns` fixo (larguras `minmax(...)`
  específicas por página) + linha de cabeçalho com a mesma grade, texto uppercase, cor
  `TEXT_MUTED`, tamanho `SIZE['micro']` (10px). `st.dataframe` nativo só aparece em: tabelas
  de detalhe dentro de diálogos (histórico de termos, linhas de origem de NE) e "Composição"
  (Execução Orçamentária).

### 4.7 Campo de formulário editável em grade (cartões de Bolsas/Contratos Contínuos/Vigência)
- **Onde**: `_render_card`/`_abrir_detalhe` de Bolsas, Contratos Contínuos, Contratos —
  Vigência.
- **Padrão**: rótulo pequeno (`.bls-label`/`.cc-label`/`.ct-label`, uppercase, 9–9.5px,
  `TEXT_MUTED`) diretamente acima do widget (`st.text_input`/`st.number_input`, sem o rótulo
  nativo do Streamlit — `label_visibility="collapsed"`), em grades de 4–5 colunas.
- **Variação de estado**: campos vindos da Execução Anual (saldo, meses empenhados/liquidados
  quando a NE já foi localizada) viram **exibição somente leitura** (mesma tipografia, sem
  borda de input) em vez de editáveis — rótulo ganha o sufixo "(Execução Anual)".

### 4.8 Botão "+ Novo" (`st.popover`)
- **Onde**: Bolsas ("+ Novo programa"), Contratos Contínuos ("+ Novo contrato") — canto
  superior direito, ao lado do título.
- **Padrão**: `st.popover(icon=":material/add:", width=380)` contendo um `st.form` com
  `clear_on_submit=True`.

---

## 5. Mapa de cores por significado

| Cor (hex/rgba) | Token | Significado | Onde aparece |
|---|---|---|---|
| `#0B1220` | `BG` | Fundo de página (decorativa) | Fundo base de todo app |
| `#101A2E` | `BG_GRADIENT_EDGE` | Realce decorativo do gradiente | Canto superior esquerdo do fundo |
| `#0E1626` | `SIDEBAR_BG` | Fundo da barra lateral (decorativa) | Sidebar |
| `#121B2D` | `SURFACE` | Fundo de cartão/expander (decorativa) | Todo `st.container(border=True)`, `st.expander`, cartões HTML |
| `#1C2537` | `SURFACE_ALT` | Hover/zebra (decorativa) | Reservada — não vi uso ativo nas páginas atuais |
| `#232E45` | `BORDER` | Hairline estrutural (decorativa) | Bordas de cartão, cabeçalho de tabela, divisor de sidebar |
| `rgba(255,255,255,0.07)` | `BORDER_SOFT` | Divisor sutil entre linhas (decorativa) | Separador de linha em toda grade CSS |
| `#E7ECF5` | `TEXT` | Texto principal (semântica: conteúdo primário) | Títulos, valores de métrica, nomes |
| `#93A1B8` | `TEXT_MUTED` | Texto secundário (semântica: metadado/rótulo) | Rótulos uppercase, códigos, legendas, KPI label |
| `#6E7994` | `TEXT_FAINT` | Texto terciário (semântica: ausência de dado) | Placeholders, "—" |
| `#4C8DFF` | `ACCENT` | **Acento de marca/navegação** (semântica: interativo/selecionado) | Item de menu ativo, ícones de badge de contexto, scrollbar |
| `#7FB0FF` | `ACCENT_STRONG` | **Destaque numérico** (semântica: valor calculado em evidência) | Métrica grande de cartão (`.po-metric`, `.bls-resumo-metric`), valor forte de tabela; também usado como "Alerta" (não erro) em Pagamentos |
| `rgba(76,141,255,0.14)` | `ACCENT_SOFT` | Fill/hover tintado (semântica: seleção) | Fundo de item de menu ativo, fundo de linha selecionada (Consulta de Empenhos), fundo de tag |
| `rgba(76,141,255,0.35)` | `ACCENT_LINE` | Borda de tag (semântica: seleção secundária) | Borda de `.po-tag` |
| `#22C55E` | `POSITIVE` | **Semântica: positivo/OK/dentro do esperado** | Suplementação orçamentária (gráfico Dotação), tag "No prazo"/"Bate"/"Ativo"/"Publicado"/"Sem pendências" |
| `#F0576B` | `NEGATIVE` | **Semântica: negativo/erro/crítico** | Cancelamento/remanejamento negativo (gráfico Dotação), tag "Vencido"/"Crítico"/"Diverge"/"Bloqueado"/"Com pendências" |
| `#F5A524` | `WARNING` | **Semântica: atenção intermediária** | Tag "Atenção" (Vigência), banner de planilha desatualizada, faixa de vencimento 31–120 dias |

**Cores decorativas** (não carregam significado de dado — só compõem a superfície visual):
`BG`, `BG_GRADIENT_EDGE`, `SIDEBAR_BG`, `SURFACE`, `SURFACE_ALT`, `BORDER`, `BORDER_SOFT`.

**Cores semânticas** (mudam conforme o estado do dado): `ACCENT`/`ACCENT_SOFT`/`ACCENT_LINE`
(seleção/interatividade), `ACCENT_STRONG` (destaque de valor), `POSITIVE`/`NEGATIVE`/`WARNING`
(semáforo de status — único trio de "cor por significado" no sentido estrito de
verde/amarelo/vermelho).

Observação para o designer: **não existe uma paleta separada para gráficos** — o Plotly reusa
exatamente os mesmos tokens (`PLOTLY_LAYOUT.colorway = [ACCENT, ACCENT_STRONG, POSITIVE,
NEGATIVE, TEXT_MUTED]`).

---

## 6. Bibliotecas de UI

| Biblioteca | Uso | Páginas |
|---|---|---|
| **Streamlit** (nativo) | Framework base — todos os widgets de formulário, `st.dataframe`, `st.metric`, `st.tabs`, `st.dialog`, `st.popover`, `st.expander`, `st.container` | Todas |
| **Plotly** (`plotly.graph_objects`, via `st.plotly_chart`) | Único gráfico de terceiros do app — linha/área (Dotação), barras agrupadas (Execução, Série Histórica) | Dotação Orçamentária, Execução Orçamentária |
| **reportlab** | Geração de PDF (relatório de Reforço de Empenho) — não é UI renderizada na tela, só o arquivo baixado | Bolsas, Contratos Contínuos (via `st.download_button`) |
| HTML/CSS customizado (`st.markdown(unsafe_allow_html=True)`) | Cartões, grades de tabela, badges — ver seções 2–4 | Painel por Ação, Bolsas, Contratos Contínuos, Consulta de Empenhos, Contratos — Vigência, Contratos — Pagamentos |

**Não usados neste projeto**: `streamlit-aggrid`, Altair, `streamlit-plotly-events`,
`streamlit-elements`, ou qualquer outro pacote de componente customizado de terceiros. Toda a
interatividade de tabela "rica" (seleção, grupo, expansão) é construída à mão com
`st.columns`/HTML + `st.session_state`, não com um grid de terceiros.

---

## 7. Dados de exemplo

Colunas exatas (nome interno, em `snake_case`) e 2 linhas reais (dados públicos de execução
orçamentária, extração de 26/08/2026) para as bases principais.

### 7.1 Execução Anual — agregado por NE (`agregar_por_ne` + `saldo_por_ne`, usado em Execução Orçamentária; `saldo_por_ne`/`detalhar_nota_empenho` também reaproveitados, sem alteração, por Empenhos com Execução Retardada — que desde 22/09/2026 agrega pela Execução Mensal, mesmo contrato de colunas, não pela Execução Anual)

Colunas: `ne_ccor, ano, iduso_cod, iduso_desc, resultado_primario_cod, resultado_primario_desc, categoria_economica_cod, categoria_economica_desc, acao_cod, acao_desc, elemento_cod, elemento_desc, fonte_cod, fonte_desc, gnd_cod, gnd_desc, natureza_despesa_cod, natureza_despesa_desc, pi_cod, pi_desc, po_acao_cod, po_cod, po_desc, ptres, ug_executora_cod, ug_executora_desc, ug_responsavel_cod, ug_responsavel_desc, ugr_cod, ugr_desc, ne_favorecido, natureza_detalhada_label, subitem_resumo, empenhada, liquidada, paga, ne_descricao, processo_ne, saldo`

| ne_ccor | ano | acao_cod | elemento_desc | ne_favorecido | empenhada | liquidada | paga | saldo |
|---|---|---|---|---|---|---|---|---|
| 153165152392025NE000690 | 2025 | 20RK | OUTROS SERVIÇOS DE TERCEIROS PJ - OP.INT.ORC. | OI S.A. - EM RECUPERAÇÃO JUDICIAL | 0,00 | (nulo) | (nulo) | 0,00 |
| 153165152392026NE000006 | 2026 | 20RK | OUTROS SERVIÇOS DE TERCEIROS - P.FÍSICA | UNIVERSIDADE FEDERAL RURAL DE PERNAMBUCO | 6.000,00 | 3.325,00 | 3.325,00 | 2.675,00 |

### 7.2 Dotação Anual (`consolidated_data`, usado em Dotação Orçamentária, Painel por Ação)

Colunas: `arquivo_origem, aba_origem, linha_origem, coluna_origem, ano_lancamento, iduso_codigo, iduso_descricao, resultado_primario_codigo, resultado_primario_descricao, grupo_despesa_codigo, grupo_despesa_descricao, acao_codigo, acao_descricao, ptres_codigo, fonte_recursos_detalhada_codigo, fonte_recursos_detalhada_descricao, plano_orcamentario_codigo, plano_orcamentario_descricao, item_informacao_origem, item_informacao_codigo, valor_movimento_liquido`

| ano_lancamento | acao_codigo | grupo_despesa_descricao | ptres_codigo | item_informacao_codigo | valor_movimento_liquido |
|---|---|---|---|---|---|
| 2020 | 0181 | PESSOAL E ENCARGOS SOCIAIS | 186652 | dotacao_atualizada | 42.058.157,00 |
| 2021 | 20RK | OUTRAS DESPESAS CORRENTES | 169903 | dotacao_atualizada | 274.252,58 |

### 7.3 Contratos Contínuos (`ler_contratos_continuos` + `com_saldo_execucao`)

Colunas: `ano_contrato, contrato_numero, processo_contratacao, processo_empenho, fornecedor, tipo_contrato, tipo_despesa, fornecedor_cnpj_cpf, vigencia_fim, status_contrato, unidade_cod, acao_cod, ptres, fonte_cod, natureza_despesa_cod, ugr_cod, pi_cod, tem_varios_itens, ne_curta, meses_de_saldo, meses_empenhados, meses_liquidados, item_licitacao, item_percentual, despesa_mensal, despesa_anual, valor_empenhado, saldo_colado_planilha, meses_a_empenhar, valor_a_empenhar` (+ após `com_saldo_execucao`: `saldo_execucao, diverge_saldo, valor_empenhado_execucao, valor_empenhado_planilha_total_ne, diverge_valor_empenhado, meses_empenhados_execucao, meses_liquidados_execucao, necessidade_via`)

| contrato_numero | fornecedor | status_contrato | ne_curta | despesa_mensal | valor_empenhado | saldo_colado_planilha |
|---|---|---|---|---|---|---|
| 28/2021 | Sim Gestão Ambiental Serviços Ltda | ATIVO | 2026NE000083 | 5.540,10 | 33.240,58 | 1.008,22 |
| 29/2024 | Brascon Gestão Ambiental Ltda | ATIVO | 2026NE000094 | 17.698,80 | 106.192,80 | 39.221,85 |

### 7.4 Bolsas e Auxílios (`ler_bolsas_auxilios` + `com_saldo_execucao`)

Colunas: `processo, programa_bolsa, unidade_cod, acao_cod, ptres, fonte_cod, natureza_despesa_cod, ugr_cod, pi_cod, ne_curta, tem_saldo, meses_de_saldo, meses_empenhados, meses_liquidados, meses_no_ano, qtd_inicial, qtd_efetiva, valor_unitario, valor_mensal, valor_anual, valor_empenhado_tg, saldo_colado_planilha, situacao_tg, ocorrencias_tg, meses_a_empenhar, valor_a_empenhar`

| processo | programa_bolsa | ne_curta | qtd_efetiva | valor_mensal | valor_empenhado_tg | saldo_colado_planilha | situacao_tg |
|---|---|---|---|---|---|---|---|
| 001167/2026-78 | AUXÍLIOS PARA DESENVOLVIMENTO DE ESTUDOS E PESQUISA (AJUDA DE CUSTO PARA AULA PRÁTICA) | 2026NE000057 | 1 | 30.000,00 | 217.000,00 | 86.723,00 | ATUALIZADO |
| 002429/2026-11 | PROGRAMA DE ENSINO PRESENCIAL E REMOTO DE IDIOMAS (BOLSA PEPRI) | 2026NE000232 | 3 | 2.100,00 | 11.200,00 | 1.400,00 | ATUALIZADO |

### 7.5 Contratos — Vigência (`consolidar_por_contrato`, um por número de contrato)

Colunas: `numero_contrato, ano_contrato, contratado, cnpj_cpf, objeto, classificacao_objeto, natureza_objeto, tipo_despesa, unidade_gestora, termo_atual, finalidade_termo_atual, termo_final, dias_para_vencer, criticidade, valor_mensal, valor_anual, gestor, email_gestor, garantia_status, arquivo_pdf, qtd_termos, alertas, linha_origem_atual`

| numero_contrato | contratado | termo_final | dias_para_vencer | criticidade | valor_mensal |
|---|---|---|---|---|---|
| 34/2012 | WALTER LUIZ OLIVEIRA DO VALE | 2015-07-31 | -4044 | Vencido | (nulo) |
| 35/2024 | SERVAL SERVIÇOS E LIMPEZA LTDA | 2026-06-16 | -71 | Vencido | 697.420,44 |

### 7.6 Contratos — Pagamentos (`ler_pagamentos`, ano 2026)

Colunas: `contrato_raw, competencia_raw, emissao_raw, nf, cnpj_raw, fornecedor, valor, empenho, unidade, processo, mes_planilha, mes_ordem, linha_origem, contrato, cnpj, emissao, anos_empenho, nes_empenho, mes_pagamento, mes_competencia, chave_duplicidade, ocorrencia, duplicado, alertas, status`

| contrato | fornecedor | valor | empenho | mes_planilha | status |
|---|---|---|---|---|---|
| 014/22 | INTELIGÊNCIA SEGURANÇA PRIVADA LTDA - EPP | 73.836,53 | 26NE000111 | Março | Publicado |
| 014/20 | PRIME CONSULTORIA E ASSESSORIA EMPRESARIAL | 3.023,46 | 26NE000112 | Maio | Publicado |
