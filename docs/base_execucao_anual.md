# Base ANUAL de Execução da Despesa — especificação e regras

> Documento de contrato da base. Ler antes de qualquer alteração no leitor, na validação ou na
> aba **Execução Orçamentária**. Extração analisada: 11/08/2026, 7.779 linhas, exercícios 2023–2026.

## 1. Identificação

| Item | Valor |
|---|---|
| Origem | BI PROPLAD / Tesouro Gerencial — "EXEC. DESPESAS - Por Ano" |
| Arquivo recebido | `BI_PROPLAD_-_EXEC__DESPESAS_-_Por_Ano__9_.xlsx` |
| Abas | 1 (única) |
| Colunas | 39, posicionais |
| Linhas de dados | 7.779 (a partir da linha 3 da planilha) |
| Granularidade temporal | **anual** (`Ano Lançamento`) — não há mês |
| UG Executora | constante: 153165 — UFRPE |

## 2. Layout físico

O cabeçalho ocupa **duas linhas** e não é utilizável direto pelo pandas:

- **Linha 1**: rótulos de grupo. Cada dimensão ocupa duas colunas (código, descrição) sem repetir
  o rótulo na segunda. Exceções: `Plano Orçamentário` ocupa **três** colunas; `PTRES`, `NE -
  Descrição`, `NE CCor` e `NE CCor - Favorecido` ocupam **uma**.
- **Linha 2**: preenchida apenas nas 4 últimas colunas (`Ano Lançamento` + `Movim. Líquido - R$`
  repetido 3×). O rótulo `Item Informação` da linha 1 está deslocado sobre a coluna de ano.
- **Linha 3 em diante**: dados. Tudo em texto, inclusive valores.

Por isso: ler com `header=None, skiprows=2, dtype=str` e nomear as 39 colunas **por posição**.
Nunca inferir nomes do cabeçalho. A função `_validar_assinatura` confere 6 posições-âncora e
levanta `ErroLayoutBase` se a extração mudar — falhar cedo, não adivinhar.

### Mapa posicional

| # | Coluna | # | Coluna |
|---|---|---|---|
| 1–2 | Iduso (cód, desc) | 21–22 | PI (cód, desc) |
| 3–4 | Resultado Primário Lei | 23–25 | Plano Orçamentário (ação, PO, desc) |
| 5–6 | Categoria Econômica | 26 | PTRES |
| 7–8 | Ação de Governo | 27–28 | UG Executora |
| 9–10 | Elemento de Despesa | 29–30 | UG Responsável |
| 11–12 | Fonte de Recursos | 31–32 | UGR – Gestão |
| 13–14 | Grupo de Despesa (GND) | 33 | NE – Descrição |
| 15–16 | Natureza de Despesa | 34 | NE CCor |
| 17–18 | Natureza de Despesa Detalhada | 35 | NE CCor – Favorecido |
| 19–20 | Subitem | 36 | Ano Lançamento |
| | | 37–39 | Empenhada, Liquidada, Paga |

## 3. A regra que muda tudo: dois tipos de linha

A base **mistura duas naturezas de registro** na mesma tabela:

| Tipo | Identificação | Traz | Linhas |
|---|---|---|---|
| **Linha de empenho** | `NE - Descrição` ≠ `"NAO SE APLICA"` | apenas `DESPESAS EMPENHADAS` | 4.092 |
| **Linha de item de execução** | `NE - Descrição` = `"NAO SE APLICA"` | `LIQUIDADAS` e `PAGAS` | 3.687 |

Consequências obrigatórias:

1. **Nunca conte linhas como "quantidade de despesas".** 7.779 linhas ≠ 7.779 despesas. As NEs
   distintas são 3.700.
2. **Some cada medida sobre TODAS as linhas.** Como os campos não se sobrepõem, a soma simples
   por dimensão está correta e reconcilia com a origem. Não filtre por tipo de linha antes de somar.
3. **`NE - Descrição` não é dimensão analítica de liquidado/pago** — ela só existe nas linhas de
   empenho. Para descrever o que foi liquidado, faça o join pela `NE CCor`, nunca pela descrição.
