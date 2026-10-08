# Resultado Orçamentário — especificação

Data: 08/10/2026 · Escopo aprovado em conversa, parte a parte (fontes, confronto, fórmula, necessidade,
persistência, despesas manuais, evidenciação do empenhado).
Bases: Dotação Anual, Execução Mensal, Contratos Contínuos, Bolsas e Auxílios. Despesas de Pessoal fica fora.

## 1. Problema e objetivo

Hoje cada módulo calcula a própria necessidade de empenho, e o Limite de Empenho confronta Dotação ×
Empenhado. Nenhuma tela responde se a dotação ainda disponível **cobre** o que falta empenhar no exercício.

Objetivo: uma página que confronta a dotação das **células orçamentárias escolhidas pelo usuário** com o
empenhado nessas células e com a **necessidade de empenho** até dezembro (Contratos Contínuos, Bolsas e
Auxílios e despesas previstas cadastradas à mão). O resultado é **superávit ou déficit**.

Critérios de sucesso:

- com as células marcadas, o resultado é igual a
  `Dotação Atualizada − Empenhado − Necessidade`, e cada parcela pode ser conferida até a NE, o contrato ou
  a bolsa, ou a despesa manual que a originou;
- o empenhado das células aparece em **três linhas** (Contratos Contínuos, Bolsas e Auxílios, Outros
  empenhos) cuja soma fecha com o empenhado total das células. Se não fechar, a página mostra a diferença;
- a seleção de células e as despesas manuais continuam lá depois de atualizar a página e de reiniciar o app;
- nenhuma conta existente é alterada: Necessidade, Projeção pela Execução e Limite de Empenho são só **lidos**.

## 2. Decisões tomadas com o usuário

| Tema | Decisão |
|---|---|
| Despesas consideradas | Contratos Contínuos + Bolsas e Auxílios + despesas manuais. **Sem Despesas de Pessoal**, por enquanto. |
| Recursos | Células da Dotação Anual escolhidas pelo usuário (caixa de marcar). |
| Confronto | **Bolsão**: a soma das células marcadas é comparada com a soma das despesas. Não há confronto célula a célula. |
| Fórmula | `Resultado = Dotação Atualizada (células) − Empenhado nas células (Execução Mensal) − Necessidade de empenho`. |
| Necessidade de Contratos e Bolsas | **Projeção pela execução** (`necessidade_execucao` de `src/relatorio_projecao_execucao.py`). Sem seletor. |
| Contrato ou bolsa sem NE | **Fica fora** da conta. Aparece só nos avisos (quantidade e valor contratual, como informação). Entra sozinho quando a NE for incluída no cadastro ou o status do contrato mudar. |
| Outros empenhos já executados | Já são abatidos, porque o Empenhado vem da Execução Mensal **por célula**, e não dos cadastros. |
| Evidenciação do empenhado | Três linhas: Contratos Contínuos, Bolsas e Auxílios e Outros empenhos, cada uma expansível por NE. |
| Despesas fora de Contratos e Bolsas | Cadastro manual de "Outras despesas previstas", com **um valor a empenhar por despesa** (sem distribuição mensal). |
| Persistência | **Aprovada** (exigência do AGENTS.md): arquivos JSON por exercício em `data/resultado_orcamentario/`, fora do git. |

## 3. Definições

**Célula orçamentária**: uma linha da Dotação Anual na mesma granularidade do Limite de Empenho, ou seja,
(Iduso, Resultado Primário, Ação de Governo, PTRES, Plano Orçamentário, Grupo de Despesa) mais a
**Fonte de Recursos Detalhada**. Os códigos são texto, com zeros à esquerda preservados. A chave da célula é a
tupla desses códigos, e é ela que vai para o arquivo de seleção.

**Empenhado da célula**: soma de `valor_empenhado_por_bloco` (`src/tesouro_execucao_mensal.py`, já
deduplicado) das linhas da Execução Mensal do exercício cuja célula coincide com uma célula marcada. Na
Execução Mensal, a fonte detalhada é a coluna `fonte_recursos_detalhada_cod`, e na Dotação Anual é
`fonte_recursos_detalhada_codigo`. As duas têm o mesmo formato de 10 dígitos.

