# UFRPE BudgetLab

Aplicação local em Python e Streamlit para apoiar a gestão e a análise
orçamentária da Universidade Federal Rural de Pernambuco (UFRPE).

O projeto está em sua etapa inicial. A aplicação permite importar e inspecionar
arquivos Excel, normalizar bases reconhecidas do Tesouro Gerencial e analisar
seus movimentos sem presumir identidades contábeis entre itens.

## Funcionalidades

Toda base do projeto usa o mesmo padrão de **importação versionada**: um
manifesto (`data/manifestos/`) com hash SHA-256, data de extração e totais
por exercício — é o manifesto, não o arquivo bruto, que fica versionado.
Cada página de análise lê o manifesto atual da sua base direto (nunca
`st.session_state`) e oferece sua própria seção "Reimportar base", com
prévia (contagens, totais, validação, comparação com a extração anterior) e
gravação só após confirmação explícita quando a mudança altera um exercício
já fechado ou faz um exercício desaparecer. A mecânica comum (manifesto,
delta entre extrações, política de confirmação) vive em
`src/importacao_versionada.py` e `src/ui_reimportacao.py`, compartilhada
pelas duas bases; cada uma só define sua própria leitura, validação e
medidas (`src/importacao_execucao.py`, `src/importacao_dotacao.py`).

### Visão geral

A página inicial funciona como painel operacional: informa quantas das bases
cadastradas estão disponíveis localmente, a atualização mais recente entre
elas e a situação dos prazos orçamentários cadastrados. Esses indicadores não
combinam valores financeiros de extrações diferentes. A página também oferece
acessos diretos aos principais módulos de planejamento, operação e controle.

### Gerenciamento de Prazos

Cadastro manual de prazos do exercício, com alerta conforme a antecedência
escolhida para cada um (`src/prazos_orcamentarios.py`).

A página pode se conectar ao calendário principal do Google (opcional, ver
`docs/google_agenda.md`) e mostra os eventos dos próximos 30 dias — inclusive reuniões em
que o usuário é convidado. Acesso à API isolado em `src/google_agenda.py`.

Os prazos cadastrados também são sincronizados nos dois sentidos: excluir o evento de um
prazo no Google marca o prazo como concluído (nunca o exclui). Conciliação em
`src/prazos_sincronizacao.py`.

### Dotação Anual (BI CPOC - Por Ano)

Uma única aba organiza os lançamentos por ano (não por mês), com blocos
dimensionais que usam mesclagem real de células no Excel (não repetição de
valor). O reconhecimento localiza dinamicamente a
coluna-âncora "Item Informação" na linha 1 — que sempre precede o par de
colunas de Plano Orçamentário — e interpreta os blocos dimensionais à
esquerda dela pelas mesclagens de cabeçalho de 3 linhas. Isso permite
reconhecer variantes que apenas inserem ou removem um bloco dimensional (por
exemplo, uma exportação sem Grupo de Despesa), sem exigir uma nova
assinatura fixa para cada variante. Um bloco dimensional fora do conjunto
conhecido reprova o reconhecimento em vez de ser ignorado.

A normalização resolve as mesclagens reais da planilha (não usa forward
fill heurístico): uma célula só herda o valor do topo do bloco se estiver de
fato dentro de um intervalo mesclado confirmado pelo Excel. Itens monetários
não mapeados não são descartados — recebem um código `item_nao_mapeado_*` e
geram aviso.

A validação independente compara a matriz bruta e a base normalizada (soma
total, soma por item, por ano e por ano+item, contagens de nulos/zeros/
negativos e igualdade por coordenada). Como as somas desta base chegam à
casa dos bilhões, a tolerância é de centavos (`0,01`), não de milionésimos:
nessa magnitude o próprio `float64` acumula ruído de representação bem acima
de `0,000001` mesmo sem nenhuma divergência real de dado.

Esta é a base que alimenta as páginas **Dotação Orçamentária** e **Painel
por Ação de Governo**, ambas lendo `Manifesto.atual()` de
`src/importacao_dotacao.py`.

### Execução Anual (BI PROPLAD - Por Ano)

Tem importação própria e versionada (`src/importacao_execucao.py`),
acionada pela seção "Reimportar base" da própria página **Execução
Orçamentária**.

A página **Execução Orçamentária** mostra, sobre o recorte filtrado
(Exercício, GND, Fonte, Resultado Primário, UGR): cartões de Empenhado,
Liquidado e Pago com os percentuais de execução; uma série histórica em
barras agrupadas por exercício, com o exercício em andamento marcado
visualmente; composição por uma dimensão por vez (GND, Fonte, Ação,
Natureza Detalhada, Resultado Primário, UG Responsável, UGR, PI, PTRES,
Plano Orçamentário ou Favorecido), com ranking limitado às 15 maiores
categorias quando a dimensão tem alta cardinalidade; e rastreabilidade por
Nota de Empenho, exibindo as linhas de origem (`linha_origem`).

Layout de origem, regras de reconciliação e decisões de arquitetura estão
em `docs/base_execucao_anual.md`.

### Consulta de Empenhos — relatório de liquidação do grupo

Na página **Consulta de Empenhos** (Execução Mensal), as NEs marcadas na
lista podem ser extraídas em PDF e Excel (`src/relatorio_liquidacao_empenhos.py`):
Liquidado mês a mês, uma linha por NE e ano. Cada NE usa uma única base,
indicada na coluna "Base": **Competência** (mês de referência, base
Liquidação por Competência) quando a NE tem registro nela; caso contrário,
**Data de liquidação** (mês de lançamento, Execução Mensal), com aviso. O
resumo por NE reconcilia o total da série com o liquidado total da NE na
Execução Mensal e sinaliza competência parcial ou defasada (no Excel); o PDF
traz, em vez dele, a Consolidação Orçamentária do Grupo da tela (também presente
no Excel, aba "Consolidação"). As NEs saem
em ordem do número do empenho. Um quadro "Comparativo por
exercício" (PDF e aba "Por exercício" do Excel) soma as NEs por ano do mês,
informando quantas NEs de cada base compõem cada ano. O seletor "Base do
relatório" permite gerar tudo "Somente por data de liquidação", para comparar
exercícios no mesmo critério quando a base de competência não cobre os anos
anteriores; o modo aparece no título, nos parâmetros e no nome do arquivo.

### Contratos Contínuos

A página **Contratos Contínuos** trabalha sobre um cadastro nativo, multi-exercício, em
`data/contratos_continuos/<ano>/` (`src/contratos_continuos_cadastro.py`; a migração a partir
da planilha de trabalho está em "Migração dos cadastros nativos"). Cada contrato tem despesa
mensal, itens de licitação com rateio percentual, NE, classificação orçamentária e os campos de
período descritos abaixo. O saldo e o Empenhado vêm da Execução Mensal, cruzados por NE; o
Liquidado vem da base Liquidação por Competência quando ela está disponível
(`data/raw/Liquidação por Competência.xlsx`), senão do mês de lançamento. Quando uma NE não
tem correspondência, os campos de comparação ficam nulos, nunca zero.

**Campos de período (sempre do cadastro).** Status (`ATIVO`, `VENCIDO` ou `SUSPENSO`), Vigência
(fim), Início da Execução (por data ou pelo botão de mês), Data da Suspensão e Meses no Ano. A regra comum (`src/necessidade_empenho.py::meses_vigentes_no_exercicio`):

- `SUSPENSO` **com Data da Suspensão** vale até a véspera dela, como um fim de vigência (mês final
  proporcional); a partir da data, nada de necessidade, projeção ou sugestão de reforço. `SUSPENSO`
  **sem data** não gera nada no exercício inteiro, mesmo vigente. A data da suspensão só tem efeito
  com o status `SUSPENSO`;
- com data, **a data manda sobre o status**: fim anterior ao exercício ou início posterior a ele
  zeram; sem data de fim, `VENCIDO` zera e os demais seguem até dezembro;
- o mês de início e o mês de fim são **proporcionais aos dias** (fim em 15/11 conta 15/30 de
  novembro; início em 16/07 conta 16/31 de julho);
- só o início **informado** (data ou botão de mês) corta meses; o mês detectado
  automaticamente pelo primeiro empenho não corta nada, e a data vale mais que o mês.

