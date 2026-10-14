# Projeção pela execução editável (Contratos Contínuos) — desenho

Data: 14/10/2026. Estado: **aguardando revisão do usuário** (nenhuma linha de código escrita).

## Objetivo

Permitir ajustar à mão o valor **esperado de um mês** de uma NE na "Projeção pela execução", gravar o ajuste e fazer
todo o sistema que usa a projeção passar a valer por ele. Um botão devolve a NE (ou o exercício inteiro) à estimativa
da metodologia, sem apagar histórico.

Pedido do usuário (14/10/2026), com o layout da "Conciliação por competência — todos os contratos" como modelo.

## Decisões já tomadas pelo usuário

| Tema | Decisão |
|---|---|
| Significado do número digitado | **Esperado total do mês.** O sistema continua descontando o liquidado do mês: projetado = esperado − liquidado (nunca negativo). |
| Onde vale | Em tudo que usa a projeção: relatório (tela, PDF, Excel), Necessidade de Empenho no modo "Projeção pela execução" e Resultado Orçamentário. |
| Base | **Só Contratos Contínuos.** Bolsas e Auxílios não muda. |
| Refazer pela metodologia | Por NE **e** geral (exercício inteiro), ambos com confirmação. |
| Mês que vira realizado | O valor executado substitui o valor gravado como projeção (o realizado manda). |
| Edição | Por NE (um campo por mês), e não grade tipo planilha. |
| Título do contrato | Toda linha, seletor e aviso traz o número do contrato e o fornecedor (como na conciliação). |

Hipótese minha, assumida por falta de objeção: a branch parte da `master` (sem o WIP de Bolsas inteiras).

## Fora de escopo

Bolsas e Auxílios; edição do fator, do teto ou do custo; edição de meses já realizados; qualquer alteração da
Necessidade de Empenho pelo valor contratual; alerta em Alertas Gerenciais.

## 1. Dados e persistência (**persistência nova — aprovação explícita do usuário, 14/10/2026**)

- Pasta `data/projecao_execucao/<exercício>/`, **um arquivo JSON por evento**, fora do git, gravação atômica (tmp +
  replace), exatamente o padrão de `src/decisoes_conciliacao.py`. Arquivo ilegível: erro visível e nunca sobrescrito.
  (Revisão de 14/10/2026: a primeira versão deste desenho previa um arquivo único por exercício; o padrão do projeto é um
  arquivo por evento e foi mantido.)
- **Log de eventos que só acrescenta.** Evento:
  `{versao_schema, id, tipo: "ajustar" | "refazer_ne" | "refazer_tudo", ne_curta, valores, registrado_em, extracao}` —
  `valores` é `{mês (1-12): esperado | null}` (só em "ajustar"; `null` = voltar este mês à metodologia) e `extracao` é o
  hash curto da Execução Mensal vigente quando o ajuste foi feito.
- O estado atual é **reconstruído** do log, em ordem: "ajustar" define os meses informados (o último vence; `null`
  remove), "refazer_ne" limpa a NE, "refazer_tudo" limpa o exercício.
- Valor: zero é válido (esperado 0,00); campo vazio na tela = sem ajuste, nunca zero. Valor negativo é recusado.
- Códigos como identificador: `ne_curta` é texto (ex.: `2026NE000551`), nunca número.

## 2. Regra de cálculo

Em `src/relatorio_projecao_execucao.py`:

- `projetar_meses(..., ajustes: dict[int, float] | None = None)`: para o mês `m` com ajuste e que seja projetável
  (ver abaixo), `esperado[m] = ajuste` — **substitui** custo × fator e também o teto. Em seguida vale a conta de sempre:
  `projetado = max(0, esperado − liquidado)`; o asterisco de "liquidado abatido" e o Realizado de mês já liquidado por
  inteiro seguem iguais.
- **Meses editáveis:** do primeiro mês em aberto até dezembro, **inclusive os que a metodologia deixa vazios** (custo nulo
  ou zero, vigência encerrada). Mês realizado (até o último fechado) não edita.
- **Ajuste superado:** se o mês do ajuste já é fechado na extração atual, o ajuste é ignorado na conta (o liquidado manda),
  permanece no arquivo e a tela avisa "ajuste superado: <NE> <mês>". Nada é apagado.
