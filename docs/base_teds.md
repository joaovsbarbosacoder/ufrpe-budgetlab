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
- **"Total do rodapé"**: as 4 extrações reais revisadas não tiveram uma linha de rodapé com
  total confirmado coluna a coluna. Capturar isso exigiria presumir um formato ainda não
  visto — não implementado nesta rodada (ver AGENTS.md).

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
  geral saiu (seria 100% por construção). Integrar a competência real ao TEDs é decisão
  **futura**, fora deste escopo.
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

Dez tipos (`src/teds_alertas.py`), cada um com funções puras testáveis sem banco e uma
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

  Não implementados por falta de definição: "TED em execução sem movimentação" (o que conta
  como movimentação?) e "estado incompatível com os documentos". Sem número de TED, sem SIAFI e
  mesma chave TED–SIAFI com descrições conflitantes não podem ocorrer hoje (a chave exige os
  dois e a descrição fica numa linha por TED). Com o banco atual: 3 TEDs vencidos em execução e
  3 documentos (PF) fora da vigência.

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
exige responsável. Importação, reversão de lote, criação/remoção de vínculo e exportação
(também listadas na seção 16 do briefing) **não** são auditadas ainda.

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
6. **Configurações** — só tolerância monetária, integridade do banco (`PRAGMA
   integrity_check`) e exportação do `.db` são reais; os demais campos (UG padrão, exercício
   padrão, formato de moeda etc.) são placeholders visíveis mas claramente marcados como
   ainda não aplicados.

## 10. O que NÃO foi aprovado ainda

- Competência real no TEDs (Documento Hábil × mês de referência, via Liquidação por
  Competência) — ver seção 6.
- Alertas além dos dez da seção 8.
- Edição do mapeamento de colunas na tela de Importações.
- Campo de observação manual por TED.
- Persistência dos parâmetros de Configurações além da sessão do navegador.
- Auditoria de importação, reprocessamento, reversão de lote, exportação e criação/remoção de
  vínculo; identificação de usuário autenticado.

Qualquer um desses itens exige aprovação explícita antes de implementação, conforme AGENTS.md.
