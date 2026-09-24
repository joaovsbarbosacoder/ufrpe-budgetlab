# Base de Emendas — Acompanhamento

Contrato do relatório que identifica emendas parlamentares e seus PTRES. A
base alimenta o painel Streamlit, possui importação versionada por exercício e
pode ser complementada por cadastros manuais a partir de 2026.

## 1. Referência analisada

| Item | Valor |
|---|---|
| Arquivo recebido | `2026 - Emendas - Acompanhamento (1) (1).xlsx` |
| Fixture congelada | `tests/fixtures/emendas_acompanhamento_2026-08-28.xlsx` |
| SHA-256 | `5db888d2f8fa413257bd395caff2d14256360f026274970cff90b3a8d1959672` |
| Abas reconhecidas | 1 |
| Linhas físicas de dados | 29 |
| Exercícios | 2016, 2019–2026 |
| Emendas distintas | 25 |
| PTRES distintos | 27 |
| Resultado Primário | RP 6 |

A fixture é deliberadamente estática. Um relatório posterior não deve
sobrescrevê-la: precisa receber outro nome de referência, com totais e
expectativas recalculados e revisados.

## 2. Layout físico

O cabeçalho ocupa três linhas e as dimensões usam mesclagens reais:

| Coluna | Conteúdo normalizado |
|---|---|
| A | Resultado Primário Lei |
| B | PTRES |
| C | Número da emenda |
| D | Autor / rótulo da emenda |
| E | Grupo de Despesa |
| F | Ano de lançamento |
| G | Item 13 — Dotação Atualizada |
| H | Item 23 — Despesas Empenhadas |
| I | Item 25 — Despesas Liquidadas |
| J | Item 28 — Despesas Pagas |

O reconhecimento confere os rótulos, os códigos dos quatro itens, as dez
colunas e as mesclagens de cabeçalho. Mudança de layout reprova a leitura em
vez de tentar adivinhar posições.

As dimensões de uma linha só herdam o valor da célula superior quando a
coordenada pertence a um intervalo mesclado confirmado pelo Excel. Isso é
necessário, por exemplo, nas linhas adicionais de GND dos PTRES `217658` e
`238855`.

## 3. Granularidade e chaves

A linha normalizada representa:

```text
exercício × RP × número da emenda × PTRES × GND
```

A entidade da emenda usa `(exercício, RP, número da emenda)`. O vínculo com a
Execução usa `(exercício, RP, PTRES)`.

Uma emenda pode ter vários PTRES. A referência comprova isso em:

- `201630800008`: PTRES `111760` e `119923`;
- `202632990006`: PTRES `261462` e `269202`.

Para atribuição automática, um mesmo `(exercício, RP, PTRES)` não pode estar
associado a números de emenda diferentes. Essa ambiguidade bloqueia o vínculo
e exige resolução manual; nenhuma divisão de valor é presumida.

## 4. Nulo, zero e negativo

Os valores são preservados como encontrados:

| Medida | Nulos | Zeros | Negativos |
|---|---:|---:|---:|
| Dotação Atualizada | 0 | 4 | 0 |
| Empenhada | 8 | 0 | 0 |
| Liquidada | 19 | 0 | 0 |
| Paga | 20 | 0 | 0 |

Nulo significa ausência de movimento no relatório, não zero. Linhas de
dotação zero continuam relevantes porque preservam associações de emenda,
PTRES e GND.

Valores financeiros não vazios que não possam ser convertidos causam erro
com a coordenada da célula. Fórmulas também são rejeitadas: o relatório deve
conter valores materializados.

## 5. Totais da fixture

| Medida | Total |
|---|---:|
| Dotação Atualizada | R$ 10.525.108,00 |
| Empenhada | R$ 7.962.726,79 |
| Liquidada | R$ 1.800.329,44 |
| Paga | R$ 1.447.991,04 |

Esses totais pertencem somente à fotografia recebida. A coluna de Dotação
Atualizada não é renomeada para "Valor Indicado": não há regra de negócio que
declare os conceitos equivalentes.

## 6. Política temporal

- O relatório inicial pode conter todo o histórico disponível.
- A carga inicial é registrada uma única vez e funciona como âncora histórica.
- Exercícios anteriores a 2026 permanecem estáticos e usam os valores do
  relatório, mesmo que a Execução Anual seja reimportada.