**Contrato suspenso só conta o que já foi empenhado e liquidado** (06/10/2026,
`src/contratos_continuos.py::com_efeitos_da_suspensao`). Para contrato `SUSPENSO`, a **Despesa anual**
(cartão-resumo e Cobertura Orçamentária por PTRES) passa a ser o valor já empenhado (Execução Mensal;
sem a NE na Execução, o empenhado do cadastro; NE compartilhada por mais de um contrato usa o do
cadastro), e o **Saldo a liquidar (execução)** do cartão-resumo fica zero. Saldo, empenhado, liquidado e despesa mensal não
mudam; a despesa contratual original fica preservada em `despesa_anual_contratual`.

**Aditivos (06/10/2026, `src/contratos_aditivos.py`; aba "Aditivos" na janela de edição).** Quando um
contrato é prorrogado o valor mensal costuma ser reajustado, e um único valor para o exercício inteiro
distorcia a projeção. O contrato guarda uma lista de aditivos; cada um tem nº do termo (texto), tipo
(Reajuste, Repactuação, Prorrogação, Acréscimo/supressão, Outro), situação (**Assinado** ou **Previsto** —
valor estimado, ainda não assinado), data de início (pode ser passada), data de assinatura (opcional) e,
opcionalmente, novo valor mensal, nova vigência e novo rateio dos itens (campo vazio = mantém o anterior,
nunca zero). "Despesa mensal" e "Vigência (fim)" do contrato continuam sendo os **originais**; o valor, a
vigência e o rateio em vigor em cada data são derivados dos aditivos. Todas as contas passam a somar, mês a
mês e dia a dia, o valor em vigor (reajuste no meio do mês é proporcional aos dias):

- **Necessidade até dezembro** = custo do exercício − empenhado (nunca negativa); a diferença **retroativa**
  dos reajustes entra sozinha. **Projeção mensal**: cada mês projetado usa o custo do mês; o retroativo
  (reajuste assinado depois do início, nos meses já realizados entre as duas datas) entra no primeiro mês
  projetado, em coluna própria. **Sugestão do Reforço**: alvo = custo de janeiro ao mês vigente − empenhado,
  em meses do valor vigente; valor mensal e itens da linha são os vigentes. **Despesa anual** e Cobertura por
  PTRES: soma da série.
- **Previsto** entra nas contas, destacado (laranja) no Excel/PDF, na faixa do topo e nos avisos. Sem aditivo
  previsto, a projeção **para no vencimento** e o relatório avisa "Renovação não cadastrada".
- O Excel do relatório de Necessidade ganha a aba **Aditivos** (um aditivo por linha: valor anterior → novo,
  datas, retroativo) e colunas no Resumo por NE; contrato **sem aditivo** calcula exatamente o mesmo que antes
  (teste de não regressão `tests/test_retrato_contratos.py`, com retrato congelado dos contratos reais).
- Limites: a aba de aditivos edita só os itens de licitação já existentes no contrato; a janela "Novo
  contrato" não tem aditivos (cadastrados depois, ao editar). Para um contrato que **já teve o reajuste
  digitado por cima** de "Despesa mensal", volte o campo ao valor antigo e lance o aditivo com o novo — o
  sistema não faz essa troca sozinho.

**Integração com o Contratos.gov.br (10/2026, `src/contratos_continuos.py`).** A tela cruza cada registro do
cadastro com a fotografia atual do Contratos.gov.br (tabelas `contratos`, `termos` e `empenhos` de
`src/contratos_cadastro.py`), em memória: nada é gravado e a fotografia nunca é alterada. Sem fotografia (ou
com erro de leitura) a tela segue como antes, com aviso.

- **Ligação** (`com_contratosgov`): primeiro pela **NE** (`ne_curta` do cadastro = `ne` dos empenhos do gov, mesmo
  formato); depois por número normalizado + CNPJ/CPF (só dígitos; número sem CNPJ/CPF não liga). NE e número
  apontando contratos diferentes, ou NE em mais de um contrato, é `conflito` e nada do gov é aplicado. Vários
  registros (uma NE cada) podem ligar ao mesmo contrato do gov.
- **Conciliação de vigência:** `vigencia_fim_efetiva` do cadastro (já com os aditivos nativos) contra a vigência
  do gov, igualdade exata de data. Falta de data ou de par nunca vira divergência. A linha do registro mostra
  "Gov: vigência confere/diverge", "sem par no Contratos.gov" ou "conflito de ligação".
- **Aditivos do gov sem registro** (`aditivos_pendentes`): só `Termo Aditivo` conta (apostilamento e rescisão
  não). Um termo está registrado se um aditivo nativo tem o mesmo número normalizado ou a mesma data de
  assinatura — **casamento heurístico**, porque o número nativo é texto livre. Na janela de edição, a seção
  "Contratos.gov" mostra o histórico de termos e um botão "Registrar aditivo do gov" por pendente, que só
  **pré-preenche a aba Aditivos**: nada é gravado até clicar em Salvar. O tipo sugerido vem da qualificação do
  termo (REAJUSTE > VIGÊNCIA > ACRÉSCIMO/SUPRESSÃO; um termo com várias qualificações vira um aditivo) e é
  editável. A **prorrogação** começa na vigência do termo (`vigencia_inicio`); reajuste e demais, na data do novo
  valor (senão, na assinatura). **O valor mensal não é importado**: a parcela do gov é do contrato inteiro e Contínuos traz a
  parcela da ação 20RK (por isso ela aparece só como referência, nunca comparada).
- **Novos no Contratos.gov** (`candidatos_novos`): todos os contratos vigentes ou a iniciar que ainda não têm
  registro no exercício em tela (o gov não informa se o contrato é contínuo — a escolha é sua). Contrato sem
  vigência ou envolvido em conflito de ligação fica "em dúvida", sem botão. "Incluir" abre a janela "Novo
  contrato" preenchida só com o que o gov tem (número, ano, fornecedor, CNPJ/CPF, vigência e, se escolher a
  NE, a NE, a natureza de despesa, o plano interno e a fonte dela); ação, PTRES e UGR ficam em branco.
  O formulário "Novo contrato" deixa **em branco** (nulo, nunca zero) tudo que não foi preenchido — despesa
  mensal, empenhado, saldo, meses empenhados/liquidados e os textos (`novo_contrato_do_formulario`); um zero
  digitado continua zero, e "Meses no ano" em branco vale 12 nas contas. Só grava em "Adicionar contrato".

**Estimativa de reajuste (cenário por competência).** Seção "Estimativa de reajuste" em Contratos Contínuos
(`src/estimativa_reajuste.py`, `src/indices_economicos.py`, `src/ui_reajuste.py`; spec em
`docs/superpowers/specs/2026-10-11-estimativa-reajuste-contratos-design.md`). **Cenário separado**: não altera
Necessidade de Empenho, Projeção nem aditivos. Para cada contrato, uma matriz mês/ano (inclusive vigências que
atravessam exercícios) do **acréscimo** causado pelo reajuste:
- **Data-base:** a manual; senão o **início da vigência de renovação mais recente** (termo aditivo com vigência no
  Contratos.gov ou aditivo ASSINADO com nova vigência), repetida a cada 12 meses enquanto cabe na vigência efetiva
  (prorrogação prevista conta, marcada) e a partir de janeiro do exercício. Se um Reajuste ASSINADO já começa nessa
  renovação (ou depois), ele já está no valor em vigor e o ciclo seguinte vem 12 meses depois dele. Sem renovação:
  12 meses após o início da vigência. Data-base passada sem reajuste registrado gera acréscimo retroativo a conferir.
  Sem ciclo na vigência: "sem reajuste previsto" (nulo, nunca 0).
- **Percentual:** manual > oficial (índice do contrato; **padrão IPCA**, ou INPC/IGP-M; acumulado de 12 meses da API do
  Banco Central, só em sessão) > sem índice. Zero manual vale; ausente nunca vira 0%. Ciclos são compostos.
- **Base:** o reajuste incide sobre o **liquidado por competência** (Liquidação por Competência, estornos com sinal,
  NEs de todos os exercícios do contrato). Competência já apurada sem lançamento fica **vazia**; competência futura usa
  o valor contratado, rotulado **teto**. NE ligada a dois contratos é inconsistência sinalizada (o liquidado dela fica fora).
