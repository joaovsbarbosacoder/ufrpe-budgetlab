# Cadastro de Contratos a partir do Contratos.gov.br — especificação

Data: 08/10/2026 · Base: conversa com o usuário e consulta real (somente leitura) à API pública do
Contratos.gov.br (`https://contratos.comprasnet.gov.br/docs/api-docs.json`) para a UG 153165 em 08/10/2026.

## 1. Problema e objetivo

O módulo atual de Vigência de Contratos (`src/contratos_vigencia.py`, planilha manual BASE_CONTRATOS) não
atende ao usuário ("hoje pra mim é inútil"). O objetivo é criar, **do zero**, um **cadastro robusto de
contratos** com o Contratos.gov.br como fonte, que sirva de base para ferramentas futuras (vencimentos e
prorrogações, execução financeira por contrato, necessidade de empenho). Fiscalização e qualidade de cadastro
estão fora do escopo.

Esta etapa entrega **somente o cadastro** (dados, atualização e consulta). As ferramentas que o usarão são
etapas posteriores, cada uma com sua proposta.

**Critérios de sucesso:**

- Uma atualização a partir da API grava uma fotografia completa e rastreável dos contratos da UG 153165
  (tipo "Contrato", todos os anos, ativos e inativos), com termos e NEs de cada contrato.
- A página mostra a lista e o detalhe de cada contrato a partir da fotografia mais recente.
- Toda atualização exibe prévia do que mudou e só grava após confirmação.
- Complementos manuais (valor mensal, observações) são editáveis e nunca alterados pela atualização.
- Nenhuma alteração em Contratos Contínuos, Necessidade de Empenho, Reforço, Vigência antiga, Alertas,
  Prazos e Execução Retardada; suíte completa passando.

## 2. Decisões do usuário (08/10/2026)

| Decisão | Escolha |
|---|---|
| Fonte | Contratos.gov.br (API pública, sem credencial). Portal da Transparência e SIOP ficam fora. |
| Módulo antigo de Vigência | Começar do zero; o antigo fica intocado nesta etapa (remoção é decisão futura). |
| Relação com Contratos Contínuos | **Independentes por ora.** Nenhum dos dois lê ou escreve no outro. |
| Recorte | Todos os instrumentos do tipo **"Contrato"**, todos os anos (ativos + inativos). Empenhos substitutivos (tipo "Empenho") ficam fora. |
| Campos não confiáveis na API | **Complemento manual**, gravado separado dos dados da API (persistência aprovada). |
| Armazenamento dos dados da API | Abordagem A: fotografia JSON imutável + manifesto (padrão das demais bases). |
| Atualização | Manual (botão), incremental, com prévia e confirmação. |

## 3. Fatos da fonte (verificados em 08/10/2026)

Endpoints públicos usados (GET, sem autenticação):

| Endpoint | Conteúdo |
|---|---|
| `/api/contrato/ug/153165` | 1.787 instrumentos (210 "Contrato", 1.577 "Empenho"); todos com `situacao = "Ativo"` |
| `/api/contrato/inativo/ug/153165` | 10 instrumentos, todos "Contrato", `situacao = "Inativo"` |
| `/api/contrato/{id}/historico` | Termos: contrato, termo aditivo, termo de apostilamento — com `vigencia_fim`, `valor_global`, `novo_valor_global`, `novo_valor_parcela`, `data_inicio_novo_valor`, `retroativo_*` |
| `/api/contrato/{id}/empenhos` | NEs vinculadas: `unidade_gestora`, `gestao`, `numero` (`2026NE000522`), PI, natureza, fonte, `empenhado`, `aliquidar`, `liquidado`, `pago`, `rp*` |

Observações que orientam o desenho:

- **`situacao` não é confiável:** 1.478 instrumentos "Ativo" têm `vigencia_fim` anterior a 08/10/2026. A
  situação de vigência é **calculada pelas datas**; `situacao` da API é guardada como veio, só para
  rastreabilidade.
- **Valor da parcela não é confiável:** 36 dos 43 contratos vigentes têm `num_parcelas = 1` e
  `valor_parcela = valor_global`. Por isso o valor mensal é complemento manual — **nenhuma regra de derivação
  é presumida**.
- Valores monetários vêm como texto no formato brasileiro (`"830.906,44"`); datas como `AAAA-MM-DD`.
- `garantias`, `arquivos`, `cronograma`, `faturas` e `unidades_requisitantes` vieram vazios nas amostras —
  fora do escopo.
- O CPF de fornecedor pessoa física vem completo (`"183.847.064-68"`).
- NE completa = `unidade_gestora` + `gestao` + `numero` → `153165` + `15239` + `2026NE000522` =
  `153165152392026NE000522`, mesmo formato usado pela Execução Anual/Mensal.

## 4. Componentes