**Necessidade de empenho**:
- Contratos Contínuos e Bolsas e Auxílios: soma de `necessidade_execucao` das linhas do
  `RelatorioProjecaoExecucao` de cada base. Valem **todas** as NEs do relatório, mesmo as que estão em células
  não marcadas, porque no bolsão a necessidade precisa ser coberta pelos recursos escolhidos.
- Despesas manuais: soma do `valor` das despesas cadastradas no exercício.

## 4. Regra de evidenciação do empenhado

Para cada NE com empenho nas células marcadas:

1. Se a NE está no cadastro de Contratos Contínuos → **Contratos Contínuos**.
2. Senão, se a NE está no cadastro de Bolsas e Auxílios → **Bolsas e Auxílios**.
3. Senão → **Outros empenhos**.

- Cada NE é contada **uma única vez**, pelo valor da Execução Mensal. Se a mesma NE estiver ligada a mais de
  um contrato, gera o aviso de NE compartilhada que já existe.
- Se a NE aparecer nos dois cadastros, fica em Contratos e gera o aviso "NE em Contratos e em Bolsas —
  conferir".
- Uma NE de contrato ou bolsa em célula **não marcada** não entra no empenhado. A necessidade dela continua
  entrando (ver §3).
- A conferência `Contratos + Bolsas + Outros = Empenhado total das células` é mostrada sempre, e a
  diferença é exibida quando não for zero (tolerância de R$ 0,01).

## 5. Valores nulos, zero e negativos

- Célula marcada sem Dotação Atualizada (nulo) → aviso e "—" na tabela. Ela não vira zero na soma, e o
  resultado é marcado como **incompleto**.
- Dotação zero ou negativa entra como está.
- Empenhado negativo (estorno líquido) entra como está.
- `necessidade_execucao` já é `max(0, …)` na origem e não é tratada de novo aqui.
- Despesa manual: o valor é obrigatório, não aceita nulo e precisa ser maior que zero. O cadastro recusa
  valores inválidos com uma mensagem.

## 6. Persistência

Diretório `data/resultado_orcamentario/<exercício>/`, git-ignorado, com `.gitkeep`. A gravação é atômica
(arquivo temporário + `Path.replace`), no mesmo padrão de `src/limite_empenho_preferencias.py`.

- `celulas.json`: `{"celulas": [{chave da célula}, …], "atualizado_em": ISO-8601}`.
  Se uma célula gravada não existir mais na Dotação atual (por exemplo, depois de uma reimportação), ela é
  mantida no arquivo e aparece em aviso como "célula selecionada ausente da base". Não é removida
  silenciosamente.
- `despesas_manuais.json`: `{"despesas": [{"id": uuid, "descricao", "valor", "observacao", "celula": chave ou
  null, "criado_em", "atualizado_em"}]}`. A célula da despesa manual é **apenas informativa** e não muda o
  cálculo.
- Arquivo ausente equivale a nenhuma célula marcada ou nenhuma despesa. Um arquivo corrompido gera erro visível,
  e a página não grava por cima.

## 7. Componentes

| Arquivo | Papel | Dependências |
|---|---|---|
| `src/resultado_orcamentario.py` | Regra pura: recebe DataFrames (Dotação, Execução Mensal, relatórios de projeção, cadastros, despesas manuais, seleção) e devolve `ResultadoOrcamentario` (parcelas, quebra por origem, tabelas por NE, avisos, flag de incompleto). | pandas |
| `src/resultado_orcamentario_cadastro.py` | Ler e gravar `celulas.json` e `despesas_manuais.json`, e validar despesa manual. | stdlib |
| `app_pages/resultado_orcamentario.py` | Interface: exercício, tabela de células com caixa de marcar, cartões, tabelas expansíveis, cadastro de despesas manuais, avisos e datas das extrações. | Streamlit + os dois acima |
| `app.py` | Nova entrada no menu, perto de "Limite de Empenho". | — |