- **Configuração** (índice, percentual e data-base manuais) é gravada no próprio registro do contrato; "Registrar
  aditivo previsto" cria o aditivo REAJUSTE/PREVISTO do próximo ciclo só por clique; a estimativa sai em Excel.
- **Dúvidas registradas (não são regra definitiva):** janela do índice (12 meses anteriores à data-base); reajuste
  composto entre ciclos; incidência sobre o valor mensal total; data-base pela vigência (e não pela proposta);
  um percentual manual único para todos os ciclos; último mês "apurado" = mês anterior à data de referência.

**Necessidade de Empenho até Dezembro (card "Resumo Consolidado").** É o que falta empenhar
para cobrir os meses do exercício: despesa mensal × meses restantes, nunca negativa, em que
meses restantes = menor entre os meses no ano e os meses em execução (regra acima) − empenhado ÷
despesa mensal. O saldo (empenhado − liquidado) **não** entra nessa conta, porque já está dentro do
empenhado; ele é exibido e abate a projeção mensal, abaixo. Contrato sem NE entra à parte, sem
saldo. A conta vive em `src/relatorio_necessidade_empenho.py::necessidade_por_ne` e é usada
pela tela e pelos relatórios, para não divergirem. **Bolsas e Auxílios** usa a mesma regra no Resumo
Consolidado e no cartão-resumo (`necessidade_ate_dezembro`, em `src/necessidade_empenho.py`): valor
mensal × meses restantes, sem subtrair o saldo — corrigido em 05/10/2026, quando também lá o saldo era
descontado duas vezes.

**Registro de contratos (06/10/2026).** A coluna **A empenhar** e a **Situação** usam a mesma
Necessidade até dezembro do card (`necessidade_por_linha`; NE compartilhada mostra o valor da NE em cada
linha), não mais o saldo — antes, contrato com saldo aparecia como "Necessita reforço" e o sem saldo não.
Situação, nesta ordem (`src/contratos_continuos.py::situacao_contrato`): Vencido e Suspenso (status do
cadastro); **Vigência encerrada** (vigência efetiva, com aditivos, anterior a hoje, com outro status — o
status não é alterado); Necessita reforço (necessidade > 0); Ativo. O saldo (empenhado − liquidado)
segue na coluna Saldo, em "Meses de saldo" da janela de edição e em **Saldo a liquidar (execução)** no
cartão-resumo. NE que está na Execução Mensal e não tem nenhuma liquidação, nem lá nem na competência,
tem liquidado **0,00** (as duas bases confirmam) e é calculada pela Execução; se a Execução tem liquidação e
a competência não, o liquidado continua nulo e valem os campos manuais do cadastro.

**Relatório de Necessidade de Empenho (PDF e Excel).** Dois botões (PDF e Excel) abaixo do card. Uma linha por NE
na grade Jan–Dez do exercício: os meses com Liquidação por Competência aparecem como
**realizado**; do primeiro mês sem liquidação até dezembro aparece a **projeção** (sombreada e
em itálico), por despesa mensal fixa — o primeiro mês projetado é despesa mensal − saldo atual
do empenho e os seguintes a despesa mensal cheia (saldo maior que a despesa mensal é abatido
nos meses seguintes). A projeção respeita o período de execução acima e os meses no ano. NE sem
nenhuma competência e contrato sem NE projetam a partir do mês seguinte ao da extração da
Execução Mensal — salvo a NE **sem nenhuma liquidação** também na Execução Mensal (liquidado
0,00 confirmado pelas duas bases, base "Sem liquidação (Execução e Competência)"), que projeta desde o
início da execução, para concordar com o card. Nenhuma média nem tendência: só a despesa mensal cadastrada. O PDF traz a
grade, o total mensal e o resumo por NE; o Excel, as abas Projeção mensal, Detalhe mensal (com o
tipo de cada mês), Total mensal, Resumo por NE e Parâmetros (totais, regra e avisos). Mês sem dado
fica vazio (nulo), distinto de zero. Os avisos listam contratos suspensos, vencidos ou com
vigência encerrada, sem data de vigência, NEs sem saldo ou sem competência, e NEs com primeiro
empenho depois de janeiro e sem início definido.

**Projeção pela execução (06/10/2026, relatório separado; `src/relatorio_projecao_execucao.py`).** Seção
própria abaixo do relatório de Necessidade, com botões PDF e Excel; não altera nenhum outro quadro ou
relatório. Projeta a despesa até dezembro pelo que cada NE de fato liquida: **fator de execução** = 1 +
(execução observada − 1) × peso, em que a execução observada é o liquidado por competência ÷ custo
contratado acumulados nos últimos 6 meses fechados (os dois meses anteriores ao da extração ainda estão em
aberto) e o peso (de 0 a 1) cresce com o número de meses e cai com a oscilação mensal (prudência alta,
τ² = 0,01). Menos de 3 meses: valor mensal cheio, ou o fator de um **contrato antecessor** escolhido na
própria seção (a escolha não é gravada no cadastro). Meses em aberto com menos de 50% do esperado (ou sem
registro) projetam o restante. Mostra, por NE, a despesa projetada pela execução e pelo valor contratado, a
**necessidade pela execução** (projetada − saldo do empenho) e a Necessidade até dezembro contratual, e avisa
liquidação muito abaixo do cadastrado (fator < 0,5) ou acima do contrato (execução > 1,03). A diferença para o
contratado é tratada como execução abaixo do contratado (decisão do usuário). Contrato sem NE fica de fora.

**Projeção pela execução em Bolsas e Auxílios (07/10/2026).** O mesmo relatório (mesma regra do fator e da
projeção, PDF e Excel) tem seção própria na página de Bolsas, abaixo do Resumo Consolidado, com os rótulos da
base (Programa, Processo, Situação). Só o custo do mês tem regra própria, em `src/projecao_execucao_bolsas.py`:
valor mensal do cadastro em `meses_no_ano` meses seguidos a partir do **início da execução**, até dezembro.
Início, nesta ordem: o informado no cadastro; o primeiro mês do exercício com liquidação positiva por
competência da NE (o empenho costuma sair em janeiro, mas a bolsa pode começar a pagar depois); o mês do
primeiro empenho; janeiro. O Relatório de Reforço continua usando o início pelo primeiro empenho. Saldo e
empenhado vêm da Execução Mensal, com os da planilha como reserva; a necessidade comparada é a do Resumo
Consolidado. Programas que dividem uma NE somam numa linha. Sem a escolha de contrato antecessor. Programa
sem NE fica de fora (contado nos avisos).

A necessidade do card (por empenho) e a projeção da grade (por calendário, a partir do gasto)
são **métodos diferentes** e seus totais não coincidem por definição; o Resumo por NE traz as
duas colunas e o relatório avisa a diferença.

**Relatório de Reforço de Empenho.** O botão de relatórios da página também emite Reforço e
Anulação de Saldo de Empenho (PDF nos modelos detalhado e resumido, `src/relatorio_reforco_empenho.py`).
A sugestão inicial de cada linha respeita status, vigência e início da execução (data, com mês
inicial proporcional): contrato suspenso sem data, vencido ou com vigência encerrada começa com sugestão
zero, e a vigência (ou a véspera da suspensão) limita os meses sugeridos. A edição por linha continua livre; a Anulação
nunca tem sugestão automática.

**Layout dos cadastros.** Contratos Contínuos e Bolsas e Auxílios compartilham o mesmo desenho
(`src/ui_cadastro.py`): um cartão-resumo no topo (faixa "Necessidade de empenho até dezembro" e grade
de indicadores) e um **Registro** em tabela — abas de situação com contagem, filtro de categoria (ou
ação, em Bolsas), ordenação, linhas com título e subtítulo, situação em chip e ações por ícone. As linhas
ficam numa caixa com barra de rolagem; o registro abre com 15 linhas e "Ver mais" mostra todas num clique
só ("Ver menos" volta às 15). Os quadros "Necessidade de Empenho por NE" e "Empenhado × Liquidado" de
Contratos Contínuos seguem o mesmo padrão (3 linhas; "Ver mais" expande no próprio quadro, com rolagem,
em vez de abrir uma janela). "Editar"
abre uma janela com os campos em seções e só grava ao clicar em "Salvar"; "Remover" pede confirmação;
"Novo contrato"/"Novo programa" abre o formulário em janela. Os dados e as regras de negócio não
mudaram, mas a antiga edição ao vivo na sessão (os quadros refletindo o que estava digitado antes de
salvar) deixou de existir: os quadros sempre refletem o cadastro gravado.

