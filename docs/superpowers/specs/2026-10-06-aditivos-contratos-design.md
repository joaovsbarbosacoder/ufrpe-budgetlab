# Aditivos de Contratos Contínuos — especificação

Data: 06/10/2026 · Escopo aprovado em conversa, parte a parte (dados, cálculo, tela, relatórios, testes).
Base: Contratos Contínuos (`app_pages/contratos_continuos.py`). Bolsas e Auxílios fica fora.

## 1. Problema e objetivo

Quando um contrato vence e é prorrogado, o valor mensal normalmente é reajustado. Hoje o contrato tem
um único `despesa_mensal`: ao digitar o valor novo, ele passa a valer para o exercício inteiro e
distorce a necessidade de empenho, a projeção mensal, a sugestão do Reforço e a despesa anual.

Objetivo: registrar **aditivos** no contrato, cada um com o que muda e a partir de quando, e fazer
todas as contas usarem, mês a mês, o valor **em vigor naquele mês**.

Critérios de sucesso:

- contrato de 12 meses com aniversário em junho, 1º TA (01/07/2025, R$ 10.400) e 2º TA (01/07/2026,
  R$ 10.800): despesa anual de 2026 = 6 × 10.400 + 6 × 10.800 = **R$ 127.200**; em 2027 começa em
  R$ 10.800;
- contrato **sem aditivo**: todos os números (necessidade, projeção, despesa anual, cobertura por
  PTRES, sugestão do Reforço) **idênticos** aos de antes da mudança;
- todo valor derivado de aditivo é rastreável até o termo (nº, tipo, datas, valor anterior → novo).

## 2. Decisões tomadas com o usuário

| Tema | Decisão |
|---|---|
| Abordagem | A: lista `aditivos` dentro do cadastro do contrato (mesmo padrão de `itens`) + módulo isolado de cálculo. Sem banco nem persistência nova. |
| Conteúdo do aditivo | Novo valor mensal + data de início; nova vigência (fim); nº do termo e tipo; novo rateio dos itens. |
| Retroativo | Entra na necessidade; na projeção, no **primeiro mês projetado**, identificado como "retroativo". |
| Data de assinatura | Campo opcional do aditivo; define o retroativo da projeção. |
| Renovação ainda não assinada | Aditivo com situação **PREVISTO** (valor estimado), destacado em tela e relatórios. Sem previsto, a projeção **para no vencimento**, com aviso. |
| "Meses no ano" | Referência/teto. As datas (início, vigência efetiva, suspensão) decidem quais meses contam. |
| "Despesa mensal" do contrato | Passa a significar o **valor original**, antes do primeiro aditivo cadastrado. |

## 3. Dados

### 3.1 Aditivo (item da lista `aditivos` do contrato)

| Campo | Tipo gravado | Obrigatório | Significado |
|---|---|---|---|
| `numero` | texto | sim | Nº do termo, ex. "2º TA". Identificador, nunca convertido em número. |
| `tipo` | texto | sim | `REAJUSTE`, `REPACTUACAO`, `PRORROGACAO`, `ACRESCIMO_SUPRESSAO`, `OUTRO`. |
| `situacao` | texto | sim | `PREVISTO` ou `ASSINADO`. |
| `data_inicio` | `"AAAA-MM-DD"` | sim | A partir de quando o aditivo vale (pode ser passada: retroativo). |
| `data_assinatura` | `"AAAA-MM-DD"` ou nulo | não | Data em que foi assinado. |
| `valor_mensal` | número ou nulo | não | Nulo = mantém o valor anterior. |
| `vigencia_fim` | `"AAAA-MM-DD"` ou nulo | não | Nulo = mantém a vigência anterior. |
| `itens` | lista `{numero, percentual}` ou nulo | não | Nulo = mantém o rateio anterior. |

Datas aninhadas são gravadas como texto ISO (o `st.date_input` devolve `date`, que não é
serializável; `src/cadastro_por_exercicio._serializavel` só converte `pd.Timestamp`).

### 3.2 Contrato

- `aditivos` entra em `CAMPOS_IDENTIDADE` de `src/contratos_continuos_cadastro.py`: é **copiado ao
  duplicar o exercício** (o histórico acumula; o valor de 1º de janeiro de cada ano sai da aplicação
  dos aditivos em ordem). Registro antigo sem o campo = lista vazia.
- `despesa_mensal` = valor original (antes do 1º aditivo). `vigencia_fim` = vigência original. Nenhum
  dos dois é sobrescrito por aditivo.

### 3.3 Derivados (calculados, nunca gravados)

- **Valor mensal vigente** em uma data: o `valor_mensal` do último aditivo (por `data_inicio` ≤ data)
  que tem valor; senão `despesa_mensal`.
