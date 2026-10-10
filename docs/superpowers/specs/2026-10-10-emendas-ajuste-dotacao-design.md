# Emendas — decisão registrada sobre divergência de dotação — Design

Data: 2026-10-10 · Status: aguardando revisão do usuário · Base: `master` (`0af1226`)

## Problema

O quadro **"Dotação informada ≠ Dotação Anual por PTRES"** (`app_pages/emendas_parlamentares.py`,
`divergencias_dotacao`) mostra a diferença entre a dotação da emenda no relatório de Emendas e a Dotação Anual do
PTRES, mas é só informativo ("os dois valores são exibidos sem indicar qual está correto … confira na origem").
Não há como resolver. Caso real (conferido em 10/10/2026): emenda `202642780018` (Teresa Leitão), RP6, PTRES
`261464`, exercício 2026 — relatório R$ 300.000,00 × Dotação Anual R$ 600.000,00 (diferença R$ 300.000,00; única
divergência da base; só uma emenda usa esse PTRES).

## Decisão do usuário (10/10/2026)

**Decisão registrada por divergência**: em cada divergência o usuário escolhe adotar a Dotação Anual, manter o
relatório ou informar outro valor, com justificativa; a decisão fica num registro imutável (quem, quando, valor
anterior e novo), vale nas contas e totais, pode ser desfeita, e o valor original do relatório continua guardado.

## Objetivo

Permitir sanear cada divergência de dotação sem alterar o relatório importado, com rastreabilidade total.

## Fora de escopo (lacunas encontradas, para decidir depois)

Editar/remover cadastro manual de emendas (hoje só cria); exibir as sobreposições cadastro manual × relatório
(`composicao.sobreposicoes` existe e não aparece); exibir conflitos de vínculo (`ResultadoComposicaoVinculos.conflitos`);
comparar a SOMA das emendas de um PTRES com a Dotação Anual (hoje cada emenda é comparada sozinha); qualquer
alteração de valores executados (empenhado/liquidado/pago) — só a **dotação atualizada**.

## Regras

- **Escopo:** exercícios `>= ANO_INICIO_ATUALIZACAO` (2026), na granularidade do vínculo
  `(ano, resultado_primario_cod, emenda_numero, ptres)`. Exercícios anteriores ficam estáticos, sem decisão.
- **Três decisões** (`decisao`):
  1. `adotar_dotacao_anual` — valor efetivo = Dotação Anual do PTRES. **Só permitida quando o PTRES tem uma única
     emenda no exercício/RP**: a Dotação Anual é do PTRES inteiro e não pode ser atribuída a uma emenda quando há
     outras (nesse caso a opção não é oferecida e a validação no servidor recusa).
  2. `manter_relatorio` — valor efetivo = o do relatório; a divergência passa a "decidida" (não alerta mais), nenhum
     valor muda nas contas.
  3. `valor_informado` — valor efetivo digitado: número ≥ 0 (zero é válido e diferente de vazio; vazio não é aceito).
- **Justificativa obrigatória** (texto, mínimo de 10 caracteres úteis) e **responsável** (texto livre obrigatório; o
  sistema não tem login).
- **Registro imutável**: um JSON por evento em `data/emendas/ajustes_dotacao/` (mesmo padrão de
  `data/emendas/vinculos/`; novo diretório = nova persistência, aprovada com a escolha acima e a confirmar nesta spec).
  Ações: `decidir` e `desfazer` (desfazer acrescenta evento, nunca apaga). Campos do evento: `evento_id`, `acao`,
  `decisao_id`, chave do vínculo, `decisao`, `valor_relatorio` (na data da decisão), `valor_dotacao_anual` (idem),
  `valor_efetivo`, `justificativa`, `responsavel`, `registrado_em` (UTC ISO). O estado vigente é reconstruído pela
  sequência e validado antes de aplicar (arquivo ilegível levanta erro, nunca vira "sem decisões").
- **Uma decisão ativa por chave.** Para alterar: desfazer e decidir de novo (a interface faz os dois eventos).
- **Decisão obsoleta:** a decisão só é aplicada enquanto o valor do relatório atual for igual (±R$ 0,01) ao
  `valor_relatorio` gravado. Se um relatório novo mudar o valor, a decisão fica **obsoleta**: não é aplicada, a
  divergência volta a aparecer como pendente com o aviso "decisão de DD/MM/AAAA obsoleta: o relatório mudou de R$ X
  para R$ Y" — nunca se aplica um ajuste antigo sobre dado novo em silêncio.
- **Se a divergência deixa de existir** (ex.: relatório novo já traz R$ 600.000,00): a decisão continua registrada
  mas aparece como "sem efeito" (valores já iguais). **"Sem efeito" tem precedência sobre "obsoleta"**: sem
  divergência não há alerta a trazer de volta, mesmo que o relatório tenha mudado desde a decisão.
- **Valor original sempre preservado**: o relatório importado não muda; as visões ganham `dotacao_relatorio`
  (original) ao lado de `dotacao_atualizada` (efetiva). Nulo ≠ zero.

