# Emendas — acompanhamento (tramitação, objeto, destinatário) e novo visual — Design

Data: 2026-10-10 · Status: aguardando revisão do usuário · Base: `feat/emendas-ajuste-dotacao`
Complementa `2026-10-10-emendas-ajuste-dotacao-design.md` (etapa 1) e usa a maquete
`2026-10-10-emendas-visual-mockup.html` (etapa 3).

## Pedidos do usuário (10/10/2026)

1. Dentro do cadastro de cada emenda, **registrar um status atual** e manter o **histórico da tramitação**.
2. Poder informar **objeto** e **destinatário** manualmente.
3. Novo visual conforme a maquete (registro compacto, exercício 2026+ por padrão, cores com sentido).
4. Status: **lista sugerida + "Outro"** (decisão do usuário).

## Etapas (mesma branch, cada uma com testes e commits próprios)

1. Decisão registrada sobre divergência de dotação (spec própria, já aprovada).
2. **Acompanhamento da emenda** (esta spec, seções 1–5).
3. **Novo visual** (esta spec, seção 6).

## Princípios

O relatório oficial importado nunca é alterado. Os dados novos são **manuais**, guardados como **eventos imutáveis**
(um JSON por evento, como `data/emendas/vinculos/`): nada é editado nem apagado; corrigir é acrescentar um evento.
Persistência nova (`data/emendas/acompanhamento/`) — aprovada com este pedido, a confirmar nesta spec.
Valor nulo ≠ vazio digitado ≠ zero (não há valores monetários aqui). Códigos como texto.

## 1. Chave e escopo

Chave da emenda: `(ano, resultado_primario_cod, emenda_numero)`, como texto/inteiro conforme o restante do módulo.
Vale para **qualquer exercício** (histórico incluído): é informação de acompanhamento, não valor financeiro. O
servidor valida que a chave existe na composição atual (relatório + cadastros manuais); evento de chave que depois
some do relatório fica **órfão**: permanece registrado e é listado como tal, nunca descartado.

## 2. Tramitação (status + histórico)

- **Status** (`status`): lista sugerida — `Indicada`, `Recebida pela UFRPE`, `Em análise técnica`,
  `Impedimento técnico`, `Proposta aceita`, `Empenhada`, `Liquidada`, `Paga`, `Concluída`, `Cancelada` — mais
  `Outro`, que exige `status_outro` (texto livre, 3 a 80 caracteres). A lista é uma constante do módulo (mudar a
  lista não altera registros antigos, que guardam o texto do status).
- **Registro de status** (evento `registrar_status`): `evento_id`, chave, `status`, `status_outro`, `data_status`
  (data em que o status valeu; padrão hoje, pode ser retroativa, **não pode ser futura**), `observacao`
  (opcional, até 500 caracteres), `responsavel` (obrigatório, texto livre — não há login), `registrado_em` (UTC ISO).
- **Status atual** = o registro não cancelado com maior `data_status` (desempate: `registrado_em`). Mostrado no
  cartão/linha da emenda e usado no filtro.
- **Histórico** = todos os registros em ordem cronológica, com quem registrou e quando; os cancelados continuam
  visíveis, riscados.
- **Correção**: evento `cancelar_status` (referencia `evento_id`, `motivo` obrigatório, `responsavel`); o registro
  original permanece. Um registro só é cancelado uma vez.
- Mesmo status em sequência é permitido (ex.: nova observação); sem regra de transição presumida — o sistema **não
  impõe ordem entre status** (regra de negócio não definida; sinalizada abaixo).

## 3. Objeto e destinatário (complemento manual)

- Campos livres por emenda: `objeto` (até 500 caracteres) e `destinatario` (até 200). Vazio = não informado (nulo),
  nunca string vazia gravada.
- Evento `definir_complemento` com **os dois campos juntos** (retrato completo), `responsavel`, `motivo` (opcional),
  `registrado_em`. O valor vigente é o do último evento; o histórico de alterações é listado (valor anterior → novo).
- O relatório oficial não traz objeto nem destinatário (conferido: colunas do relatório); se um dia trouxer, o manual
  continua separado e visível como "informado manualmente".
- Também disponível (opcional) no diálogo **"Cadastrar emenda"** (gera o evento logo após o cadastro).

## 4. Módulo `src/acompanhamento_emendas.py` (novo)

