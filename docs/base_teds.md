# Base de TEDs (Termos de Execução Descentralizada) — especificação e regras

> Documento de contrato do módulo. Ler antes de qualquer alteração em `src/teds_*.py` ou nas
> páginas `app_pages/teds_*.py`. As decisões abaixo foram aprovadas explicitamente em
> conversa de alinhamento (não presumidas) — ver AGENTS.md sobre não presumir regra de
> negócio não definida.

## 1. Por que este módulo tem persistência própria

Ao contrário das demais bases do projeto (manifesto versionado em `data/manifestos/`, sem
banco — `src/importacao_versionada.py`), o acompanhamento de TEDs precisa cruzar cinco fontes
diferentes (TED, DOC NC, DOC PF, DOC NE e a execução no Tesouro Gerencial) e manter uma fila
de decisões humanas (vínculo de NE pendente, alerta com justificativa e histórico) que não
cabe no padrão de "recarregar tudo do Excel a cada acesso".

O banco fica isolado em `data/teds/teds.db` (SQLite), sem afetar o padrão das outras bases.
Schema completo em `src/teds_schema.py`.

## 2. Fontes de dados

| Fonte | Leitor | Extração real revisada? |
|---|---|---|
| SIMEC — Execução: Orçamentário e Financeiro | `ler_execucao_anual_simec` (`src/teds_importacao_simec.py`) | Sim — 4 arquivos, exercício 2026 |
| SIMEC — Documentos: DOC NE | `ler_doc_ne_simec` | Sim |
| SIMEC — Documentos: DOC NC | `ler_doc_nc_simec` | Sim |
| SIMEC — Documentos: DOC PF | `ler_doc_pf_simec` | Sim |
| Tesouro Gerencial — execução por empenho | `montar_execucao_tg` (`src/teds_importacao_tesouro_gerencial.py`) — deriva da Execução Mensal, sem arquivo próprio | Sim — extração real da Execução Mensal, ver seção 6 |
| Tesouro Gerencial — NC até 2025 ("Destaques Recebidos") | `ler_nc_tg_historica` (`src/teds_celula_orcamentaria.py`) | Sim — extração real de 24/09/2026, ver seção 11 |
| Tesouro Gerencial — NC 2026 | `ler_nc_tg_2026` | Sim — extração real de 24/09/2026, ver seção 11 |
| Tesouro Gerencial — células das NEs (PTRES, fonte, natureza, PI) | `montar_ne_celulas` — deriva da Execução Mensal, no mesmo lote da sincronização | Sim, ver seção 11 |

A leitura do arquivo bruto (abertura do Excel, cálculo do hash SHA-256) é responsabilidade de
`src/teds_lotes.py`; os leitores do SIMEC recebem o `DataFrame` já carregado e devolvem
registros normalizados + linhas rejeitadas com motivo — nunca lançam exceção por uma linha
ruim isolada.

## 3. Valores monetários: `Decimal`, nunca `float`

Diferente do padrão das demais bases do projeto (que usam `float64`/pandas com tolerância de
centavos), todo valor monetário do módulo de TEDs trafega como `Decimal` e é persistido como
texto decimal exato (`src/teds_normalizacao.valor_para_texto` / `texto_para_valor`), nunca
`REAL` no SQLite. Decisão deliberada: o módulo compara e soma valores entre fontes distintas
(SIMEC × Tesouro Gerencial), onde arredondamento acumulado de ponto flutuante poderia mascarar
ou criar divergências que não existem na origem.

## 4. Chaves naturais

Construídas em `src/teds_normalizacao.py`, sempre a partir de `normalizar_codigo` (preserva
zeros à esquerda, resolve o `.0` que o pandas adiciona a código lido como `float`, maiúsculas
por último):

| Chave | Composição | Uso |
|---|---|---|
| `chave_ted` | `TED\|código SIAFI` | identifica o TED |
| `chave_empenho` | `UG emitente\|gestão emitente\|número NE` | identifica a NE |
| `chave_nc_documento` | `TED+SIAFI+número NC+operação+data`, **sem** UG emitente | agrega linhas de um mesmo documento NC |
| `chave_nc_linha` | lote de importação + índice de origem | idempotência linha a linha do DOC NC, nunca usada para agrupar |
| `chave_pf` | `UG emitente\|número PF` | identifica o documento PF |

`chave_nc_documento` não usa a UG emitente porque ela não identifica o documento e vem ausente
em boa parte das linhas reais (ver seção 5).

