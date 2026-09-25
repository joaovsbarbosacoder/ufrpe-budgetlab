"""Glossário de termos orçamentários e contábeis usados no BudgetLab.

Reúne, agrupados por tema, os conceitos que aparecem nas páginas do sistema
(dotação, empenho, PTRES, TED, restos a pagar etc.), com a definição
condensada a partir de duas fontes oficiais:

- **MCASP** — Manual de Contabilidade Aplicada ao Setor Público, Secretaria
  do Tesouro Nacional, 11ª Edição (2025), Parte I — Procedimentos Contábeis
  Orçamentários;
- **MTO** — Manual Técnico de Orçamento 2026, Secretaria de Orçamento
  Federal, 7ª Versão.

Cada verbete cita o manual e a página onde a definição original aparece
(`fonte`); o texto de `definicao` é uma condensação, não uma transcrição
literal — para o texto integral, consulte a página citada. Alguns códigos
usados no dia a dia do SIAFI (UG, UGR, PI) não têm uma definição formal nos
dois manuais — nesses casos, `fonte` sinaliza isso explicitamente em vez de
citar uma página que não sustenta o verbete (ver AGENTS.md: não presumir
regra não documentada).

Este módulo não lê nem depende de nenhuma base de dados do projeto — é
conteúdo estático, mantido junto ao código para poder evoluir por revisão
igual a qualquer outra regra do sistema.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TermoGlossario:
    """Um verbete do glossário."""

    termo: str
    definicao: str
    fonte: str
    tema: str
    sigla: str | None = None
    ver_tambem: tuple[str, ...] = field(default_factory=tuple)

    @property
    def titulo(self) -> str:
        return f"{self.termo} ({self.sigla})" if self.sigla else self.termo


TEMAS: tuple[str, ...] = (
    "Receita e princípios orçamentários",
    "Classificações orçamentárias",
    "Créditos e alterações orçamentárias",
    "Execução da despesa",
    "Restos a pagar",
    "Programação orçamentária e limite de empenho",
    "Descentralização, TED e convênios",
    "Emendas parlamentares",
)

GLOSSARIO: tuple[TermoGlossario, ...] = (
    # -- Receita e princípios orçamentários -----------------------------
    TermoGlossario(
        termo="Princípios Orçamentários",
        definicao=(
            "Regras básicas que conferem racionalidade, eficiência e transparência à "
            "elaboração, execução e controle do orçamento público. Os principais: "
            "Unidade/Totalidade (um único orçamento por ente), Universalidade (a LOA "
            "contém todas as receitas e despesas de todos os Poderes, órgãos, entidades "
            "e fundos), Anualidade (o exercício financeiro coincide com o ano civil), "
            "Exclusividade (a LOA não trata de matéria estranha à receita/despesa, salvo "
            "créditos suplementares e ARO), Orçamento Bruto (registro pelo valor total, "
            "sem deduções) e Não Vinculação da Receita de Impostos (art. 167, IV, CF)."
        ),
        fonte="MTO, p. 15-16",
        tema="Receita e princípios orçamentários",
    ),
    TermoGlossario(
        termo="Receita Orçamentária",
        definicao=(
            "Disponibilidade de recursos financeiros que ingressa nos cofres públicos "
            "durante o exercício e constitui elemento novo para o patrimônio público; "
            "integra a LOA e viabiliza a execução das políticas públicas. Distingue-se "
            "dos ingressos extraorçamentários, que são recursos de terceiros sob guarda "
            "temporária do Estado."
        ),
        fonte="MTO, p. 17",
        tema="Receita e princípios orçamentários",
        ver_tambem=("Ingressos Extraorçamentários",),
    ),
    TermoGlossario(
        termo="Ingressos Extraorçamentários",
        definicao=(
            "Recursos financeiros de caráter temporário que não integram a LOA — o "
            "Estado é mero depositário. Exemplos: depósitos em caução, fianças e "
            "Operações de Crédito por Antecipação de Receita Orçamentária (ARO). Suas "
            "restituições não se sujeitam a autorização legislativa."
        ),
        fonte="MTO, p. 17",
        tema="Receita e princípios orçamentários",
        sigla="ARO",
    ),
    TermoGlossario(
        termo="Categoria Econômica da Receita",
        definicao=(
            "Primeiro dígito da natureza de receita. Receitas Correntes (código 1) "
            "aumentam a disponibilidade financeira do Estado com efeito positivo sobre "
            "o patrimônio líquido (tributos, contribuições, patrimonial, agropecuária, "
            "industrial, serviços, transferências correntes). Receitas de Capital "
            "(código 2) também aumentam a disponibilidade financeira, mas sem efeito "
            "sobre o patrimônio líquido (operações de crédito, alienação de bens, "
            "amortização de empréstimos, transferências de capital, superávit do "
            "orçamento corrente)."
        ),
        fonte="MTO, p. 19-20",
        tema="Receita e princípios orçamentários",
    ),
    # -- Classificações orçamentárias ------------------------------------
    TermoGlossario(
        termo="Esfera Orçamentária",
        definicao=(
            "Identifica se a despesa pertence ao Orçamento Fiscal — F, código 10 "
            "(Poderes, fundos, órgãos e entidades da administração direta e indireta), "
            "ao da Seguridade Social — S, código 20, ou ao de Investimento das Empresas "
            "Estatais — I, código 30."
        ),
        fonte="MTO, p. 39",
        tema="Classificações orçamentárias",
    ),
    TermoGlossario(
        termo="Classificação Institucional",
        definicao=(
            "Reflete a estrutura organizacional e administrativa por meio de dois "
            "níveis: Órgão Orçamentário (agrupamento de Unidades Orçamentárias) e "
            "Unidade Orçamentária — UO (agrupamento de serviços subordinados ao mesmo "
            "órgão, ao qual são consignadas dotações próprias). Código de 5 dígitos "
            "(2 para o órgão + 3 para a UO). Um órgão orçamentário ou uma UO não "
            "correspondem necessariamente a uma estrutura administrativa real."
        ),
        fonte="MCASP, p. 73; MTO, p. 14 e 40",
        tema="Classificações orçamentárias",
        sigla="UO",
    ),
    TermoGlossario(
        termo="Classificação Funcional",
        definicao=(
            "Explicita as áreas de atuação em que as despesas são realizadas, por meio "
            "de Função (maior nível de agregação, ligado à competência institucional do "
            "órgão — ex.: educação, saúde) e Subfunção (nível de agregação inferior, "
            "ligado à área específica da despesa). Código de 5 dígitos (2 para a função "
            "+ 3 para a subfunção), de aplicação obrigatória e independente dos "
            "programas."
        ),
        fonte="MCASP, p. 73-74; MTO, p. 40-41",
        tema="Classificações orçamentárias",
    ),
    TermoGlossario(
        termo="Programa",
        definicao=(
            "Instrumento de organização da atuação governamental que articula um "
            "conjunto de ações para concretizar um objetivo comum, atendendo a uma "
            "necessidade da sociedade; é o vínculo entre a LOA e o PPA. Pode ser "
            "Finalístico (concretiza diretamente uma política pública) ou de Gestão "
            "(despesas de manutenção dos órgãos — pessoal, custeio administrativo)."
        ),
        fonte="MCASP, p. 75; MTO, p. 43",
        tema="Classificações orçamentárias",
    ),
    TermoGlossario(
        termo="Ação Orçamentária",
        definicao=(
            "Principal classificador do orçamento público federal: operação da qual "
            "resultam produtos (bens ou serviços) que contribuem para o objetivo de um "
            "programa. Classifica-se em Atividade (instrumento contínuo/permanente, "
            "mantém o nível da produção pública), Projeto (limitado no tempo, expande "
            "ou aperfeiçoa a ação de governo, ou se incorpora ao patrimônio), Operação "
            "Especial (não gera produto nem contraprestação direta em bens/serviços — "
            "dívidas, indenizações, transferências) ou Reserva de Contingência (reserva "
            "de recursos para contingências fiscais)."
        ),
        fonte="MCASP, p. 75-76; MTO, p. 44-51",
        tema="Classificações orçamentárias",
        ver_tambem=("Subtítulo", "Plano Orçamentário"),
    ),
    TermoGlossario(
        termo="Subtítulo",
        definicao=(
            "Menor nível da categoria de programação; especifica a localização física "
            "da ação orçamentária, sem poder alterar sua finalidade, produto ou metas. "
            "Também chamado de localizador de gasto — não deve ser confundido com o "
            "Plano Orçamentário, que é gerencial e não consta da LOA."
        ),
        fonte="MCASP, p. 76; MTO, p. 64",
        tema="Classificações orçamentárias",
    ),
    TermoGlossario(
        termo="Plano Orçamentário",
        definicao=(
            "Identificação orçamentária de caráter gerencial (não consta da LOA), "
            "vinculada à ação orçamentária, que permite que a elaboração, a execução e "
            "o acompanhamento físico-financeiro do orçamento ocorram num nível mais "
            "detalhado do que a ação e o subtítulo. Toda ação tem ao menos um PO — "
            "quando não há POs específicos, o SIOP gera automaticamente o PO \"0000\", "
            "que absorve toda a dotação da ação."
        ),
        fonte="MTO, p. 58-59",
        tema="Classificações orçamentárias",
        sigla="PO",
        ver_tambem=("Programa de Trabalho Resumido",),
    ),
    TermoGlossario(
        termo="Programa de Trabalho Resumido",
        definicao=(
            "Código de 6 dígitos atribuído pelo SIAFI para agilizar a execução, o "
            "controle e o acompanhamento dos planos definidos pela Unidade "
            "Orçamentária. É a chave gerencial, no nível do SIOP/SIAFI, que resulta da "
            "combinação subtítulo + Plano Orçamentário: cada par (subtítulo, PO) de uma "
            "ação gera um PTRES próprio."
        ),
        fonte="MTO, p. 58",
        tema="Classificações orçamentárias",
        sigla="PTRES",
        ver_tambem=("Plano Orçamentário", "Subtítulo"),
    ),
    TermoGlossario(
        termo="Natureza da Despesa",
        definicao=(
            "Classificação da despesa orçamentária por Categoria Econômica + Grupo de "
            "Natureza da Despesa + Modalidade de Aplicação + Elemento de Despesa, com "
            "código no formato \"c.g.mm.ee.dd\"."
        ),
        fonte="MCASP, p. 76-84",
        tema="Classificações orçamentárias",
        ver_tambem=("Grupo de Natureza da Despesa", "Modalidade de Aplicação", "Elemento de Despesa"),
    ),
    TermoGlossario(
        termo="Categoria Econômica da Despesa",
        definicao=(
            "Primeiro dígito da natureza da despesa: 3 = Despesas Correntes (não "
            "contribuem diretamente para a formação de um bem de capital) e 4 = "
            "Despesas de Capital (contribuem diretamente para a formação ou aquisição "
            "de um bem de capital)."
        ),
        fonte="MCASP, p. 77",
        tema="Classificações orçamentárias",
    ),
    TermoGlossario(
        termo="Grupo de Natureza da Despesa",
        definicao=(
            "Agregador de elementos de despesa com as mesmas características quanto ao "
            "objeto do gasto. Categorias: 1-Pessoal e Encargos Sociais; 2-Juros e "
            "Encargos da Dívida; 3-Outras Despesas Correntes; 4-Investimentos; "
            "5-Inversões Financeiras; 6-Amortização da Dívida."
        ),
        fonte="MCASP, p. 78",
        tema="Classificações orçamentárias",
        sigla="GND",
    ),
    TermoGlossario(
        termo="Modalidade de Aplicação",
        definicao=(
            "Informação gerencial que indica se os recursos são aplicados diretamente "
            "por órgãos/entidades da mesma esfera de governo ou por outro ente da "
            "Federação, evitando dupla contagem de recursos transferidos ou "
            "descentralizados (ex.: 90-Aplicações Diretas, 40-Transferências a "
            "Municípios)."
        ),
        fonte="MCASP, p. 79",
        tema="Classificações orçamentárias",
    ),
    TermoGlossario(
        termo="Elemento de Despesa",
        definicao=(
            "Identifica os objetos de gasto (vencimentos, material de consumo, "
            "serviços de terceiros, obras, equipamentos, auxílios, amortização etc.) "
            "que a administração utiliza para atingir seus fins."
        ),
        fonte="MCASP, p. 84",
        tema="Classificações orçamentárias",
    ),
    TermoGlossario(
        termo="Identificador de Uso",
        definicao=(
            "Indica se os recursos da despesa se destinam à contrapartida de "
            "empréstimos/doações, à identificação de despesas com Ações e Serviços "
            "Públicos de Saúde (ASPS) ou com Manutenção e Desenvolvimento do Ensino "
            "(MDE), ou se não têm nenhuma dessas destinações específicas."
        ),
        fonte="MTO, p. 38 (tabela) e p. 39",
        tema="Classificações orçamentárias",
        sigla="IDUSO",
    ),
    TermoGlossario(
        termo="Fonte ou Destinação de Recursos",
        definicao=(
            "Agrupamento de receitas que possuem as mesmas normas de aplicação; "
            "identifica, para a receita, a que despesas os recursos se destinam e, "
            "para a despesa, de onde vêm os recursos. Código de 4 dígitos (1º = grupo "
            "da fonte, 2º-4º = especificação). Indica se os recursos são vinculados "
            "(destinação específica prevista em norma) ou não vinculados (alocação "
            "livre, dentro das competências do órgão)."
        ),
        fonte="MCASP, p. 139-141; MTO, p. 26-27",
        tema="Classificações orçamentárias",
        sigla="FR",
    ),
    TermoGlossario(
        termo="Identificador de Resultado Primário",
        definicao=(
            "Classifica receitas e despesas conforme seu efeito sobre o resultado "
            "primário do governo. Para a receita: \"1\" = primária (entra no cálculo do "
            "resultado primário), \"0\" = financeira (não entra). Para a despesa "
            "discricionária, os códigos incluem 2 (demais discricionárias), 3 "
            "(discricionárias do PAC), 6 (emendas individuais), 7 (emendas de bancada "
            "estadual) e 8 (emendas de comissão) — ver Emendas Parlamentares."
        ),
        fonte="MTO, p. 26 e p. 202-203",
        tema="Classificações orçamentárias",
        sigla="RP",
        ver_tambem=("Emenda Individual", "Emenda de Bancada Estadual", "Emenda de Comissão"),
    ),
    TermoGlossario(
        termo="Unidade Gestora",
        definicao=(
            "Código do SIAFI que identifica a unidade administrativa investida do "
            "poder de gerir recursos orçamentários e financeiros, próprios ou "
            "descentralizados, e de registrar os atos de execução da despesa. Não é "
            "necessariamente a mesma coisa que a Unidade Orçamentária (que é uma "
            "classificação legal, da LOA) — uma UO pode ter uma ou mais UGs vinculadas."
        ),
        fonte=(
            "Conceito operacional do SIAFI, sem definição própria no MCASP ou no MTO "
            "consultados aqui — ver Classificação Institucional para a Unidade "
            "Orçamentária correspondente na lei orçamentária."
        ),
        tema="Classificações orçamentárias",
        sigla="UG",
        ver_tambem=("Classificação Institucional",),
    ),
    TermoGlossario(
        termo="Unidade Gestora Responsável",
        definicao=(
            "No BudgetLab, identifica a Unidade Gestora à qual uma despesa ou "
            "programação está vinculada como responsável pela execução — equivalente "
            "operacional, no SIAFI, ao conceito de \"Unidade Responsável\" pela execução "
            "da ação orçamentária (unidade administrativa, entidade ou parceiro "
            "responsável pela execução)."
        ),
        fonte=(
            "MTO, p. 57 (conceito de \"Unidade Responsável\" pela ação orçamentária); a "
            "sigla UGR em si é uso do SIAFI, sem definição própria no MCASP ou no MTO "
            "consultados aqui"
        ),
        tema="Classificações orçamentárias",
        sigla="UGR",
        ver_tambem=("Unidade Gestora",),
    ),
    TermoGlossario(
        termo="Plano Interno",
        definicao=(
            "Código de controle gerencial que cada Unidade Gestora pode criar no SIAFI "
            "para detalhar, internamente, a execução de uma ação ou de um PTRES — uso "
            "interno da unidade, sem correspondência direta na estrutura programática "
            "da LOA."
        ),
        fonte=(
            "Conceito operacional do SIAFI, sem definição própria no MCASP ou no MTO "
            "consultados aqui — não confundir com o Plano Orçamentário (PO), que é "
            "definido no MTO e integra a estrutura programática nacional."
        ),
        tema="Classificações orçamentárias",
        sigla="PI",
        ver_tambem=("Plano Orçamentário",),
    ),
    # -- Créditos e alterações orçamentárias -----------------------------
    TermoGlossario(
        termo="Dotação Orçamentária",
        definicao=(
            "Autorização, dada pela Lei Orçamentária Anual (ou por crédito adicional), "
            "para a realização de uma despesa até determinado valor. É sobre a dotação "
            "que incide o empenho: sem dotação disponível, a despesa não pode ser "
            "empenhada."
        ),
        fonte="MCASP, p. 72 e p. 105",
        tema="Créditos e alterações orçamentárias",
    ),
    TermoGlossario(
        termo="Crédito Adicional",
        definicao=(
            "Autorização de despesas não computadas ou insuficientemente dotadas na "
            "Lei Orçamentária. Classifica-se em Suplementar (reforço de dotação já "
            "existente), Especial (despesa sem dotação específica) ou Extraordinário "
            "(despesas urgentes e imprevistas — guerra, comoção intestina ou "
            "calamidade pública). Vigência restrita ao exercício financeiro em que "
            "forem autorizados, salvo exceções para os especiais/extraordinários "
            "abertos nos últimos quatro meses do ano."
        ),
        fonte="MCASP, p. 101",
        tema="Créditos e alterações orçamentárias",
    ),
    TermoGlossario(
        termo="Transposição, Remanejamento e Transferência",
        definicao=(
            "Realocações de recursos previstas na Constituição de 1988 (não se "
            "confundem com créditos adicionais). Transposição: realocação entre "
            "programas de trabalho, dentro do mesmo órgão. Remanejamento: realocação "
            "de recursos de um órgão para outro. Transferência: realocação entre "
            "categorias econômicas, dentro do mesmo órgão e programa."
        ),
        fonte="MCASP, p. 102",
        tema="Créditos e alterações orçamentárias",
    ),
    TermoGlossario(
        termo="Descentralização de Créditos Orçamentários",
        definicao=(
            "Movimentação de parte do orçamento para que outra unidade administrativa "
            "possa executar a despesa, mantidas as classificações institucional, "
            "funcional, programática e econômica — não altera a programação nem a "
            "titularidade orçamentária do crédito. Provisão: descentralização interna, "
            "entre Unidades Gestoras do mesmo órgão. Destaque: descentralização "
            "externa, entre Unidades Gestoras de órgãos diferentes. É a base "
            "orçamentária, no SIAFI, das operações de TED."
        ),
        fonte="MCASP, p. 103",
        tema="Créditos e alterações orçamentárias",
        ver_tambem=("Termo de Execução Descentralizada", "Nota de Crédito"),
    ),
    # -- Execução da despesa ---------------------------------------------
    TermoGlossario(
        termo="Empenho",
        definicao=(
            "Ato de autoridade competente que cria para o Estado uma obrigação de "
            "pagamento, pendente ou não de implemento de condição, e reserva a dotação "
            "orçamentária para um fim específico. Primeiro dos três estágios da "
            "execução da despesa (empenho, liquidação, pagamento). Tipos: Ordinário "
            "(valor fixo, pagamento de uma só vez), Estimativo (montante não "
            "determinável previamente — água, energia, combustível) e Global "
            "(despesas contratuais sujeitas a parcelamento — ex.: aluguéis)."
        ),
        fonte="MCASP, p. 105",
        tema="Execução da despesa",
        ver_tambem=("Nota de Empenho", "Liquidação", "Pagamento"),
    ),
    TermoGlossario(
        termo="Nota de Empenho",
        definicao=(
            "Documento que formaliza o empenho, contendo o nome do credor, a "
            "especificação da despesa e a importância envolvida, além dos demais dados "
            "necessários ao controle da execução orçamentária."
        ),
        fonte="MCASP, p. 105",
        tema="Execução da despesa",
        sigla="NE",
        ver_tambem=("Empenho",),
    ),
    TermoGlossario(
        termo="Liquidação",
        definicao=(
            "Segundo estágio da execução da despesa: verificação do direito adquirido "
            "pelo credor, com base nos títulos e documentos comprobatórios do crédito. "
            "Apura a origem e o objeto do que se deve pagar, a importância exata a "
            "pagar e a quem se deve pagar."
        ),
        fonte="MCASP, p. 106",
        tema="Execução da despesa",
    ),
    TermoGlossario(
        termo="Pagamento",
        definicao=(
            "Terceiro e último estágio da execução da despesa: entrega de numerário ao "
            "credor por cheque nominativo, ordem de pagamento ou crédito em conta, só "
            "podendo ser efetuado após a regular liquidação da despesa. A Ordem de "
            "Pagamento é o despacho de autoridade competente que determina que a "
            "despesa liquidada seja paga."
        ),
        fonte="MCASP, p. 106",
        tema="Execução da despesa",
    ),
    TermoGlossario(
        termo="Despesas de Exercícios Anteriores",
        definicao=(
            "Despesas cujo fato gerador ocorreu em exercício anterior àquele em que "
            "deva ocorrer o pagamento — empenhos considerados insubsistentes e anulados, "
            "restos a pagar com prescrição interrompida, ou compromissos reconhecidos "
            "após o encerramento do exercício correspondente."
        ),
        fonte="MCASP, p. 136",
        tema="Execução da despesa",
        sigla="DEA",
    ),
    TermoGlossario(
        termo="Suprimento de Fundos",
        definicao=(
            "Regime de adiantamento de valores a um servidor para despesas que não "
            "possam se subordinar ao processo normal de aplicação — despesas "
            "eventuais, de caráter sigiloso ou de pequeno vulto —, sujeito a posterior "
            "prestação de contas. Percorre os três estágios da despesa orçamentária "
            "(empenho, liquidação, pagamento), mas não representa, pelo enfoque "
            "patrimonial, uma despesa no momento da concessão."
        ),
        fonte="MCASP, p. 137-139",
        tema="Execução da despesa",
    ),
    # -- Restos a pagar ----------------------------------------------------
    TermoGlossario(
        termo="Restos a Pagar",
        definicao=(
            "Despesas regularmente empenhadas, do exercício atual ou anterior, mas não "
            "pagas até 31 de dezembro do exercício financeiro vigente. Distinguem-se "
            "dois tipos: os Processados (despesas já liquidadas) e os Não Processados "
            "(despesas ainda a liquidar ou em liquidação)."
        ),
        fonte="MCASP, p. 128",
        tema="Restos a pagar",
        ver_tambem=("Restos a Pagar Processados", "Restos a Pagar Não Processados"),
    ),
    TermoGlossario(
        termo="Restos a Pagar Não Processados",
        definicao=(
            "Despesas empenhadas mas ainda não liquidadas, inscritas em restos a pagar "
            "quando o serviço/material contratado ainda não foi entregue (despesa \"a "
            "liquidar\") ou já foi entregue mas ainda está em fase de verificação "
            "(despesa \"em liquidação\")."
        ),
        fonte="MCASP, p. 130",
        tema="Restos a pagar",
        sigla="RPNP",
    ),
    TermoGlossario(
        termo="Restos a Pagar Processados",
        definicao=(
            "Despesas já liquidadas — o serviço, a obra ou o material contratado foi "
            "entregue e aceito pelo contratante — mas ainda não pagas no exercício "
            "financeiro. Em geral não podem ser canceladas, pois a Administração já "
            "confirmou a obrigação; resta apenas o pagamento."
        ),
        fonte="MCASP, p. 131",
        tema="Restos a pagar",
        sigla="RPP",
    ),
    TermoGlossario(
        termo="Cancelamento de Restos a Pagar",
        definicao=(
            "Baixa de uma inscrição em restos a pagar, com tratamento contábil "
            "diferente conforme o estágio em que a despesa se encontrava (a liquidar, "
            "em liquidação ou liquidada). Deve ser criterioso quando a despesa já foi "
            "liquidada, pois o fornecedor já cumpriu sua obrigação."
        ),
        fonte="MCASP, p. 133",
        tema="Restos a pagar",
    ),
    # -- Programação orçamentária e limite de empenho ---------------------
    TermoGlossario(
        termo="Decreto de Programação Orçamentária e Financeira",
        definicao=(
            "Normativo, publicado em regra até 30 dias após a publicação da LOA, que "
            "define os limites orçamentários (para empenho, estabelecidos pela "
            "SOF/MPO) e financeiros (para pagamento, estabelecidos pela STN/MF) das "
            "despesas primárias discricionárias dos órgãos e entidades do Poder "
            "Executivo federal. É atualizado ao longo do ano, inclusive por avaliações "
            "bimestrais de receitas e despesas."
        ),
        fonte="MTO, p. 196",
        tema="Programação orçamentária e limite de empenho",
        sigla="DPOF",
    ),
    TermoGlossario(
        termo="Limite de Movimentação e Empenho",
        definicao=(
            "Valor, disponibilizado pela SOF/MPO via SIOP no nível de Órgão "
            "Orçamentário, dentro do qual o órgão pode emitir empenhos no exercício. "
            "Cada órgão é responsável por distribuir seu limite entre as Unidades "
            "Orçamentárias vinculadas."
        ),
        fonte="MTO, p. 201",
        tema="Programação orçamentária e limite de empenho",
        sigla="LME",
    ),
    TermoGlossario(
        termo="Faseamento dos Limites de Empenho",
        definicao=(
            "Divisão do limite de movimentação e empenho em períodos (bimestres), "
            "liberados progressivamente ao longo do ano, com o valor ainda não "
            "liberado retido como referência para os períodos seguintes. Mecanismo de "
            "prudência e transparência fiscal que cadencia a execução orçamentária."
        ),
        fonte="MTO, p. 200-201",
        tema="Programação orçamentária e limite de empenho",
    ),
    TermoGlossario(
        termo="Cotas de Limite de Empenho",
        definicao=(
            "Códigos gerenciais de uma letra que identificam o tipo de despesa dentro "
            "de cada Identificador de Resultado Primário (RP), usados no SIOP/SIAFI "
            "como \"conta corrente\" do limite. Cada RP tem suas próprias cotas — por "
            "exemplo, RP6 (emendas individuais) usa as cotas K a N, RP7 (emendas de "
            "bancada) usa O a R e RP8 (emendas de comissão) usa S a V."
        ),
        fonte="MTO, p. 202-203",
        tema="Programação orçamentária e limite de empenho",
        ver_tambem=("Identificador de Resultado Primário",),
    ),
    TermoGlossario(
        termo="Contingenciamento",
        definicao=(
            "Indisponibilização de dotações orçamentárias para atendimento à meta de "
            "resultado primário da LDO, aplicada quando a projeção de receitas e "
            "despesas aponta para um resultado fiscal abaixo da meta fixada — "
            "limitação de empenho e movimentação financeira prevista no art. 9º da "
            "LRF."
        ),
        fonte="MTO, p. 207-208",
        tema="Programação orçamentária e limite de empenho",
    ),
    TermoGlossario(
        termo="Bloqueio de Limite",
        definicao=(
            "Reserva de dotações para cancelamento futuro, destinada a atender aos "
            "limites individualizados de despesas primárias do arcabouço fiscal (Lei "
            "Complementar nº 200/2023). Não se confunde com o bloqueio de empenho de "
            "encerramento do exercício, que é a data-limite anual para emissão de "
            "novos empenhos."
        ),
        fonte="MTO, p. 208",
        tema="Programação orçamentária e limite de empenho",
    ),
    # -- Descentralização, TED e convênios --------------------------------
    TermoGlossario(
        termo="Termo de Execução Descentralizada",
        definicao=(
            "Instrumento por meio do qual um órgão ou entidade da administração "
            "pública federal descentraliza crédito orçamentário a outro, para execução "
            "de ação de interesse recíproco, nas mesmas ou em diferentes esferas de "
            "governo — sem que isso configure transferência de recursos entre entes "
            "da Federação (a execução, o empenho, a liquidação e o pagamento ocorrem "
            "na unidade descentralizadora). No orçamento, apoia-se na descentralização "
            "de créditos por provisão ou destaque."
        ),
        fonte="MTO, p. 55-56 (referência ao Decreto nº 10.426/2020, art. 2º, I)",
        tema="Descentralização, TED e convênios",
        sigla="TED",
        ver_tambem=("Descentralização de Créditos Orçamentários",),
    ),
    TermoGlossario(
        termo="Nota de Crédito",
        definicao=(
            "Documento do SIAFI que formaliza a descentralização de crédito "
            "orçamentário entre Unidades Gestoras — por provisão (dentro do mesmo "
            "órgão) ou por destaque (entre órgãos diferentes) —, base orçamentária das "
            "operações de TED."
        ),
        fonte=(
            "MCASP, p. 103 (conceito de descentralização de créditos orçamentários — "
            "provisão e destaque); a sigla NC em si é do SIAFI"
        ),
        tema="Descentralização, TED e convênios",
        sigla="NC",
        ver_tambem=("Descentralização de Créditos Orçamentários", "Termo de Execução Descentralizada"),
    ),
    TermoGlossario(
        termo="Descentralização/Delegação",
        definicao=(
            "Forma de implementação de uma ação orçamentária em que uma atividade ou "
            "projeto, na área de competência da União, é executado por outro ente da "
            "Federação (Estado, Distrito Federal ou Município), com recursos "
            "repassados pela União — por exemplo, por convênio ou termo de "
            "compromisso. Se a execução for feita por outra Unidade Orçamentária da "
            "própria União, não se configura descentralização."
        ),
        fonte="MTO, p. 55",
        tema="Descentralização, TED e convênios",
    ),
    TermoGlossario(
        termo="Transferências (voluntárias e obrigatórias)",
        definicao=(
            "Entrega de recursos financeiros a outro ente da Federação, a consórcios "
            "públicos ou a entidades privadas, com ou sem fins lucrativos, sem "
            "contraprestação direta em bens ou serviços ao transferidor. No âmbito das "
            "ações orçamentárias, dividem-se em Obrigatórias (por determinação "
            "constitucional ou legal, como o FPM) e Outras/voluntárias (sem "
            "determinação constitucional ou legal)."
        ),
        fonte="MCASP, p. 118; MTO, p. 56",
        tema="Descentralização, TED e convênios",
    ),
    # -- Emendas parlamentares ---------------------------------------------
    TermoGlossario(
        termo="Emenda Parlamentar",
        definicao=(
            "Proposta de alteração do projeto de lei orçamentária apresentada por "
            "parlamentar, bancada estadual ou comissão do Congresso Nacional. No "
            "orçamento e na execução, cada tipo de emenda é identificado por um "
            "Identificador de Resultado Primário próprio (RP6, RP7 ou RP8), o que "
            "determina regras específicas de limite de empenho, de pagamento e de "
            "prazo de execução."
        ),
        fonte="MTO, p. 199 e p. 202-203",
        tema="Emendas parlamentares",
        ver_tambem=("Identificador de Resultado Primário",),
    ),
    TermoGlossario(
        termo="Emenda Individual",
        definicao=(
            "Emenda apresentada por um único parlamentar, identificada pelo "
            "Identificador de Resultado Primário RP6. De execução obrigatória (nos "
            "termos constitucionais), tem regras próprias de bloqueio de empenho — no "
            "DPOF 2026, prazo até 4 de dezembro, diferente do prazo geral de 31 de "
            "dezembro das demais despesas discricionárias."
        ),
        fonte="MTO, p. 199, 202 e 206",
        tema="Emendas parlamentares",
        sigla="RP6",
    ),
    TermoGlossario(
        termo="Emenda de Bancada Estadual",
        definicao=(
            "Emenda apresentada em conjunto pela bancada de deputados e senadores de "
            "um mesmo Estado, identificada pelo Identificador de Resultado Primário "
            "RP7. Assim como as emendas individuais, tem prazo de bloqueio de empenho "
            "diferenciado (até 4 de dezembro, no DPOF 2026)."
        ),
        fonte="MTO, p. 199, 203 e 206",
        tema="Emendas parlamentares",
        sigla="RP7",
    ),
    TermoGlossario(
        termo="Emenda de Comissão",
        definicao=(
            "Emenda apresentada por comissão do Congresso Nacional, identificada pelo "
            "Identificador de Resultado Primário RP8, com valores autorizados para "
            "pagamento definidos em anexo próprio do DPOF (Anexo V)."
        ),
        fonte="MTO, p. 199 e 203",
        tema="Emendas parlamentares",
        sigla="RP8",
    ),
)


def termos_por_tema() -> dict[str, tuple[TermoGlossario, ...]]:
    """Agrupa os verbetes por tema, preservando a ordem de `TEMAS`."""

    agrupado: dict[str, list[TermoGlossario]] = {tema: [] for tema in TEMAS}
    for termo in GLOSSARIO:
        agrupado[termo.tema].append(termo)
    return {tema: tuple(sorted(itens, key=lambda t: t.termo)) for tema, itens in agrupado.items()}


def buscar(consulta: str) -> tuple[TermoGlossario, ...]:
    """Filtra verbetes cujo termo, sigla ou definição contenham `consulta`.

    Busca case-insensitive e sem acentuação (evita frustrar o usuário que
    digitar "orcamento" em vez de "orçamento").
    """

    alvo = _normalizar(consulta.strip())
    if not alvo:
        return GLOSSARIO
    return tuple(
        termo
        for termo in GLOSSARIO
        if alvo in _normalizar(termo.termo)
        or (termo.sigla and alvo in _normalizar(termo.sigla))
        or alvo in _normalizar(termo.definicao)
    )


def _normalizar(texto: str) -> str:
    import unicodedata

    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sem_acento.casefold()
