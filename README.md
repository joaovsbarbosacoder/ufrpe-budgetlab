# UFRPE BudgetLab

Aplicação local em Python e Streamlit para apoiar a gestão e a análise
orçamentária da Universidade Federal Rural de Pernambuco (UFRPE).

O projeto está em sua etapa inicial. A aplicação permite importar e inspecionar
arquivos Excel, normalizar bases reconhecidas do Tesouro Gerencial e analisar
seus movimentos sem presumir identidades contábeis entre itens.

## Funcionalidades

Toda base do projeto usa o mesmo padrão de **importação versionada**: um
manifesto (`data/manifestos/`) com hash SHA-256, data de extração e totais
por exercício — é o manifesto, não o arquivo bruto, que fica versionado.
Cada página de análise lê o manifesto atual da sua base direto (nunca
`st.session_state`) e oferece sua própria seção "Reimportar base", com
prévia (contagens, totais, validação, comparação com a extração anterior) e
gravação só após confirmação explícita quando a mudança altera um exercício
já fechado ou faz um exercício desaparecer. A mecânica comum (manifesto,
delta entre extrações, política de confirmação) vive em
`src/importacao_versionada.py` e `src/ui_reimportacao.py`, compartilhada
pelas duas bases; cada uma só define sua própria leitura, validação e
medidas (`src/importacao_execucao.py`, `src/importacao_dotacao.py`).

### Visão geral

A página inicial funciona como painel operacional: informa quantas das bases
cadastradas estão disponíveis localmente, a atualização mais recente entre
elas e a situação dos prazos orçamentários cadastrados. Esses indicadores não
combinam valores financeiros de extrações diferentes. A página também oferece
acessos diretos aos principais módulos de planejamento, operação e controle.

### Dotação Anual (BI CPOC - Por Ano)

Uma única aba organiza os lançamentos por ano (não por mês), com blocos
dimensionais que usam mesclagem real de células no Excel (não repetição de
valor). O reconhecimento localiza dinamicamente a
coluna-âncora "Item Informação" na linha 1 — que sempre precede o par de
colunas de Plano Orçamentário — e interpreta os blocos dimensionais à
esquerda dela pelas mesclagens de cabeçalho de 3 linhas. Isso permite
reconhecer variantes que apenas inserem ou removem um bloco dimensional (por
exemplo, uma exportação sem Grupo de Despesa), sem exigir uma nova
assinatura fixa para cada variante. Um bloco dimensional fora do conjunto
conhecido reprova o reconhecimento em vez de ser ignorado.

A normalização resolve as mesclagens reais da planilha (não usa forward
fill heurístico): uma célula só herda o valor do topo do bloco se estiver de
fato dentro de um intervalo mesclado confirmado pelo Excel. Itens monetários
não mapeados não são descartados — recebem um código `item_nao_mapeado_*` e
geram aviso.

A validação independente compara a matriz bruta e a base normalizada (soma
total, soma por item, por ano e por ano+item, contagens de nulos/zeros/
negativos e igualdade por coordenada). Como as somas desta base chegam à
casa dos bilhões, a tolerância é de centavos (`0,01`), não de milionésimos:
nessa magnitude o próprio `float64` acumula ruído de representação bem acima
de `0,000001` mesmo sem nenhuma divergência real de dado.

Esta é a base que alimenta as páginas **Dotação Orçamentária** e **Painel
por Ação de Governo**, ambas lendo `Manifesto.atual()` de
`src/importacao_dotacao.py`.

### Execução Anual (BI PROPLAD - Por Ano)

Tem importação própria e versionada (`src/importacao_execucao.py`),
acionada pela seção "Reimportar base" da própria página **Execução
Orçamentária**.

A página **Execução Orçamentária** mostra, sobre o recorte filtrado
(Exercício, GND, Fonte, Resultado Primário, UGR): cartões de Empenhado,
Liquidado e Pago com os percentuais de execução; uma série histórica em
barras agrupadas por exercício, com o exercício em andamento marcado
visualmente; composição por uma dimensão por vez (GND, Fonte, Ação,
Natureza Detalhada, Resultado Primário, UG Responsável, UGR, PI, PTRES,
Plano Orçamentário ou Favorecido), com ranking limitado às 15 maiores
categorias quando a dimensão tem alta cardinalidade; e rastreabilidade por
Nota de Empenho, exibindo as linhas de origem (`linha_origem`).

Layout de origem, regras de reconciliação e decisões de arquitetura estão
em `docs/base_execucao_anual.md`.

### Emendas Parlamentares

O relatório **Emendas — Acompanhamento** possui leitor específico em
`src/tesouro_emendas_acompanhamento.py`. Ele preserva as mesclagens reais,
códigos como texto e a distinção entre nulo, zero e negativo. A granularidade
é exercício × emenda × PTRES × GND; uma emenda pode possuir vários PTRES.

`src/emendas_parlamentares.py` cruza o cadastro com a Execução Anual por
`(exercício, RP, PTRES)`. Exercícios anteriores a 2026 permanecem estáticos;
de 2026 em diante, Empenhado, Liquidado e Pago vêm da Execução quando há
vínculo. Execução sem emenda identificada e PTRES sem execução são devolvidos
como lacunas explícitas.