**Montagem dos relatórios de projeção**: hoje as páginas de Contratos e de Bolsas montam a entrada de
`relatorio_projecao_execucao.montar_relatorio`. Se essa montagem estiver dentro de `app_pages/`, ela será
extraída para uma função reutilizável em `src/` **sem mudar o resultado**. Os testes atuais das duas páginas
precisam continuar passando sem alteração.

## 8. Tela

1. Seletor de exercício, com o padrão sendo o exercício em andamento da Dotação.
2. **Cartões:** Dotação Atualizada das células · (−) Empenhado · (−) Necessidade · **Resultado**, este com
   sinal e rótulo "Superávit" ou "Déficit".
3. **Composição:**
   - Empenhado: Contratos Contínuos | Bolsas e Auxílios | Outros empenhos, mais a linha de conferência.
   - Necessidade: Contratos Contínuos | Bolsas e Auxílios | Outras despesas previstas.
   - Cada linha pode ser expandida em uma tabela por NE (Contratos: contrato e fornecedor; Bolsas: programa) ou
     por despesa manual.
4. **Células:** tabela da Dotação do exercício com caixa de marcar, Dotação Atualizada e Empenhado de cada
   célula, e o botão "Salvar seleção".
5. **Outras despesas previstas:** lista com incluir, editar e excluir.
6. **Avisos:** contratos e bolsas sem NE (fora da conta), NE compartilhada, NE nos dois cadastros, célula
   selecionada ausente, célula sem dotação, diferença na conferência, e as datas de extração de Dotação e
   Execução Mensal, que são independentes.

## 9. Testes

- `tests/test_resultado_orcamentario.py`, regra pura com DataFrames pequenos montados no teste:
  - resultado = dotação − empenhado − necessidade, calculado à mão;
  - quebra do empenhado em três linhas, com soma que fecha;
  - NE nos dois cadastros vai para Contratos, com aviso;
  - NE de contrato em célula não marcada: empenhado fora, necessidade dentro;
  - contrato ou bolsa sem NE fora da conta, com aviso;
  - célula com dotação nula deixa o resultado incompleto (nulo ≠ zero);
  - célula selecionada ausente da base gera aviso e continua no arquivo;
  - códigos com zero à esquerda preservados no casamento Dotação × Execução.
- `tests/test_resultado_orcamentario_cadastro.py`: ida e volta dos JSON, gravação atômica, arquivo ausente e
  arquivo corrompido, e validação da despesa manual.
- Teste de página (padrão `tests/_apptest.py`): a página abre com bases de fixture, e marcar uma célula e
  salvar grava o arquivo.
- Se a montagem dos relatórios for extraída (§7), os testes atuais de Contratos e Bolsas precisam passar
  sem mudança.

## 10. Pré-requisito

A projeção de Bolsas foi commitada em `ab481a5` (pré-requisito cumprido).

## 10a. Detalhes levantados no código (08/10/2026)

- `valor_empenhado_por_bloco` não leva a **Fonte de Recursos Detalhada** entre as dimensões do bloco. Ela
  precisa ser acrescentada (`fonte_recursos_detalhada_cod`/`_desc`), o que é aditivo e não muda nenhum valor.
  Sem isso, o empenhado não casa com a célula.
- **Contrato antecessor:** na página de Contratos, quem emite o relatório de projeção pode escolher a cada
  vez um contrato antecessor para herdar o fator, e essa escolha não é gravada. O Resultado Orçamentário usa
  a projeção **sem antecessor** (NE sem histórico = fator 1, valor mensal cheio). A diferença aparece em uma
  nota na página.
- **Liquidação por Competência ausente** (`data/raw/Liquidação por Competência.xlsx`): a projeção não pode ser
  calculada. Nesse caso, a necessidade de Contratos e Bolsas fica **indisponível**, e não zero, e o resultado
  é marcado como incompleto.

## 11. Fora do escopo

- Despesas de Pessoal.
- Confronto célula a célula.
- Distribuição mensal das despesas manuais.
- Limite de empenho liberado (fração da PROPLAD) no lugar da Dotação Atualizada.
- Exportação em PDF ou Excel (pode ser um próximo passo).