- **Vigência efetiva**: `vigencia_fim` do último aditivo que a informa; senão a do contrato.
- **Rateio vigente** em uma data: idem, a partir de `itens`.
- **Tem previsto**: algum aditivo `PREVISTO` afeta o exercício.

Aditivos `PREVISTO` entram em todos os derivados (marcados como tal).

### 3.4 Validação (ao salvar a janela)

- `numero`, `tipo`, `situacao`, `data_inicio` obrigatórios;
- ao menos uma alteração: `valor_mensal`, `vigencia_fim` ou `itens`;
- `itens`, quando informado, soma 100% (tolerância de 0,5 p.p., como hoje);
- duas `data_inicio` iguais no mesmo contrato: bloqueado (ordem ambígua);
- `valor_mensal` negativo: aceito, com destaque na tela (a base real já tem um caso);
- erro mostrado junto do aditivo; nada é gravado enquanto houver erro.

### 3.5 Dados existentes

Contratos sem aditivo não mudam. Contrato que **já teve o reajuste digitado por cima** em "Despesa
mensal": para registrar o aditivo, o usuário volta "Despesa mensal" ao valor antigo e lança o aditivo
com o novo. O sistema não faz essa troca sozinho (dado financeiro não é alterado sem o usuário ver).

## 4. Regra de cálculo

Módulo novo `src/contratos_aditivos.py` (puro: só pandas/datetime, sem Streamlit, sem leitura de
arquivo). Toda conta abaixo vive nele ou em `src/necessidade_empenho.py`; tela e relatórios só
consomem.

### 4.1 Valor por dia e custo do mês

- `valor(d)` = valor mensal vigente no dia `d` (§3.3).
- **Dias em execução** no exercício: do início da execução informado (data ou mês manual; senão
  1º/jan) até o menor entre a vigência efetiva e a véspera da suspensão (quando `SUSPENSO` com
  data), mesmas regras de status de hoje (`SUSPENSO` sem data ou `VENCIDO` sem data: nenhum dia;
  data manda sobre status).
- **Teto de "meses no ano"** (`N`, 12 se vazio): os dias em execução, contados a partir do primeiro,
  param quando a soma das frações mensais (`dias do mês em execução ÷ dias do mês`) atinge `N`.
- **Custo do mês** `m` = Σ, nos dias em execução de `m`, de `valor(d) ÷ dias_do_mês(m)`.

Com valor constante, `Σ custo(m) = despesa_mensal × meses vigentes` — a mesma conta de hoje.

### 4.2 Necessidade de Empenho até Dezembro

`necessidade = max(0, Σ_m custo(m) − empenhado)`. Retroativo incluído automaticamente.
"Meses já empenhados" = meses (fracionados) cobertos pelo empenhado percorrendo `custo(m)` de janeiro
em diante; "meses restantes" = meses em execução − meses já empenhados (nunca negativo).
Mantém `necessidade_por_ne(...)` como ponto único usado pelo card, pela faixa do topo e pelo relatório.

### 4.3 Projeção mensal (Relatório de Necessidade)

- Cada mês projetado vale `custo(m)` (antes: despesa mensal fixa); o abatimento do saldo no primeiro
  mês e nos seguintes continua igual.
- **Retroativo** de um aditivo com `valor_mensal`, `ASSINADO` e `data_assinatura > data_inicio`:
  Σ, nos dias de `[data_inicio, data_assinatura)` que caem em meses **já realizados** (com
  liquidação por competência) do exercício, de `(valor(d) − valor_sem_esse_aditivo(d)) ÷ dias_do_mês`.
  Somado ao **primeiro mês projetado**, em coluna própria `retroativo`. Sem `data_assinatura`: zero.
- Mês projetado em que o valor vem de aditivo `PREVISTO`: tipo "projetado — aditivo previsto".
- Sem aditivo previsto depois do vencimento, a projeção para na vigência efetiva (regra atual).

### 4.4 Sugestão do Reforço "por calendário"

`alvo = Σ custo(m)` de janeiro até o mês vigente (mesma regra de "mês vigente" e de exercício
encerrado de `necessidade_ate_mes_vigente`); `valor_sugerido = max(0, alvo − empenhado)`;
`meses_sugeridos = valor_sugerido ÷ valor mensal vigente` (nulo se o vigente for 0 ou nulo).
Itens: rateio vigente. A sugestão de reserva por execução (`meses_a_empenhar`) passa a usar o valor
mensal vigente. Edição por linha continua livre; Anulação continua sem sugestão.

### 4.5 Despesa anual e Cobertura por PTRES

`despesa_anual = Σ` dos valores mensais de janeiro em diante, até `N` meses (teto de "meses no ano"),
**sem** o corte de vigência/início (como hoje). Contrato `SUSPENSO`: continua o já empenhado
(`com_efeitos_da_suspensao`, inalterado).

## 5. Tela (janela "Editar contrato")