## Componentes

### 1. `src/ajustes_dotacao_emendas.py` (novo; regra específica da base de Emendas)

- `registrar_decisao(chave, decisao, valor_efetivo, justificativa, responsavel, vinculos, diretorio=...) -> dict` —
  valida (2026+, chave existente em `vinculos`, regras acima, justificativa/responsável, valor), grava o evento.
- `desfazer_decisao(decisao_id, justificativa, responsavel, diretorio=...)`.
- `carregar_eventos(diretorio=...)`, `reconstruir_decisoes(eventos) -> list[dict]` (estado ativo/desfeito).
- `aplicar_decisoes(vinculos, decisoes) -> (vinculos_efetivos, status)` — acrescenta `dotacao_relatorio`,
  `dotacao_decisao`, `dotacao_decisao_id`, `dotacao_decisao_estado` (`ativa`/`obsoleta`/`sem_efeito`/nulo) e
  substitui `dotacao_atualizada` só nas decisões ativas; `status` lista cada decisão com seu estado.
- `ptres_com_uma_emenda(vinculos, ano, rp, ptres) -> bool`.

### 2. `src/emendas_parlamentares.py`

`vincular_execucao_emendas(..., decisoes_dotacao=None)`: aplica as decisões ao `vinculos` ANTES de comparar com a
Dotação Anual (`_acrescentar_dotacao_anual`), de modo que `diferenca_dotacao`/`dotacao_divergente` usem a dotação
efetiva e os totais por emenda (`_resumir_emendas_vinculadas`) já saiam corretos. `divergencias_dotacao` passa a
devolver também o estado da decisão (pendente × decidida × obsoleta). Sem `decisoes_dotacao`, comportamento idêntico
ao atual (teste de não regressão).

### 3. Tela (`app_pages/emendas_parlamentares.py`)

- Quadro de divergências: só as **pendentes** (e obsoletas, com o aviso), cada linha com botão **"Resolver"** que
  abre a janela `@st.dialog`: mostra relatório, Dotação Anual, diferença e se o PTRES é compartilhado; opções
  adotar/manter/informar valor (adotar só quando permitido); campos justificativa e responsável; confirmar grava.
- Seção **"Decisões de dotação"** (expansor): lista as decisões (ativas, obsoletas, sem efeito) com valores, quem e
  quando, e o botão "Desfazer" (com justificativa).
- Cartão da emenda: marca "dotação decidida" e mostra o valor original do relatório quando a efetiva é diferente.
- Sem fotografia de Dotação Anual: o quadro não aparece (como hoje); decisões existentes continuam aplicadas.

## Regras permanentes respeitadas

Relatório importado e Dotação Anual nunca alterados; transformações em memória; códigos (emenda, PTRES) como texto;
nulo ≠ zero ≠ negativo; regra específica fora do importador genérico; persistência só em arquivos de evento
imutáveis; nenhuma regra presumida: toda decisão é humana, justificada e reversível.

## Testes (pytest, `-n 4` na pasta do Drive)

Unidade (diretório temporário): validações (2026+, chave inexistente, justificativa/responsável ausentes, valor
vazio/negativo; zero aceito), PTRES compartilhado recusa `adotar`, reconstrução com desfazer, uma decisão ativa por
chave, obsolescência quando o relatório muda, "sem efeito" quando já igual, arquivo de evento ilegível levanta erro,
não alteração do relatório. Integração: o caso real (emenda `202642780018`, 300.000 × 600.000) com `adotar` →
`dotacao_atualizada` 600.000, `dotacao_relatorio` 300.000, divergência decidida, totais da emenda corretos;
não regressão sem decisões. Página (`AppTest`): quadro com "Resolver", janela com os campos e sem gravar ao abrir;
seção "Decisões de dotação" lista decisão existente e "Desfazer". Suíte completa ao final.

## Riscos e dúvidas

- Dotação Anual por PTRES × várias emendas: tratada acima (`adotar` bloqueada), mas a comparação automática de cada
  emenda contra o PTRES inteiro continua podendo gerar falsa divergência quando há PTRES compartilhado (fora de
  escopo; sinalizado).
- "Responsável" é texto livre (sem login): a rastreabilidade depende de quem digita.
- O vínculo agrega linhas por GND; a decisão vale para o total do vínculo (emenda × PTRES), não por GND.

## Critérios de aceitação

1. No caso real, o usuário resolve a divergência pela tela e o total da emenda passa a R$ 600.000,00, com o
   original (R$ 300.000,00), o motivo, o responsável e a data visíveis.
2. Desfazer restaura R$ 300.000,00 sem apagar nenhum arquivo de evento.
3. Relatório novo com valor diferente torna a decisão obsoleta, com aviso, sem aplicá-la.
4. `adotar` é recusada (interface e servidor) quando o PTRES tem mais de uma emenda.
5. Sem decisões, nada muda no sistema; suíte completa verde.