**Processos nos cadastros.** As janelas de edição e de cadastro novo das duas telas trazem, em
Identificação, o **Processo da contratação** e o **Processo de empenho** (texto, zeros à esquerda
preservados; copiados ao duplicar o exercício). Em Contratos os dois já vinham da planilha. Em Bolsas, o
antigo campo "Processo" é o processo de empenho (bate com o processo das NEs na aba "Base TG" da
planilha) e passou a se chamar assim; o processo da contratação é campo novo, vazio nos registros
existentes até ser digitado. O Relatório de Reforço/Anulação continua agrupando pelo processo de empenho.

As seções analíticas das duas telas — **Resumo Consolidado**, **Empenhado × Liquidado** (só em
Contratos Contínuos) e **Cobertura Orçamentária por PTRES** — seguem o mesmo desenho: cartão com
kicker, título e destaque à direita, e linhas/tabelas com valores à direita. No Resumo Consolidado a
linha da NE com dado mensal tem um botão de ícone para a linha do tempo mensal. Apenas a
apresentação mudou; dados, totais e regras são os mesmos.

Limites conhecidos: contrato prorrogado com a data de fim desatualizada no cadastro aparece sem
projeção até a data ser corrigida no card; a competência dos últimos meses costuma estar
defasada, o que afeta o saldo e o realizado desses meses; a data de início só é considerada
quando informada.

### Contratos (Contratos.gov.br)

A página **Contratos** é um cadastro dos contratos da UG 153165 montado a partir da API pública do
Contratos.gov.br (somente leitura, sem credencial). A integração com Contratos Contínuos (conciliação de
vigência, aditivos e contratos novos) está descrita na seção Contratos Contínuos. Recorte: instrumentos do tipo "Contrato", todos os anos, ativos e inativos
(empenhos substitutivos ficam fora). Detalhes (endpoints, formato, regras de conversão) em
`docs/contratosgov.md`.

- **Fotografia versionada.** Cada atualização confirmada grava um JSON imutável em
  `data/raw/contratosgov/` (hash no nome, nunca sobrescrito) e um manifesto em `data/manifestos/`;
  a página sempre lê a fotografia atual e mostra o histórico de atualizações. Nada é consultado na
  rede ao abrir a página.
- **Atualização incremental, com prévia.** O botão "Consultar agora" reconsulta o detalhe (termos e
  NEs) só de vigentes, a iniciar, novos e alterados; os demais reaproveitam a fotografia anterior
  (ou "atualização completa" reconsulta todos). A prévia mostra o delta (contratos, termos, vigência,
  valor global, NEs); remoção de contrato, termo ou NE exige "Estou ciente da remoção". A gravação é
  tudo ou nada e uma falha de API mantém a fotografia anterior.
- **Vigência calculada pelas datas.** A `situacao` da API não é confiável (muitos "Ativo" já vencidos),
  então a situação (vigente, a iniciar, encerrado, inativo) sai das datas, com a data de referência
  de hoje.
- **Complementos manuais.** O valor mensal (a parcela da API não é confiável, e nenhuma derivação é
  presumida) e as observações são digitados no detalhe e gravados à parte em
  `data/contratos/complementos.json`; a atualização nunca os altera, e o complemento de contrato
  ausente da API é preservado. Nulo, zero e negativo são sempre distintos; códigos e CNPJ/CPF ficam
  como texto, com zeros iniciais.
- **Fixture congelada.** Os testes leem `tests/fixtures/contratosgov_2026-10-08.json` (CPFs de
  pessoa física anonimizados), nunca de `data/`; ela não é sobrescrita automaticamente — o
  procedimento para atualizá-la deliberadamente está em `docs/contratosgov.md`.

### Emendas Parlamentares

O relatório **Emendas — Acompanhamento** possui leitor específico em
`src/tesouro_emendas_acompanhamento.py`. Ele preserva as mesclagens reais,
códigos como texto e a distinção entre nulo, zero e negativo. A granularidade
é exercício × emenda × PTRES × GND; uma emenda pode possuir vários PTRES.

`src/emendas_parlamentares.py` cruza o cadastro com a Execução Anual por
`(exercício, RP, PTRES)`. Exercícios anteriores a 2026 permanecem estáticos;
de 2026 em diante, Empenhado, Liquidado e Pago vêm da Execução quando há
vínculo. Execução sem emenda identificada e PTRES sem execução são devolvidos
como lacunas explícitas.

A página **Emendas Parlamentares** usa a carga histórica inicial recebida,
sem dados fictícios. A importação versionada em `src/importacao_emendas.py`
compõe as extrações por exercício: a carga inicial conserva todo o histórico,
enquanto uploads posteriores são aceitos somente com exercícios a partir de
2026. Assim, uma atualização que traga apenas 2026 substitui somente 2026 e
mantém 2016–2025 intactos. Cada bruto recebe nome com hash e nunca sobrescreve
outro upload. O painel também permite cadastro manual de emendas 2026+ com
múltiplos PTRES e preserva esses registros em `data/emendas/`. Na fila de
pendências, a execução RP6/RP7/RP8 sem emenda pode ser vinculada a uma emenda
existente ou a uma nova emenda. Esses vínculos também são limitados a 2026+ e
usam um log de eventos em `data/emendas/vinculos/`: desfazer acrescenta um
novo evento, sem apagar o original. Se um relatório posterior passar a trazer
o mesmo `(exercício, RP, PTRES)`, o dado oficial absorve o vínculo manual sem
duplicar a execução; conflitos com outra emenda permanecem explícitos.

**Decisão de dotação.** Quando o valor do relatório diverge da Dotação Anual do
PTRES, a divergência pode ser resolvida na própria página: adotar a Dotação
Anual, manter o valor do relatório ou informar outro valor, sempre com
justificativa (mín. 10 caracteres) e responsável. A decisão é um evento
imutável em `data/emendas/ajustes_dotacao/` (desfazer acrescenta novo evento);
o valor original do relatório nunca é alterado. Se o relatório mudar depois, a
decisão fica "obsoleta" e a divergência volta a pendente. "Adotar" é bloqueada
quando o PTRES tem mais de uma emenda.

**Acompanhamento por emenda.** Cada emenda (de qualquer exercício) aceita
status de tramitação com data, observação e responsável (lista sugerida +
"Outro"), além de objeto e destinatário manuais, em
`data/emendas/acompanhamento/` (eventos imutáveis; status registrado por
engano é cancelado com motivo, não apagado). A lista de status é uma proposta
a validar com a área; não há ordem imposta entre status e "responsável" é
texto livre.

**Visual.** Registro compacto (uma linha por emenda, detalhe na própria linha),
exercício 2026+ por padrão, filtro/coluna de Tramitação; vermelho só para
problema real.

O contrato completo está em `docs/base_emendas_acompanhamento.md`.

### Dotação Orçamentária

A página **Dotação Orçamentária** lê `Manifesto.atual()` de
`src/importacao_dotacao.py` (não `st.session_state`). Ela mostra:

- filtros por Ano de lançamento, Ação Governo, PTRES, Plano Orçamentário,
  Grupo de Despesa, Fonte de Recursos Detalhada, IDUSO e Resultado Primário;
- cartões com os quatro indicadores conhecidos (Dotação Inicial,
  Suplementar, Atualizada, Cancelada/Remanejada), cada um somado
  isoladamente, sem identidade algébrica presumida entre eles;
- um gráfico interativo (Plotly) de evolução por ano — curva suave
  preenchida, com seletor para trocar o indicador exibido; o exercício em
  andamento (derivado da data de extração do manifesto) aparece com
  marcador diferenciado e "⏳" no rótulo;
- a seção "Reimportar base", mesmo componente (`src/ui_reimportacao.py`) e
  mesma política de confirmação que a Execução Anual usa.

