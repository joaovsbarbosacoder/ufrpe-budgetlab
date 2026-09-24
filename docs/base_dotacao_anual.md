# Base ANUAL de Dotação — especificação e regras

> Documento de contrato da base. Ler antes de qualquer alteração no leitor, na validação ou nas
> abas **Dotação Orçamentária** e **Painel por Ação de Governo**. Extração analisada: recebida em
> 11/08/2026, 284 linhas de dimensão × 7.952 linhas normalizadas, exercícios 2020–2026.

## 1. Identificação

| Item | Valor |
|---|---|
| Origem | BI CPOC / Tesouro Gerencial — "DOTAÇÃO - Por Ano" |
| Arquivo recebido | `BI CPOC - DOTAÇÃO - Por Ano (1).xlsx` |
| Abas | 1 (única), nome não fixo — reconhecimento é pela estrutura, não pelo nome |
| Colunas | 41 (13 de dimensão + 28 monetárias: 7 exercícios × 4 indicadores) |
| Linhas de dimensão | 284 (a partir da linha 4 da planilha) |
| Linhas normalizadas | 7.952 (284 × 28 células monetárias, uma linha por célula) |
| Granularidade temporal | **anual** — uma coluna por exercício, não por mês |

## 2. Layout físico

O cabeçalho ocupa **três linhas**, com **mesclagem real de células do Excel** (não repetição de
valor) para os blocos dimensionais — diferente da Execução Anual, que repete o rótulo em cada
linha:

- **Linha 1**: rótulo de cada bloco dimensional (`Iduso`, `Resultado Primário Lei`, `Grupo
  Despesa`, `Ação Governo`, `PTRES`, `Fonte Recursos Detalhada`), mesclado sobre as colunas do
  bloco; e o rótulo de cada indicador monetário (`DOTAÇÃO INICIAL`, `SUPLEMENTAR`, `ATUALIZADA`,
  `CANCELADA E REMANEJADA`), uma coluna por combinação indicador × exercício.
- **Linha 2**: vazia nos blocos dimensionais; o exercício (ano) de cada coluna monetária.
- **Linha 3**: vazia nos blocos dimensionais; `"Movim. Líquido - R$ (Item Informação)"` em cada
  coluna monetária.
- **Linha 4 em diante**: dados. Blocos dimensionais mesclados verticalmente quando o valor se
  repete entre linhas adjacentes (ex.: duas linhas da mesma Ação de Governo).

O reconhecimento (`src/tesouro_dotacao_anual.py`) localiza a coluna-âncora rotulada **"Item
Informação"** — que sempre precede o par de colunas de Plano Orçamentário e antecede a matriz
monetária — e interpreta os blocos à esquerda dela pelas mesclagens reais de cabeçalho. Isso
permite reconhecer variantes que inserem ou removem um bloco dimensional inteiro (ex.: uma
exportação sem `Grupo Despesa`) sem exigir uma nova assinatura fixa para cada variante — um
bloco fora do conjunto conhecido reprova o reconhecimento em vez de ser ignorado silenciosamente.

A normalização resolve as mesclagens **de verdade**: uma célula só herda o valor do topo do
bloco se estiver dentro de um intervalo mesclado confirmado pelo Excel — nunca um forward-fill
heurístico que arriscaria herdar valor de uma linha não relacionada.

## 3. A regra que muda tudo: quatro indicadores, nunca somados entre si

Cada célula monetária pertence a exatamente um dos quatro indicadores conhecidos
(`KNOWN_ITEM_INDICATORS` em `src/dotacao_anual_analysis.py`):

| Código | Rótulo |
|---|---|
| `dotacao_inicial` | Dotação inicial |
| `dotacao_suplementar` | Dotação suplementar |
| `dotacao_atualizada` | Dotação atualizada |
| `dotacao_cancelada_remanejada` | Dotação cancelada/remanejada |

Consequências obrigatórias:

1. **Nunca presuma identidade algébrica entre indicadores.** `Inicial + Suplementar +
   Cancelada/Remanejada = Atualizada` pode ser verdade na prática, mas o projeto não afirma isso
   — cada indicador é somado isoladamente, nas páginas e nas agregações.
2. **Nulo ≠ zero.** Uma combinação de dimensões pode não ter valor para um indicador num exercício
   (célula vazia na planilha) — isso é ausência de movimento, não `R$ 0,00`. Toda agregação usa
   `sum(min_count=1)` para preservar nulo; só converte para exibição depois.
