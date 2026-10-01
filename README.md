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
real da extração do SIMEC, não do briefing original — a coluna vem vazia em cerca de 41% das
linhas); e três de conciliação SIMEC (NC líquida e PF líquido dos documentos importados contra os
totais consolidados, e PF líquido maior que a NC líquida) e seis de validação cadastral e de
vigência (vigência invertida, SIAFI em mais de um TED, TED sem UG descentralizadora, documento
fora da vigência, TED vencido ainda em execução e TED em execução sem movimentação) e três de
execução por NE no Tesouro Gerencial (liquidado maior que empenhado, pago maior que liquidado e
valor da NE no SIMEC diferente do empenhado do Tesouro, sempre pelo acumulado da NE) e um de importação
(o total do rodapé do relatório do SIMEC deve bater com a soma das linhas importadas; no DOC NC e no DOC PF
o rodapé é absoluto, então compara-se a soma bruta) e um de TED sem
código SIAFI na Execução Anual (a linha não é importada e o TED fica fora dos totais até o código existir), e dois de execução do TED (crédito sem NE vinculada e repasse sem pago no Tesouro, ambos com prazo
de 90 dias) e um de célula orçamentária (a célula da NE — PTRES, fonte detalhada, natureza e Plano Interno — não consta
entre as células das NCs do mesmo TED e exercício, lidas dos relatórios de NC do Tesouro Gerencial; é alerta para
conferência, nunca conclusão de uso indevido). Os demais alertas previstos no
briefing original (crédito sem empenho etc.) ficam para uma fase seguinte, fora do
escopo já aprovado.

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

O contrato completo (tabelas, chaves e decisões de projeto) está em
`docs/base_teds.md`.

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

## Evolução prevista

A arquitetura deverá acomodar gradualmente:

- projeção de insuficiência orçamentária;
- acompanhamento de contratos e bolsas;
- DEA;

Esses componentes serão incorporados conforme as regras de negócio forem
definidas, mantendo a interface Streamlit separada do processamento em `src/`.
