# Cadastro de Contratos — Contratos.gov.br

Contrato do módulo **Contratos** (`app_pages/contratos.py`): cadastro dos contratos da UG 153165
(UFRPE) montado a partir da API pública do Contratos.gov.br. Esta etapa entrega só o cadastro
(dados, atualização e consulta); ferramentas que o usem (vencimentos, execução por contrato,
necessidade de empenho) são etapas posteriores. O módulo é independente de Contratos Contínuos,
Necessidade de Empenho, Reforço e do antigo Contratos — Vigência: nenhum lê ou escreve nos outros.

Especificação aprovada: `docs/superpowers/specs/2026-10-08-contratosgov-cadastro-design.md`.

## 1. Fonte e recorte

API pública, somente leitura (GET, sem credencial), em `https://contratos.comprasnet.gov.br`.
Cliente em `src/contratosgov_api.py` (único módulo que acessa a rede; devolve JSON cru).

| Endpoint | Conteúdo |
|---|---|
| `/api/contrato/ug/153165` | Instrumentos da UG com situação "Ativo" |
| `/api/contrato/inativo/ug/153165` | Instrumentos inativos |
| `/api/contrato/{id}/historico` | Termos: contrato, aditivo, apostilamento |
| `/api/contrato/{id}/empenhos` | NEs vinculadas ao contrato |

Recorte: só instrumentos do tipo **"Contrato"**, todos os anos, ativos e inativos. Empenhos
substitutivos (tipo "Empenho") ficam de fora. Garantias, arquivos, cronograma, faturas e unidades
requisitantes não são lidos.

Resiliência: HTTP 5xx, timeout e falha de conexão são repetidos até 3 vezes, com pausa exponencial
(2 s, 4 s, 8 s); HTTP 429 respeita `Retry-After` numérico; os demais 4xx abortam sem repetir; JSON
inválido também aborta. Há uma pausa de cortesia de 0,2 s entre chamadas. Esgotadas as tentativas,
levanta `ErroApiContratosGov` com a URL e o status — nunca devolve dado parcial.

## 2. Fotografia

Cada atualização confirmada grava uma **fotografia** imutável em
`data/raw/contratosgov/contratosgov_<sha256[:12]>.json` (não versionada no Git, como o resto de
`data/raw/`) e um manifesto em `data/manifestos/` (base `contratosgov`, versionado). O manifesto
atual é o ponteiro: `carregar_atual` confere o hash do arquivo contra o manifesto e falha de forma
explícita se o arquivo sumiu ou foi alterado. Uma fotografia já gravada nunca é sobrescrita.

Formato (`versao_formato: 1`), com as respostas da API guardadas sem transformação:

```text
{"versao_formato": 1, "consultado_em", "ug",
 "lista_ativos": [...], "lista_inativos": [...],
 "detalhes": {"<id>": {"historico": [...], "empenhos": [...], "consultado_em", "origem"}}}
```

`origem` é `consulta` ou `reaproveitado:<sha12>` (hash da fotografia em que o detalhe foi realmente
consultado). O manifesto registra data/hora da consulta, valor global somado dos vigentes e as
contagens: contratos, vigentes, termos, NEs, reconsultados, reaproveitados e uma contagem por
categoria do delta.

## 3. Atualização incremental

Módulo `src/contratosgov_extracao.py`. A fotografia nova é sempre completa; muda só quais contratos
têm o detalhe reconsultado:

- reconsultados: vigentes e a iniciar (pela vigência calculada com as datas do item novo da lista),
  contratos novos, contratos cujo item da lista mudou (comparação sem a chave `links`), contratos
  que trocaram de lista (ativo ↔ inativo) e todos, se o usuário marcar "atualização completa";
- reaproveitados: encerrados e inativos sem mudança copiam o detalhe da fotografia anterior.

Qualquer falha de API aborta a atualização inteira; nada é gravado.

**Delta** (por contrato, fotografia anterior × nova): contratos novos e ausentes; termos novos e
removidos; vigência alterada (fim antes → depois); valor global alterado; situação alterada; NEs
novas e desvinculadas; NEs movimentadas (só contagem dos campos de valor). Termos e NEs são
comparados só entre contratos presentes nas duas fotografias.

**Confirmação reforçada:** qualquer remoção (contrato ausente, termo removido, NE desvinculada) exige
"Estou ciente da remoção" antes de gravar; sem isso `gravar` levanta `ConfirmacaoNecessaria` antes de
escrever qualquer arquivo. Itens removidos continuam nas fotografias anteriores. A gravação é tudo ou
nada: a fotografia é validada montando as tabelas derivadas antes de qualquer escrita, e nada é
escrito fora de `data/raw/contratosgov/` e `data/manifestos/`.

Primeira carga ≈ 2 + 2 × (nº de contratos) chamadas; as seguintes ≈ 2 + 2 × (vigentes + novos +
alterados). A página nunca consulta a rede ao ser aberta — só no botão "Consultar agora".

## 4. Tabelas derivadas e regras de conversão

`src/contratos_cadastro.py` (funções puras, em memória; a fotografia nunca é alterada) monta três
tabelas. A data de referência da vigência é parâmetro (padrão: hoje).

- **`contratos`** — uma linha por contrato: identificação (`contrato_id`, `numero`, `ano_contrato`),
  fornecedor (`fornecedor_tipo`, `fornecedor_documento` só dígitos, `fornecedor_nome`), `processo`,
  `objeto`, `categoria`, `modalidade`, datas, valores (`valor_inicial`, `valor_global`,
  `num_parcelas`, `valor_parcela`, `valor_acumulado`), `situacao_api`, `inativo_api`,
  `situacao_vigencia`, `dias_para_vencer`, `qtd_termos`, `qtd_empenhos`, `detalhe_consultado_em`,
  `detalhe_origem`.
