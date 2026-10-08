# TEDs — alertas sem falso positivo e conferência com a planilha de controle de NCs — especificação

Data: 08/10/2026 · Base: revisão crítica do módulo de TEDs feita em conversa com o usuário (dados do banco
`data/teds/teds.db`: SIMEC de 22/09, Tesouro de 25/09) e a planilha `CONTROLE DESC.CREDITOS ATUALIZADA.xlsx`.
Revisão 2 (08/10/2026): a planilha **não é fonte contínua** — serve para sanear dúvidas e pendências (pedido do
usuário). Ela não é gravada no banco nem alimenta as regras de alerta.

## 1. Problema e objetivo

Dos 96 alertas abertos, cerca de 60 (63%) são ruído ou falso positivo, e nenhum foi tratado até hoje. Medido nos
dados reais:

| Alerta | Abertos | Causa |
|---|---|---|
| `pf_liquida_diverge_consolidado` | 12 | 3 somem ao comparar o mesmo período (PF desde 2019 × consolidado desde 2023); 9 são TEDs sem nenhum PF no extrato, comparados como R$ 0 |
| `pf_liquida_maior_que_nc` | 7 | Todos têm vigência iniciada antes de 2023: a NC daquele período não está no consolidado |
| `nc_ug_emitente_ausente` | 41 | Falha sistemática do SIMEC (28% das NCs sem UG); um alerta por NC polui a Central |
| `ted_sem_movimentacao` | 13 | 12 válidos; o TED 10782 aparece "sem movimento desde 2021" com R$ 1,6 mi repassado em 2023–2026 no consolidado |

**Objetivo:** (1) os alertas de conciliação passam a apontar só divergência comprovável pelas fontes oficiais
(SIMEC e Tesouro); (2) a planilha manual de controle de NCs vira uma **ferramenta de consulta** na página Conciliação,
para tirar dúvidas e sanear pendências caso a caso.

**Critérios de sucesso** (com os dados atuais do banco):

- `pf_liquida_diverge_consolidado`: os 3 casos de janela deixam de ser divergência; os 9 TEDs sem PF no extrato
  passam a "sem base" (sem alerta).
- `pf_liquida_maior_que_nc`: os 7 TEDs com vigência anterior ao consolidado passam a "sem base" (sem alerta).
- `nc_ug_emitente_ausente`: um alerta por TED (17 TEDs), não por NC (41).
- Alertas úteis inalterados: crédito sem empenho (8), NE SIMEC ≠ Tesouro (3), vencido em execução (3), documento
  fora da vigência (3), repasse sem execução (6).
- A planilha nunca é gravada: a conferência roda em memória; o único registro persistente é a resolução de alerta
  feita pelo usuário (com justificativa e auditoria, como já existe).

## 2. Decisões

| Tema | Decisão |
|---|---|
| Papel da planilha | Ferramenta de consulta, **em memória**. Sem tabela, sem lote, sem coluna nova no banco, sem efeito nas regras |
| Persistência nova | **Nenhuma** |
| Alertas que deixam de valer | **Opção A (aprovada em 08/10/2026):** a reavaliação fecha os alertas abertos que as regras revistas não sustentam, com justificativa automática e auditoria (§4) |
| Resolver alerta pela planilha | **Incluído** (decisão do controlador após "pode seguir"): botão por alerta relacionado, justificativa pré-preenchida e editável, gravada pelo fluxo de resolução já existente (auditado). Nunca automático |
| Célula orçamentária da NC | Fora: deve vir dos relatórios de NC do Tesouro (leitor já existe) |

## 3. Regras revistas (só fontes oficiais)

### 3.1 Janela comum (`pf_liquida_diverge_consolidado`, `nc_liquida_diverge_consolidado`)

- O consolidado (`execucao_anual`) cobre, por TED, um conjunto de anos (`ano_emissao`). A soma analítica passa a
  considerar **só os documentos com data nesses anos**.
- Documento sem data não pode decidir sozinho (revisão de 08/10/2026, achado nos dados reais: NCs principais de TEDs
  vêm sem data): só há alerta se a diferença persistir **com e sem** os documentos sem data (janela e janela + sem
  data, ambos contra o consolidado). Senão, inconclusivo, sem alerta. A descrição cita o valor sem data.
- **TED sem nenhum documento do tipo no extrato** = "sem base" → **sem alerta**.
- Quando houver alerta, a descrição cita o valor dos documentos fora da janela.

### 3.2 PF maior que a NC (`pf_liquida_maior_que_nc`)

- Se a vigência do TED começa antes de 1º de janeiro do primeiro ano do consolidado daquele TED → "sem base", **sem
  alerta** (a NC do período anterior não está nas fontes oficiais importadas).
- Senão, alerta como hoje (repasse consolidado > NC consolidada além da tolerância).

### 3.3 NC sem UG emitente (`nc_ug_emitente_ausente`)

- Um alerta **por TED** (documento `ted:<chave_ted>`, gravidade `baixa`), com a lista das NCs sem UG. TED sem NC
  nessa situação não gera alerta.

