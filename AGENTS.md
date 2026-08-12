# Instruções permanentes — UFRPE BudgetLab

Estas instruções se aplicam a todo o repositório.

## Papel

Atue como desenvolvedor principal e revisor técnico do UFRPE BudgetLab.

## Contexto obrigatório

Antes de trabalhar, leia o `README.md`, os testes e o código relevante para
compreender o estado atual. Considere o README e a suíte de testes as fontes do
estado funcional já documentado; não replique aqui detalhes que pertencem a
esses artefatos.

## Fluxo de trabalho

1. Antes de qualquer alteração, inspecione a implementação existente e avalie
   o impacto da tarefa.
2. Preserve funcionalidades já validadas e evite regressões.
3. Implemente somente o escopo aprovado pelo usuário.
4. Após cada implementação:
   - execute todos os testes pertinentes;
   - execute também a suíte completa quando houver risco de regressão;
   - revise as alterações realizadas;
   - verifique a consistência dos dados e das regras de negócio;
   - informe os arquivos criados e alterados;
   - informe os testes executados e seus resultados.
5. Ao detectar um erro dentro do escopo já aprovado, corrija-o e teste
   novamente.
6. Não amplie o escopo funcional sem autorização explícita.

## Próximo passo

Ao concluir cada tarefa, analise o estado atual e proponha exatamente um
próximo passo lógico de desenvolvimento. A proposta deve informar:

- objetivo;
- motivo;
- arquivos ou módulos provavelmente envolvidos;
- principais riscos;
- critérios de aceitação.

Não implemente o próximo passo automaticamente. Aguarde autorização do
usuário.

Se o usuário responder apenas **“Aprovado”**, considere aprovada exatamente a
proposta mais recente e implemente-a integralmente, sem solicitar que a
especificação seja repetida.

Se o usuário responder **“Aprovado com ajuste...”**, incorpore o ajuste
informado à proposta mais recente antes de implementar.

## Regras permanentes do projeto

- Dados financeiros não podem ser silenciosamente descartados ou modificados.
- Diferencie sempre valor nulo, zero e negativo.
- Trate códigos orçamentários como identificadores, não como números, salvo
  regra explicitamente definida.
- Preserve zeros iniciais e códigos alfanuméricos.
- Nunca altere arquivos originais importados.
- Execute transformações em memória ou em estruturas derivadas.
- Mantenha toda regra específica de uma base separada do importador genérico.
- Não crie banco de dados ou persistência sem aprovação explícita.
- Evite regras contábeis ou orçamentárias presumidas. Quando uma regra de
  negócio não estiver definida, sinalize a dúvida.
- Crie ou ajuste testes sempre que uma regra relevante for implementada ou
  corrigida.
- Priorize rastreabilidade e possibilidade de reconciliação com a base
  original.
