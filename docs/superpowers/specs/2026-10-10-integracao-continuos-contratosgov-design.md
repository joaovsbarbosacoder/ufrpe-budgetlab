# Integração Contratos Contínuos × Contratos.gov.br (vigência e aditivos) — Design

Data: 2026-10-10 · Status: aguardando revisão do usuário · Base: `feat/google-agenda`

Substitui a spec/plano de 2026-10-10 escritos contra a cópia antiga do projeto (planilha
`BASE_CONTRATOS`, já removida daqui).

## Objetivo

Refletir no cadastro nativo de Contratos Contínuos (`app_pages/contratos_continuos.py`,
`src/contratos_continuos_cadastro.py`) a vigência e os aditivos vindos da fotografia do
Contratos.gov.br (`src/contratos_cadastro.py`: `contratos`, `termos`, `empenhos`), e oferecer a
inclusão, no cadastro de Contínuos, de contratos do gov que ainda não estão nele.

## Decisões do usuário (10/10/2026)

- Candidatos a Contínuos: **todos os vigentes ausentes do cadastro** (o gov não tem o campo
  "contínuo"; o usuário escolhe na lista).
- Aditivos no gov sem registro no cadastro: **sinalizar e permitir registrar com clique**.
- Escopo: conciliação + aditivos + contratos novos, nessa ordem.
- Código no módulo existente `src/contratos_continuos.py` (sem módulo novo) e UI na página
  existente de Contínuos.

## Fora de escopo

Divergência de valor (Contínuos = parcela da ação 20RK; gov = contrato inteiro — sem regra
definida), importar valor mensal do gov automaticamente, alterar a fotografia do gov ou as
planilhas, nova persistência (usa só o cadastro nativo já existente).

## Dados

- Cadastro de Contínuos: um registro por contrato/NE e exercício (`contrato_numero`,
  `fornecedor_cnpj_cpf`, `ne_curta`, `vigencia_fim` ORIGINAL, `aditivos` nativos,
  `vigencia_fim_efetiva` derivada de `src/contratos_aditivos.py`).
- Gov: `contratos` (`numero` "00018/2014", `fornecedor_documento` só dígitos, `vigencia_fim`,
  `situacao_vigencia` ∈ vigente/a_iniciar/encerrado/inativo/sem_vigencia, `valor_parcela`),
  `termos` (`tipo` "Contrato"/"Termo Aditivo"/…, `qualificacao_termo` "VIGÊNCIA; REAJUSTE",
  `vigencia_fim`, `novo_valor_parcela`, `data_inicio_novo_valor`, `data_assinatura`, `numero`),
  `empenhos` (`ne` forma curta "2026NE000522", `natureza_despesa`, `plano_interno`,
  `fonte_recurso`).
- A `ne` do gov e o `ne_curta` de Contínuos têm o mesmo formato: **a NE é a chave principal**.

## Componentes

### 1. `com_contratosgov(df, contratos, termos, empenhos, hoje=None)` — `src/contratos_continuos.py`

Função pura em memória; acrescenta colunas ao DataFrame de `como_dataframe`, sem alterar linhas
nem valores originais.
- Ligação, nesta ordem: (a) `ne_curta` ∈ `empenhos.ne` → `contrato_id` do gov; (b) número
  normalizado (`normalizar_numero_contrato`, de `src/contratos_pagamentos.py`, aplicada aos dois
  lados) + CNPJ/CPF iguais. Colunas: `contratosgov_id`, `ligacao_por` ("ne"/"numero"/nulo).
- NE e número apontando contratos diferentes, ou NE em mais de um contrato, ou número ambíguo no
  gov → `situacao_conciliacao = "conflito"`, nada do gov é aplicado.
- Vários registros de Contínuos (uma NE cada) podem ligar ao mesmo contrato do gov.
- Vigência: compara `vigencia_fim_efetiva` do cadastro com `vigencia_fim` do gov (igualdade
  exata; nulo em qualquer lado → `sem_data_para_comparar`, nunca divergência).
  `diverge_vigencia` em `boolean` (True/False/NA).
- `situacao_conciliacao` ∈ {`conciliado`, `divergente`, `sem_par_no_contratosgov`, `conflito`,
  `sem_data_para_comparar`}; `situacao_vigencia_gov` repassa a do gov (contrato "encerrado" no
  gov e "ATIVO" no cadastro é sinalizado).
- Traz também `qtd_termos`, `qtd_aditivos_gov` (só `tipo == "Termo Aditivo"`),
  `qtd_aditivos_pendentes` (item 2) e `valor_parcela_contratosgov` (referência, nunca comparado).

### 2. Aditivos do gov sem registro — mesmo módulo

`aditivos_pendentes(aditivos_nativos, termos_do_contrato) -> list[dict]`
- Só termos com `tipo == "Termo Aditivo"` são candidatos (apostilamento, rescisão etc. aparecem
  no histórico, nunca contados como aditivo).
- Um termo está **registrado** se algum aditivo nativo tem o mesmo `numero` normalizado ou a
  mesma `data_assinatura`; caso contrário é pendente. *Dúvida de negócio:* o `numero` nativo é
  texto livre; o casamento é heurístico e por isso só sugere, nunca grava sozinho.