4. 54 linhas de item trazem `EMPENHADAS` ≠ 0 (anulações que **se cancelam**: soma = R$ 0,00).
   Há teste garantindo isso; se um dia deixar de somar zero, a extração mudou.
5. Nulo em liquidada/paga significa **ausência de movimento**, não zero. Só use `fillna(0)` depois
   de agregar (`sum(min_count=1)`), nunca na leitura.

## 4. Fatos verificados na extração

- `Ano Lançamento` **é sempre igual ao ano da NE** (posições 12–15 da `NE CCor`).
  → **Não há restos a pagar nesta base**: toda execução é do próprio exercício. A comparação
  Empenhado × Liquidado × Pago é intra-exercício e legítima. Se essa igualdade quebrar numa
  reextração, a análise precisa ser repensada (a validação emite alerta).
- Zero duplicatas na chave dimensional completa.
- 22 valores negativos em `EMPENHADAS` = anulações. **Preservar**, nunca filtrar.
- Hierarquia da natureza (código de 8 dígitos): `3.1.90.01.01` →
  posição 1 = categoria econômica, 2 = GND, 3–4 = modalidade, 5–6 = elemento, 7–8 = subitem.
  Conferido: `Natureza Despesa` = 6 primeiros dígitos da detalhada; categoria e elemento batem.
- ⚠️ **`Subitem` isolado não é chave**: 68 códigos para 233 descrições — o subitem só é único
  dentro da natureza. Agrupe sempre por `Natureza Despesa Detalhada` (249 valores), não por subitem.
- Mesmo cuidado com `Natureza Despesa` (45 códigos × 34 descrições) e `PI` (200 × 191): use
  sempre o par código+descrição como chave de agrupamento, ou o label `cód - desc`.
- `Plano Orçamentário` col. 23 é idêntica ao código da Ação; o PO real é a coluna 24, e o PO
  `0000` reaproveita a descrição da ação.
- Dimensões com baixa cardinalidade (bons filtros): GND (3), Categoria (2), Iduso (2),
  Resultado Primário (7), UGR (15), Fonte (16). Alta cardinalidade (bons rankings):
  Favorecido (1.156), Natureza Detalhada (249), PI (200), PTRES (165), Plano Orçamentário (102),
  UG Responsável (104), Ação de Governo (53).

## 5. Reimportação: como a base é atualizada

A base é substituída por reextrações periódicas. Política adotada:

- **Substituição total** — a extração mais recente é a verdade completa. Não há merge de
  exercícios entre arquivos; o DataFrame lido substitui integralmente o anterior.
- **Data de referência** — vem da data de modificação do arquivo (`mtime`), automaticamente.
- **Identidade da extração** — hash SHA-256 do arquivo. Reimportar o mesmo arquivo é
  idempotente: nada é registrado de novo.

O que fica versionado não são os dados, e sim o **manifesto** de cada importação: um JSON com
hash, data, contagens e totais por exercício, gravado em `data/manifestos/` mais um ponteiro
`execucao_anual_atual.json`. É ele que responde "esses R$ X de 2026 são de qual foto?" e permite
o **delta** entre extrações.

O delta classifica as mudanças:

| Situação | Tratamento |
|---|---|
| Exercício corrente avançou | informativo, esperado |
| Exercício anterior mudou | **alerta de mudança retroativa** (anulação/reprocessamento) — números já divulgados precisam ser reconferidos |
| Exercício novo apareceu | informativo |
| Exercício sumiu da extração | **alerta** — com substituição total, ele deixa de existir no painel |

Anos "fechados" não são imutáveis: anulação e reprocessamento alteram o passado. Por isso o
delta **reporta** a diferença em vez de bloquear a importação. Manifesto só é gravado quando a
validação não tem erros — extração inválida não vira referência histórica.

### Efeito nos testes

Totais absolutos não podem ficar congelados na suíte, senão toda reextração deixa a suíte
vermelha e cria pressão para afrouxar teste — o que o AGENTS.md proíbe. A suíte tem dois níveis:

