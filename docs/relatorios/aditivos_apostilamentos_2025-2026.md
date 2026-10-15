# Aditivos e apostilamentos assinados — 01/01/2025 a 14/10/2026

Fonte: fotografia do Contratos.gov.br (UG 153165) consultada em **2026-10-08T09:42:00** — `contratosgov_2026-10-08.json`. Contratos na fotografia: 6; com detalhe lido: 6.

Critério: termos do histórico com tipo diferente de "Contrato" e **data de assinatura** entre 01/01/2025 e hoje (14/10/2026). Valores como vêm da API (valor global do contrato após o termo; "novo valor" é o campo informado no termo, 0,00 = não informado). Nada foi alterado nos dados.

## Resumo

- Total de termos assinados no período: **4** — Termo Aditivo: 3; Termo de Apostilamento: 1
- Contratos com ao menos um termo: **3** de 6
- Termos sem data de assinatura (excluídos): 0

| Contrato | Fornecedor | Aditivos | Apostilamentos |
|---|---|---:|---:|
| 00029/2021 | TEKIS TECNOLOGIAS AVANCADAS LTDA | 1 | 0 |
| 00021/2017 | RIO AVE IMOVEIS LTDA | 0 | 1 |
| 00021/2023 | PESSOA FÍSICA FICTÍCIA | 2 | 0 |

## Detalhamento por contrato

### Contrato 00029/2021 — TEKIS TECNOLOGIAS AVANCADAS LTDA

- Objeto: CONTRATAÇÃO DE SERVIÇOS DE LICENÇA DE USO, SUPORTE E MANUTENÇÃO E IMPLANTAÇÃO E CAPACITAÇÃO DOS SISTEMAS DA VERSÃO ENTERPRISE DA PLATAFORMA STELA EXPERTA©.
- Situação na API: Ativo · Vigência atual: 18/10/2021 a 17/10/2026 · Valor global atual: R$ 93.307,80 · Processo: 23082.006789/2021-88

| Termo | Tipo | Assinatura | Qualificação | Vigência do termo | Valor global | Novo valor global | Novo valor parcela | Retroativo |
|---|---|---|---|---|---:|---:|---:|---|
| 00004/2025 | Termo Aditivo | 16/09/2025 | VIGÊNCIA, REAJUSTE | 18/10/2025 a 17/10/2026 | R$ 93.307,80 | R$ 0,00 | R$ 0,00 | sim |

### Contrato 00021/2017 — RIO AVE IMOVEIS LTDA

- Objeto: LOCAÇÃO DE IMÓVEL SITUADO NO ENDEREÇO RUA CENTO E SESSENTA E TRÊS, 300, GARAPU, CEP 54518-430, CABO DE SANTO AGOSTINHO/PE, DENOMINADO EMPRESARIAL CABO CORPORATE, COM ÁREA TOTAL DISPONIBILIZADA DE 11.582,72 M², PARA ABRIG…
- Situação na API: Ativo · Vigência atual: 29/05/2017 a 28/05/2027 · Valor global atual: R$ 10.354.305,17 · Processo: 23082..01412/5/20-16

| Termo | Tipo | Assinatura | Qualificação | Vigência do termo | Valor global | Novo valor global | Novo valor parcela | Retroativo |
|---|---|---|---|---|---:|---:|---:|---|
| 00004/2026 | Termo de Apostilamento | 20/01/2026 | — | 29/11/2024 a 28/05/2027 | R$ 10.354.305,17 | R$ 10.354.305,17 | R$ 10.354.305,17 | sim |

### Contrato 00021/2023 — PESSOA FÍSICA FICTÍCIA

- Objeto: CONTRATAÇÃO DE SERVIÇOS DE LEILOEIRO OFICIAL PARA PREPARAR, ORGANIZAR E CONDUZIR 5 (CINCO) LEILÕES PARA A VENDA DE BENS MÓVEIS INSERVÍVEIS PERTENCENTES À UNIVERSIDADE FEDERAL RURAL DE PERNAMBUCO. TAXA DA COMISSÃO CONTRAT…
- Situação na API: Ativo · Vigência atual: 03/10/2023 a 03/10/2027 · Valor global atual: R$ 0,00 · Processo: 23082.011145/2020-37

| Termo | Tipo | Assinatura | Qualificação | Vigência do termo | Valor global | Novo valor global | Novo valor parcela | Retroativo |
|---|---|---|---|---|---:|---:|---:|---|
| 00002/2025 | Termo Aditivo | 02/10/2025 | VIGÊNCIA | 04/10/2025 a 03/10/2026 | R$ 0,00 | R$ 0,00 | R$ 0,00 | sim |
| 00003/2026 | Termo Aditivo | 02/10/2026 | VIGÊNCIA | 04/10/2026 a 03/10/2027 | R$ 0,00 | R$ 0,00 | R$ 0,00 | sim |

## Ressalvas

- **Cobertura limitada:** a fotografia atual segundo o manifesto (`data/manifestos/contratosgov_atual.json`, 11/10/2026, 220 contratos e 712 termos) fica em `data/raw/contratosgov/`, que não é versionada e não existe neste ambiente. O relatório usa a única fotografia disponível, a fixture congelada de 08/10/2026 (6 contratos, CPFs anonimizados). Os números acima **não representam todos os contratos da UFRPE**; deve-se regerar o relatório sobre a fotografia de 11/10/2026.
- Apostilamento sem qualificação na API: o tipo da alteração (reajuste, etc.) não é informado; não foi presumido.
- "Valor global" é o do contrato após o termo, não o valor da variação; a variação não foi calculada por não haver regra definida.