- O mesmo vale para o mês da extração e os abertos: ajuste num mês aberto vale enquanto ele não fechar.
- `montar_relatorio(..., ajustes: dict[str, dict[int, float]] | None = None)`: NE → mês → esperado. Nova coluna em
  `linhas`: `ajustada_manualmente` (bool). A coluna de comparação "valor cheio" **não leva** ajuste. `necessidade_execucao`
  segue `max(0, total projetado − saldo)`.
- `src/resultado_orcamentario_fontes.py::projecao_contratos` carrega os ajustes do exercício e os repassa; assim relatório,
  Necessidade e Resultado Orçamentário leem a mesma fonte.
- Sinalização: marca ✎ na célula ajustada (tela, Excel por formato, PDF), coluna "Ajustado manualmente" no Excel, linha de
  aviso com as NEs ajustadas (com título do contrato) e legenda.

## 3. Interface (Contratos Contínuos)

- Novo bloco "Editar a projeção pela execução", abaixo do relatório de projeção, só no modo de base "Projeção pela execução".
- **Matriz de leitura** NE × 12 meses no estilo `html_consolidada` (HTML próprio, funções `html_*` puras, sem
  `st.dataframe`): coluna do contrato mostra **número em negrito, fornecedor abaixo**, NE ao lado; células com as cores de
  realizado, azul (projetado), laranja (restante em aberto) e ✎ (ajustado); `title` com esperado, liquidado e projetado.
- **Edição por NE:** seletor de NE com o rótulo `<NE> — <fornecedor> — Contrato <nº>`; abaixo, uma linha com um campo
  numérico por mês editável (preenchido com o esperado vigente: ajuste ou metodologia) e o botão **Gravar**. Só grava o que
  mudou; campo igual à metodologia não gera ajuste.
- **Refazer:** "Refazer esta NE" e "Refazer todas do exercício", cada um com confirmação (checkbox + botão). Gravam
  evento, não apagam o log.
- Sem `st.data_editor` (quebra dentro de `st.dialog`, ver memória do projeto) e sem diálogo para a grade.
- Importante: a página só enxerga código novo após reiniciar o Streamlit (`fileWatcherType = "none"`).

## 4. Testes

- Regra: ajuste substitui esperado e teto; mês com liquidado parcial abate; ajuste 0,00; mês vazio da metodologia editável;
  mês fechado superado e ignorado; ajuste em NE inexistente ignorado e avisado; `cheio` não muda.
- Persistência: gravar, reconstruir, refazer NE, refazer tudo, arquivo corrompido não é sobrescrito, valor negativo
  recusado, código com zeros à esquerda preservado.
- Integração: `projecao_contratos` com e sem ajustes (Necessidade e Resultado Orçamentário refletem); Excel com a coluna e
  o formato ✎; PDF gera.
- Página: editar, gravar, refazer NE, refazer tudo (AppTest), e o título do contrato presente.

## 5. Arquivos

Novos: `src/projecao_ajustes.py` (persistência + reconstrução), `src/ui_projecao_execucao.py` (HTML puro + render),
`tests/test_projecao_ajustes.py`, `tests/test_ui_projecao_execucao.py`.
Alterados: `src/relatorio_projecao_execucao.py`, `src/resultado_orcamentario_fontes.py`, `app_pages/contratos_continuos.py`,
`README.md`, testes correspondentes.

## 6. Riscos

- A frente de Bolsas inteiras (WIP, commits `187b171` e `4cccc9a` na branch `chore/pendencias-em-andamento`) altera o mesmo
  `src/relatorio_projecao_execucao.py`: conflito previsível na junção; esta branch parte da `master` e será rebaseada.
- Ajuste de um mês antes do primeiro em aberto é impossível por regra; o valor digitado não pode reescrever realizado.
- Vários usuários/abas gravando o mesmo arquivo: o log só acrescenta e é regravado de forma atômica; última gravação vale.
- Resultado Orçamentário passa a depender de arquivo local de ajustes: arquivo ilegível exibe aviso e usa a metodologia.

## 7. Critérios de aceitação

1. Editar o esperado de um mês projetado de uma NE, gravar e ver, no relatório, na Necessidade e no Resultado Orçamentário,
   o novo projetado (esperado − liquidado) e a necessidade recalculada.
2. A célula ajustada é marcada, e a NE aparece no aviso e na coluna do Excel, sempre com número do contrato e fornecedor.
3. "Refazer esta NE" e "Refazer todas" devolvem a metodologia e continuam no log.
4. Mês que fecha numa nova extração: o realizado aparece, o ajuste fica "superado" e avisado.
5. Bolsas e Auxílios e a Necessidade pelo valor contratual não mudam; suíte completa verde.