3. Itens monetários fora dos quatro conhecidos não são descartados — recebem um código
   `item_nao_mapeado_*` previsível e geram aviso, mesmo padrão da Execução Anual.

## 4. Fatos verificados na extração

- Zero duplicatas nas coordenadas de origem (`arquivo_origem`/`aba_origem`/`linha_origem`/
  `coluna_origem`).
- Cardinalidades por dimensão (extração de referência): IDUSO 4, Resultado Primário 4, Grupo de
  Despesa (GND) 3, Ação de Governo 21, Fonte de Recursos Detalhada 52, Plano Orçamentário 25,
  PTRES 141.
- `Dotação Cancelada/Remanejada` é negativa por natureza (redução de crédito) — preservar, nunca
  filtrar como se fosse erro.
- A validação independente compara a matriz bruta e a base normalizada (soma total, soma por
  item, por ano e por ano+item, contagens de nulos/zeros/negativos, igualdade por coordenada).
  Tolerância de centavos (`0,01`), não de milionésimos: nessa magnitude (bilhões de reais) o
  próprio `float64` acumula ruído de representação acima de `0,000001` sem nenhuma divergência
  real de dado — mesmo raciocínio e mesma tolerância da Execução Anual.

## 5. Reimportação: como a base é atualizada

Mesma política da Execução Anual, sobre o núcleo genérico compartilhado
(`src/importacao_versionada.py`):

- **Composição por exercício** — cada extração é a verdade completa *para os exercícios que
  traz*; um exercício ausente da extração nova mantém o último dado importado (`carregar_atual`).
  Sem merge linha a linha dentro de um mesmo exercício. Se o xlsx de um exercício sumir de
  `data/raw/` (pasta fora do Git), `carregar_atual` levanta `ArquivoHistoricoAusente` nomeando
  ano(s) e arquivo, e "Atualizar Planilhas" mostra a "Procedência por exercício".
- **Data de referência** — vem da data de modificação do arquivo (`mtime`) no momento em que ele
  é gravado em disco. Para uploads pela interface, isso é o momento do upload (o navegador não
  preserva o `mtime` do arquivo original) — mesma limitação já documentada para a Execução Anual.
- **Identidade da extração** — hash SHA-256 do arquivo. Reimportar o mesmo arquivo é idempotente.

O manifesto (`data/manifestos/dotacao_anual_atual.json` + histórico) grava hash, data de
extração, exercícios, totais por indicador e por exercício, e contagens estruturais
(`abas_reconhecidas`, `linhas_normalizadas`, `nulos`, `zeros`, `negativos`) — formato genérico
(`contagens` aninhado), diferente do formato antigo específico da Execução Anual (ver
`src/importacao_versionada.py`, docstring do módulo).

O delta classifica as mudanças com o mesmo critério da Execução Anual — exercício novo/avanço são
informativos; exercício anterior alterado ou exercício que some exigem confirmação explícita na
interface antes de gravar (`exige_confirmacao`, por campos estruturados do delta, não por texto
do alerta).

### Efeito nos testes

`tests/test_importacao_dotacao.py` reaproveita as fixtures já existentes de
`tests/test_tesouro_dotacao_anual.py` e `tests/test_dotacao_session_flow.py` (removido neste
passo, junto com a página de upload em memória) para testar a leitura, reconciliação e validação
adaptadas ao núcleo genérico, sem reimplementar nem duplicar as checagens estruturais que já
existiam. `tests/test_dotacao_orcamentaria_reimportacao.py` cobre os três caminhos do gate
(retroatividade, exercício removido, avanço sem gate) com fixtures sintéticas de duas
colunas-ano — a Dotação Anual guarda um indicador por coluna-ano, então duas colunas do mesmo
indicador com anos diferentes já reproduzem os três cenários sem precisar editar um arquivo de
milhares de linhas.

## 6. Números de reconciliação da extração de referência

| Exercício | Inicial | Suplementar | Atualizada | Cancelada/Remanejada |
|---|---:|---:|---:|---:|
| 2020 | 647.253.612,00 | 121.222.424,00 | 661.615.140,00 | -106.860.896,00 |
| 2021 | 694.272.633,00 | 316.835.167,00 | 654.455.308,00 | -356.652.492,00 |
| 2022 | 649.073.904,00 | 16.883.209,00 | 656.031.880,00 | -9.932.233,00 |
| 2023 | 652.529.348,00 | 89.357.403,00 | 734.927.983,00 | -6.958.768,00 |
| 2024 | 736.741.668,00 | 40.985.352,00 | 747.154.183,00 | -30.572.837,00 |
| 2025 | 747.163.606,00 | 106.379.332,00 | 851.526.938,00 | -2.016.000,00 |
| 2026 * | 908.319.687,00 | 14.454.280,00 | 921.773.967,00 | -1.000.000,00 |
| **Total** | **5.035.354.458,00** | **706.117.167,00** | **5.227.485.399,00** | **-513.993.226,00** |