Não há tabela bruta linha a linha nesta página; a granularidade de origem
(arquivo/aba/linha/coluna) continua preservada na base normalizada, só não
é exposta diretamente na interface.

### Painel por Ação de Governo

A página **Painel por Ação de Governo** também lê o manifesto atual da
Dotação Anual. Apresenta um cartão por Ação de Governo, com as subdivisões
(combinação de Plano Orçamentário, Fonte, Grupo de Despesa, Resultado
Primário, IDUSO e PTRES) em uma tabela compacta dentro do cartão, ordenadas
pela Dotação Atualizada. Os quatro indicadores conhecidos aparecem nas
colunas da tabela e nos totais de rodapé de cada cartão, todos somados
isoladamente. Valor nulo (célula ausente na origem) aparece como "—"; valor
zero aparece como `0` — os dois estados nunca são confundidos. O seletor de
Ano marca o exercício em andamento com "⏳".

### Resultado Orçamentário

A página **Resultado Orçamentário** (menu, logo depois de "Limite de Empenho") responde se a dotação
das células orçamentárias escolhidas pelo usuário **cobre** o que ainda falta empenhar no exercício. Ela
só **lê** as contas existentes (Necessidade, Projeção pela Execução, Limite de Empenho); nada é alterado.
Bases: Dotação Anual, Execução Mensal, Contratos Contínuos e Bolsas e Auxílios. Despesas de Pessoal fica
fora por enquanto.

**Fórmula (bolsão).** A soma das células marcadas é confrontada com a soma das despesas; não há
confronto célula a célula:

```text
Resultado = Dotação Atualizada (células) − Empenhado nas células (Execução Mensal) − Necessidade de empenho
```

O sinal dá o rótulo: positivo é **Superávit**, negativo é **Déficit**.

**Célula orçamentária.** Mesma granularidade do Limite de Empenho, com a Fonte de Recursos Detalhada
acrescentada: Iduso, Resultado Primário, Ação de Governo, PTRES, Plano Orçamentário, Grupo de Despesa e
Fonte Detalhada (7 códigos). Os códigos são texto, com zeros à esquerda preservados. A Fonte Detalhada é
`fonte_recursos_detalhada_codigo` na Dotação Anual e `fonte_recursos_detalhada_cod` na Execução Mensal
(mesmo formato de 10 dígitos); por isso `valor_empenhado_por_bloco` passou a carregar essa dimensão
(mudança aditiva, nenhum valor muda).

**Empenhado em cinco linhas.** O empenhado das células marcadas vem da Execução Mensal, por célula, e é
dividido por origem, cada NE contada uma única vez: **Contratos Contínuos** (NE no cadastro de contratos),
**Bolsas e Auxílios** (NE no cadastro de bolsas) e, para o resto, pelo elemento de despesa (pedido de
08/10/2026): **Despesas de Exercícios Anteriores (elemento 92)**, **Material de Consumo (elemento 30)** e
**Outros empenhos** (os demais elementos). Contrato e Bolsa têm prioridade sobre o elemento; uma NE com mais
de um elemento se divide entre as linhas pelo valor de cada elemento. Se a NE está nos dois
cadastros, fica em Contratos e gera o aviso "NE em Contratos e em Bolsas — conferir". Cada linha expande em
uma tabela por NE. A **conferência** `soma das linhas = Empenhado total das células` aparece
sempre, e a diferença é exibida quando a diferença é de R$ 0,01 ou mais. NE de contrato ou bolsa em célula não marcada não
entra no empenhado (a necessidade dela continua entrando).

**Necessidade de empenho.** Contratos e Bolsas usam a **projeção pela execução**
(`necessidade_execucao` de `src/relatorio_projecao_execucao.py`), somando **todas** as NEs do relatório,
mesmo as de células não marcadas, porque no bolsão a necessidade precisa ser coberta pelos recursos
escolhidos. A projeção é **sem contrato antecessor**: na página de Contratos o antecessor é escolhido a cada
emissão e não é gravado, então aqui uma NE sem histórico tem fator 1 (valor mensal cheio). A diferença
aparece em uma nota na página. Se `data/raw/Liquidação por Competência.xlsx` não existir, a projeção não
pode ser calculada: a necessidade de Contratos e Bolsas fica **indisponível** (não zero) e o resultado é
marcado como incompleto.
Se o exercício não tem arquivo de cadastro de Contratos/Bolsas (`anos_disponiveis()`), a necessidade dessa
base aparece como indisponível e o resultado fica incompleto: arquivo ausente não é tratado como lista
vazia (decisão 08/10/2026).
Item sem valor mensal cadastrado (custo nulo nos 12 meses, como em uma bolsa sem valor): o relatório
Projeção pela Execução mostra a necessidade dessa NE como "—" (não 0), fora dos totais e com aviso, e aqui a
necessidade da base fica indisponível, com o resultado incompleto (08/10/2026). Em Contratos Contínuos a
despesa mensal nula ainda vira 0 antes do relatório (soma dos itens em `necessidade_por_ne`), então esse
caso ainda não é sinalizado para contratos.

**Contratos e bolsas sem NE** ficam **fora da conta** e aparecem só nos avisos (quantidade e valor
contratual, como informação). Entram sozinhos quando a NE for incluída no cadastro ou o status do contrato
mudar. Exceção (08/10/2026): **contrato sem NE com status ATIVO entra** na necessidade de Contratos pela
necessidade contratual (Resumo Consolidado), com aviso, e aparece no detalhe como "sem NE (contrato
ativo)". Status ausente não conta como ativo; bolsa sem NE continua fora.

Na seção de células, os grupos de cada Ação começam **recolhidos** ("Ver células"; abrem sozinhos só durante
uma busca), e a opção **Mostrar só as selecionadas** guarda a última escolha em
`data/resultado_orcamentario/preferencias.json`, valendo depois de atualizar a página.

**Outras despesas previstas.** Cadastro manual (incluir, editar, excluir) para despesas que não são de
Contratos nem de Bolsas, com **um valor a empenhar por despesa**, sem distribuição mensal. O valor é
obrigatório e maior que zero; a célula informada é só informativa e não muda o cálculo.

**Persistência.** Aprovada em 08/10/2026: arquivos JSON por exercício em
`data/resultado_orcamentario/<exercício>/` (`celulas.json` e `despesas_manuais.json`), fora do git
(`.gitignore`, com `.gitkeep`), gravados de forma atômica. A seleção de células e as despesas sobrevivem a
atualizar a página e a reiniciar o app. Uma célula gravada que sumiu da Dotação (por exemplo, após
reimportação) é mantida no arquivo e avisada como "célula selecionada ausente da base". Arquivo ausente
equivale a nada marcado; arquivo corrompido gera erro visível e a página não grava por cima.

**Nulo não é zero.** Célula marcada sem Dotação Atualizada aparece como "—" e com aviso; não vira zero na
soma e o resultado é marcado como **incompleto**. O mesmo vale para empenhado nulo em célula marcada.
Dotação zero ou negativa e empenhado negativo (estorno líquido) entram como estão.

**Avisos e datas.** A página lista contratos e bolsas sem NE, NE compartilhada, NE nos dois cadastros,
célula ausente, célula sem dotação, diferença na conferência e as datas de extração da Dotação e da
Execução Mensal, que são independentes.

**Código.** A regra pura está em `src/resultado_orcamentario.py`; a persistência em
`src/resultado_orcamentario_cadastro.py`; a página em `app_pages/resultado_orcamentario.py`. A montagem
dos relatórios de projeção de Contratos e Bolsas vive agora em `src/resultado_orcamentario_fontes.py`,
compartilhada pelas páginas de Contratos Contínuos, de Bolsas e Auxílios e pelo Resultado Orçamentário,
sem mudar o resultado delas. A especificação completa está em
`docs/superpowers/specs/2026-10-08-resultado-orcamentario-design.md`.

### Despesas de Pessoal