- Atualizações posteriores, por relatório ou cadastro manual, só podem alterar
  exercícios a partir de 2026.
- Um upload que contenha exercício anterior a 2026 é bloqueado por inteiro e
  lista os exercícios protegidos; linhas não são descartadas silenciosamente.
- Um upload válido pode conter somente 2026 ou qualquer conjunto de exercícios
  posteriores. Ele substitui apenas os anos que traz; os exercícios anteriores
  continuam vindo da carga histórica inicial.
- Em 2026 e anos posteriores, Dotação Atualizada permanece no relatório de
  Emendas, enquanto Empenhado, Liquidado e Pago vêm da Execução Anual para
  PTRES vinculados.

## 6.1 Dotação Anual por PTRES

Para exercícios dinâmicos (2026 em diante), `vincular_execucao_emendas(..., dotacao=...)` liga a
Dotação Anual por `(ano, RP, PTRES)` **ao lado** — nunca no lugar — da Dotação Atualizada do
relatório ou do cadastro manual (`agregar_dotacao_por_ptres`). Regras:

1. **Colunas separadas.** `dotacao_atualizada` (relatório/cadastro) permanece intacta;
   `dotacao_anual_ptres` é a da Dotação Anual. Não há regra definida de qual prevalece.
2. **Divergência só sinalizada.** `diferenca_dotacao` e `dotacao_divergente` (diferença
   arredondada em centavos > R$ 0,01) só existem quando os DOIS valores existem. Informativo:
   não bloqueia nem corrige nada.
3. **PTRES compartilhado.** A Dotação Anual é por PTRES, não por emenda; o mesmo
   `(ano, RP, PTRES)` em duas emendas continua barrado (`ErroVinculoEmenda`) — o valor nunca é
   dividido nem atribuído.
4. **Sem correspondência = nulo**, nunca zero (`ptres_com_dotacao_anual` conta os PTRES que
   têm valor). Só o indicador `dotacao_atualizada` é somado (`min_count=1`); os quatro
   indicadores da Dotação nunca se somam entre si.
5. **Exercícios anteriores a 2026** ficam só com o valor do relatório (fotografia estática).

A página lista os PTRES divergentes (`divergencias_dotacao`) num quadro com os dois valores e a
diferença, respeitando os filtros. É informativo: não indica qual valor está correto e não gera
alerta no painel geral (`alertas_gerenciais`).

⚠️ A soma é sobre o PTRES inteiro (todas as fontes e planos orçamentários), não sobre a emenda:
o valor é rotulado "Dotação Anual (por PTRES)" e não deve ser lido como valor da emenda. Linha da
Dotação sem ano, RP ou PTRES interrompe o vínculo com erro explícito, como na Execução.

## 7. Reconciliação com a Execução Anual

`agregar_execucao_por_ptres` soma Empenhado, Liquidado e Pago em todas as
linhas da Execução, com `min_count=1`, por `(ano, RP, PTRES)`. Essa regra
respeita a coexistência de linhas de empenho e linhas de item de execução.

`vincular_execucao_emendas` devolve quatro visões:

1. `emendas`: uma linha por emenda, com valores do relatório, valores da
   Execução e valores efetivos conforme a política temporal;
2. `vinculos`: uma linha por emenda × PTRES, incluindo diferenças para
   reconciliação;
3. `execucao_sem_vinculo`: RP 6/7/8 executado sem emenda identificada;
4. `ptres_sem_execucao`: PTRES cadastrado a partir de 2026 ainda sem execução.

Na fotografia de 28/08/2026, o PTRES `269202` vincula R$ 1.000.000,00
empenhados à emenda `202632990006`. O PTRES `267239`, com R$ 209.000,00
empenhados, liquidados e pagos, permanece em `execucao_sem_vinculo` até que
uma emenda seja identificada no relatório ou vinculada manualmente via
`registrar_vinculo_manual`/`registrar_nova_emenda_vinculada` (`src/vinculos_emendas.py`)
— o painel atual não expõe essa resolução, só a lista de emendas e o cadastro manual.

### 7.1. Resolução manual da fila

