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

   Para executar os testes, dê sempre preferência às ferramentas de
   `requirements-dev.txt` que agilizam a suíte, em vez de
   `python -m unittest`:
   - rodadas intermediárias: `python -m pytest tests --testmon -n auto`
     (só os testes afetados pelo código alterado, em paralelo);
   - suíte completa (ao concluir a tarefa, ou se mudou fixture, planilha ou
     base, que o testmon não acompanha): `python -m pytest tests -n auto`.
   Se essas ferramentas não estiverem instaladas, instale-as com
   `python -m pip install -r requirements-dev.txt` antes de recorrer ao
   `unittest`.
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

## Fixtures de teste vs. dados de trabalho (Contratos Contínuos, Bolsas, Contratos — Pagamentos)

`data/raw/SERVIÇOS CONTÍNUOS - 2026 - AGO A DEZ.xlsm`,
`data/raw/BOLSAS E AUXÍLIOS 2026 - AGO A DEZ.xlsx` e
`data/raw/CONTRATOS - CONTROLE 2020 - Pagamentos.xlsx` são planilhas de
trabalho mantidas manualmente (sem manifesto versionado como
Dotação/Execução Anual) — serão substituídas em atualizações futuras, sem
aviso prévio de layout.

Os testes de `src/contratos_continuos.py`, `src/bolsas_auxilios.py` e
`src/contratos_pagamentos.py` **não** leem de
`data/raw/`: leem de fixtures congeladas em `tests/fixtures/`
(`contratos_continuos_2026-08-13.xlsm`, `bolsas_auxilios_2026-08-13.xlsx`,
`contratos_pagamentos_2026-08-15.xlsx`),
desacopladas de propósito. A fixture de pagamentos é *reduzida* às 8 abas
mensais de 2026 realmente lidas (a planilha de origem tem ~90 abas e 7,8 MB —
a maioria fora de escopo; ver docstring de `src/contratos_pagamentos.py` e de
`tests/test_contratos_pagamentos.py`), não uma cópia integral como as demais.
Ao atualizar as planilhas de trabalho em `data/raw/`:

- **Não sobrescreva a fixture automaticamente.** Ela é a referência congelada
  contra a qual os valores esperados dos testes (`tests/test_contratos_continuos.py`,
  `tests/test_bolsas_auxilios.py`) foram calculados manualmente.
- Se decidir atualizar a fixture, faça isso deliberadamente: copie a nova
  planilha para `tests/fixtures/` com um nome novo incluindo a data de
  referência, recalcule à mão os valores esperados nos testes (contagens,
  saldos, divergências) contra a nova extração, e só então aponte
  `CAMINHO_BASE` para o arquivo novo.
- O mesmo raciocínio vale para `tests/fixtures/execucao_anual_manifesto_formato_antigo.json`,
  fixture equivalente para o formato antigo do manifesto de Execução Anual.
- `tests/fixtures/contratosgov_2026-10-08.json` é a fotografia congelada do
  Contratos.gov.br (UG 153165, 6 contratos), lida pelos testes de
  `src/contratos_cadastro.py` e `src/contratosgov_extracao.py` (e da página
  Contratos), no lugar de `data/raw/contratosgov/` (fotografias gravadas pela
  própria página, imutáveis e não versionadas). Os CPFs de pessoa física estão
  anonimizados. Mesma regra: não a sobrescreva automaticamente; para trocá-la,
  crie um arquivo novo com a data de referência e recalcule à mão os valores
  esperados.