A página **Despesas de Pessoal** usa a estrutura do HTML
`design_handoff_streamlit/acompanhamento-pessoal.dc.html`: cabeçalho com data-base,
quatro indicadores, faixa de situação, tabela única de rubricas com grupos
expandidos na própria tabela e tabela de saldos mensais. A primeira coluna fica
fixa durante a rolagem horizontal. Os valores são das bases locais, não do exemplo
de design. O componente usa HTML/CSS/JavaScript local, sem dependência do runtime
externo do arquivo de referência.

Clique no nome de um grupo para recolher ou expandir suas rubricas; na data-base
para escolher o mês e o exercício da dotação; e em um valor projetado de rubrica
para editá-lo. As edições ficam em memória, na sessão e na referência escolhida,
e podem ser restauradas pelo rodapé. Meses executados permanecem protegidos.

A fonte do realizado é a Liquidada da Execução Mensal. As regras existentes
em `src/despesas_pessoal.py` alimentam os meses futuros. Execução Anual, Dotação
Anual e Execução Mensal são lidas pelos seus manifestos (importação versionada,
`src/importacao_execucao_mensal.py`). As datas das extrações são independentes
e ficam informadas no rodapé.

A página tem três abas. **Acompanhamento** é o painel acima. **Fórmulas de
projeção** descreve cada fórmula e deixa editáveis os seus números: multiplicador
por natureza de despesa, multiplicadores por grupo de sentenças e indenizações,
multiplicador de rubrica sem regra em 2004/212B, meses e fração do 13º, repetição
de novembro em dezembro no Ativo e critério de mês fechado. Os campos começam nas
regras confirmadas e valem só para a sessão. O painel recalcula na hora e avisa
que as fórmulas foram ajustadas; a procedência lista cada ajuste. Um valor
inválido (por exemplo, multiplicador abaixo de 12) aparece como erro, e o painel
volta às fórmulas padrão. **Exercícios anteriores** mostra a execução de um
exercício passado, sem projeção: Dotação Atualizada, Empenhada, Liquidada e Paga
por grupo e por natureza, pela Execução Anual. Quando a Execução Mensal cobre o
exercício, mostra também a Liquidada mês a mês e a conciliação com o total anual.
Mostra ainda a **projeção reconstruída × executado**: as fórmulas em uso (padrão ou
ajustadas na sessão) são aplicadas a partir de um mês de referência do exercício
passado. O padrão é o mesmo mês da data-base do painel. O resultado é comparado,
por grupo e mês a mês, com a Liquidada real. A diferença é executado − projetado.
Os totais só somam os meses que têm os dois lados. Ajustes manuais de meses do
painel não entram nessa comparação. A chave **Comparar todos os meses de partida**
monta uma tabela com a Diferença % de cada mês de partida (janeiro a novembro),
por grupo. Um sinal que se repete em várias linhas indica desvio sistemático; um
valor isolado muito alto indica mês de partida atípico. O cálculo leva alguns
segundos e só roda com a chave ligada. O quadro **Outros Benefícios por Plano
Orçamentário** abre a mesma comparação por (Ação, PO), ordenada pela maior
diferença absoluta. A soma dos PO fecha com a linha do grupo; se não fechar, a
página avisa. A Diferença % aparece como “—” quando o projetado é zero ou negativo.

Dotação por rubrica aparece como “—”, pois a base não oferece essa dimensão.
Benefício Especial e Precatórios preservam os lugares previstos no layout, com
mapeamento pendente e valores ausentes, sem inventar zeros ou reclassificar dados.
Outros Benefícios conserva as ações 2004/212B. A execução histórica exibida nas
rubricas é comparada ao total da base anual no mesmo escopo, com diferença explícita.
13º e férias aparecem sem Base PLOA individual, conforme o layout; o grupo conserva
a soma do mês de referência. Os cálculos de férias e 13º existentes não foram
revisados nesta mudança de apresentação.

### TEDs (Termos de Execução Descentralizada)

O módulo de TEDs é a única base do projeto com persistência própria: em vez do padrão
"manifesto versionado + recarregar do Excel", grava num banco SQLite isolado
(`data/teds/teds.db`), porque precisa cruzar cinco fontes (TED, DOC NC, DOC PF, DOC NE e a
execução no Tesouro Gerencial) e manter uma fila de decisões humanas (vínculo de NE
pendente, alertas com justificativa e histórico) que não cabe em "recarregar tudo a cada
acesso". Valores monetários trafegam como `Decimal` em todo o módulo (nunca `float`) e são
persistidos como texto decimal exato — decisão deliberada, diferente das demais bases, porque
o módulo compara e soma valores entre fontes distintas onde arredondamento acumulado poderia
mascarar ou criar divergências.

A importação é idempotente em duas camadas: arquivo idêntico (mesmo hash SHA-256 já
importado) é um no-op; linha a linha, reimportar um arquivo que traga uma linha já conhecida
atualiza aquela linha em vez de duplicá-la. `linha_origem` preserva a linha original da
planilha para auditoria, e o histórico de lotes de importação nunca é sobrescrito.

O grupo "TEDs" na barra lateral tem 7 páginas: Visão geral, Lista (com detalhe em
drill-down), Conciliação (SIMEC × Tesouro Gerencial), Células NC × NE, Central de Alertas,
Importações (assistente de 4 passos: Arquivo → Mapeamento → Validação → Confirmação) e
Configurações. Dezenove
alertas estão implementados: empenho associado a mais de um TED; NC sem UG emitente (achado
real da extração do SIMEC, não do briefing original — a coluna vem vazia em cerca de 28% das
NCs; um alerta de gravidade baixa por TED, com a lista das NCs); e três de conciliação SIMEC (NC líquida
e PF líquido dos documentos importados contra os totais consolidados, e PF líquido maior que a NC
líquida; comparados só na janela de anos que o consolidado cobre, sem alerta quando o TED não tem
documento do tipo no extrato ou quando a vigência começa antes do consolidado, e sem decidir por
documentos sem data) e seis de validação cadastral e de
vigência (vigência invertida, SIAFI em mais de um TED, TED sem UG descentralizadora, documento
fora da vigência, TED vencido ainda em execução e TED em execução sem movimentação — esta considera
também liquidação e pagamento no Tesouro) e três de
execução por NE no Tesouro Gerencial (liquidado maior que empenhado, pago maior que liquidado e
valor da NE no SIMEC diferente do empenhado do Tesouro, sempre pelo acumulado da NE) e um de importação
(o total do rodapé do relatório do SIMEC deve bater com a soma das linhas importadas; no DOC NC e no DOC PF
o rodapé é absoluto, então compara-se a soma bruta) e um de TED sem
código SIAFI na Execução Anual (a linha não é importada e o TED fica fora dos totais até o código existir), e dois de execução do TED (crédito sem NE vinculada e repasse sem pago no Tesouro, ambos com prazo
de 90 dias) e um de célula orçamentária (a célula da NE — PTRES, fonte detalhada, natureza e Plano Interno — não consta
entre as células das NCs do mesmo TED e exercício, lidas dos relatórios de NC do Tesouro Gerencial; é alerta para
conferência, nunca conclusão de uso indevido). Os demais alertas previstos no
briefing original ficam para uma fase seguinte, fora do escopo já aprovado.

Revisão de 08/10/2026: a reavaliação de alertas fecha sozinha, com justificativa "Regra revisada em
08/10/2026…" e auditoria, os alertas abertos dos cinco tipos de regra revista que as regras atuais não
sustentam mais. Na página Conciliação, a seção "Conferir com a planilha de controle" lê a planilha
`CONTROLE DESC.CREDITOS ATUALIZADA.xlsx` enviada pelo usuário **em memória** (nunca é gravada nem alimenta
as regras), confere as NCs do SIMEC com ela, oferece o resultado em Excel e permite resolver alertas
relacionados com justificativa pré-preenchida (só com o clique do usuário). Ver `docs/base_teds.md` §9.1–9.2.

A fonte do Tesouro Gerencial é a mesma extração de Execução Mensal já usada por outra página
do projeto (`src/tesouro_execucao_mensal.py`) — não uma extração separada. Na página
Importações, o botão "Sincronizar com a Execução Mensal" espelha essa extração em `execucao_tg`
(uma linha por NE × mês de **lançamento**, não de competência; lote auditável, idempotente pelo
sha256 da extração, nunca apaga linhas). Antes da primeira sincronização, os indicadores de
Liquidado/Pago e a conciliação contra o Tesouro Gerencial mostram "Sem dado" em vez de um valor
inventado. Competência real (Documento Hábil × mês de referência) não é necessária no módulo de TEDs
(decisão de 24/09/2026).