Uma pendência pode ser associada a uma emenda existente do mesmo exercício e
RP ou originar uma nova emenda manual. A operação é aceita somente para 2026+
e revalida no servidor se a chave ainda está na fila; os limites do seletor da
interface não são tratados como validação de negócio.

Cada vínculo possui um identificador próprio e somente um vínculo manual pode
estar ativo para `(exercício, RP, PTRES)`. O desfazimento não edita nem remove
o evento de criação: acrescenta outro evento referenciando o mesmo vínculo.

Na composição com um relatório posterior:

- a mesma chave oficial apontando para a mesma emenda absorve o vínculo manual,
  que continua no histórico e não gera uma segunda linha;
- a mesma chave oficial apontando para outra emenda gera conflito explícito e
  o vínculo manual não é aplicado;
- a ausência da identidade da emenda deixa o vínculo órfão e também impede sua
  aplicação.

## 8. Importação e persistência

`src/importacao_emendas.py` especializa o núcleo de importação versionada do
projeto. A carga inicial e cada atualização possuem manifesto com SHA-256,
data, exercícios, contagens e totais. Arquivos brutos recebem o hash no nome e
ficam em `data/raw/`; uma nova versão nunca sobrescreve a anterior.

O painel usa composição por exercício:

```text
carga inicial: 2016–2026
atualização:          2026
resultado:      2016–2025 da carga inicial + 2026 da atualização
```

Cadastros manuais ficam em `data/emendas/`, um JSON por emenda, e podem conter
múltiplos PTRES. Se uma chave manual já estiver presente em um relatório
oficial, o relatório prevalece para evitar dupla contagem, mas o JSON manual é
mantido e a sobreposição fica disponível em `composicao.sobreposicoes`
(`compor_relatorio_com_cadastros`), mesmo sem exibição própria no painel atual.

Eventos de vínculo ficam em `data/emendas/vinculos/`, um JSON imutável por
ação (`vincular` ou `desfazer`). O estado ativo é reconstruído pela sequência
completa, que é validada antes da composição. Uma emenda criada diretamente a
partir de uma pendência permanece cadastrada como identidade, mas seu PTRES é
aplicado exclusivamente pelo evento; assim, desfazer não exige modificar o
cadastro original.

## 9. API

```python
from src.emendas_parlamentares import (
    compor_relatorio_com_cadastros,
    validar_anos_importaveis,
    vincular_execucao_emendas,
)
from src.importacao_emendas import carregar_atual, importar
from src.vinculos_emendas import (
    carregar_eventos_vinculo,
    compor_relatorio_com_vinculos,
)
from src.tesouro_emendas_acompanhamento import (
    ler_emendas_acompanhamento,
    reconciliar_emendas_acompanhamento,
)

relatorio = ler_emendas_acompanhamento("emendas.xlsx")
resumo = reconciliar_emendas_acompanhamento(relatorio)

# Somente para atualizações posteriores, não para a carga histórica inicial.
validar_anos_importaveis(relatorio)

resultado = vincular_execucao_emendas(relatorio, execucao_anual)
resultado.emendas
resultado.execucao_sem_vinculo

eventos = carregar_eventos_vinculo()
relatorio_com_vinculos = compor_relatorio_com_vinculos(
    relatorio, cadastros_manuais, eventos
).relatorio
```

## 10. Arquivos

| Arquivo | Papel |
|---|---|
| `src/tesouro_emendas_acompanhamento.py` | reconhecimento, leitura e reconciliação do relatório |
| `src/importacao_emendas.py` | carga inicial, manifestos, composição histórica e uploads 2026+ |
| `src/emendas_parlamentares.py` | política temporal e vínculo com a Execução |
| `src/vinculos_emendas.py` | log auditável, reversão e composição dos vínculos manuais |
| `app_pages/emendas_parlamentares.py` | painel (lista de emendas, filtros em cascata) e cadastro manual |
| `tests/test_emendas_parlamentares.py` | invariantes, referência e casos de vínculo |
| `tests/test_vinculos_emendas.py` | criação, reversão, conflito e absorção de vínculos manuais |
| `tests/test_importacao_emendas.py` | carga histórica e composição das atualizações |
| `tests/test_emendas_parlamentares_page.py` | renderização e integração da página |
| `tests/fixtures/emendas_acompanhamento_2026-08-28.xlsx` | referência congelada |