| Unidade | Responsabilidade | Depende de |
|---|---|---|
| `src/contratosgov_api.py` | Cliente HTTP só leitura: `listar_contratos_ug(ug)`, `listar_contratos_inativos_ug(ug)`, `historico(id)`, `empenhos(id)`. Timeout, novas tentativas, pausa entre chamadas. Devolve JSON cru; nenhuma regra de negócio. | `requests` |
| `src/contratosgov_extracao.py` | Monta a fotografia (lista + detalhes com política incremental), calcula o delta contra a fotografia anterior, decide se exige confirmação reforçada e grava (JSON bruto + manifesto). Tudo ou nada. | `contratosgov_api`, `importacao_versionada` (`Manifesto`, `destino_sem_sobrescrever`) |
| `src/contratos_cadastro.py` | Funções puras: fotografia → tabelas `contratos`, `termos`, `empenhos`; conversão de valores e datas; vigência calculada. | `pandas`, `decimal` |
| `src/contratos_complementos.py` | Leitura e gravação atômica dos complementos manuais por `contrato_id`. | `json` |
| `app_pages/contratos.py` | Página: Atualizar (prévia + confirmação), Lista (filtros), Detalhe (dados, termos, NEs, complemento editável). | módulos acima |

Registro da página em `app.py` como página nova; nenhuma página existente é alterada.

### 4.1 Tabelas derivadas (`contratos_cadastro`)

**`contratos`** — uma linha por contrato:
`contrato_id` (texto), `numero` (texto, ex. `00013/2026`), `ano_contrato` (inteiro tirado de `numero`, só
quando o padrão `NNNNN/AAAA` for reconhecido; senão nulo), `fornecedor_tipo`, `fornecedor_documento` (só
dígitos, texto, zeros preservados), `fornecedor_nome`, `processo`, `objeto`, `categoria`, `modalidade`,
`data_assinatura`, `vigencia_inicio`, `vigencia_fim`, `valor_inicial`, `valor_global`, `num_parcelas`,
`valor_parcela`, `valor_acumulado` (`Decimal` ou nulo), `situacao_api` (como veio), `inativo_api`
(veio do endpoint de inativos), `situacao_vigencia` (calculada: `vigente` se
`vigencia_inicio ≤ referência ≤ vigencia_fim`; `a_iniciar` se `referência < vigencia_inicio`; `encerrado` se
`vigencia_fim < referência`; `inativo` se `inativo_api`; `sem_vigencia` se faltar data), `dias_para_vencer`,
`qtd_termos`, `qtd_empenhos`, `detalhe_consultado_em`, `detalhe_origem` (`consulta` ou `reaproveitado:<sha>`).

**`termos`** — uma linha por item de `/historico`: `contrato_id`, `termo_id`, `tipo`, `numero`,
`qualificacao_termo`, `data_assinatura`, `vigencia_inicio`, `vigencia_fim`, `valor_global`,
`novo_valor_global`, `novo_num_parcelas`, `novo_valor_parcela`, `data_inicio_novo_valor`, `retroativo`,
`retroativo_valor`, `retroativo_periodo` (texto `MM/AAAA–MM/AAAA` quando houver), `observacao`.
Ordenação: `data_assinatura`, depois `termo_id`.

**`empenhos`** — uma linha por item de `/empenhos`: `contrato_id`, `empenho_id`, `ne_ccor` (NE completa),
`ne` (`2026NE000522`), `ug`, `gestao`, `data_emissao`, `fonte_recurso`, `plano_interno`,
`natureza_despesa`, `empenhado`, `a_liquidar`, `liquidado`, `pago`, `rp_inscrito`, `rp_a_liquidar`,
`rp_liquidado`, `rp_pago`.

Regras comuns: códigos (UG, gestão, NE, número, CNPJ/CPF, fonte, natureza) sempre texto; valor vazio ou
`null` → nulo; valor não conversível → `ErroDadoContratosGov` com `contrato_id`, endpoint e campo; nulo,
zero e negativo preservados. A data de referência da vigência é parâmetro (padrão: hoje) para testes
determinísticos.

### 4.2 Complementos manuais

Arquivo `data/contratos/complementos.json` (diretório novo; hoje **não** coberto pelo `.gitignore` —
acrescentar `data/contratos/*` + `!data/contratos/.gitkeep`, no padrão de `data/contratos_continuos/`). O
manifesto em `data/manifestos/` é versionado, como nas demais bases; a fotografia em `data/raw/` não. Um registro por `contrato_id`:
`valor_mensal` (texto decimal com até 2 casas, lido como `Decimal`; vazio = nulo), `observacoes` (texto),
`alterado_em` (ISO 8601). Gravação atômica (arquivo temporário + rename), como em
`src/limite_empenho_remanejamentos.py`. Arquivo ilegível → erro explícito, nunca "sem complementos".
Complemento de contrato que não está na fotografia atual é mantido e exibido como "contrato ausente na
última consulta".

## 5. Atualização e delta