Um lote de importação pode ser revertido na página Importações: as linhas que ele criou saem dos
totais e as que sobrescreveu voltam ao valor anterior (o gatilho de histórico de versões guarda a
versão antiga), nada é apagado, e a ação é auditada. Só lotes importados depois do histórico
existir podem ser revertidos com segurança.

Cada importação só dispara os alertas que existiam quando rodou; regras criadas depois não enxergam
dados antigos. O botão "Reavaliar alertas" (Importações) roda todas as verificações sobre os dados já
importados, sem reimportar: só cria alertas ausentes (mesma deduplicação por tipo + documento), não fecha
nem altera os existentes nem os dados importados, e a execução fica na trilha de auditoria. Não reavalia
NE em mais de um TED (recalcula `status_validacao`) nem TED sem SIAFI (depende das linhas rejeitadas de uma
leitura).

**TEDs de outros órgãos (TransfereGov).** Os TEDs do MEC tramitam no SIMEC; os de outros órgãos (MDA, INCRA,
MPA, MDS…) tramitam no TransfereGov e entram pela API de dados abertos
(`https://api.transferegov.gestao.gov.br/ted/`, `src/teds_transferegov.py`), com o botão "Sincronizar com o
TransfereGov" em Importações. É uma origem separada, em tabelas próprias (`tg_*`): não entra nos totais, na
conciliação nem nos alertas dos TEDs do SIMEC. Na Lista, o seletor "Origem" mostra esses TEDs (planos de ação
em que a UFRPE é executora, com termo, NCs e seus eventos, PFs e suas linhas TRF); a Visão geral traz só as
quantidades. **Nenhum total de NC/PF é calculado:** o significado dos códigos de evento da NC (300300, 300302…)
e da situação contábil da TRF (TRF003, TRF004…) não foi confirmado, então os valores aparecem sem sinal, ao lado
do código. As NEs da Execução Mensal com a mesma célula (exercício, PTRES, fonte, natureza e PI) de um evento de
NC aparecem como indício para conferência, nunca como vínculo. A sincronização é um lote como os demais
(idempotente pelo SHA-256 da resposta, reversível, JSON bruto guardado em `tg_extracao_bruta`). Validado em
08/10/2026 com a API real: 53 planos, 93 NCs, 104 eventos, 80 PFs, 84 linhas TRF e 44 NEs com célula
coincidente, nenhuma delas já vinculada a TED do SIMEC.

O contrato completo (tabelas, chaves e decisões de projeto) está em
`docs/base_teds.md`.

### Diário Oficial (DOU)

Página que baixa o Diário Oficial da União pelo INLABS (Imprensa Nacional) e
lista as matérias que citam a UFRPE (`src/dou_inlabs.py`). O botão "Baixar
atualizações do DOU" consulta só os dias que faltam — do dia seguinte ao último
consultado até hoje (na primeira vez, os últimos 7 dias; no máximo 30 por
clique). Dia sem edição fica registrado como consultado, sem erro.

A busca ignora acentos e maiúsculas e tem dois grupos de termos: **Termos de
busca** (a matéria cita algum deles; padrão: nome, sigla, UG 153165 e UO 26248)
e **Refinar** (opcional: também precisa citar algum destes — ex.: "pregão" traz
só os pregões da UFRPE, não os do país inteiro). As duas listas são salvas em
`data/dou/termos.json` a cada mudança (fora do git, incluídas no backup) e
"Restaurar termos padrão" volta aos padrões. Um termo novo alcança também os
dias já baixados, sem novo download. Período por atalhos (7 dias, 30 dias, mês
atual, tudo ou datas livres) e seção. O resultado traz um resumo (dias com
ocorrência, divisão por seção, termo mais frequente) e as matérias em cartões
agrupados por dia — com os termos destacados no trecho que casou e link para a
página no DOU —, ou em tabela; ordenação por data e exportação em CSV do recorte.

Exige conta pessoal no INLABS, com credenciais só em variáveis de ambiente —
a página não pede nem guarda senha. Os ZIPs ficam intactos em
`data/raw/dou/<data>/` com manifesto (sha256), sem banco de dados. Também há
uso por linha de comando (`python -m src.dou_inlabs AAAA-MM-DD`). Detalhes em
`docs/dou_inlabs.md`.

### Limitações atuais

- não há soma, reconciliação ou identidade rígida entre itens de dotação;
- o acompanhamento de pessoal compara sua projeção com a Dotação Atualizada;
  isso não constitui uma reconciliação entre extrações de mesma data.
  A integração geral entre bases continua limitada pela ambiguidade temporal (granularidade mês x
  ano nas exportações mensais do Tesouro Gerencial, hoje fora do projeto;
  ausência de um "as of" comum entre extrações de bases diferentes); ver
  `docs/base_execucao_anual.md`;
- cada base usa manifesto versionado (`data/manifestos/`), sem banco de dados
  nem view unificada entre elas — exceto TEDs, que tem persistência própria
  em SQLite (`data/teds/teds.db`) por precisar cruzar cinco fontes e manter
  uma fila de decisões humanas; ver `docs/base_teds.md`.

## Visual e tema

A interface usa exclusivamente uma área de trabalho clara com navegação lateral
azul persistente, inspirada em painéis administrativos institucionais. Não há
alternância para modo escuro. As cores, tipografia e
espaçamentos ficam centralizados em `src/design_tokens.py`; `src/ui_theme.py`
consome esses tokens para o CSS global e os helpers reutilizáveis
(`render_page_header`, `render_alert`, `render_metric_grid`,
`format_brl_compact`, `format_brl_full`). `.streamlit/config.toml` reflete os
mesmos tokens de cor de fundo, superfície e texto.

## Preparação do ambiente

Requer Python 3.10 ou superior.

No Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Execução

```powershell
streamlit run app.py
```

### Desempenho na leitura das bases (07/10/2026)

- **Leitor de Excel rápido** (`src/leitura_excel.py`): os leitores que passam por `pandas.read_excel`
  (Execução Mensal e Anual, Liquidação por Competência, Contratos Contínuos, Bolsas, Vigência e Pagamentos)
  usam o `python-calamine` quando instalado — de 3 a 6 vezes mais rápido que o openpyxl nas planilhas reais.
  Sem ele, voltam ao motor padrão do pandas. A paridade é testada sobre as fixtures
  (`tests/test_leitura_excel.py`); a única diferença conhecida é a favor do dado: célula marcada como data
  com número fora do intervalo de datas é descartada pelo openpyxl e preservada pelo calamine na coluna
  bruta. Dotação Anual, Emendas e Captação seguem no openpyxl (leem célula a célula).
- **Cache das bases lidas** (`src/cache_bases.py`, ligado em `app.py`): o DataFrame devolvido por esses
  leitores fica gravado em Parquet em `data/processed/cache_bases/` (fora do Git) e é reaproveitado
  enquanto o conteúdo do arquivo, o caminho dele e o código do leitor não mudarem (a chave inclui o
  SHA-256 dos bytes e o caminho — arquivos de mesmo conteúdo e nomes diferentes não compartilham a cópia,
  porque os leitores gravam o nome em `arquivo_origem`). Só é gravado o que volta idêntico na releitura; qualquer falha do cache cai na leitura normal, e
  a planilha original nunca é alterada. Vigência e Pagamentos ficam sem cache (têm colunas de tipo misto
  que o Parquet não devolveria idênticas). Para limpar, basta apagar a pasta. Nos testes o cache fica
  desligado (`tests/conftest.py` define `BUDGETLAB_CACHE_BASES=desligado`): a suíte sempre lê as planilhas
  e não toca na pasta real.
- **Memória das páginas com bases grandes**: a cada interação o `st.cache_data` devolve cópias das bases
  (DataFrames inteiros), que ficavam presas em referências circulares — na Consulta de Empenhos a sessão
  subia de ~1,5 GB para ~7 GB em 30 interações; em Empenhos com Execução Retardada, Limite de Empenho e
  Despesas de Pessoal, de ~1,5 GB para 5–8 GB em 20. Essas quatro páginas rodam `gc.collect()` no início e
  no fim de cada execução e ficam estáveis abaixo de 2 GB. As demais páginas medidas (07/10/2026) não
  acumulam de forma relevante. Os testes de página fazem o mesmo ao fim de cada teste (`tests/conftest.py`).