A página **Emendas Parlamentares** usa a carga histórica inicial recebida,
sem dados fictícios. A importação versionada em `src/importacao_emendas.py`
compõe as extrações por exercício: a carga inicial conserva todo o histórico,
enquanto uploads posteriores são aceitos somente com exercícios a partir de
2026. Assim, uma atualização que traga apenas 2026 substitui somente 2026 e
mantém 2016–2025 intactos. Cada bruto recebe nome com hash e nunca sobrescreve
outro upload. O painel também permite cadastro manual de emendas 2026+ com
múltiplos PTRES e preserva esses registros em `data/emendas/`. Na fila de
pendências, a execução RP6/RP7/RP8 sem emenda pode ser vinculada a uma emenda
existente ou a uma nova emenda. Esses vínculos também são limitados a 2026+ e
usam um log de eventos em `data/emendas/vinculos/`: desfazer acrescenta um
novo evento, sem apagar o original. Se um relatório posterior passar a trazer
o mesmo `(exercício, RP, PTRES)`, o dado oficial absorve o vínculo manual sem
duplicar a execução; conflitos com outra emenda permanecem explícitos.

O contrato completo está em `docs/base_emendas_acompanhamento.md`.

### Dotação Orçamentária

A página **Dotação Orçamentária** lê `Manifesto.atual()` de
`src/importacao_dotacao.py` (não `st.session_state`). Ela mostra:

- filtros por Ano de lançamento, Ação Governo, PTRES, Plano Orçamentário,
  Grupo de Despesa, Fonte de Recursos Detalhada, IDUSO e Resultado Primário;
- cartões com os quatro indicadores conhecidos (Dotação Inicial,
  Suplementar, Atualizada, Cancelada/Remanejada), cada um somado
  isoladamente, sem identidade algébrica presumida entre eles;
- um gráfico interativo (Plotly) de evolução por ano — curva suave
  preenchida, com seletor para trocar o indicador exibido; o exercício em
  andamento (derivado da data de extração do manifesto) aparece com
  marcador diferenciado e "⏳" no rótulo;
- a seção "Reimportar base", mesmo componente (`src/ui_reimportacao.py`) e
  mesma política de confirmação que a Execução Anual usa.

Não há tabela bruta linha a linha nesta página; a granularidade de origem
(arquivo/aba/linha/coluna) continua preservada na base normalizada, só não
é exposta diretamente na interface.

### Painel por Ação de Governo

A página **Painel por Ação de Governo** também lê o manifesto atual da
Dotação Anual. Apresenta um cartão por Ação de Governo, com as subdivisões
(combinação de Plano Orçamentário, Fonte, Grupo de Despesa, Resultado
Primário, IDUSO e PTRES) em uma tabela compacta dentro do cartão, ordenadas
pela Dotação Atualizada. Os quatro indicadores conhecidos aparecem nas
colunas da tabela e nos totais de rodapé de cada cartão, todos somados
isoladamente. Valor nulo (célula ausente na origem) aparece como "—"; valor
zero aparece como `0` — os dois estados nunca são confundidos. O seletor de
Ano marca o exercício em andamento com "⏳".

### Despesas de Pessoal

A página **Despesas de Pessoal** usa a estrutura do HTML
`design_handoff_streamlit/acompanhamento-pessoal.dc.html`: cabeçalho com data-base,
quatro indicadores, faixa de situação, tabela única de rubricas com grupos
expandidos na própria tabela e tabela de saldos mensais. A primeira coluna fica
fixa durante a rolagem horizontal. Os valores são das bases locais, não do exemplo
de design. O componente usa HTML/CSS/JavaScript local, sem dependência do runtime
externo do arquivo de referência.

Clique no nome de um grupo para recolher ou expandir suas rubricas; na data-base
para escolher o mês e o exercício da dotação; e em um valor projetado de rubrica
para editá-lo. As edições ficam em memória, na sessão e na referência escolhida,
e podem ser restauradas pelo rodapé. Meses executados permanecem protegidos.

A fonte do realizado é a Liquidada da Execução Mensal. As regras existentes
em `src/despesas_pessoal.py` alimentam os meses futuros. Execução Anual, Dotação
Anual e Execução Mensal são lidas pelos seus manifestos (importação versionada,
`src/importacao_execucao_mensal.py`). As datas das extrações são independentes
e ficam informadas no rodapé.

Dotação por rubrica aparece como “—”, pois a base não oferece essa dimensão.
Benefício Especial e Precatórios preservam os lugares previstos no layout, com
mapeamento pendente e valores ausentes, sem inventar zeros ou reclassificar dados.
Outros Benefícios conserva as ações 2004/212B. A execução histórica exibida nas
rubricas é comparada ao total da base anual no mesmo escopo, com diferença explícita.
13º e férias aparecem sem Base PLOA individual, conforme o layout; o grupo conserva
a soma do mês de referência. Os cálculos de férias e 13º existentes não foram
revisados nesta mudança de apresentação.

