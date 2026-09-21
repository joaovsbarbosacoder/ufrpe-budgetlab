# Base MENSAL de Execução da Despesa — especificação e regras

> Documento de contrato da base. Ler antes de qualquer alteração no leitor ou na regra de
> deduplicação. Extração de referência ATUAL: recebida em 21/09/2026, 5.773 linhas brutas,
> abas 2024/2025/2026 (`tests/fixtures/execucao_mensal_2026-09-21.xlsx`). Layout anterior
> (aba única, extração de 03/09/2026) documentado na seção 9, "Histórico de layout" — não é
> mais lido pelo leitor atual.

Esta base cobre **2024 em diante**, por mês, em abas separadas por exercício (ver seção 9 —
até 21/09/2026 cobria só 2026+; o usuário decidiu ampliar para 2024-2026 quando o layout
mudou para multi-aba). A Base ANUAL (`docs/base_execucao_anual.md`, origem BI PROPLAD)
continua existindo separadamente — nenhuma reconciliação entre as duas foi definida ainda;
não presuma qual prevalece para um mesmo ano/NE sem confirmar.

## 1. Identificação

| Item | Valor |
|---|---|
| Origem | BI CPOC / Tesouro Gerencial — "EXEC. DESPESAS - Por Ano", variante com quebra mensal |
| Abas | 1 por exercício (nome da aba = ano, ex. `"2026"`) — quantidade não fixa, lidas todas dinamicamente |
| Colunas | 41 dimensionais (posições 0–40) + 3 por bloco mensal presente na aba (Empenhada, Liquidada, Paga) |
| Linhas de dados | 5.773 na extração de referência (a partir da linha 7 de cada aba) |
| Granularidade temporal | **mensal** (`ano_mes` = ano×100+mês); `ano` vem do nome da aba, não é mais coluna de dado |
| UG Executora | constante: 153165 — UFRPE |

## 2. Layout físico

Cada aba tem **2 linhas de banner de relatório** ("Páginas:", "Ano Lançamento: AAAA") + 1
linha em branco, depois um cabeçalho de **três linhas** (linhas 4-6 da aba):

- **Linha 4**: rótulos de grupo das dimensões, mais o rótulo do bloco (`"JAN/2026"`,
  `"013/2025"` — encerramento, ver abaixo — ...) repetido 3× por bloco a partir da coluna 41
  (0-indexada).
- **Linha 5**: `"Item Informação"` sobreposto na coluna 39 (a coluna `ne_item_cod`) +
  `"DESPESAS EMPENHADAS/LIQUIDADAS/PAGAS (CONTROLE EMPENHO)"` repetido por bloco.
- **Linha 6**: `"NE Item"` sobreposto na mesma coluna 39 + `"Movim. Líquido - R$ (Item
  Informação)"` repetido por bloco.
- **Linha 7 em diante**: dados. Tudo em texto, inclusive valores.

Ler com `header=None, skiprows=6, dtype=str` (banner + cabeçalho = 6 linhas). **Nunca
hardcodar a quantidade de blocos nem de abas**: a extração ganha um bloco novo a cada mês que
passa, e o leitor itera `pd.ExcelFile(caminho).sheet_names` inteiro, não uma lista fixa de
anos. Blocos rotulados com 3 dígitos numéricos em vez de mês (`"013/2025"`, `"014/2025"` —
período de encerramento de exercício, natureza exata não confirmada) são reconhecidos e
**descartados deliberadamente**, decisão do usuário (21/09/2026) — não é erro de layout, mas
também não entram no resultado. Detecção em `_blocos_mensais`/`_rotulo_mes`/
`_PADRAO_ROTULO_ENCERRAMENTO` (`src/tesouro_execucao_mensal.py`).

### Mapa posicional (colunas dimensionais, 0-indexadas)

Idêntico à Base Anual (ver `docs/base_execucao_anual.md`, seção 2) até a posição 25
(`PTRES`). A partir daí, DUAS dimensões novas frente à Base Anual E ao layout antigo desta
base (seção 9):

| # | Coluna |
|---|---|
| 26–27 | **Unidade Orçamentária** (código, descrição) — dimensão nova |
| 28–33 | UG Executora, UG Responsável, UGR (como na Base Anual) |
| 34 | NE - Núm. Processo (`processo_ne`) |
| 35 | **NE - Informação Complementar** (`ne_informacao_complementar`) — dimensão nova, só existe nesta base (Base Anual não tem) |
| 36–38 | NE - Descrição, NE CCor, NE CCor - Favorecido (como na Base Anual) |
| 39–40 | **NE Item** (código, descrição) — ver seção 3 |
| 41+ | blocos mensais (Empenhada, Liquidada, Paga) × N blocos |

## 3. NE Item: o que é e o que NÃO é

Cada empenho pode ter uma ou mais linhas de **item** dentro dele — o que está sendo
comprado/pago naquela nota. Exemplos reais da extração de referência:

