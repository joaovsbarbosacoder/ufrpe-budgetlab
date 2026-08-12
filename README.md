# UFRPE BudgetLab

Aplicação local em Python e Streamlit para apoiar a gestão e a análise
orçamentária da Universidade Federal Rural de Pernambuco (UFRPE).

O projeto está em sua etapa inicial. A aplicação permite importar e inspecionar
arquivos Excel, normalizar bases reconhecidas do Tesouro Gerencial e analisar
seus movimentos sem presumir identidades contábeis entre itens.

## Funcionalidades

### Importação de Bases

A página **Importação de Bases** aceita arquivos `.xlsx` e `.xls`, lê o
arquivo somente em memória e reconhece a Dotação Anual (BI CPOC - Por Ano).
Ela não é identificada pelo nome do arquivo ou da aba — o reconhecimento
depende exclusivamente da assinatura estrutural da base. O arquivo enviado
não é alterado nem gravado localmente.

A Execução Anual (BI PROPLAD - Por Ano) não passa por este fluxo — tem
importação própria, versionada em disco (ver "Execução Anual" abaixo).

Para cada base reconhecida, a página mostra o status de reconhecimento, o
resultado da validação de integridade e, quando aprovada, disponibiliza o
conjunto normalizado para as páginas de análise através da sessão do
Streamlit. Bases não reconhecidas ou com inconsistências não ficam
disponíveis para análise.

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

Esta é hoje a base que alimenta a página **Dotação Orçamentária**.

### Execução Anual (BI PROPLAD - Por Ano)

Diferente da Dotação Anual, a Execução Anual não passa pelo fluxo de upload
em memória da Importação de Bases: tem importação própria e versionada
(`src/importacao_execucao.py`), acionada pela seção "Reimportar base" da
própria página **Execução Orçamentária**. Cada importação gera um manifesto
(`data/manifestos/`) com hash SHA-256, data de extração (do `mtime` do
arquivo) e totais por exercício — é o manifesto, não o arquivo bruto, que
fica versionado; a política é de substituição total, sem merge entre
extrações.

Se a nova extração altera um exercício já fechado ou faz um exercício
desaparecer, a interface exige confirmação explícita antes de gravar,
mostrando exatamente o que mudou; nos demais casos (exercício novo, avanço
do exercício corrente), a substituição é gravada direto, só com o resumo.
Validação com erro sempre bloqueia a importação.

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

### Dotação Orçamentária

A página **Dotação Orçamentária** usa exclusivamente a base de **Dotação
Anual** validada na sessão. Ela mostra:

- filtros por Ano de lançamento, Ação Governo, PTRES, Plano Orçamentário,
  Grupo de Despesa, Fonte de Recursos Detalhada, IDUSO e Resultado Primário;
- cartões com os quatro indicadores conhecidos (Dotação Inicial,
  Suplementar, Atualizada, Cancelada/Remanejada), cada um somado
  isoladamente, sem identidade algébrica presumida entre eles;
- um gráfico interativo (Plotly) de evolução por ano — curva suave
  preenchida, com seletor para trocar o indicador exibido.

Não há tabela bruta linha a linha nesta página; a granularidade de origem
(arquivo/aba/linha/coluna) continua preservada na base normalizada em
memória, só não é exposta diretamente na interface.

### Painel por Ação de Governo

A página **Painel por Ação de Governo** também usa a base de Dotação Anual
validada na sessão. Apresenta um cartão por Ação de Governo, com as
subdivisões (combinação de Plano Orçamentário, Fonte, Grupo de Despesa,
Resultado Primário, IDUSO e PTRES) em uma tabela compacta dentro do cartão,
ordenadas pela Dotação Atualizada. Os quatro indicadores conhecidos
aparecem nas colunas da tabela e nos totais de rodapé de cada cartão, todos
somados isoladamente. Valor nulo (célula ausente na origem) aparece como
"—"; valor zero aparece como `0` — os dois estados nunca são confundidos.

### Limitações atuais

- não há soma, reconciliação ou identidade rígida entre itens de dotação;
- nenhuma página cruza Dotação com Execução hoje — a integração está
  suspensa pela ambiguidade temporal entre as bases (granularidade mês x
  ano, ausência de marcador de exercício parcial na Dotação, sem data de
  extração registrada); ver `docs/base_execucao_anual.md`;
- persistência em disco hoje se limita aos manifestos versionados da
  Execução Anual (`data/manifestos/`); não há banco de dados nem
  versionamento para as demais bases.

## Visual e tema

A interface usa tema escuro. As cores, tipografia e espaçamentos ficam
centralizados em `src/design_tokens.py`; `src/ui_theme.py` consome esses
tokens (sem hexadecimais soltos) para o CSS global e os helpers reutilizáveis
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

## Estrutura do projeto

```text
ufrpe-budgetlab/
|-- app.py                          # Ponto de entrada da interface Streamlit
|-- app_pages/                      # Páginas da interface
|   |-- home.py
|   |-- importacao_bases.py
|   |-- dotacao_orcamentaria.py     # Fonte: Dotação Anual
|   |-- painel_acoes.py             # Cartões por Ação de Governo (Dotação Anual)
|   `-- execucao_orcamentaria.py    # Fonte: Execução Anual (BI PROPLAD); inclui reimportação
|-- design_handoff_streamlit/       # Material de referência do handoff visual
|-- requirements.txt                # Dependências Python do projeto
|-- README.md                       # Documentação e instruções de uso
|-- src/
|   |-- design_tokens.py            # Tokens de cor/tipografia/espaçamento
|   |-- dotacao_anual_analysis.py   # Filtros e agregações da Dotação Anual
|   |-- excel_importer.py           # Leitura e diagnóstico inicial de Excel
|   |-- execucao_anual.py           # Leitura, validação e agregação da Execução Anual (BI PROPLAD)
|   |-- importacao_execucao.py      # Manifesto versionado, substituição total, delta entre extrações
|   |-- tesouro_dotacao_anual.py    # Reconhecimento e normalização da Dotação Anual
|   |-- tesouro_dotacao_anual_validation.py
|   |-- tesouro_dotacao_anual_workbook.py
|   `-- ui_theme.py                 # Componentes visuais reutilizáveis
|-- data/
|   |-- manifestos/                 # Manifestos versionados da Execução Anual (hash, extração, totais)
|   |-- processed/                  # Dados tratados e padronizados
|   `-- raw/                        # Dados originais, sem transformação
`-- tests/
```

Os arquivos brutos em `data/raw/` e `data/processed/` não são versionados
(`.gitkeep` mantém só a estrutura das pastas vazias); os manifestos em
`data/manifestos/` são pequenos e versionados normalmente — são o registro
de procedência da Execução Anual, não dado bruto.

## Testes

```powershell
python -m unittest discover -s tests -v
```

## Evolução prevista

A arquitetura deverá acomodar gradualmente:

- projeção de insuficiência orçamentária;
- acompanhamento de contratos e bolsas;
- DEA;
- emendas parlamentares.

Esses componentes serão incorporados conforme as regras de negócio forem
definidas, mantendo a interface Streamlit separada do processamento em `src/`.