- **`termos`** — uma linha por item de `/historico`, por `data_assinatura` e `termo_id`.
- **`empenhos`** — uma linha por item de `/empenhos`; `ne_ccor` = `unidade_gestora` + `gestao` +
  `numero` (ex. `153165152392026NE000522`), o mesmo formato da Execução Anual/Mensal.

Regras:

- `situacao` da API **não é confiável** (instrumentos "Ativo" com vigência vencida): é guardada como
  `situacao_api` e a situação real é calculada pelas datas — `vigente`, `a_iniciar`, `encerrado`,
  `inativo` (veio da lista de inativos) ou `sem_vigencia` (falta data).
- O valor mensal **não é derivado** do `valor_parcela` (36 dos 43 vigentes têm 1 parcela igual ao valor
  global): só existe como complemento manual.
- Códigos (id, número, UG, gestão, NE, fonte, natureza, CNPJ/CPF) são sempre texto, com zeros iniciais
  preservados. `ano_contrato` só sai de números no padrão `NNNNN/AAAA`; senão fica nulo.
- Valores: texto brasileiro (`"830.906,44"`) → `Decimal`. Vazio ou `null` → nulo; zero e negativo
  são preservados e distintos de nulo. Formato fora do padrão → `ErroDadoContratosGov` citando
  `contrato_id`, endpoint e campo. Datas `AAAA-MM-DD`.
- Campo obrigatório = chave presente (valor `null` é aceito e vira nulo): na lista `id, numero, tipo,
  fornecedor, vigencia_inicio, vigencia_fim, valor_global`; em `/empenhos` `numero, unidade_gestora,
  gestao`; em `/historico` `id, tipo, data_assinatura`. `id` repetido nas listas é erro.

Diferenças em relação à API real, achadas ao congelar a fixture de 08/10/2026:

- `qualificacao_termo` vem como **lista** de `{codigo, descricao}`; é guardado como texto
  `"descricao1; descricao2"`.
- `retroativo` vem como `"Sim"`/`"Não"` e é convertido em booleano; outro texto é erro.
- `retroativo_periodo` (`MM/AAAA–MM/AAAA`) só existe quando os quatro campos de referência estão
  presentes; período parcial fica **nulo** (o dado bruto permanece na fotografia).

## 5. Complementos manuais

`src/contratos_complementos.py`, em `data/contratos/complementos.json` (não versionado). Um registro
por `contrato_id`: `valor_mensal`, `observacoes` e `alterado_em`. Ficam separados dos dados da API:
uma atualização nunca os toca, e o complemento de um contrato que sumiu da API é preservado e exibido
como ausente na última consulta.

- Valor mensal em texto BR (`862.858,76` ou `862858,76`), no máximo 2 casas, nunca negativo. Vazio é
  nulo (não informado); `0,00` é zero. Gravado como texto decimal e lido como `Decimal`.
- Gravação atômica (temporário + `replace`). Arquivo ilegível levanta `ValueError` — nunca vira
  "nenhum complemento", para não sobrescrever dado digitado na gravação seguinte.

## 6. Página Contratos

Registrada em `app.py` no grupo "Contratos", antes de Contratos Contínuos. Três abas:

- **Cadastro** — resumo (contratos, vigentes, vencem em 90 dias, valor global dos vigentes), abas por
  situação, busca livre, filtro de categoria, ordenação e a lista; o botão da linha abre o detalhe
  (`st.dialog`) com dados do contrato, complemento editável, linha do tempo dos termos e NEs com
  total. Nulo aparece "—" e zero "R$ 0,00"; o valor mensal vem só do complemento, marcado "MANUAL".
  A grade de edição usa widgets comuns — nunca `st.data_editor` dentro de `st.dialog`.
- **Atualizar** — "Consultar agora" (ou "Fazer primeira carga"), opção de atualização completa,
  progresso, prévia do delta e "Gravar fotografia"; falha da API mostra a URL e mantém a fotografia
  anterior.
- **Histórico de atualizações** — um manifesto por linha, a atual marcada.

## 7. Testes e fixture

Nenhum teste acessa a rede (cliente HTTP falso montado a partir da fixture; `unittest.mock` sobre
`requests`). A fixture `tests/fixtures/contratosgov_2026-10-08.json` é uma fotografia real reduzida
de 08/10/2026 (vigente, encerrado, inativo, aditivos, apostilamento com novo valor, várias NEs, sem
NE), com os CPFs de pessoa física trocados por `000.000.001-91`. Os valores esperados dos testes
(`tests/test_contratos_cadastro.py`, `test_contratosgov_extracao.py`, `test_contratos_page.py`) foram
calculados à mão contra ela.

**A fixture é uma referência congelada — não a sobrescreva automaticamente.** Para atualizá-la, de
propósito:

1. Gere uma fotografia nova (ou copie uma de `data/raw/contratosgov/`) e salve em `tests/fixtures/` com
   um **nome novo**, incluindo a data de referência (ex. `contratosgov_2026-12-01.json`).
2. Antes de versionar, reanonimize os CPFs de fornecedor pessoa física para `000.000.001-91` (e o nome
   para `PESSOA FÍSICA FICTÍCIA`), na lista e nos históricos; confira que nenhum CPF real ficou.
3. Recalcule à mão os valores esperados dos testes (contagens, situações, totais, delta) contra a nova
   fotografia e só então aponte o caminho da fixture nos testes para o arquivo novo.
4. Se a API mudar de formato, registre a diferença na docstring de `src/contratos_cadastro.py` — o
   desvio é sinalizado, não adivinhado.

Mesma regra do `AGENTS.md` para as demais fixtures de trabalho.