- Elemento **30** (Material de Consumo): item = produto de compra real, ex. `"Item compra:
  00201 - PAPEL FILME, MATERIAL PVC..."`, `"Item compra: 00202 - COADOR DESCARTAVEL
  CAFE..."`.
- Elemento **01** (Pessoal/Aposentadorias, folha de pagamento): item = rubrica fixa da folha,
  ex. `"PROVENTOS - PESSOAL CIVIL - FOLHA DE PAGAMENTO"`, `"13 SALARIO - PESSOAL CIVIL -
  FOLHA DE PAGAMENTO"`.

**`NE Item` descreve O QUE foi comprado — não QUANTO desse item específico foi empenhado.**
O valor "Empenhada" de um mês aparece **idêntico, repetido**, em toda linha de item que
compartilha a mesma `(NE, Natureza Despesa Detalhada, Subitem)` — é o total daquele bloco
(aquela fatia orçamentária do empenho, naquele mês), não um valor por item. Confirmado
manualmente (ver seção 5): uma NE de folha de pagamento com 7 itens repete o mesmo valor
mensal 7×; uma NE de material de consumo com 100 itens de compra repete o mesmo valor 100×.

**Consequência obrigatória**: somar "Empenhada" direto pelas linhas de item multiplica o
valor pela quantidade de itens do bloco. A soma correta agrupa por
`(ne_ccor, natureza_detalhada_cod, subitem_cod, ano_mes)` e pega o valor **uma vez** por
grupo antes de somar — é isso que `valor_empenhado_por_bloco()` faz.

Sentinela: `ne_item_cod = "-9"` / `ne_item_desc = "SEM INFORMACAO"` marca ausência de item
(mesmas linhas de "item de execução" que a Base Anual já tem, `NE - Descrição = "NAO SE
APLICA"` — ver seção 4).

## 4. A regra que já vinha da Base Anual: dois tipos de linha

Mesma regra da Base Anual (`docs/base_execucao_anual.md`, seção 3), sem mudança:

| Tipo | Identificação | Traz | Linhas (referência) |
|---|---|---|---|
| **Linha de empenho** | `NE - Descrição` ≠ `"NAO SE APLICA"` | apenas `Empenhada` (repetida por bloco, ver seção 3) | 4.588 |
| **Linha de item de execução** | `NE - Descrição` = `"NAO SE APLICA"` | `Liquidada` e `Paga` | 1.185 |

Liquidada/Paga **não** sofrem a duplicação por item (só existem nas linhas de item de
execução, uma por NE × mês) — somar direto por linha continua correto para essas duas
medidas, só Empenhada precisa da deduplicação da seção 3.

Os valores mensais são **incrementais** (o movimento daquele mês específico), não saldo
acumulado — confirmado observando que os valores por mês de uma mesma NE não são
monotonicamente crescentes. Por isso a coerência "pago ≤ liquidado" só vale **acumulada** ao
longo do exercício, nunca mês a mês isolado (um pagamento de maio pode ser referente a uma
liquidação registrada em abril).

## 5. Validação cruzada contra a Base Anual

Feita uma vez, contra a extração antiga de 03/09/2026 (aba única, só 2026) — ver seção 9: os
totais desta base deduplicada batiam até o centavo com o manifesto ativo da Base Anual para
o mesmo dia (`test_totais_batem_com_o_manifesto_da_base_anual`, hoje renomeado/ajustado — ver
`tests/test_tesouro_execucao_mensal.py`).

A extração atual (21/09/2026, multi-aba 2024-2026, hash `672398fd`) **não tem** essa
conferência cruzada: não há manifesto da Base Anual cobrindo os 3 exercícios extraído no
mesmo dia para comparar. Os totais de referência desta extração (`REFERENCIAS["672398fd"]`
no arquivo de testes) foram fixados a partir da validação estrutural própria da base
(`validar()`, sem erros nem alertas), não de uma conferência externa — sinalizado aqui de
propósito, não presuma que já foi cruzado com a Base Anual.

## 6. Diferenças frente à Base Anual

| | Base Anual | Base Mensal |
|---|---|---|
| Linhas de cabeçalho | 2 | 3 (+ 3 linhas de banner antes, ver seção 2) |
| Abas | 1 | 1 por exercício |
| Colunas dimensionais | 40 (posicional fixo) | 41 (posicional fixo) + 3×N blocos (N detectado dinamicamente) |
| Cobertura temporal | 2023–2026 | 2024 em diante (abas presentes na extração) |
| Granularidade | 1 valor/ano por linha | 1 valor/mês por linha (formato longo: 1 linha bruta → N linhas, uma por mês) |
| Dimensões exclusivas | — | `NE Item`, `Unidade Orçamentária`, `NE - Informação Complementar` (nenhuma existe na Base Anual) |
| Deduplicação de Empenhada | não precisa (1 valor por NE já é o total) | precisa (repetido por item dentro do bloco, ver seção 3) |
| Importação versionada (manifesto, delta) | sim (`src/importacao_execucao.py`) | **ainda não** |
| Reconciliação entre as duas para o mesmo ano (2024-2026) | — | **não definida** (ver seção 5) |

## 7. O que ainda falta