- **Invariantes** (`TestInvariantesDaBase`) — valem para qualquer extração: liquidado ≤ empenhado,
  empenhado das linhas de item soma zero, ano da NE = ano de lançamento, sem duplicatas,
  agregação preserva total, rastreabilidade até a linha de origem. Se um quebrar, a base mudou
  de natureza. Nunca afrouxar.
- **Referência** (`TestReferenciaDaExtracao`) — totais absolutos de uma extração identificada por
  hash, no dicionário `REFERENCIAS`. Com outro arquivo em disco, esses três testes são **pulados**,
  não falham. Ao adotar uma extração nova, **acrescente** uma entrada em `REFERENCIAS` (não edite
  a existente): o histórico de referências fica preservado e o hash decide qual se aplica.

Verificado: trocando o arquivo por uma extração simulada diferente, os 25 testes continuam
passando com 3 pulados.

## 6. Números de reconciliação da extração de referência

| Exercício | Empenhado | Liquidado | Pago |
|---|---:|---:|---:|
| 2023 | 762.455.916,88 | 723.987.833,09 | 651.361.558,65 |
| 2024 | 784.086.352,51 | 759.877.180,18 | 687.779.472,58 |
| 2025 | 931.345.340,39 | 882.774.236,76 | 790.633.667,10 |
| 2026 * | 754.439.889,56 | 498.330.754,13 | 486.238.063,81 |
| **Total** | **3.232.327.499,34** | **2.864.970.004,16** | **2.616.012.762,14** |

\* 2026 é **exercício em andamento** na data da extração. Qualquer comparação com anos fechados
deve rotular 2026 como parcial na interface; não calcular variação % contra anos completos sem aviso.

Coerência verificada em todos os anos: liquidado ≤ empenhado e pago ≤ liquidado.

## 7. Arquivos entregues

| Arquivo | Papel | Onde colocar |
|---|---|---|
| `execucao_anual.py` | leitura + normalização + validação + agregação (camada de dados) | junto dos demais módulos de base específica |
| `importacao_execucao.py` | manifesto, substituição total, delta entre extrações, histórico | mesma camada, um nível acima do leitor |
| `test_execucao_anual.py` | 25 testes (invariantes + referência por hash + importação) | suíte existente |
| `base_execucao_anual.md` | este documento | `docs/` |

A pasta `data/manifestos/` (versionada no Git — são arquivos pequenos e são a memória de quais
números vieram de qual extração) foi criada como irmã de `data/raw/` e `data/processed/`, já
existentes no projeto — nada de pasta `dados/` paralela.

Ajustado no código: os imports em `test_execucao_anual.py` e `importacao_execucao.py` passaram a
`from src.execucao_anual import ...` / `from src.importacao_execucao import ...`, e `CAMINHO_BASE`
aponta para `data/raw/BI PROPLAD - EXEC. DESPESAS - Por Ano (9).xlsx` (nome original preservado,
mesmo padrão já usado para a Dotação Anual). O módulo não importa Streamlit e não conhece a
interface — respeita a separação leitor / regra de base / validação / analítica / interface.

### API

```python
df   = ler_execucao_anual(caminho)      # DataFrame normalizado + linha_origem + tipo_linha
rec  = reconciliar(df)                  # totais globais e por ano
rel  = validar(df, esperado=ESPERADO)   # .ok, .erros, .alertas, .resumo
tab  = agregar(df, por=["gnd_cod", "gnd_desc"])   # + % execução e % pagamento
ne   = detalhar_nota_empenho(df, "153165152392025NE000709")  # rastreabilidade

# importação versionada
res  = importar("data/raw/BI PROPLAD - EXEC. DESPESAS - Por Ano (9).xlsx")
res.df           # base completa, substitui a anterior
res.manifesto    # hash, data_extracao, totais por exercício
res.delta.resumo_texto()   # o que mudou desde a última importação
res.delta.alertas          # mudança retroativa, exercício removido
historico_como_tabela()    # uma linha por importação já feita
```