\* 2026 é **exercício em andamento** na data da extração (mesmo critério da Execução Anual:
ano da `data_extracao` do manifesto). A interface marca 2026 com "⏳" no seletor de ano
(Painel por Ação) e no gráfico de evolução (Dotação Orçamentária) — nunca fica visualmente
igual a um exercício fechado.

Hash da extração de referência: `5e299b17` (manifesto completo em
`data/manifestos/dotacao_anual_atual.json`).

## 7. Arquivos e onde tudo mora

| Arquivo | Papel |
|---|---|
| `src/tesouro_dotacao_anual.py` | reconhecimento dinâmico de blocos mesclados + normalização (camada de leitura) |
| `src/tesouro_dotacao_anual_validation.py` | validação independente (matriz bruta × normalizada) |
| `src/tesouro_dotacao_anual_workbook.py` | processamento multiaba, consolidação |
| `src/dotacao_anual_analysis.py` | filtros e agregações (`build_item_indicators`, `build_dotacao_anual_year_analysis`, `build_dotacao_anual_subdivision_analysis`) |
| `src/importacao_dotacao.py` | especificação sobre o núcleo genérico: manifesto, delta, importação versionada |
| `src/importacao_versionada.py` | núcleo genérico (compartilhado com a Execução Anual) |
| `src/ui_reimportacao.py` | componente "Reimportar base" (compartilhado com a Execução Anual) |
| `tests/test_tesouro_dotacao_anual*.py`, `test_dotacao_anual_analysis.py` | reconhecimento, normalização, agregação |
| `tests/test_importacao_dotacao.py` | adaptação ao núcleo genérico |
| `tests/test_dotacao_orcamentaria_page.py`, `test_painel_acoes_page.py`, `test_dotacao_orcamentaria_reimportacao.py` | páginas |

### API

```python
leitura = ler_dotacao_anual(caminho)          # LeituraDotacaoAnual: .workbook, .conteudo
r       = reconciliar_dotacao_anual(leitura)  # anos, totais, totais_por_ano, contagens
rel     = validar_dotacao_anual(leitura)      # .ok, .erros, .alertas

# importação versionada
res  = importar("data/raw/BI CPOC - DOTAÇÃO - Por Ano (1).xlsx")
res.manifesto             # hash, data_extracao, totais por exercício
res.delta.resumo_texto()  # o que mudou desde a última importação
res.delta.alertas         # mudança retroativa, exercício removido
historico_como_tabela()   # uma linha por importação já feita
```

## 8. O que as abas mostram

**Dotação Orçamentária** (`app_pages/dotacao_orcamentaria.py`): filtros por Ano de lançamento,
Ação Governo, PTRES, Plano Orçamentário, Grupo de Despesa, Fonte de Recursos Detalhada, IDUSO e
Resultado Primário; cartões com os quatro indicadores, cada um somado isoladamente; gráfico de
evolução por ano (curva suave, indicador selecionável), com o exercício em andamento marcado por
símbolo diferenciado e "⏳" no eixo; rodapé de procedência (data de extração + hash); seção
"Reimportar base".

**Painel por Ação de Governo** (`app_pages/painel_acoes.py`): um cartão por Ação de Governo, com
as subdivisões (combinação de Plano Orçamentário, Fonte, Grupo de Despesa, Resultado Primário,
IDUSO e PTRES) numa tabela compacta dentro do cartão, ordenadas pela Dotação Atualizada. Valor
nulo aparece como "—"; valor zero aparece como `0`. O seletor de Ano marca o exercício em
andamento com "⏳" e um aviso adicional aparece quando ele está selecionado.

O que **não** fazer nestas abas: cruzar com Execução (integração suspensa pela ambiguidade
temporal entre as bases — ver `docs/base_execucao_anual.md`, seção 8), presumir identidade
algébrica entre os quatro indicadores, e persistir em DuckDB — etapa posterior já sequenciada no
projeto.