Resolvido desde então (histórico, não repetir como pendência): importação versionada própria
(seção 10, 21/09/2026), páginas de análise (`app_pages/execucao_mensal.py`,
`app_pages/consulta_empenhos.py`), busca por item em Consulta de Empenhos.

Ainda em aberto:

- O que fazer quando um mês futuro cruzar para um novo ano (ex. uma aba trazer JAN/2027 junto
  com meses de 2026 na MESMA aba, não em abas separadas como o layout atual já suporta) —
  `_blocos_mensais` já lê o ano de cada rótulo individualmente (não presume um único ano por
  aba), mas isso ainda não foi testado com uma extração real nesse formato.
- Reconciliação entre Execução Mensal e Execução Anual para os anos em que as duas bases
  coexistem (2024-2026) — nenhuma regra definida sobre qual prevalece (ver seção 5).

## 8. Arquivos entregues

| Arquivo | Papel |
|---|---|
| `src/tesouro_execucao_mensal.py` | leitura + normalização (formato longo) + deduplicação + validação |
| `tests/test_tesouro_execucao_mensal.py` | testes (invariantes + referência por hash) |
| `tests/fixtures/execucao_mensal_2026-09-21.xlsx` | fixture congelada da extração de referência ATUAL (layout multi-aba) |
| `tests/fixtures/execucao_mensal_2026-09-03.xlsx` | fixture do layout ANTIGO (histórico, não lida por nenhum teste — ver seção 9) |
| `base_execucao_mensal.md` | este documento |

### API

```python
df     = ler_execucao_mensal(caminho)     # formato longo: 1 linha bruta -> N linhas (1 por mes/bloco), todas as abas
dedup  = valor_empenhado_por_bloco(df)    # Empenhada correta, 1 linha por (NE, Nat. Detalhada, Subitem, mes)
tempo  = linha_do_tempo_por_ne(df)        # 1 linha por (NE, mes): Empenhado/Liquidado/Pago
por_ne = agregar_por_ne(df)               # 1 linha por NE (todo o período) — mesmo contrato de
                                           # src.execucao_anual.agregar_por_ne, usada por
                                           # app_pages/consulta_empenhos.py (fonte principal desde
                                           # 21/09/2026, ver seção 10)
rec    = reconciliar(df)                  # totais (Empenhada ja deduplicada) globais e por ano
rel    = validar(df, esperado=None)       # .ok, .erros, .alertas, .resumo
```

Colunas derivadas: `linha_origem`, `arquivo_origem`, `aba_origem`, `tipo_linha`, `ne_ano`,
`ne_numero`, `natureza_detalhada_label`, `tem_item`, `mes` (1–12), `ano_mes` (ex. 202601).

## 10. Consumo por `app_pages/consulta_empenhos.py` (21/09/2026)

Pedido explícito do usuário: a página "Consulta de Empenhos", que lia da Base Anual, passou a
ler desta base como fonte PRINCIPAL (não mais só para busca por item/linha do tempo). Decisão
tomada cientes das consequências: a página perde 2023 (fora do período coberto por esta base)
até uma extração futura trazer aquele exercício; a página também perde a importação
versionada/manifesto que a Base Anual tinha (esta base ainda não tem — rodapé da página mostra
data do arquivo em disco, não hash de extração confirmada). `agregar_por_ne()` foi escrita
espelhando o contrato de saída de `src.execucao_anual.agregar_por_ne` (mesmos nomes de coluna)
de propósito, para a página não precisar reescrever filtros/consolidação/painel de detalhe —
só a leitura/gating no rodapé do script. A dimensão nova desta base sem equivalente na Anual
(`NE - Informação Complementar`) foi acrescentada como filtro só nesta página (não no módulo
compartilhado `src/ui_filtros_execucao.py`, que `app_pages/empenhos_execucao_retardada.py`
também usa, continuando na Base Anual — adicionar lá quebraria aquela página).

## 9. Histórico de layout — extração de 03/09/2026 (superado)

Válido só para `tests/fixtures/execucao_mensal_2026-09-03.xlsx`, não mais lido pelo leitor
atual (que exige o layout multi-aba da seção 1-2). Registrado aqui por rastreabilidade.

- **1 aba única**, sem banner de relatório — cabeçalho já começava na linha 1.
- Cabeçalho de 3 linhas, dados a partir da **linha 4**.
- 39 colunas dimensionais (posições 0–38): idêntico à Base Anual até a posição 35 (`NE CCor -
  Favorecido`), depois `NE Item` (código/descrição, posições 36–37) e `Ano Lançamento`
  (posição 38, coluna de dado real — cada linha carregava seu próprio ano).
- Sem `Unidade Orçamentária` nem `NE - Informação Complementar` (dimensões que só existem a
  partir da extração de 21/09/2026).
- Cobria só 2026 em diante (a extração de referência tinha só a aba 2026, meses JAN-SET).
- Sem blocos de encerramento ("013"/"014") — esses só apareceram na extração de 21/09/2026,
  para os exercícios já fechados (2024/2025).