- `aditivo_sugerido(termo) -> dict` no formato `aditivo_para_registro`: `tipo` por qualificação
  (REAJUSTE → `REAJUSTE`; senão VIGÊNCIA → `PRORROGACAO`; senão ACRÉSCIMO / SUPRESSÃO →
  `ACRESCIMO_SUPRESSAO`; INFORMATIVO/vazio → `OUTRO`), `situacao = "ASSINADO"`,
  `data_inicio = data_inicio_novo_valor` (se nula, `data_assinatura`), `vigencia_fim` do termo,
  `numero`/`data_assinatura` do termo. **`valor_mensal` fica nulo** (parcela do gov é do contrato
  inteiro). *Dúvida de negócio:* termo com várias qualificações vira um aditivo só; o usuário
  ajusta antes de salvar.

### 3. `candidatos_novos(df, contratos, empenhos, hoje=None) -> (candidatos, em_duvida)`

- Candidato: contrato do gov com `situacao_vigencia` em {vigente, a_iniciar} sem registro
  ligado em Contínuos (mesma ligação do item 1; um contrato já incluído na sessão/cadastro deixa
  de aparecer).
- `em_duvida`: `sem_vigencia` (sem datas) e contratos com conflito de ligação — listados com o
  motivo, sem botão "Incluir".
- Cada linha traz: número, ano, fornecedor, CNPJ/CPF (texto, zeros preservados), objeto,
  categoria, vigência, `valor_parcela` (referência) e as NEs do contrato com natureza de
  despesa, plano interno e fonte.

### 4. Tela (`app_pages/contratos_continuos.py`)

- **Cartão:** tag de conciliação (confere / divergente com as duas datas / sem par / conflito /
  sem data); linha com termo atual, nº de termos, nº de aditivos do gov e valor da parcela como
  referência; histórico de termos (`popover`); aviso "N aditivo(s) no gov sem registro" com
  botão **"Registrar aditivo do gov"**.
- **Registrar aditivo do gov:** abre a janela de edição do contrato com o aditivo sugerido já
  adicionado na aba Aditivos (em `st.session_state[f"{k}_aditivos"]`); **nada é gravado até o
  usuário clicar Salvar**, e todos os campos continuam editáveis. Usa a persistência do cadastro
  que já existe (`atualizar_contrato`).
- **Bloco "Novos no Contratos.gov":** candidatos e em dúvida. "Incluir" abre a janela "Novo
  contrato" pré-preenchida com os campos que o gov tem: número, ano, fornecedor, CNPJ/CPF,
  `vigencia_fim` (do termo atual), NE (se o contrato tem uma só; se tiver várias, o usuário
  escolhe), natureza de despesa, plano interno e fonte da NE. Ação, PTRES, UGR, despesa mensal e
  meses ficam em branco (nulos, nunca zero). Só grava ao salvar.
- Sem fotografia do gov, ou com erro de leitura: a tela segue sem a integração, com aviso
  explícito (mesmo padrão de `app_pages/contratos.py::_carregar`).

## Regras permanentes respeitadas

Planilhas e fotografia nunca alteradas; transformações em memória; códigos como texto (NE, CNPJ,
números de contrato); nulo ≠ zero ≠ negativo; regra de base fora do importador genérico; sem nova
persistência; dúvidas de negócio sinalizadas acima.

## Testes (pytest; `python -m pytest tests -n auto` ao concluir)

Fixture congelada `tests/fixtures/contratosgov_2026-10-08.json` (UG 153165, 6 contratos) e
fixtures do cadastro de Contínuos já existentes; valores esperados calculados à mão. Casos:
ligação por NE; ligação por número+CNPJ; conflito NE × número; NE em dois contratos; vários
registros → mesmo contrato do gov; vigência igual/divergente/nula; contrato encerrado no gov e
ATIVO no cadastro; aditivo pendente × registrado (por número e por data); apostilamento e
rescisão fora da contagem de aditivos; `aditivo_sugerido` por qualificação (valor mensal nulo);
candidatos vigentes, encerrados, sem vigência, já incluído; pré-preenchimento do novo contrato;
teste de página (`AppTest`) para tag, botão de registrar sem gravar e bloco de novos.

## Riscos

- Heurística de aditivo "registrado" (número/data) e de tipo por qualificação.
- Cadastro nativo é por NE/exercício: contrato do gov com várias NEs pode ter vários registros —
  a conciliação é por registro.
- Lista de candidatos grande (todos os vigentes ausentes) — mostrada compacta, só revela ao abrir.

## Critérios de aceitação

1. Registros ligados por NE trazem `contratosgov_id`, `ligacao_por = "ne"` e conciliação correta.
2. Nenhum arquivo do gov/planilha alterado; nada gravado sem clique em Salvar.
3. Cartão exibe tag, termos e aditivos pendentes; "Registrar aditivo do gov" só pré-preenche.
4. Candidatos novos listados com motivo; "Incluir" pré-preenche só campos do gov.
5. Testes novos e suíte completa verdes.