### Limitações atuais

- não há soma, reconciliação ou identidade rígida entre itens de dotação;
- o acompanhamento de pessoal compara sua projeção com a Dotação Atualizada;
  isso não constitui uma reconciliação entre extrações de mesma data.
  A integração geral entre bases continua limitada pela ambiguidade temporal (granularidade mês x
  ano nas exportações mensais do Tesouro Gerencial, hoje fora do projeto;
  ausência de um "as of" comum entre extrações de bases diferentes); ver
  `docs/base_execucao_anual.md`;
- cada base tem seu próprio manifesto versionado (`data/manifestos/`); não
  há banco de dados nem view unificada entre bases.

## Visual e tema

A interface usa exclusivamente uma área de trabalho clara com navegação lateral
azul persistente, inspirada em painéis administrativos institucionais. Não há
alternância para modo escuro. As cores, tipografia e
espaçamentos ficam centralizados em `src/design_tokens.py`; `src/ui_theme.py`
consome esses tokens para o CSS global e os helpers reutilizáveis
(`render_page_header`, `render_alert`, `render_metric_grid`,
`format_brl_compact`, `format_brl_full`). `.streamlit/config.toml` reflete os
mesmos tokens de cor de fundo, superfície e texto.

## Preparação do ambiente

Requer Python 3.10 ou superior.

No Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Execução

```powershell
streamlit run app.py
```

### Migração dos cadastros nativos

Bolsas e Auxílios e Contratos Contínuos usam cadastros JSON locais, separados das planilhas
de trabalho originais. O comando oficial executa por padrão somente uma simulação: lê as
duas planilhas, monta os cadastros em diretórios temporários, confere contagens, totais e
hashes e não grava em `data/bolsas_auxilios/` nem em `data/contratos_continuos/`.

```powershell
python -m scripts.migrar_cadastros_nativos
```

Depois de revisar a saída, use `--aplicar` para promover os dois cadastros validados:

```powershell
python -m scripts.migrar_cadastros_nativos --aplicar
```

O comando nunca sobrescreve um exercício existente. Caminhos e exercício podem ser informados
explicitamente com `--bolsas`, `--contratos`, `--ano`, `--diretorio-bolsas` e
`--diretorio-contratos`. As planilhas de origem são somente lidas e seus hashes são conferidos
novamente antes de qualquer gravação.

## Estrutura do projeto

```text
ufrpe-budgetlab/
|-- app.py                          # Ponto de entrada da interface Streamlit
|-- app_pages/                      # Páginas da interface
|   |-- home.py
|   |-- dotacao_orcamentaria.py     # Fonte: Dotação Anual; inclui reimportação
|   |-- painel_acoes.py             # Cartões por Ação de Governo (Dotação Anual)
|   `-- execucao_orcamentaria.py    # Fonte: Execução Anual (BI PROPLAD); inclui reimportação
|-- design_handoff_streamlit/       # Material de referência do handoff visual
|-- requirements.txt                # Dependências Python do projeto
|-- README.md                       # Documentação e instruções de uso
|-- src/
|   |-- design_tokens.py            # Tokens de cor/tipografia/espaçamento
|   |-- dotacao_anual_analysis.py   # Filtros e agregações da Dotação Anual
|   |-- execucao_anual.py           # Leitura, validação e agregação da Execução Anual (BI PROPLAD)
|   |-- importacao_dotacao.py       # Especificação da Dotação Anual sobre o núcleo genérico
|   |-- importacao_emendas.py       # Carga histórica e atualizações 2026+ de Emendas
|   |-- importacao_execucao.py      # Especificação da Execução Anual sobre o núcleo genérico
|   |-- importacao_versionada.py    # Núcleo genérico: manifesto, delta, política de confirmação
|   |-- tesouro_dotacao_anual.py    # Reconhecimento e normalização da Dotação Anual
|   |-- tesouro_dotacao_anual_validation.py
|   |-- tesouro_dotacao_anual_workbook.py
|   |-- ui_reimportacao.py          # Componente "Reimportar base", reutilizado pelas duas bases
|   `-- ui_theme.py                 # Componentes visuais reutilizáveis
|-- data/
|   |-- manifestos/                 # Manifestos versionados de cada base (hash, extração, totais)
|   |-- processed/                  # Dados tratados e padronizados
|   `-- raw/                        # Dados originais, sem transformação
`-- tests/
```

Os arquivos brutos em `data/raw/` e `data/processed/` não são versionados
(`.gitkeep` mantém só a estrutura das pastas vazias); os manifestos em
`data/manifestos/` são pequenos e versionados normalmente — são o registro
de procedência de cada base, não dado bruto.

## Testes

```powershell
python -m unittest discover -s tests -v
```

## Evolução prevista

A arquitetura deverá acomodar gradualmente:

- projeção de insuficiência orçamentária;
- acompanhamento de contratos e bolsas;
- DEA;

Esses componentes serão incorporados conforme as regras de negócio forem
definidas, mantendo a interface Streamlit separada do processamento em `src/`.