- "Período de execução" ganha as abas **Período** e **Aditivos** (`st.tabs` dentro do `st.dialog`).
- **Período**: campos atuais; "Vigência (fim)" rotulado "original"; abaixo, a vigência efetiva
  (somente leitura) quando algum aditivo a altera.
- **Aditivos**: um cartão por aditivo, em ordem de `data_inicio`. Linha 1: Nº, Tipo, Situação, Data de
  início, Data de assinatura. Linha 2: Novo valor mensal, Nova vigência, "Alterar rateio dos itens"
  (abre os percentuais, mesmo formato da seção de itens). Botão "Remover aditivo"; abaixo,
  "Adicionar aditivo". Lista em `st.session_state`, recarga só do fragmento (`st.rerun(scope="fragment")`),
  grade feita com `st.columns` e widgets — **nunca `st.data_editor`** (quebra dentro de `st.dialog`).
- Topo da janela: "Valor mensal vigente" (com o TA que o definiu e marca "previsto"), "Vigência
  efetiva" e "Despesa anual" pela série.
- Registro de contratos: coluna de vigência mostra a efetiva (marca "TA" / "previsto"); subtítulo
  ganha "N aditivo(s)".
- "Novo contrato": sem aditivos.

## 6. Relatórios e avisos

- **Relatório de Necessidade** — grade: meses de aditivo previsto com marca e legenda "valor
  estimado (aditivo previsto)"; retroativo no primeiro mês projetado com nota "inclui R$ X de
  retroativo (nº TA)". Excel: "Detalhe mensal" distingue "realizado"/"projetado"/"projetado — aditivo
  previsto" e ganha a coluna "Retroativo"; **aba nova "Aditivos"** (contrato, NE, nº, tipo, situação,
  início, assinatura, valor anterior → novo, nova vigência, retroativo). Resumo por NE: "Valor mensal
  vigente", "Custo do exercício", "Retroativo".
- **Avisos novos**: "Renovação não cadastrada" (contrato não suspenso cuja vigência efetiva termina no
  exercício sem aditivo posterior, nem previsto); "Aditivos previstos (valores estimados)"; "Aditivo
  com valor mensal negativo".
- **Card "Resumo Consolidado" e faixa do topo**: necessidade inclui previstos, com "inclui R$ X
  estimados em aditivos previstos" quando houver.
- **Relatório de Reforço**: "Valor mensal" = vigente; rateio vigente; situação da linha mostra
  "2º TA desde 01/07/2026" e "previsto". Layout dos dois PDFs inalterado.
- **Cobertura por PTRES**: despesa pela série; "inclui aditivos previstos" quando houver.

## 7. Testes

- **Retrato de referência** (gravado antes de qualquer mudança de conta): necessidade por NE,
  projeção mês a mês, despesa anual, cobertura por PTRES e sugestão do Reforço dos contratos reais de
  2026; teste exige igualdade depois da mudança (contratos sem aditivo).
- Suíte atual (1646 testes) continua passando.
- Novos, com valores calculados à mão: série (sem aditivo, aditivo dia 1º, meio do mês, dois no ano —
  R$ 127.200 —, vindo do ano anterior, só prorrogação, previsto, com suspensão, com início, com
  `N < 12`); vigência efetiva e "renovação não cadastrada"; retroativo com e sem assinatura;
  validações; cadastro (ida e volta com datas ISO e nº como texto, duplicação copia, registro antigo
  sem o campo); relatórios (aba Aditivos, colunas, avisos, marca de previsto; PDFs do Reforço
  inalterados); página (janela abre com as abas Período e Aditivos sem erro).

## 8. Entrega em etapas

1. `src/contratos_aditivos.py` (série, custo, vigência efetiva, rateio vigente, retroativo, validação)
   + retrato de referência.
2. Cadastro (`aditivos` em `CAMPOS_IDENTIDADE`, leitura de registros antigos).
3. Necessidade, projeção, despesa anual, cobertura.
4. Reforço.
5. Tela.
6. Relatórios, avisos, README.

Cada etapa: testes da etapa + suíte completa quando houver risco de regressão.

## 9. Fora do escopo

Bolsas e Auxílios; aditivos na janela "Novo contrato"; leitura de aditivos da planilha "Contratos —
Vigência" ou de qualquer base externa; cálculo automático de reajuste por índice; conversão
automática de contratos já reajustados por cima.

## 10. Riscos

- **Regressão nas contas centrais** (necessidade, projeção, Reforço): mitigada pelo retrato de
  referência e pela equivalência matemática com valor constante.
- **Complexidade da janela** (abas + cartões dinâmicos dentro de `st.dialog`): o `AppTest` só exercita
  a abertura da janela; interação interna fica coberta por testes da regra.
- **Previsto confundido com definitivo**: mitigado pelas marcas em tela, relatórios e avisos.