### Atalho de inicialização com atualização automática (um único computador)

`Iniciar BudgetLab.bat`, na raiz do projeto, abre o sistema com dois cliques
(chama `scripts/atualizar_e_iniciar.ps1`):

1. atualiza o código pelo GitHub (`git pull --ff-only` no branch atual);
2. cria o `.venv` na primeira execução e reinstala as dependências somente quando o
   `requirements.txt` mudou;
3. inicia o sistema e abre o navegador em `http://localhost:8501`. Se ele já estiver
   aberto, apenas abre o navegador. A janela do atalho precisa ficar aberta, porque
   fechá-la encerra o sistema.

Sem internet, ou quando o Git recusa a atualização (alterações locais conflitantes,
histórico divergente), o atalho mostra o motivo e abre a versão já instalada. Ele nunca
descarta alterações: não usa `reset`, `stash` nem `checkout`. Os dados locais de
`data/` que não são versionados (cadastros, bancos SQLite, planilhas importadas) não são
tocados. A exceção é `data/manifestos/`, que é versionado: uma importação local
altera esses arquivos e pode fazer o Git recusar a próxima atualização até que as
alterações sejam enviadas (commit/push) ou resolvidas manualmente.

Para criar o atalho na área de trabalho: clique com o botão direito em
`Iniciar BudgetLab.bat` > *Enviar para* > *Área de trabalho (criar atalho)*.

O atalho foi pensado para **um único usuário**. Os dados ficam no computador onde o
sistema roda: cópias em outras máquinas não compartilham cadastros nem importações.
Requisitos na primeira execução: Python 3.10+, Git e internet.

### Migração dos cadastros nativos

Bolsas e Auxílios e Contratos Contínuos usam cadastros JSON locais, separados das planilhas
de trabalho originais. O comando oficial executa por padrão somente uma simulação: lê as
duas planilhas, monta os cadastros em diretórios temporários, confere contagens, totais e
hashes e não grava em `data/bolsas_auxilios/` nem em `data/contratos_continuos/`.

```powershell
python -m scripts.migrar_cadastros_nativos
```

Depois de revisar a saída, use `--aplicar` para promover os dois cadastros validados:

```powershell
python -m scripts.migrar_cadastros_nativos --aplicar
```

O comando nunca sobrescreve um exercício existente. Caminhos e exercício podem ser informados
explicitamente com `--bolsas`, `--contratos`, `--ano`, `--diretorio-bolsas` e
`--diretorio-contratos`. As planilhas de origem são somente lidas e seus hashes são conferidos
novamente antes de qualquer gravação.

### Backup dos dados (Administração → Backup dos dados)

`data/raw/`, os cadastros nativos e os bancos SQLite não vão para o git. Para levar o sistema a
outra máquina, a página gera um `.zip` com as pastas escolhidas de `data/` e restaura um `.zip`
no destino (`src/backup_dados.py`).

- O `.zip` traz um `MANIFESTO_BACKUP.json` com tamanho e SHA-256 de cada arquivo. Exportar só lê
  `data/`; bancos SQLite são copiados pela API de backup do SQLite.
- Segredos: o `token.json` do Google Agenda nunca entra (fica fora de `data/`; na outra máquina,
  reconecte). `credentials.json` só entra com a caixa marcada. `.env` e
  `.streamlit/secrets.toml` não são incluídos — copie à mão se existirem.
- Senha opcional (mín. 8 caracteres): cifra o arquivo inteiro com AES-256-GCM (chave por scrypt) e
  gera `.zip.enc`; conteúdo, nomes e manifesto ficam ilegíveis. Senha errada ou arquivo adulterado
  são recusados sem gravar nada. A senha não é recuperável. Sem senha, o `.zip` é comum e legível
  (a página avisa quando o `credentials.json` vai incluído sem senha). Dependência: `cryptography`.
- Restaurar confere o pacote inteiro antes de gravar; pacote adulterado, com caminho fora das
  pastas conhecidas ou fora do manifesto é recusado sem gravar nada.
- Arquivo existente e diferente nunca é sobrescrito em silêncio: a prévia lista as diferenças e,
  ao substituir, a cópia atual vai para `data/_backup_restauracao/<carimbo>/`. A gravação é
  tudo-ou-nada.
- Limite de upload do Streamlit: 200 MB por padrão (`server.maxUploadSize`).

## Estrutura do projeto

```text
ufrpe-budgetlab/
|-- app.py                          # Ponto de entrada da interface Streamlit
|-- app_pages/                      # Páginas da interface
|   |-- home.py
|   |-- dotacao_orcamentaria.py     # Fonte: Dotação Anual; inclui reimportação
|   |-- painel_acoes.py             # Cartões por Ação de Governo (Dotação Anual)
|   `-- execucao_orcamentaria.py    # Fonte: Execução Anual (BI PROPLAD); inclui reimportação
|-- design_handoff_streamlit/       # Material de referência do handoff visual
|-- requirements.txt                # Dependências Python do projeto
|-- README.md                       # Documentação e instruções de uso
|-- src/
|   |-- design_tokens.py            # Tokens de cor/tipografia/espaçamento
|   |-- dotacao_anual_analysis.py   # Filtros e agregações da Dotação Anual
|   |-- dou_inlabs.py               # Download e filtro do DOU (INLABS)
|   |-- execucao_anual.py           # Leitura, validação e agregação da Execução Anual (BI PROPLAD)
|   |-- importacao_dotacao.py       # Especificação da Dotação Anual sobre o núcleo genérico
|   |-- importacao_emendas.py       # Carga histórica e atualizações 2026+ de Emendas
|   |-- importacao_execucao.py      # Especificação da Execução Anual sobre o núcleo genérico
|   |-- importacao_versionada.py    # Núcleo genérico: manifesto, delta, política de confirmação
|   |-- tesouro_dotacao_anual.py    # Reconhecimento e normalização da Dotação Anual
|   |-- tesouro_dotacao_anual_validation.py
|   |-- tesouro_dotacao_anual_workbook.py
|   |-- ui_reimportacao.py          # Componente "Reimportar base", reutilizado pelas duas bases
|   `-- ui_theme.py                 # Componentes visuais reutilizáveis
|-- data/
|   |-- manifestos/                 # Manifestos versionados de cada base (hash, extração, totais)
|   |-- processed/                  # Dados tratados e padronizados
|   `-- raw/                        # Dados originais, sem transformação
`-- tests/
```

Os arquivos brutos em `data/raw/` e `data/processed/` não são versionados
(`.gitkeep` mantém só a estrutura das pastas vazias); os manifestos em
`data/manifestos/` são pequenos e versionados normalmente — são o registro
de procedência de cada base, não dado bruto.

## Testes

```powershell
python -m unittest discover -s tests -v
```

Forma preferencial — com as ferramentas de desenvolvimento
(`python -m pip install -r requirements-dev.txt`), que agilizam a suíte; o `unittest` acima fica só
como alternativa quando elas não estiverem disponíveis:

```powershell
python -m pytest tests -n auto        # suíte completa em paralelo (pytest-xdist, um processo por núcleo)
python -m pytest tests --testmon      # só os testes afetados pelo código alterado desde a última rodada
```

O `--testmon` (pytest-testmon) serve para as rodadas intermediárias e pode ser combinado com `-n auto`.
Ele acompanha o código Python, não as planilhas: mudou uma fixture ou base, rode a suíte completa. A
primeira rodada com `--testmon` executa tudo (monta o mapa em `.testmondata`, fora do Git). Antes de
concluir uma tarefa, rode a suíte completa com `-n auto`.

## Evolução prevista

A arquitetura deverá acomodar gradualmente:

- projeção de insuficiência orçamentária;
- acompanhamento de contratos e bolsas;
- DEA;

Esses componentes serão incorporados conforme as regras de negócio forem
definidas, mantendo a interface Streamlit separada do processamento em `src/`.
