# Estimativa de reajuste — revisão das regras (v2)

Data: 11/10/2026. Substitui as regras de data-base e de "reajuste assinado" de
`2026-10-11-estimativa-reajuste-contratos-design.md` (o resto daquela spec continua valendo: base liquidado, IPCA
padrão, cenário separado, nulo ≠ zero).

## Por que mudou

Auditoria dos 34 contratos ligados ao Contratos.gov (11/10/2026):

- O termo aditivo com qualificação REAJUSTE é assinado **antes ou no dia** do novo valor em 43 de 44 casos: ele
  formaliza o direito, não traz o valor. O valor costuma vir depois, por **apostilamento**, muitas vezes
  **retroativo** (5 contratos com apostilamento retroativo assinado em 2026, cobrindo competências de 2024 a 2026).
- A cadência é anual na maioria, mas há reajustes/renovações em intervalos curtos (92 a 152 dias).
- Erros da v1: (1) reajuste formalizado saía da estimativa e a despesa sumia; (2) ciclos anteriores a janeiro eram
  presumidos já incorporados ao valor, o que é falso quando há retroativo; (3) data-base pela última renovação falha
  com renovações curtas.

## Decisões do usuário

| Tema | Decisão |
|---|---|
| Data-base | Aniversário de 12 em 12 meses a partir do **último reajuste formalizado** (termo aditivo com REAJUSTE no gov ou aditivo de Reajuste assinado no cadastro); sem nenhum, a partir do início do contrato. A data manual continua mandando. |
| Retroativo de anos anteriores | Aparece **separado**, como exercícios anteriores, fora do total das competências do exercício. |

## Regras de formação dos ciclos (validadas contra os 36 contratos reais)

- **Eventos de reajuste:** termo aditivo do gov com REAJUSTE; aditivo de Reajuste assinado no cadastro (com ou sem
  valor); e **apostilamento com novo valor** — o reajuste por índice costuma ser formalizado por apostila —, mas só
  quando não há termo de reajuste a menos de um ano dele (perto de um termo, o apostilamento é a implantação daquele
  reajuste, não um ciclo próprio).
- **Anualidade:** evento a menos de 330 dias do reajuste anterior (ou do início do contrato) não abre ciclo novo
  (interregno mínimo de um ano). Com isso, a janela do índice é sempre os **12 meses anteriores** à data-base.
- **Implantação:** o primeiro apostilamento assinado a partir da data-base com novo valor até um ano depois dela; a
  data de implantação é a maior entre assinatura e novo valor. O **liquidado** de competência iniciada depois da
  implantação já vem reajustado — o ciclo não incide de novo sobre ele (sem dupla contagem). A base contratada
  (teto) continua recebendo o acréscimo enquanto o valor não for registrado no cadastro.
- **Pendente antes do exercício:** ciclo formalizado anterior a janeiro só entra se sua implantação foi assinada no
  exercício ou se um apostilamento retroativo assinado no exercício cobre a data-base.
- **NEs de anos anteriores:** além das NEs do cadastro, entram as NEs do contrato no Contratos.gov **com o mesmo
  plano interno** do cadastro (o gov traz o contrato inteiro, de várias ações; Contínuos é a parcela da 20RK). Sem
  PI no cadastro, nenhuma NE do gov é acrescentada.

## Modelo: ciclos com estado

| Estado | Quando | Entra na estimativa? |
|---|---|---|
| **Registrado** | Aditivo de Reajuste ASSINADO **com valor** no cadastro (ou reajuste do gov a até 45 dias dele) | Não — o valor real já está no valor mensal. Serve de âncora. |
| **Formalizado, a confirmar** | Reajuste no gov (ou aditivo assinado sem valor) sem valor no cadastro, com data-base **no exercício** — ou **antes** dele, se um apostilamento **retroativo assinado no exercício** cobre essa data | Sim, pelo índice, em todas as competências desde a data-base. |
| (incorporado) | Formalizado antes do exercício sem retroativo no exercício | Não — presume-se no valor do cadastro. Serve de âncora. |
| **Projetado** | Aniversários futuros a partir da âncora (último reajuste registrado/formalizado, senão início), dentro da vigência efetiva, a partir de janeiro do exercício | Sim, pelo índice. |

- **Percentual de cada ciclo:** manual > índice oficial acumulado nos 12 meses anteriores à data-base > ausente.
- **Acréscimo por competência** separado em **formalizado** e **projetado** (composição na ordem dos ciclos).
- **Competências de anos anteriores** só aparecem quando um ciclo formalizado as alcança; ficam marcadas
  `exercicio_anterior` e somadas à parte.
- **Retroativo do gov** (apostilamentos retroativos assinados no exercício) aparece só como **referência**: é o valor
  do contrato inteiro, não a parcela da 20RK.
- **Projeções futuras não são afetadas:** Necessidade de Empenho e Projeção usam só o valor registrado; registrar o
  aditivo com valor transforma o ciclo em "registrado" e ele sai da estimativa (sem dupla contagem). A promoção a
  aditivo PREVISTO vale só para ciclos projetados.

## Dúvidas registradas

- Janela do índice de 12 meses anteriores à data-base (e não a da data da proposta).
- Tolerância de 45 dias para casar reajuste do gov com aditivo registrado; anualidade com folga (330 dias).
- Apostilamento não traz o tipo: um apostilamento de outra natureza (acréscimo, correção) longe de um termo de
  reajuste pode virar um ciclo "por apostila" — limitado a um por ano pela anualidade.
- Um retroativo que cubra um ciclo não formalizado em termo (ex.: 03/2023, retroativo 02/2025–02/2026) aparece só
  como referência; o ciclo de 2025 não é reconstruído.
- Retroativo do gov é do contrato inteiro: não é comparável à parcela da 20RK.
