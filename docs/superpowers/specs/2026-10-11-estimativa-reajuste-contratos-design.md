# Estimativa de reajuste de Contratos Contínuos — design

Data: 11/10/2026. Aprovado pelo usuário em chat ("Pode seguir", após as decisões abaixo).

## Objetivo

Estimar a despesa adicional que o reajuste anual causará nos Contratos Contínuos, **competência a competência
(mês/ano)**, inclusive em contratos cuja vigência atravessa exercícios. É um **cenário separado**: não altera
Necessidade de Empenho, Projeção pela Execução, Registro nem aditivos cadastrados.

## Decisões do usuário

| Tema | Decisão |
|---|---|
| Percentual | Oficial (BCB/SGS) **e** manual; o manual sobrescreve. Índices: IPCA (**padrão**, ajuste de 11/10/2026), INPC, IGP-M. |
| Data-base | Início da **vigência de renovação mais recente** (termos aditivos de vigência do Contratos.gov, aditivos ASSINADOS de vigência), repetida a cada 12 meses — ajuste de 11/10/2026 ("pelas últimas vigências"); Reajuste ASSINADO na renovação já está no valor (próximo ciclo +12 meses); sem renovação, início + 12 meses. Editável por contrato. |
| Destino | Cenário separado; promoção a aditivo "Previsto" só por clique. |
| Detalhe | Matriz por competência (mês/ano), vigência multianual. |
| Base de cálculo | **Liquidado por competência** (Liquidação por Competência, com estornos). O reajuste incide só sobre o executado. |
| NE x contrato | Uma NE pertence a um único contrato. NE ligada a dois contratos = inconsistência sinalizada; esse liquidado fica fora. |

## Regras

1. **Janela de competências** do contrato: do mês do início da vigência (Contratos.gov; sem ele, o exercício
   selecionado) ao mês do fim da vigência **efetiva** (aditivos, inclusive prorrogação PREVISTA, marcada). Nenhuma
   competência após o fim.
2. **Datas-base** (ciclos): a primeira conforme a decisão acima (ou a manual); as seguintes a cada 12 meses.
   Só há ciclo com data-base **dentro** da vigência efetiva. Contrato sem ciclo = `sem_reajuste_na_vigencia`
   (nunca zero). Sem início da vigência nem data manual nem reajuste assinado = `sem_data_base`.
3. **Percentual do ciclo**: manual (se informado) > oficial acumulado de 12 meses (os 12 meses anteriores ao mês da
   data-base) > oficial "último disponível" (marcado como estimado) > ausente. Ausente = `sem_indice`, nunca 0%.
4. **Fator acumulado**: o reajuste do ciclo k incide sobre o valor já reajustado (composto). Ciclo sem percentual
   torna **nulos** os acréscimos dele e dos ciclos seguintes.
5. **Base da competência**: se a competência é anterior ou igual ao último mês coberto pela base de Liquidação
   por Competência: soma do liquidado do contrato nela (origem `liquidado`); sem lançamento = **vazio**
   (`sem_liquidado`, nunca zero). Competência posterior ao último mês coberto: valor contratado em vigor
   (origem `contratado`, **teto**, sempre rotulado).
6. **Acréscimo** da competência = base × (fator acumulado − 1), com o mês da data-base proporcional aos dias
   a partir dela. Liquidado negativo (estorno líquido) fica como veio e é sinalizado.
7. **Promoção**: cria aditivo REAJUSTE/PREVISTO com `data_inicio` = data-base e `valor_mensal` = valor mensal
   vigente × (1 + percentual do ciclo), apenas para o próximo ciclo ainda sem aditivo.

## Persistência (sem arquivo/banco novo)

Três campos opcionais no registro do contrato existente (`data/contratos_continuos/<ano>/`): `reajuste_indice`,
`reajuste_percentual_manual`, `reajuste_data_base_manual`. Índices oficiais: consulta em sessão (cache), nada gravado.

## Módulos

- `src/indices_economicos.py` — cliente BCB/SGS (séries 433, 188, 189) e acumulado de 12 meses; falha de rede nunca derruba a página.
- `src/estimativa_reajuste.py` — cálculo puro (datas-base, percentuais, matriz por competência, resumo, aditivo previsto).
- `src/ui_reajuste.py` — seção "Estimativa de reajuste" em Contratos Contínuos, edição dos 3 campos, promoção, exportação Excel.
- `src/contratos_continuos_cadastro.py` — campos novos em `CAMPOS_IDENTIDADE`.

## Dúvidas registradas (não presumidas como regra definitiva)

- Janela do índice (12 meses anteriores ao mês da data-base) e uso do "último disponível".
- Reajuste composto entre ciclos e incidência sobre o valor mensal total do contrato.
- Data-base pela vigência, e não pela data da proposta/orçamento.
- Um percentual manual único vale para todos os ciclos sem percentual oficial.
- Contrato com NE em exercícios diferentes: o liquidado é somado por `contrato_numero` entre exercícios.

## Critérios de aceitação

- Contrato 01/06/2026–31/05/2028: ciclos em 01/06/2027 (e 01/06/2028 fora); acréscimo só de jun/2027 em diante; soma das competências = total.
- Contrato 01/06/2026–31/05/2027 sem prorrogação: `sem_reajuste_na_vigencia`.
- API fora do ar: página segue, sugestão oficial some, manual funciona.
- Sem índice nem manual: `sem_indice`, nunca 0%.
- Liquidado ausente numa competência apurada: vazio; futura: contratado/teto rotulado.
- Promoção só com clique; suíte completa verde.
