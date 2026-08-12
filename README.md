# UFRPE BudgetLab

Aplicação local em Python e Streamlit para apoiar a gestão e a análise
orçamentária da Universidade Federal Rural de Pernambuco (UFRPE).

O projeto está em sua etapa inicial. A aplicação permite importar e inspecionar
arquivos Excel, normalizar bases reconhecidas do Tesouro Gerencial e analisar
seus movimentos sem presumir identidades contábeis entre itens.

## Funcionalidades

### Importação de Bases

A página **Importação de Bases** aceita arquivos `.xlsx` e `.xls`, lê o
arquivo somente em memória e reconhece, de forma independente, três bases:
Dotação do Tesouro Gerencial (mensal), Execução da Despesa do Tesouro
Gerencial e Dotação Anual (BI CPOC - Por Ano). Nenhuma delas é identificada
pelo nome do arquivo ou da aba — o reconhecimento depende exclusivamente da
assinatura estrutural de cada base. O arquivo enviado não é alterado nem
gravado localmente.

Para cada base reconhecida, a página mostra o status de reconhecimento, o
resultado da validação de integridade e, quando aprovada, disponibiliza o
conjunto normalizado para as páginas de análise através da sessão do
Streamlit. Bases não reconhecidas ou com inconsistências não ficam
disponíveis para análise.

### Dotação do Tesouro Gerencial (mensal)

Para abas que correspondem à assinatura estrutural confirmada de Dotação
mensal, a aplicação normaliza a matriz de valores (colunas JAN/AAAA a
DEZ/AAAA) em formato longo, uma linha por célula monetária original,
identificada por arquivo, aba, linha e coluna Excel. As colunas `013/AAAA` e
`014/AAAA` são preservadas na matriz bruta, mas excluídas da normalização e
das análises; sua quantidade e soma ficam disponíveis para auditoria.

Uma rotina de validação independente compara a matriz original e o
DataFrame longo (contagens de nulos/zeros/negativos, soma total, soma por
período, por Item Informação e por período+item, e igualdade célula a
célula), com tolerância absoluta de `0,000001`.

Itens de Dotação desconhecidos não são descartados: o texto original é
mantido e um código previsível com prefixo `item_nao_mapeado_` é gerado.

O processamento é multiaba: cada aba é reconhecida, normalizada e validada
independentemente, e as abas reconhecidas são consolidadas em um único
DataFrame em memória, preservando `arquivo_origem`, `aba_origem`,
`linha_origem` e `coluna_origem`.

Esta base hoje alimenta a página **Visão Orçamentária**; não é mais a fonte
da página **Dotação Orçamentária** (ver abaixo).

### Dotação Anual (BI CPOC - Por Ano)

Formato distinto do mensal: uma única aba organiza os lançamentos por ano
(não por mês), com blocos dimensionais que usam mesclagem real de células no
Excel (não repetição de valor). O reconhecimento localiza dinamicamente a
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

### Execução da Despesa do Tesouro Gerencial

O núcleo de Execução reconhece, normaliza e valida em memória a assinatura
estrutural confirmada da exportação anual de despesas (duas linhas de
cabeçalho, dimensões em `A:AI`, medidas `AJ:AL`: empenhado, liquidado e
pago). É independente do módulo de Dotação e ainda não possui tela analítica
própria — alimenta apenas a página **Visão Orçamentária**.

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

### Visão Orçamentária

A página **Visão Orçamentária** requer uma base validada de Dotação
(mensal) e outra de Execução, ambas mantidas em memória na sessão. Mostra
Dotação Atualizada, Empenhado, Liquidado e Pago para o mesmo recorte de
filtros comuns (IDUSO, Resultado Primário, Ação Governo, Plano Orçamentário,
Grupo de Despesa, Fonte de Recursos Detalhada e PTRES). Não há junção linha
a linha: cada indicador é agregado diretamente a partir de sua origem. A
página não calcula saldo, insuficiência ou relações entre as medidas.

#### Limitações atuais

- não há soma, reconciliação ou identidade rígida entre itens de dotação;
- a página Dotação Orçamentária não cruza Dotação com Execução (isso existe
  apenas em Visão Orçamentária, sem cálculo de saldo);
- não há persistência, banco de dados ou tratamento de outras bases
  orçamentárias nesta etapa.

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
|   `-- visao_orcamentaria.py       # Fonte: Dotação mensal + Execução
|-- design_handoff_streamlit/       # Material de referência do handoff visual
|-- requirements.txt                # Dependências Python do projeto
|-- README.md                       # Documentação e instruções de uso
|-- src/
|   |-- design_tokens.py            # Tokens de cor/tipografia/espaçamento
|   |-- dotacao_analysis.py         # Filtros e agregações da Dotação mensal
|   |-- dotacao_anual_analysis.py   # Filtros e agregações da Dotação Anual
|   |-- dotacao_export.py           # Exportação Excel auditável (Dotação mensal)
|   |-- excel_importer.py           # Leitura e diagnóstico inicial de Excel
|   |-- execucao_analysis.py        # Estado analítico validado da Execução
|   |-- tesouro_dotacao.py          # Tratamento da Dotação mensal
|   |-- tesouro_dotacao_validation.py
|   |-- tesouro_dotacao_workbook.py
|   |-- tesouro_dotacao_anual.py    # Reconhecimento e normalização da Dotação Anual
|   |-- tesouro_dotacao_anual_validation.py
|   |-- tesouro_dotacao_anual_workbook.py
|   |-- tesouro_execucao.py
|   |-- tesouro_execucao_validation.py
|   |-- tesouro_execucao_workbook.py
|   |-- ui_theme.py                 # Componentes visuais reutilizáveis
|   `-- visao_orcamentaria.py       # Agregação conjunta por recorte comum
|-- data/
|   |-- raw/                        # Dados originais, sem transformação
|   `-- processed/                  # Dados tratados e padronizados
`-- tests/
```

Os arquivos de dados locais não são versionados. Os arquivos `.gitkeep` em
`data/` mantêm no repositório apenas a estrutura das pastas vazias.

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
