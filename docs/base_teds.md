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
| Tesouro Gerencial — execução por empenho | `ler_execucao_tg` (`src/teds_importacao_tesouro_gerencial.py`) | **Não** — ver seção 6 |

A leitura do arquivo bruto (abertura do Excel, cálculo do hash SHA-256) é responsabilidade de
`src/teds_lotes.py`; os leitores acima recebem o `DataFrame` já carregado e devolvem
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

## 6. Fonte do Tesouro Gerencial: resolvida — é a Execução Mensal (plano de integração, ainda não implementado)

O briefing original descrevia **duas** bases do Tesouro Gerencial ("execução da despesa por
empenho" e "liquidação por competência"), mas o schema (`execucao_tg`) modelava as duas
misturadas numa única tabela, por falta de uma extração real para confirmar. Sem essa
extração, `ler_execucao_tg` (`src/teds_importacao_tesouro_gerencial.py`) assumia o cenário mais
permissivo — uma linha por `(NE, documento hábil, documento contábil, competência)`.

**Confirmado pelo usuário em 22/09/2026: a extração do Tesouro Gerencial É a extração de
Execução Mensal já implementada em `src/tesouro_execucao_mensal.py`** (BI CPOC / Tesouro
Gerencial — ver `docs/base_execucao_mensal.md`). Não existe uma segunda base separada a
importar; TEDs deve consumir a mesma extração que já alimenta a Execução Mensal, em vez de ter
seu próprio leitor de arquivo.

Isso substitui a leitura de arquivo dedicada por consumir a saída já pronta de
`src/tesouro_execucao_mensal.py`:

| Campo de `execucao_tg` | Fonte na Execução Mensal | Situação |
|---|---|---|
| `numero_completo_ne` | `ne_ccor` (formato "CCOR"; `ne_ano`/`ne_numero` já são derivados dele via slice — ver `tesouro_execucao_mensal.py:285-286`) | precisa confirmar conversão para o formato `AAAANEnnnnnn` que `decompor_numero_ne` espera |
| `favorecido` | `ne_favorecido` (`_DIMENSOES_CONSTANTES_POR_NE`) | mapeamento direto |
| `empenhado` | `linha_do_tempo_por_ne(df)["empenhada"]` | já deduplicado corretamente por bloco (ver docstring da função) |
| `liquidado` | `linha_do_tempo_por_ne(df)["liquidada"]` | mapeamento direto |
| `pago` | `linha_do_tempo_por_ne(df)["paga"]` | mapeamento direto |
| `ano_competencia`/`mes_competencia` | decompor `ano_mes` (inteiro `ano*100+mes`) | mapeamento direto |
| `valor_competencia` | sem equivalente óbvio — Execução Mensal não separa "competência" de "mês" | precisa decisão: campo pode ficar redundante com `mes_competencia` |
| `descricao` | sem equivalente ao nível de NE nesta base | provavelmente fica sem fonte |
| `documento_habil` / `documento_contabil` | sem equivalente nesta base | **decisão registrada: remover do schema** `execucao_tg` (não há fonte prevista) |

**Status: plano registrado, implementação NÃO iniciada.** `src/tesouro_execucao_mensal.py`
está em reestruturação ativa pelo usuário no momento desta decisão (nova coluna `Fonte
Recursos Detalhada` adicionada em 22/09/2026, por exemplo) — conectar TEDs a essa base agora
significa construir sobre um contrato que ainda está mudando. A implementação (reescrever
`src/teds_importacao_tesouro_gerencial.py` para consumir `linha_do_tempo_por_ne` em vez de ler
um arquivo próprio, remover `documento_habil`/`documento_contabil` de `src/teds_schema.py`,
resolver os mapeamentos em aberto acima) fica para quando o usuário confirmar que a Execução
Mensal estabilizou.

Enquanto o plano não for implementado, o comportamento atual se mantém: os indicadores de
Liquidado/Pago e a conciliação SIMEC × Tesouro Gerencial (páginas Visão geral e Conciliação)
mostram "Sem dado (Tesouro Gerencial)" em vez de um valor inventado.

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

Dois tipos (`src/teds_alertas.py`), cada um com funções puras testáveis sem banco e uma
`sincronizar_alertas_*` que lê do SQLite e grava alertas novos sem duplicar um alerta já
aberto para o mesmo documento — e sem nunca fechar um alerta sozinha (resolução é sempre ação
humana, registrada na Central de Alertas):

- **Empenho associado a mais de um TED** — caso concreto documentado no briefing (NE
  2026NE000422 nos TEDs 17352 e 17454). A NE fica com `status_validacao='pendente'` e é
  excluída da soma de `valor_ne` por TED até uma decisão humana (`decisao_vinculo_ne`,
  append-only: os vínculos originais não são apagados, só um fica contabilizável).
- **NC sem UG emitente** (`status_relacionamento='PARCIAL'`) — achado da extração real do
  SIMEC (seção 5), não do briefing original; aprovado explicitamente para gerar alerta.

Os demais alertas previstos no briefing (crédito sem empenho, PF maior que NC, vigência etc.)
ficam para uma fase seguinte, fora do escopo aprovado até aqui.

## 9. Páginas (barra lateral, grupo "TEDs")

1. **Visão geral** — dado real, consultado direto do banco; Liquidado/Pago mostram "Sem dado"
   enquanto a seção 6 não for resolvida.
2. **Lista e detalhe** — uma página só (drill-down via
   `st.session_state["teds_chave_selecionada"]`, não uma entrada própria na barra lateral).
   "Registrar observação" fica desabilitado: não existe campo de observação manual no schema.
3. **Central de Alertas** — mestre-detalhe real sobre `src/teds_alertas.py`; workflow de
   análise (marcar "em análise", resolver com justificativa/responsável) também é real.
4. **Importações** — assistente de 4 passos (Arquivo → Mapeamento → Validação → Confirmação)
   sobre os leitores já testados; "Mapeamento" não é editável nesta versão.
5. **Conciliação** — SIMEC × Tesouro Gerencial, tolerância configurável via
   `st.session_state["teds_tolerancia_monetaria"]` (padrão R$ 0,01), não persistida em disco.
6. **Configurações** — só tolerância monetária, integridade do banco (`PRAGMA
   integrity_check`) e exportação do `.db` são reais; os demais campos (UG padrão, exercício
   padrão, formato de moeda etc.) são placeholders visíveis mas claramente marcados como
   ainda não aplicados.

## 10. O que NÃO foi aprovado ainda

- Implementação do plano de integração com a Execução Mensal (seção 6) — planejado e aprovado
  em decisão, mas aguardando a Execução Mensal estabilizar antes de codificar.
- Alertas além dos dois da seção 8.
- Edição do mapeamento de colunas na tela de Importações.
- Campo de observação manual por TED.
- Persistência dos parâmetros de Configurações além da sessão do navegador.

Qualquer um desses itens exige aprovação explícita antes de implementação, conforme AGENTS.md.