### 3.4 Sem movimentação (`ted_sem_movimentacao`)

- Movimentação = a mais recente entre NC/PF emitida (como hoje) e liquidação/pagamento ≠ 0 no Tesouro em NE vinculada
  ao TED (último dia do mês de lançamento).
- Se o consolidado tem NC/PF no ano corrente sem documento datado correspondente, a descrição avisa ("o consolidado
  indica movimentação em AAAA que não está nos documentos importados"); o alerta continua.

### 3.5 Crédito sem empenho (`ted_credito_sem_empenho`)

- Regra igual. A descrição separa TED encerrado (comprovado, finalizado, prestação de contas, relatório de
  cumprimento: "NE não registrada no SIMEC — pendência para a prestação de contas") de TED em execução.

## 4. Reavaliação fecha alertas obsoletos (opção A)

Para os tipos revistos (`nc_liquida_diverge_consolidado`, `pf_liquida_diverge_consolidado`, `pf_liquida_maior_que_nc`,
`nc_ug_emitente_ausente`, `ted_sem_movimentacao`): alerta aberto cujo `(tipo, documento)` não é mais produzido pelas
regras → `resolvido`, responsável "sistema", justificativa "Regra revisada em 08/10/2026: <motivo>", registro
`alerta_status_alterado` na auditoria, na mesma transação. Tipos não revistos nunca são fechados. Alerta resolvido
manualmente nunca é reaberto.

## 5. Conferência com a planilha de controle (página Conciliação)

### 5.1 Leitura em memória (`src/teds_controle_nc.py`, novo, sem Streamlit)

- Uma aba por ano. Cabeçalho = primeira das 6 primeiras linhas com uma célula "NC"; colunas por apelido (layouts
  diferentes por ano): NC, DATA, UG EMITENTE, NOME ÓRGÃO/UNIDADE ORÇAMENTÁRIA, OFÍCIO, FONTE, PTRES, ND, PI,
  TED / TED N., TRANSFERÊNCIA (ou "TED N. TRANSFERENCIA" colado, 2014–2017), VALOR / VALOR RECEBIDO,
  PROCESSO / PROCESSO SIPAC, OBSERVAÇÃO.
- Linha de continuação herda NC, data, UG, órgão, ofício, fonte, TED, transferência e processo da linha de cima, na
  mesma aba. Linha sem valor numérico é rejeitada com motivo. Aba não reconhecida (hoje: 2021) é listada, nunca
  ignorada em silêncio. Códigos como texto; "-" vira nulo. Nada é corrigido.

### 5.2 Conferência (em memória, contra o banco)

- Por NC do SIMEC: liga pelo número da NC e o TED; quando as duas trazem UG, a UG também precisa bater. Situação:
  `confere` (valor em R$ 0,01), `diverge`, `ambigua` (mais de um candidato, ex.: mesmo número em UGs diferentes) ou
  `sem_planilha`. Mostra a UG que a planilha traz para NC sem UG no SIMEC (sugestão, não gravada).
- Por TED: NCs da planilha com data anterior ao primeiro ano do consolidado (responde aos casos "sem base" de PF > NC).
- Descentralizações sem TED na planilha (informativo).
- Download do resultado em Excel (abas: Conferência por NC, NC anterior ao consolidado, Sem TED, Abas e linhas não
  lidas).

### 5.3 Resolver alerta com base na planilha

- Para alertas abertos dos tipos `nc_ug_emitente_ausente`, `pf_liquida_maior_que_nc`, `pf_liquida_diverge_consolidado`
  e `ted_credito_sem_empenho` de TEDs com dado na planilha, a seção lista o alerta com uma justificativa sugerida
  (ex.: "Planilha de controle: NC 2022NC001794 de 03/08/2022, R$ 2.246.361,47 (UG 152734)."), editável, campo de
  responsável e botão **Resolver**. Grava pelo fluxo já existente (`teds_ui.atualizar_status_alerta`), auditado.
  Nada é resolvido sem o clique.

## 6. Testes

- Leitor: layouts 2014–2017, 2022–2024, 2025, 2026; continuação; aba não reconhecida; zero à esquerda; "-" nulo;
  linha sem valor rejeitada.
- Conferência: confere, diverge, ambígua, sem planilha; UG sugerida; NC anterior ao consolidado por TED.
- Regras: janela (3 casos reais em fixture), janela parcial, sem base, PF > NC sem base e real, NC sem UG por TED,
  movimentação pelo Tesouro, descrição do consolidado, descrição de crédito sem empenho por estado.
- Reavaliação: fecha obsoleto com justificativa e auditoria, mantém válido, não fecha tipo não revisto, não reabre
  resolvido, idempotente.
- Páginas: conferência com upload em memória não grava nada no banco; resolver pela planilha grava status e auditoria.

## 7. Fora do escopo

- Gravar a planilha ou usá-la nas regras.
- Célula orçamentária da NC pela planilha.
- Pendências avaliadas como "não fazer" na revisão.
- Atualização dos dados (sincronizar o Tesouro com a extração de 07/10, reimportar o SIMEC): operação na página
  Importações, recomendada antes de validar.