## 5. Achados da extração real do SIMEC (não presumidos — confirmados linha a linha contra 4 arquivos, exercício 2026)

- **TED, UG e Gestão Emitente** costumam vir como `float` (ex.: `12112.0`) — resolvido por
  `normalizar_codigo`.
- **DOC NC — UG emitente ausente em ~41% das linhas** (86 de 179, no arquivo de referência).
  Não é rodapé nem erro: é uma lacuna legítima da extração. Essas linhas são importadas (não
  rejeitadas), com `ug_emitente=None`, aviso `UG_EMITENTE_NC_AUSENTE` e
  `status_relacionamento='PARCIAL'`. A UG emitente ausente **nunca** é preenchida com a UG
  Descentralizadora — são UGs diferentes em todas as linhas onde as duas colunas vêm
  preenchidas.
- **DOC NC — mesmo documento em várias linhas** (rateio por fonte/ação: 20 de 122 documentos
  no arquivo de referência, totalizando 179 linhas). `ler_doc_nc_simec` preserva cada linha em
  `registros` (nunca trata repetição como duplicidade) e também devolve `documentos`, agregado
  por `chave_nc_documento`.
- **Sinal de operação**: DOC NC usa `( + )`/`( - )`; DOC PF usa `(+)`/`(-)`. Ambos convertidos
  para `+`/`-` por `normalizar_operacao` antes de persistir.
- **Sufixo monetário `(R$)`**: algumas colunas de valor da extração real trazem esse sufixo
  (ex.: "Total Descentralizado (R$)"); `normalizar_nome_coluna` remove o sufixo ao casar
  nomes de coluna, então a maioria dos campos de valor não precisou de alias explícito.
- **Rodapé com total** (confirmado em 24/09/2026 com as 4 extrações reais de 17/09/2026): a
  ÚLTIMA linha da planilha vem sem nenhum identificador (TED, SIAFI, número do documento, datas) e só
  com o(s) total(is) na(s) coluna(s) de valor. Execução Anual: os 6 totais; DOC NC, DOC NE e DOC PF:
  o valor. Nos quatro os totais batem ao centavo com a soma das linhas. **No DOC NC e no DOC PF o
  rodapé é a soma ABSOLUTA (positivas + negativas), não o líquido** — na NC real: positivas
  R$ 57.619.026,14 + negativas R$ 5.219.366,74 = R$ 62.838.392,88 = rodapé. Ver a seção 6.1.

## 6. Fonte do Tesouro Gerencial: é a Execução Mensal (implementado em 23/09/2026)