1. Buscar lista ativa e inativa; filtrar `tipo == "Contrato"`.
2. Escolher quem reconsultar no detalhe (`/historico`, `/empenhos`):
   - vigentes e a iniciar (pela vigência calculada): sempre;
   - novos (ausentes da fotografia anterior): sempre;
   - encerrados/inativos: só se algum campo da lista mudou em relação à fotografia anterior;
   - opção "atualização completa": todos.
3. Contratos não reconsultados copiam o detalhe da fotografia anterior, registrando a origem. A fotografia
   nova é sempre completa.
4. Calcular o delta e exibir a prévia. Nada é gravado antes da confirmação.
5. Ao confirmar: gravar `data/raw/contratosgov/contratosgov_<sha256[:12]>.json` (imutável, sem sobrescrever)
   e o manifesto (`Manifesto` de `importacao_versionada`, base `contratosgov`, com data/hora da consulta,
   contagens — contratos, vigentes, termos, NEs, reconsultados, reaproveitados — e valor global somado dos
   vigentes) e atualizar o ponteiro `contratosgov_atual.json`.

**Delta (por contrato):** contratos novos; contratos ausentes; termos novos; termos removidos; vigência
alterada (fim antes → depois); valor global alterado; NEs novas; NEs desvinculadas; NEs com valores
movimentados (só contagem).

**Confirmação reforçada** ("Estou ciente" + botão) quando houver qualquer remoção: contrato ausente, termo
removido ou NE desvinculada. Os itens removidos continuam nas fotografias anteriores.

**Volume:** primeira carga ≈ 2 + 220 × 2 chamadas; atualizações seguintes ≈ 2 + (vigentes + novos +
alterados) × 2. Pausa curta entre chamadas e barra de progresso.

**Formato da fotografia:** `{"versao_formato": 1, "consultado_em", "ug", "lista_ativos": [...],
"lista_inativos": [...], "detalhes": {"<id>": {"historico": [...], "empenhos": [...],
"consultado_em", "origem"}}}` — respostas da API guardadas sem transformação.

## 6. Tratamento de erros

| Situação | Comportamento |
|---|---|
| Timeout, erro de conexão, HTTP 5xx | 3 novas tentativas com pausa crescente; persistindo, aborta sem gravar, mantém a fotografia anterior e informa a URL. |
| HTTP 429 | Aguarda e tenta de novo (conta nas tentativas). |
| Falha no detalhe de um contrato | Aborta a atualização inteira. |
| HTTP 4xx (exceto 429) | Aborta com a URL e o status. |
| Formato inesperado (campo obrigatório ausente, tipo errado) | `ErroDadoContratosGov` com `contrato_id` e campo. |
| Valor/data inválidos | `ErroDadoContratosGov` com localização. |
| Nenhuma fotografia | Página mostra só a primeira carga. |
| Manifesto aponta fotografia inexistente | Erro explícito. |
| Complementos ilegíveis | Erro explícito. |

## 7. Testes

Sem acesso à rede. pytest; rodadas intermediárias com `--testmon -n auto`, suíte completa ao final.

- **Fixture** `tests/fixtures/contratosgov_2026-10-08.json` (formato da fotografia, §5): amostra real
  reduzida de ~6 contratos — vigente, encerrado, inativo, com aditivos, com apostilamento com novo valor,
  com várias NEs, sem NE. CPFs de pessoa física trocados por valores fictícios no congelamento. Valores
  esperados calculados à mão e documentados no teste. Não é sobrescrita automaticamente (mesma regra das
  demais fixtures do `AGENTS.md`).
- `test_contratos_cadastro.py`: tabelas, vigência com referência fixa, NE completa, zeros iniciais, nulo ×
  zero × negativo, erro em valor inválido.
- `test_contratosgov_extracao.py`: política incremental, tudo ou nada, cada categoria do delta, confirmação
  reforçada, gravação sem sobrescrever (cliente HTTP falso montado a partir da fixture).
- `test_contratosgov_api.py`: novas tentativas em 5xx/429, aborto após esgotar, 4xx, timeout
  (`unittest.mock` sobre `requests`).
- `test_contratos_complementos.py`: gravação atômica, arquivo ilegível, preservação de complemento de
  contrato ausente, atualização não toca nos complementos.
- Isolamento: após atualização simulada em diretório temporário, nada é escrito fora de
  `data/raw/contratosgov/`, `data/manifestos/` e `data/contratos/`.

## 8. Fora do escopo

Vencimentos/prorrogações, execução financeira por contrato, necessidade de empenho, fiscalização, empenhos
substitutivos, integração com Contratos Contínuos, remoção do módulo antigo de Vigência, atualização
automática agendada, Portal da Transparência e SIOP.

## 9. Pontos em aberto

- Nenhum bloqueante. Ajustes de nome de campo podem surgir ao congelar a fixture; qualquer campo da API
  diferente do descrito em §3 será sinalizado, não adivinhado.