`STATUS_SUGERIDOS`, `registrar_status(chave, status, status_outro, data_status, observacao, responsavel,
chaves_validas, hoje=None, diretorio=...)`, `cancelar_status(evento_id, motivo, responsavel, diretorio=...)`,
`definir_complemento(chave, objeto, destinatario, responsavel, motivo, chaves_validas, diretorio=...)`,
`carregar_eventos(diretorio=...)` (arquivo ilegível levanta erro; nunca vira "sem eventos"),
`reconstruir_tramitacao(eventos) -> DataFrame` (histórico completo com `cancelado`), `status_atual(tramitacao) ->
DataFrame` (uma linha por chave), `complemento_vigente(eventos) -> DataFrame`, `historico_complemento(eventos, chave)`,
`orfaos(eventos, chaves_validas)`.
`hoje` é parâmetro (testes determinísticos); validações no servidor, nunca só na interface.

## 5. Tela — acompanhamento

Na emenda (cartão hoje; painel de detalhe do registro na etapa 3), seção **Acompanhamento**:
- status atual (chip) + data + quem; botão **"Registrar status"** (janela: status, "Outro" se for o caso, data,
  observação, responsável) e **histórico** em linha do tempo, com "Cancelar registro" (pede motivo);
- **Objeto** e **Destinatário** com botão "Editar" (janela com os dois campos, responsável e motivo opcional) e
  lista de alterações;
- eventos órfãos listados numa seção "Registros sem emenda correspondente" (não escondidos).
Nada é gravado ao abrir uma janela; só no botão de confirmação.

## 6. Novo visual (etapa 3) — conforme a maquete

- Registro compacto (uma linha por emenda: emenda/parlamentar, exercício, dotação, barra de executado, liquidado,
  pago, situação) com detalhe por PTRES ao expandir, **no mesmo padrão de Contratos Contínuos** (`src/ui_cadastro.py`).
- Filtro de exercício abre em **2026 em diante**, com histórico a um clique; totais do topo respeitam o filtro.
- Painel de pendências no topo (divergência de dotação com "Resolver"; órfãos).
- Cores com sentido: "Aguardando execução" neutro/azul; vermelho só para problema real.
- Coluna e filtro de **Tramitação** (status atual), e objeto/destinatário no detalhe.
- Tabela por PTRES só quando houver mais de um PTRES.
- Sem mudança de regra de negócio: mesmos números, mesma composição; só apresentação.

## Fora de escopo

Impor ordem/transições entre status; notificações; permissões por usuário; anexos; exportação do histórico (pode
vir depois); editar ou remover cadastros manuais de emendas; sobreposições e conflitos de vínculo na tela.

## Dúvidas de negócio sinalizadas

- Não há regra de transição entre status (ex.: "Paga" sem "Liquidada"): o sistema não valida a ordem.
- "Responsável" é texto livre (sem login): a rastreabilidade depende de quem digita.
- A lista sugerida de status é uma proposta do desenvolvimento; ajustar com a área antes de uso oficial.

## Testes (pytest; `-n 4` na pasta do Drive; sem `-n auto`)

Unidade com diretório temporário: status válido/inválido, "Outro" exige texto, data futura recusada e retroativa
aceita, responsável obrigatório, status atual por data (e desempate), cancelamento mantém o original e some do status
atual, cancelar duas vezes recusado, complemento vazio vira nulo, retrato completo e histórico de alterações, chave
inexistente recusada, órfãos listados, arquivo ilegível levanta erro, eventos não alteram o relatório. Página
(`AppTest`): seção com status atual, janelas abrem sem gravar, histórico exibido, filtro e coluna de tramitação (etapa
3), registro compacto mostra as mesmas emendas e totais do cartão atual (não regressão visual de dados). Suíte completa
ao final de cada etapa.

## Critérios de aceitação

1. Registrar "Em análise técnica" em 12/08/2026 e depois "Proposta aceita" em 01/09/2026: o status atual é "Proposta
   aceita" e o histórico mostra os dois, com responsável e data de registro.
2. Cancelar um registro com motivo mantém o evento original e o remove do status atual.
3. Objeto e destinatário podem ser informados, alterados (com histórico) e aparecem na emenda; vazio fica "não
   informado".
4. Nenhum arquivo de evento é editado ou apagado; relatório importado intacto.
5. Registro compacto com os mesmos totais; abre em 2026+; suíte completa verde em cada etapa.