Colunas derivadas: `linha_origem` (linha exata na planilha), `arquivo_origem`, `tipo_linha`,
`ne_ano`, `ne_numero` e labels `cód - desc` prontos para exibição.

## 8. Instruções para a aba "Execução Orçamentária"

Regras de desenvolvimento (AGENTS.md) valem integralmente: inspecionar antes de alterar, não
ampliar escopo, não reduzir testes existentes, propor **um** próximo passo e aguardar aprovação.

Escopo proposto para a aba, nesta ordem:

1. **Filtros no topo** (multi-seleção, aplicados a tudo): Exercício, GND, Fonte, Resultado
   Primário, UGR. Estado em `st.session_state`.
2. **Faixa de cards** (padrão gerencial já definido: fundo claro, cantos arredondados, poucos
   indicadores, cor por status): Empenhado, Liquidado, Pago, % Liquidado/Empenhado,
   % Pago/Liquidado. Com o marcador "exercício em andamento" quando 2026 estiver no filtro.
3. **Série histórica** — barras agrupadas Empenhado × Liquidado × Pago por exercício.
4. **Composição** — uma dimensão por vez, escolhida em `selectbox` a partir de
   `DIMENSOES_ANALITICAS` (GND, Fonte, Ação, Natureza Detalhada, Resultado Primário, UG
   Responsável, UGR, PI, PTRES, PO, Favorecido).
5. **Rastreabilidade** — ao selecionar uma NE, exibir suas linhas de origem via
   `detalhar_nota_empenho`, mostrando `linha_origem`. Todo número exibido precisa chegar até a
   célula de origem.
6. **Rodapé de procedência** — data da extração e hash curto do manifesto atual, sempre visíveis.
   Ao importar um arquivo novo, mostrar o resumo do delta antes de o usuário seguir usando o
   painel, com destaque para alertas de mudança retroativa.

O que **não** fazer nesta aba: cruzar com Dotação (a integração segue suspensa pela ambiguidade
temporal), inferir mês, calcular saldo ou insuficiência, e persistir em DuckDB — tudo isso é
etapa posterior já sequenciada no projeto.

### Por que a aba lê `Manifesto.atual()` direto, sem passar pela Importação de Bases

Todas as demais bases do projeto (Dotação mensal, Execução mensal do Tesouro Gerencial, Dotação
Anual) seguem o mesmo fluxo: o usuário sobe o arquivo na página **Importação de Bases**, que
reconhece a estrutura, valida e guarda o resultado em `st.session_state`; as páginas de análise
só leem essa sessão. A Execução Anual não existia no projeto quando esse fluxo foi criado, e não
foi encaixada nele — ela já chegou com um sistema de importação versionada próprio (substituição
total, manifesto com hash, delta entre extrações), pensado para reextrações periódicas do BI
PROPLAD, e não para um upload manual por sessão de navegador. Adaptar essa base ao fluxo de
sessão jogaria fora justamente o que o manifesto resolve: saber de qual extração vieram os
números exibidos e comparar com a extração anterior, mesmo entre sessões e reinícios do servidor.

Por isso a aba **Execução Orçamentária** lê `Manifesto.atual()` (o ponteiro em
`data/manifestos/execucao_anual_atual.json`) e carrega o arquivo em `data/raw/` que ele aponta,
com `st.cache_data` chaveado por caminho e `mtime` do arquivo — não por `st.session_state`. A
página **não** chama `importar()`: ela só lê o estado já registrado por uma importação anterior
(rodada manualmente ou, no futuro, pelo item 6 desta seção, quando a reimportação ganhar botão na
interface). Isso mantém a leitura de uma página sem efeito colateral — abrir a aba nunca grava um
manifesto novo nem substitui a extração vigente.

Essa é uma exceção deliberada ao padrão do projeto, não um precedente para as bases futuras: cada
base decide seu fluxo de importação de acordo com como ela realmente chega até o projeto (upload
manual pontual vs. reextração periódica rastreável), e isso deve continuar sendo avaliado caso a
caso.