O briefing original descrevia **duas** bases do Tesouro Gerencial ("execução da despesa por
empenho" e "liquidação por competência"). **Confirmado pelo usuário em 22/09/2026: a extração
do Tesouro Gerencial usada aqui É a extração de Execução Mensal** já implementada em
`src/tesouro_execucao_mensal.py` (ver `docs/base_execucao_mensal.md`) — não existe uma segunda
extração a importar. O leitor de arquivo próprio (`ler_execucao_tg`, nunca confirmado contra
uma extração real) foi removido.

**Como funciona hoje:** `execucao_tg` é um *espelho* da Execução Mensal, com uma linha por
**NE × mês de lançamento**. Na página Importações, o botão **"Sincronizar com a Execução
Mensal"** chama `src/teds_lotes.py::sincronizar_execucao_tg_atual`, que:

- lê a extração ATUAL do manifesto versionado (`carregar_atual`, composta por ano) — nunca um
  arquivo avulso, nunca altera `data/raw/`;
- registra um lote em `import_batch` cujo hash é o **sha256 do manifesto**: a mesma extração
  já sincronizada é um no-op (a planilha nem é lida); extração nova faz *upsert* pela chave
  `(numero_completo_ne, ano_lancamento, mes_lancamento)`, mantendo o histórico de lotes;
- **nunca apaga**: linha que uma extração posterior deixe de trazer permanece como estava.

| Campo de `execucao_tg` | Fonte na Execução Mensal |
|---|---|
| `numero_completo_ne` | `execucao_ne_utils.ne_curta(ne_ccor)` → `2026NE000100` (NE fora do formato `AAAANEnnnnnn` é **rejeitada**, nunca gravada) |
| `favorecido` / `descricao` | `ne_favorecido` / `ne_descricao` (só das linhas de empenho) |
| `empenhado` / `liquidado` / `pago` | `linha_do_tempo_por_ne` — **movimentos do mês**, não acumulados; somar por NE dá o total (é o que `teds_ui` e a Conciliação fazem). Mês sem linha de liquidação/pagamento = movimento zero (convenção da própria função). Estornos entram com sinal. |
| `ano_lancamento` / `mes_lancamento` | `ano_mes` (`ano*100+mes`) |

**Decisões registradas (23/09/2026):**

- **Lançamento ≠ competência.** O mês da Execução Mensal é o de *lançamento*; competência (fato
  gerador) é outro eixo de tempo, medido pela base de **Liquidação por Competência**
  (`src/liquidacao_competencia.py`, que traz Documento Hábil, Doc. Contábil e mês de
  referência). Por isso as colunas se chamam `ano_lancamento`/`mes_lancamento` (antes
  `ano_competencia`/`mes_competencia`) e o indicador "Liquidações com competência" da Visão
  geral saiu (seria 100% por construção). Integrar a competência real ao TEDs **não é necessário**
  (decisão do usuário em 24/09/2026): fica fora do escopo do módulo, e não é uma pendência.
- **Saíram do schema** `documento_habil`, `documento_contabil` e `valor_competencia` (a
  Execução Mensal não os tem).
- **Migração do banco existente** (`src/teds_schema.py::_migrar_execucao_tg_para_lancamento`,
  roda em `conectar()`): tabela antiga vazia é recriada; com linhas, é **preservada** como
  `execucao_tg_legado` (nunca convertida nem descartada). Em `data/teds/teds.db` a tabela
  estava vazia (só as 4 fontes do SIMEC tinham sido importadas).

**Validação com a extração real** (`BI CPOC - EXEC. DESPESAS - Por Ano (8).xlsx`, 22/09/2026):
29.124 linhas NE × mês, 2.568 NEs, **0 rejeitadas**; as somas de empenhado/liquidado/pago
batem ao centavo com os totais do manifesto (R$ 2.496.385.910,24 / 2.226.639.772,51 /
2.044.402.004,58). Coberto por `tests/test_teds_importacao_tesouro_gerencial.py` e
`tests/test_teds_lotes.py`.

Antes de clicar em "Sincronizar", os indicadores de Liquidado/Pago e a conciliação SIMEC ×
Tesouro Gerencial mostram "Sem dado (Tesouro Gerencial)" em vez de um valor inventado.

### 6.1 Total do rodapé como total de controle

`_capturar_rodape` (`src/teds_importacao_simec.py`) lê o rodapé só na última linha e só se todas as
colunas fora dos campos de valor estiverem vazias: uma linha de dado nunca é tomada por rodapé.
`comparar_rodape` (`src/teds_lotes.py`) compara cada total com a soma das linhas ACEITAS — no
DOC NC e no DOC PF, a soma **bruta** (`valor_original`), nunca a líquida. O resultado vai para o
lote (`import_batch.total_rodape` só nos relatórios de valor único, `diferenca_rodape` = maior
diferença absoluta, `detalhe_rodape` = JSON por campo; NULL = arquivo sem rodapé). Diferença acima
de R$ 0,01 gera o alerta `importacao_rodape_divergente` (gravidade "alta", exibida como "Crítico"),
um por lote e sem duplicar; **o lote continua importado** — o alerta só sinaliza, quem decide é uma
pessoa. A página Importações mostra o resultado já na etapa de validação, antes de gravar. Lotes
anteriores a esta regra ficam com NULL. Validação com os 4 arquivos reais: diferença R$ 0,00 em todos.

**TED sem SIAFI:** a Execução Anual real traz o TED 16811, "Termo em cadastramento", sem SIAFI e
com todos os valores zerados. O SIAFI compõe a chave do TED (`chave_ted`), então a linha não pode ser
gravada — mas não é rodapé: antes era rejeitada com o motivo enganoso "possível linha de rodapé"; agora
tem motivo próprio ("TED 16811 sem código SIAFI (estado: …)") e gera o alerta `ted_sem_siafi`
(gravidade "media", um por TED, sem duplicar e sem fechar sozinho). Se a linha trouxer valor não nulo,
ele é citado no motivo, para nada sumir em silêncio. O TED fica **fora de todos os totais** até uma
extração trazer o SIAFI; não há marcador na lista (decisão pelo escopo mínimo). Vale só para a Execução
Anual — nos outros três relatórios a extração real não tem linha com TED e sem SIAFI.

## 7. Idempotência da importação

Duas camadas (`src/teds_lotes.py`):

- **Arquivo idêntico** (mesmo hash SHA-256 já importado com sucesso para o mesmo tipo de
  relatório) → importação inteira é um no-op; o lote antigo é reaproveitado.
- **Linha a linha**, via `INSERT ... ON CONFLICT ... DO UPDATE` pela chave natural de cada
  tabela → reimportar um arquivo diferente que traga uma linha já conhecida atualiza aquela
  linha (e sua rastreabilidade para o lote mais recente) em vez de duplicá-la.

O arquivo de origem nunca é lido nem gravado em `data/raw/` pelo importador — permanece como
o chamador entregou (regra 1 do projeto: nunca alterar arquivos importados). `linha_origem`
(JSON) preserva a linha original da planilha para auditoria; `import_batch_id` referencia o
lote que gravou/atualizou aquele registro pela última vez, e o histórico de lotes em
`import_batch` nunca é sobrescrito.

## 8. Alertas implementados

Dezenove tipos (`src/teds_alertas.py`, mais o de célula orçamentária em `src/teds_celula_orcamentaria.py`), cada um com funções puras testáveis sem banco e uma
`sincronizar_alertas_*` que lê do SQLite e grava alertas novos sem duplicar um alerta já
aberto para o mesmo documento — e sem nunca fechar um alerta sozinha (resolução é sempre ação
humana, registrada na Central de Alertas):

- **Empenho associado a mais de um TED** — caso concreto documentado no briefing (NE
  2026NE000422 nos TEDs 17352 e 17454). A NE fica com `status_validacao='pendente'` e é
  excluída da soma de `valor_ne` por TED até uma decisão humana (`decisao_vinculo_ne`,
  append-only: os vínculos originais não são apagados, só um fica contabilizável).
- **NC sem UG emitente** (`status_relacionamento='PARCIAL'`) — achado da extração real do
  SIMEC (seção 5), não do briefing original; aprovado explicitamente para gerar alerta.

- **Conciliação SIMEC analítica × consolidada** (`sincronizar_alertas_conciliacao_simec`,
  chamada ao fim das importações de Execução Anual, DOC NC e DOC PF). Três tipos, todos de
  gravidade "alta" (exibida como "Crítico"), tolerância R$ 0,01:
  - `nc_liquida_diverge_consolidado` — soma de `documento_nc.valor_assinado_total` do TED ≠
    Total Descentralizado consolidado;
  - `pf_liquida_diverge_consolidado` — soma de `documento_pf.valor_assinado` do TED ≠ Total
    Repassado consolidado (o valor é o **assinado por operação**, nunca uma soma absoluta);
  - `pf_liquida_maior_que_nc` — Total Repassado consolidado > Total Descentralizado consolidado.

  O consolidado é a soma de `execucao_anual` sobre **todos** os exercícios importados (o total
  descentralizado/repassado já é líquido de devoluções). Base analítica ainda não importada
  (`documento_nc`/`documento_pf` vazias) é "sem base", nunca zero: não gera divergência.
  Documentos sem TED conhecido ficam fora (aparecem na cobertura de relacionamentos). Os alertas
  só descrevem a diferença e as causas possíveis; nunca fecham sozinhos. Limite conhecido: as
  extrações analíticas cobrem um recorte de datas diferente do consolidado (ex.: PF de
  2019–2022 sem contrapartida no consolidado, que começa em 2023), então parte das divergências
  reflete cobertura da extração, não erro — decisão humana caso a caso. Com o banco atual
  (44 TEDs): 0 divergências de NC, 12 de PF e 7 de PF maior que NC.

- **Validações cadastrais e de vigência** (`sincronizar_alertas_cadastrais`, também ao fim de
  cada importação; briefing, seção 7). Todas descritivas — nada é excluído nem deixa de ser
  importado, e o alerta nunca fecha sozinho:
  - `ted_vigencia_invertida` (alta) — início da vigência posterior ao fim;
  - `siafi_em_multiplos_teds` (alta) — mesmo código SIAFI em mais de um número de TED;
  - `ted_sem_ug_descentralizadora` (média);
  - `documento_fora_da_vigencia` (média) — NC ou PF emitida antes do início ou depois do fim
    da vigência do seu TED; pode ser legítimo, então pede justificativa, não exclusão;
  - `ted_vencido_em_execucao` (média) — hoje é posterior ao fim da vigência e o estado é
    "Termo em Execução". **Só esse estado conta como "em execução"** (comparado sem acento nem
    caixa); os demais (prestação de contas, diligência, comprovado, finalizado) não. Um estado
    novo do SIMEC não gera alerta até ser classificado.

  - `ted_sem_movimentacao` (média) — TED em execução sem NC ou PF emitida há mais de **90
    dias** (definido com o usuário em 24/09/2026; era 180 por escolha inicial; parâmetro
    `PRAZO_SEM_MOVIMENTACAO_DIAS`). O briefing não define o prazo. Movimentação =
    NC ou PF com data de emissão (documento sem data ou com data futura não conta); a **NE não
    entra** porque `vinculo_ne` não guarda data. Sem nenhum documento, a referência é o início da
    vigência (TED recém-iniciado ainda não é "sem movimentação").
  - `ted_credito_sem_empenho` (**alta**) — TED com NC líquida positiva (consolidado) e **nenhuma NE
    ativa** vinculada (vínculo `descartado` não conta; `pendente` conta), passados **90 dias** da última
    NC de descentralização (`operacao = '+'`; NC de devolução não renova o prazo; sem NC datada, conta
    desde o início da vigência). Vale para **qualquer estado** do TED: NE ausente pode ser erro de
    inserção no SIMEC (a NE não foi lançada) — decisão do usuário em 24/09/2026. A NE não tem data no
    banco, então o prazo conta a partir da NC. Com o banco atual: 8 TEDs (última NC entre 2023 e 2025).
  - `ted_pf_sem_execucao_financeira` (média) — TED **em execução** com PF líquido positivo, NEs ativas
    com dado no Tesouro e **pago acumulado zero** nelas (execução financeira = pago no Tesouro,
    definido pelo usuário), passados 90 dias do último PF de repasse. Sem dado no Tesouro é "sem base",
    nunca zero. Com o banco atual: 6 TEDs em execução.

  Não implementado por falta de definição: "estado incompatível com os documentos". Sem número de TED, sem SIAFI e
  mesma chave TED–SIAFI com descrições conflitantes não podem ocorrer hoje (a chave exige os
  dois e a descrição fica numa linha por TED). Com o banco atual: 3 TEDs vencidos em execução, 3
  documentos (PF) fora da vigência e 9 TEDs em execução sem movimentação.

- **Execução por NE no Tesouro Gerencial** (`sincronizar_alertas_execucao_tg`, ao fim da
  sincronização da Execução Mensal, da importação de DOC NE e da reversão de lote; briefing,
  seções 8.2 e 10). Todos de gravidade "alta", tolerância R$ 0,01:
  - `ne_liquidado_maior_que_empenhado` e `ne_pago_maior_que_liquidado` — por NE;
  - `ne_simec_difere_tesouro` — por vínculo TED × NE: o `valor_ne` do SIMEC **não bate nem com o valor
    original nem com o líquido atual da NE no Tesouro** (ver abaixo).

  **Decisões (23/09/2026):** a comparação usa o **acumulado** da NE (soma de todos os meses de
  `execucao_tg`, estornos com sinal), nunca mês a mês — assim a liquidação ou o pagamento lançado
  num mês diferente do empenho não gera alerta falso. NE sem linha em `execucao_tg` (ex.: exercício
  anterior à Execução Mensal) é "sem base", nunca zero. Vínculos `descartado` (decisão de NE em
  mais de um TED) ficam de fora. Simulação com a extração real (cópia temporária do banco, sem
  gravar): de 134 NEs vinculadas, 126 têm dado no Tesouro; 24 têm valor do SIMEC diferente do
  empenhado do Tesouro; nenhuma com liquidado > empenhado ou pago > liquidado. **Valor da NE no SIMEC (decisão de 24/09/2026):** o "Valor da NE" do SIMEC é o valor ORIGINAL da NE
(confirmado pelo usuário), e o Tesouro acumula original + reforços − anulações. Por isso o alerta NÃO
compara só com o acumulado: o valor está *explicado* se bate com o **original** (primeiro movimento de
empenho não nulo da NE em `execucao_tg`) **ou** com o **líquido atual** (na extração real há NEs cujo SIMEC
já foi atualizado, ex.: 2024NE000818, original R$ 10.000, anulação de R$ 9.755,90, SIMEC R$ 244,10). O
original só é observável para NEs do primeiro ano da Execução Mensal em diante (a NE mais antiga tem o
empenho inicial fora da base, e o primeiro movimento visível seria um reforço) — NE anterior é "sem base".
Limite: reforço lançado no MESMO mês da emissão se soma ao original no primeiro movimento; nesse caso o
SIMEC só bate com o líquido, ou o alerta pede conferência.

**Relatório NE a NE (24/09/2026, extração real):** de 134 NEs vinculadas, 126 têm dado no Tesouro e 119
têm o SIMEC igual ao original. Das 28 que divergem do acumulado ou do original: **21 explicadas** (SIMEC =
original; reforços de até R$ 2,35 mi ou anulações no Tesouro, inclusive duas NEs anuladas em 100%), **4
explicadas** (SIMEC já igual ao líquido atual) e **3 sem explicação**, que geram alerta: 2025NE000695
(TED 14685; SIMEC R$ 20.000 × Tesouro R$ 10.000), 2025NE000735 (TED 16343; R$ 18.066,40 × R$ 14.781,60) e
2026NE000500 (TED 17061; SIMEC R$ 1.048.987,04 × Tesouro R$ 1.148.987,04, diferença de R$ 100.000).
Nenhuma das NEs divergentes está em mais de um TED.

**Não implementados:** "pago maior que o PF líquido" (por TED) — o pago da NE inteira seria
  atribuído ao TED mesmo quando a NE só está em parte vinculada a ele (os 24 casos acima — divergência de valor, não de vínculo), gerando
  alerta falso; "pagamento sem NE" — não se aplica, toda linha de `execucao_tg` já é por NE;
  separação de reforço e anulação — a Execução Mensal só traz o movimento líquido do mês.

Os demais alertas previstos no briefing (crédito sem empenho etc.) ficam para uma fase
seguinte, fora do escopo aprovado até aqui.

### 8.1 Trilha de auditoria (`src/teds_auditoria.py`)

Toda ação humana sobre alertas e vínculos grava um registro na tabela `auditoria`: `data_hora`
(UTC), `usuario`, `acao`, `entidade`/`entidade_id`, `valor_anterior` e `valor_novo` (JSON dos
campos que mudaram), `motivo` e `origem`. Hoje são duas ações:

- `alerta_status_alterado` — qualquer mudança de status pela Central de Alertas (em análise,
  resolvido), com responsável e justificativa como estavam antes e como ficaram;
- `vinculo_ne_decidido` — decisão sobre NE em mais de um TED, com o status de cada vínculo
  antes e depois e o TED escolhido (a decisão também gera o registro `alerta_status_alterado`).

**Garantias:** a tabela é *append-only* — gatilhos do SQLite abortam qualquer `UPDATE` e
`DELETE`, então corrigir é inserir um novo registro, nunca reescrever; a auditoria é gravada na
**mesma transação** da alteração que descreve (se uma falha, nenhuma persiste, coberto por
teste); uma justificativa encerra o alerta mas o alerta continua no banco. O banco existente
ganha a tabela e os gatilhos por `CREATE ... IF NOT EXISTS` em `conectar()`, sem tocar em
nenhum dado.

**Limite conhecido:** o projeto não tem usuário autenticado. `usuario` é o *responsável*
digitado na tela (o mesmo de `alerta.responsavel`), ou "não informado" — "Marcar em análise" não
exige responsável. A reversão de lote também é auditada (`lote_revertido`, seção 8.2).
Importação, reprocessamento, criação/remoção de vínculo e exportação (também listadas na seção
16 do briefing) **não** são auditadas ainda.

### 8.2 Reversão de lote e histórico de versões (`src/teds_reversao.py`)

As importações gravam por *upsert* (a extração mais nova vence). Para poder desfazer uma
importação sem perder o valor antigo, um gatilho copia a **versão anterior** de cada linha para
`historico_linha` sempre que um lote *diferente* a sobrescreve (7 tabelas: `ted`,
`execucao_anual`, `vinculo_ne`, `documento_nc_linha`, `documento_nc`, `documento_pf`,
`execucao_tg` — `TABELAS_VERSIONADAS` em `src/teds_schema.py`, conferida por teste contra o
esquema real). Reverter o lote B, para cada linha que hoje pertence a B:

- havia versão anterior de um lote que **não** foi revertido → a linha volta a ela, com o
  `import_batch_id` original;
- B criou a linha → ela sai da tabela de trabalho.

Em ambos os casos a versão de B vai para `linha_revertida` (JSON da linha inteira): **nada é
descartado**, só deixa de contar nos totais. O lote fica `status = 'revertido'` com `revertido_em`,
`revertido_por` e `motivo_reversao` (responsável e motivo obrigatórios), a ação entra na trilha
de auditoria (`lote_revertido`) e tudo ocorre **numa única transação**. `historico_linha` e
`linha_revertida` são append-only (gatilhos bloqueiam `UPDATE`/`DELETE`). Reverter fora de ordem
é permitido: o valor restaurado é o da versão anterior mais recente pertencente a um lote ainda
válido. O mesmo arquivo pode ser reimportado depois (vira um lote novo). Na página
**Importações**, seção "Reverter lote", com confirmação explícita. Medido: reverter um lote de
29 mil linhas leva menos de 1 s.

**Limites deliberados:**

- Só lotes gravados **depois** do histórico existir (`import_batch.versionado = 1`). Um lote
  anterior pode ter sobrescrito linhas sem guardar o valor antigo; revertê-lo apagaria dado que
  já existia, então é recusado com mensagem. No banco atual, **todos os lotes existentes são
  desse tipo** — só as importações feitas daqui em diante podem ser revertidas.
- `vinculo_ne.status_validacao` (decisão humana sobre NE em mais de um TED) não é revertido
  junto com o valor: ao restaurar um vínculo o status atual é mantido, e a sincronização de
  alertas de vínculo múltiplo roda ao final.
- Alertas já criados a partir do lote revertido **não são fechados** automaticamente (só uma
  pessoa resolve); os alertas dos dados que sobraram são recalculados.
- Não é um "desfazer" do que foi feito *depois* pelas pessoas (decisões, justificativas): essas
  ações têm a própria trilha e não são desfeitas pela reversão.

## 9. Páginas (barra lateral, grupo "TEDs")

1. **Visão geral** — dado real, consultado direto do banco; Liquidado/Pago mostram "Sem dado"
   até a Execução Mensal ser sincronizada (seção 6).
2. **Lista e detalhe** — uma página só (drill-down via
   `st.session_state["teds_chave_selecionada"]`, não uma entrada própria na barra lateral).
   "Registrar observação" fica desabilitado: não existe campo de observação manual no schema.
3. **Central de Alertas** — mestre-detalhe real sobre `src/teds_alertas.py`; workflow de
   análise (marcar "em análise", resolver com justificativa/responsável) também é real.
4. **Importações** — assistente de 4 passos (Arquivo → Mapeamento → Validação → Confirmação)
   sobre os leitores do SIMEC já testados ("Mapeamento" não é editável nesta versão), mais a
   seção "Tesouro Gerencial — Execução Mensal" com o botão de sincronização (seção 6).
5. **Conciliação** — SIMEC × Tesouro Gerencial, tolerância configurável via
   `st.session_state["teds_tolerancia_monetaria"]` (padrão R$ 0,01), não persistida em disco.
6. **Células NC × NE** — conciliação da célula orçamentária (seção 11), com indicadores por situação, filtros
   (exercício, TED, transferência, NC, NE, situação) e a tabela rastreável.
7. **Configurações** — só tolerância monetária, integridade do banco (`PRAGMA
   integrity_check`) e exportação do `.db` são reais; os demais campos (UG padrão, exercício
   padrão, formato de moeda etc.) são placeholders visíveis mas claramente marcados como
   ainda não aplicados.

## 11. Célula orçamentária NC × NE (`src/teds_celula_orcamentaria.py`, implementado em 24/09/2026)

**Objetivo:** para cada NE vinculada a um TED, comparar PTRES, fonte de recursos detalhada, natureza da
despesa (6 dígitos) e Plano Interno com as células das NCs do mesmo TED e exercício. Uma diferença é
**alerta para conferência** (`ne_celula_diverge_nc`, gravidade alta, um por TED × NE), **nunca** conclusão
de uso irregular do crédito.

**Fontes e persistência.** Duas bases de NC do Tesouro Gerencial, importadas na página Importações
("Destaques Recebidos", NCs até 2025, e "NC 2026") como novos tipos de relatório, com lote, hash, reversão
e histórico de versões como os demais. Gravam em `nc_celula` (uma linha por NC, transferência, tipo de
célula, PTRES, fonte, natureza e PI; linhas de classificação iguais são agregadas, com as `linhas_origem` da
planilha). As células das NEs vêm da Execução Mensal e são gravadas em `ne_celula` **no mesmo lote** da
sincronização (`sincronizar_execucao_tg`). São duas tabelas novas no banco de TEDs (que já tem persistência
própria, seção 1). Valores das NCs (`Saldo - Moeda Origem` / `NC Célula - Valor`) ficam guardados como
informação, **sem conciliação**: em algumas NCs a soma direta não bate com o total do extrato.

**Chaves.** A NC do extrato do SIMEC (`2025NC000408`) liga-se à do Tesouro (`154003152792025NC000408`, UG +
gestão + sufixo) pelo SUFIXO `AAAANCNNNNNN`, que sozinho **não** é chave única: desambigua-se pela
**transferência SIAFI** (`1AAMVG`) e, quando o SIMEC informa, pela UG emitente. NC do SIMEC com número
abreviado (`700014`, sem ano) não pode ser ligada e fica "ainda não identificada" — nunca ausente.
**Coincidência de célula nunca cria o vínculo** de uma NE com um TED: só o extrato TED → NE (`vinculo_ne`).

**Regras.** NC de 2026 tem células ORIGEM e DESTINO para a mesma movimentação: só DESTINO (o crédito
recebido) entra na comparação; as duas ficam guardadas e nada é somado entre elas. Códigos são texto (zeros
à esquerda preservados; apóstrofo inicial de exportação, como `'-8`, removido). NC só conta se é do
**mesmo exercício** da NE. Vínculos `descartado` ficam de fora; `pendente` entra com o status visível.
A comparação é do **conjunto**: a NE corresponde se ao menos uma célula das NCs tem os quatro campos iguais.

**Situações** (sempre visíveis na tabela): **Correspondente**; **Divergência para conferência** (há NCs
comparáveis e nenhuma tem a combinação da NE; mostra os campos divergentes e os valores que as NCs trazem
para eles); **NC não identificada ou base incompleta** (faltam NCs comparáveis ou a NE não tem célula na
base) — esta NÃO é divergência e **não gera alerta**: ausência de dado nunca aparece como conformidade nem
como irregularidade. Divergência com NC abreviada no TED avisa que a comparação pode estar incompleta.

**Validação com as extrações reais (24/09/2026).** 157 das 179 linhas de NC do SIMEC ligadas ao Tesouro
(22 abreviadas, sem ano); as 126 NEs do extrato localizadas na base de despesas; resultado: **116
correspondentes, 7 sem NC comparável e 3 divergentes** — 2024NE000423 e 2024NE000819 (TED 13103, com NC
abreviada ainda não identificada: comparação possivelmente incompleta) e o caso de referência
**2025NE000706** (R$ 4.997,80, TED 12112, transferência 1AAMVG; PTRES 230551, fonte 1000A00238, PI
MCC62G22EDN): natureza 339032 não consta nas NCs, que trazem 339014, 339030, 339033, 339036, 339039 e 339040.
A hipótese de erro no elemento previsto na programação orçamentária e financeira deve ser confirmada no
processo e no SIAFI.

**Não implementado:** o estado "vínculo com TED não confirmado" do briefing — como coincidência de célula
nunca cria vínculo, uma NE só é comparada quando o extrato TED → NE a liga ao TED; conciliação do **valor**
crédito × empenho por célula; e a análise de PF (acompanhamento financeiro separado da comparação NC × NE).

### 9.1 Reavaliação de alertas (`reavaliar_alertas`, `src/teds_lotes.py`)

Roda `sincronizar_alertas_rodape`, `_nc_parcial`, `_conciliacao_simec`, `_cadastrais`, `_execucao_tg`,
`_execucao_do_ted` e `_celula_orcamentaria` sobre os dados já importados. Só cria alertas ausentes
(deduplicação por tipo + documento entre os não resolvidos), é idempotente e grava um registro
`alertas_reavaliados` na trilha de auditoria (inclusive com 0 criados). Fica de fora
`sincronizar_alertas_multiplos_teds` (também recalcula `status_validacao`, dado derivado) e
`registrar_alertas_ted_sem_siafi` (depende das linhas rejeitadas de uma leitura). Motivo: no banco
real, as importações de 22/09 antecediam as regras de 23–24/09, e uma prévia em cópia do banco mostrou
38 alertas que nunca tinham sido gerados (12 de PF que difere do consolidado).

## 10. O que NÃO foi aprovado ainda

- Alertas além dos dezenove da seção 8.
- Edição do mapeamento de colunas na tela de Importações.
- Campo de observação manual por TED.
- Persistência dos parâmetros de Configurações além da sessão do navegador.
- Auditoria de importação, reprocessamento, exportação e criação/remoção de vínculo;
  identificação de usuário autenticado. Reversão de lotes anteriores ao histórico de versões.

Qualquer um desses itens exige aprovação explícita antes de implementação, conforme AGENTS.md.
