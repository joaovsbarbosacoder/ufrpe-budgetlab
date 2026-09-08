# Base MENSAL de Execução da Despesa — especificação e regras

> Documento de contrato da base. Ler antes de qualquer alteração no leitor ou na regra de
> deduplicação. Extração analisada: recebida em 03/09/2026, 4.295 linhas brutas, meses
> JAN–SET/2026.

Esta base é **complementar** à Base ANUAL (`docs/base_execucao_anual.md`), não sua
substituta: cobre só **2026 em diante**, por mês. A Base Anual continua sendo a fonte de
2023–2025 e a referência histórica; nada nela muda por causa desta base nova.

## 1. Identificação

| Item | Valor |
|---|---|
| Origem | BI CPOC / Tesouro Gerencial — "EXEC. DESPESAS - Por Ano", variante com quebra mensal |
| Abas | 1 (única) |
| Colunas | 39 dimensionais (posições 0–38) + 3 por mês presente na extração (Empenhada, Liquidada, Paga) |
| Linhas de dados | 4.295 na extração de referência (a partir da linha 4 da planilha) |
| Granularidade temporal | **mensal**, a partir de 2026 (`ano_mes` = ano×100+mês) |
| UG Executora | constante: 153165 — UFRPE |

## 2. Layout físico

O cabeçalho ocupa **três linhas** (a Base Anual tem duas — ver seção 8, "Diferenças frente
à Base Anual"):

- **Linha 1**: rótulos de grupo das dimensões (idêntico à Base Anual até a coluna "NE CCor -
  Favorecido"), mais o rótulo do mês (`"JAN/2026"`, `"FEV/2026"`, ...) repetido 3× por bloco
  mensal a partir da coluna 39 (0-indexada).
- **Linha 2**: `"Item Informação"` sobreposto na coluna 38 (a coluna `Ano Lançamento`, mesmo
  deslocamento documentado na Base Anual) + `"DESPESAS EMPENHADAS/LIQUIDADAS/PAGAS (CONTROLE
  EMPENHO)"` repetido por bloco mensal.
- **Linha 3**: `"Ano Lançamento"` sobreposto na mesma coluna 38 + `"Movim. Líquido - R$ (Item
  Informação)"` repetido por bloco mensal.
- **Linha 4 em diante**: dados. Tudo em texto, inclusive valores.

Ler com `header=None, skiprows=3, dtype=str`. **Nunca hardcodar a quantidade de meses**: a
extração ganha um bloco novo a cada mês que passa (JAN–SET hoje; DEZ ao fim do exercício). O
leitor detecta os blocos dinamicamente a partir dos rótulos da linha 1
(`_blocos_mensais`/`_rotulo_mes` em `src/tesouro_execucao_mensal.py`) — ler um arquivo com
mais ou menos meses não exige alterar o módulo.

### Mapa posicional (colunas dimensionais, 0-indexadas)

Idêntico à Base Anual (ver `docs/base_execucao_anual.md`, seção 2) até a posição 35 (`NE CCor
- Favorecido`). A partir daí:

| # | Coluna |
|---|---|
| 36–37 | **NE Item** (código, descrição) — dimensão nova, ver seção 3 |
| 38 | Ano Lançamento |
| 39+ | blocos mensais (Empenhada, Liquidada, Paga) × N meses |

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
| **Linha de empenho** | `NE - Descrição` ≠ `"NAO SE APLICA"` | apenas `Empenhada` (repetida por bloco, ver seção 3) | 3.869 |
| **Linha de item de execução** | `NE - Descrição` = `"NAO SE APLICA"` | `Liquidada` e `Paga` | 426 |

Liquidada/Paga **não** sofrem a duplicação por item (só existem nas linhas de item de
execução, uma por NE × mês) — somar direto por linha continua correto para essas duas
medidas, só Empenhada precisa da deduplicação da seção 3.

Os valores mensais são **incrementais** (o movimento daquele mês específico), não saldo
acumulado — confirmado observando que os valores por mês de uma mesma NE não são
monotonicamente crescentes. Por isso a coerência "pago ≤ liquidado" só vale **acumulada** ao
longo do exercício, nunca mês a mês isolado (um pagamento de maio pode ser referente a uma
liquidação registrada em abril).

## 5. Validação cruzada contra a Base Anual (03/09/2026)

Somando esta base, deduplicada pela regra da seção 3, para o exercício 2026 e comparando
contra o manifesto **já ativo** da Base Anual (`Manifesto.atual()`, base `execucao_anual`,
mesma extração do mesmo dia):

| Medida | Base Mensal (deduplicada) | Base Anual (manifesto ativo) | Diferença |
|---|---:|---:|---:|
| Empenhada | 779.416.610,23 | 779.416.610,23 | R$ 0,00 |
| Liquidada | 579.124.824,19 | 579.124.824,19 | R$ 0,00 |
| Paga | 537.533.784,32 | 537.533.784,32 | R$ 0,00 |

Batem **até o centavo** — forte confirmação de que a regra de deduplicação (seção 3) está
correta, não só aproximada. Esse é o teste `test_totais_batem_com_o_manifesto_da_base_anual`
em `tests/test_tesouro_execucao_mensal.py`.

## 6. Diferenças frente à Base Anual

| | Base Anual | Base Mensal |
|---|---|---|
| Linhas de cabeçalho | 2 | 3 |
| Colunas | 40 (posicional fixo) | 39 + 3×N meses (N detectado dinamicamente) |
| Cobertura temporal | 2023–2026 | só 2026 em diante |
| Granularidade | 1 valor/ano por linha | 1 valor/mês por linha (formato longo: 1 linha bruta → N linhas, uma por mês) |
| Dimensão `NE Item` | não existe | existe (código + descrição) |
| Deduplicação de Empenhada | não precisa (1 valor por NE já é o total) | precisa (repetido por item dentro do bloco, ver seção 3) |
| Importação versionada (manifesto, delta) | sim (`src/importacao_execucao.py`) | **ainda não** — fora do escopo desta etapa |
| Consumida por alguma página (`app_pages/`) | sim | **ainda não** — fora do escopo desta etapa |

## 7. O que ainda falta (fora do escopo desta etapa, deliberadamente)

- Importação versionada própria (manifesto, delta entre extrações) — hoje o leitor só lê um
  arquivo direto, sem `Manifesto`/histórico.
- Qualquer página em `app_pages/` que mostre esta base (painel por mês).
- Busca por palavra-chave de item em "Consulta de Empenhos" — depende deste leitor estar
  disponível para a página consumir `ne_item_desc`.
- O que fazer quando um mês futuro cruzar para um novo ano (ex. extração passar a incluir
  JAN/2027 junto com meses de 2026) — `_blocos_mensais` já lê o ano de cada rótulo
  individualmente (não presume um único ano para o arquivo inteiro), mas isso ainda não foi
  testado com uma extração real que atravesse dois exercícios.

## 8. Arquivos entregues

| Arquivo | Papel |
|---|---|
| `src/tesouro_execucao_mensal.py` | leitura + normalização (formato longo) + deduplicação + validação |
| `tests/test_tesouro_execucao_mensal.py` | testes (invariantes + referência por hash) |
| `tests/fixtures/execucao_mensal_2026-09-03.xlsx` | fixture congelada da extração de referência |
| `base_execucao_mensal.md` | este documento |

### API

```python
df     = ler_execucao_mensal(caminho)     # formato longo: 1 linha bruta -> N linhas (1 por mes)
dedup  = valor_empenhado_por_bloco(df)    # Empenhada correta, 1 linha por (NE, Nat. Detalhada, Subitem, mes)
rec    = reconciliar(df)                  # totais (Empenhada ja deduplicada) globais e por ano
rel    = validar(df, esperado=None)       # .ok, .erros, .alertas, .resumo
```

Colunas derivadas: `linha_origem`, `arquivo_origem`, `tipo_linha`, `ne_ano`, `ne_numero`,
`natureza_detalhada_label`, `tem_item`, `mes` (1–12), `ano_mes` (ex. 202601).
