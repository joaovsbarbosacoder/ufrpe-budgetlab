"""
Relatório de Reforço de Empenho / Anulação de Saldo de Empenho (Bolsas e Auxílios /
Contratos Contínuos).

Camada: regra de negócio de relatório — monta a tabela no formato usado pela PROPLAD para
pedidos de reforço OU anulação (cancelamento) de empenho, para os DOIS TIPOS de relatório
(pedido explícito posterior: mesmo modelo/mecânica do Reforço, só que para anular saldo em
vez de reforçar — ver `TipoRelatorio` mais abaixo, que parametriza o que muda entre os dois:
título/rótulo de coluna/nome de arquivo, nada da estrutura em si). Diferente de
`EspecificacaoRelatorio` (que varia por BASE: Bolsas × Contratos Contínuos), `TipoRelatorio`
varia por TIPO de relatório, independente da base — as duas dimensões são ortogonais
(`gerar_pdf_detalhado`/`gerar_pdf_resumido` recebem as duas).

Anulação de Saldo de Empenho NÃO tem sugestão automática de valor (pedido explícito do
usuário: "sem sugestão automática — todas as linhas começam zeradas") — diferente do Reforço
(que sugere a partir de `meses_a_empenhar`/"por calendário"), quem emite decide quanto anular
linha a linha. Essa escolha vive na camada de UI (`src/ui_relatorio_reforco_empenho.py`, seed
de `st.session_state`), não aqui — `linhas_para_processo` continua calculando
`meses_sugeridos` do mesmo jeito para as duas bases; a UI é quem decide se usa isso (Reforço)
ou ignora e começa em zero (Anulação).

Os DOIS modelos de PDF em uso (ver histórico da conversa para os PDFs de referência — dois
modelos distintos, os dois precisam ser emitidos, para os dois tipos de relatório):

  * "Detalhado" (`gerar_pdf_detalhado`) — Processo, Item de Despesa, Item Lic., Unidade, Ação,
    PTRES, Fonte, ND, UGR, PI, Empenho, Empenhar (R$); Processo/Unidade/Empenho repetidos em
    toda linha; uma linha por item de licitação (`linhas_para_processo`/`coluna_itens`), em
    ordem alfabética por fornecedor.
  * "Resumido" (`gerar_pdf_resumido`) — Ação, PTRES, Fonte, ND, PI, UGR, Empenhar (R$); layout
    de Tabela Dinâmica do Excel impresso de verdade (pedido explícito de correção — chegou a
    ficar quase idêntico ao detalhado, só com 2 colunas a menos): uma linha por combinação
    única dessas seis colunas, com "Empenhar (R$)" SOMADO entre todos os
    itens/fornecedores daquele grupo — sem coluna de fornecedor/item de despesa, é visão
    orçamentária, não por credor (ver `_agrupado_por_classificacao`). Processo aparece uma vez
    só no cabeçalho da página, não repetido linha a linha; PI antes de UGR (ordem invertida em
    relação ao modelo detalhado).

Não lê planilha, não é interface — recebe o DataFrame já normalizado de
`ler_bolsas_auxilios`/`ler_contratos_continuos` (com `meses_a_empenhar` já calculado por
`necessidade_empenho.py`).

"Meses a empenhar" E "Empenhar (R$)" são editáveis por linha, os dois (pedido explícito) — o
valor sugerido inicial vem de `meses_a_empenhar` (execução: empenhado − liquidado) OU, quando o
mês de início da execução é conhecido, da sugestão "por calendário" (pedido explícito:
"parametrize o sistema para que ele fique pronto para empenhar o que falta para o mês
vigente" — ver `necessidade_ate_mes_vigente`/`_com_sugestao_por_calendario`); de qualquer
forma, cada linha pode ser ajustada livremente antes de gerar o relatório (a edição em si mora
em `st.session_state`, na página, não aqui). Editar "Meses a Empenhar" recalcula "Empenhar
(R$)" (= meses × valor mensal) e sempre vence sobre um valor digitado direto antes; editar
"Empenhar (R$)" direto fica valendo como está até a próxima edição de "Meses a Empenhar" na
mesma linha.

Contrato público:
    EspecificacaoRelatorio (dataclass) — BOLSAS_AUXILIOS / CONTRATOS_CONTINUOS, prontas
    TipoRelatorio (dataclass) — TIPO_REFORCO / TIPO_ANULACAO, prontos
    linhas_para_processo(df, spec, processo, ano_referencia) -> pd.DataFrame
    excluir_linhas_zeradas(linhas) -> pd.DataFrame
    gerar_pdf_detalhado(spec, tipo, processo, linhas) -> bytes
    gerar_pdf_resumido(spec, tipo, processo, linhas) -> bytes
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from src.necessidade_empenho import necessidade_ate_mes_vigente


@dataclass(frozen=True)
class EspecificacaoRelatorio:
    """O que varia entre Bolsas e Contratos Contínuos para este relatório — o resto do
    esquema (unidade/ação/PTRES/fonte/ND/UGR/PI/empenho) já tem o mesmo nome de coluna nas
    duas bases (ver `COLUNAS_ORIGEM` de cada leitor)."""

    titulo_orgao: str
    titulo_base: str
    #: coluna que vira "PROCESSO" — o processo administrativo que agrupa vários itens de
    #: reforço num mesmo pedido (não o processo de contratação, ver histórico da conversa).
    coluna_processo: str
    #: coluna que vira "ITEM DE DESPESA" — o texto que identifica a linha para quem lê o
    #: relatório (nome do programa de bolsa, ou fornecedor do contrato).
    coluna_item_despesa: str
    coluna_valor_mensal: str
    #: coluna opcional com a lista de itens que rateiam o valor mensal do contrato/NE —
    #: `[{"numero": int, "percentual": float}, ...]`, percentuais somando 100 (ver
    #: `src.contratos_continuos_cadastro`). Pedido explícito de correção do usuário: no SIAFI
    #: o reforço de empenho é feito por item de licitação, mas a liquidação não é dividida por
    #: item — o item não é uma entidade própria no cadastro do contrato (que é 1 registro por
    #: NE inteira), só entra em jogo aqui, na hora de montar o relatório: cada item vira sua
    #: própria linha, com `valor_mensal = despesa_mensal do contrato × percentual do item`.
    #: Ausente em Bolsas e Auxílios (uma NE == um programa, sempre um item só).
    coluna_itens: str | None = None
    #: colunas opcionais para a sugestão inicial "por calendário" (pedido explícito: "fique
    #: pronto para empenhar o que falta para o mês vigente") — valor já empenhado autoritativo
    #: (Execução Anual quando disponível, cadastro como reserva; a página monta essa coluna
    #: antes de chamar `render_botao_relatorio`) e o mês (1-12) do primeiro empenho daquela NE.
    #: Sem as duas, `linhas_para_processo` cai de volta pra `meses_a_empenhar` (execução:
    #: empenhado − liquidado) — ver `necessidade_ate_mes_vigente`.
    coluna_valor_empenhado: str | None = None
    coluna_inicio_execucao: str | None = None
    #: coluna com o saldo autoritativo da NE (Execução Mensal, com o valor colado na planilha
    #: como reserva — mesmo padrão de fallback de `coluna_valor_empenhado`; a página monta essa
    #: coluna antes de chamar `render_botao_relatorio`, ver `app_pages/bolsas_auxilios.py`/
    #: `app_pages/contratos_continuos.py`). Pedido explícito: evidenciar o saldo do empenho na
    #: tela do relatório, junto do valor mensal, pra quem emite decidir quanto reforçar/anular
    #: com o dado à vista, sem precisar sair do pop-up. Sempre no nível da NE, nunca rateado por
    #: item de licitação (mesmo critério de `meses_sugeridos`, ver `_linha_base` — a liquidação
    #: não é dividida por item).
    coluna_saldo: str | None = None
    #: coluna com o total de meses que o item é pago no exercício (cadastro nativo de Bolsas,
    #: `meses_no_ano` — ausente em Contratos Contínuos, que não tem esse conceito, sempre
    #: `None` pra essa base). Teto de `meses_sugeridos` na sugestão "por calendário" (pedido
    #: explícito, corrige bug real relatado pelo usuário: sem esse teto, uma bolsa "parcela
    #: única" já paga por completo continuava sugerindo reforço só porque o calendário já tinha
    #: passado vários meses desde o início da execução — ver
    #: `necessidade_ate_mes_vigente`/`_com_sugestao_por_calendario`).
    coluna_meses_no_ano: str | None = None


BOLSAS_AUXILIOS = EspecificacaoRelatorio(
    titulo_orgao="PRÓ-REITORIA DE ADMINISTRAÇÃO - PROPLAD",
    titulo_base="BOLSAS, AUXÍLIOS FINANCEIROS E GECC",
    coluna_processo="processo",
    coluna_item_despesa="programa_bolsa",
    coluna_valor_mensal="valor_mensal",
    coluna_valor_empenhado="valor_empenhado_autoritativo",
    coluna_inicio_execucao="inicio_execucao_efetivo",
    coluna_saldo="saldo_autoritativo",
    coluna_meses_no_ano="meses_no_ano",
)

CONTRATOS_CONTINUOS = EspecificacaoRelatorio(
    titulo_orgao="PRÓ-REITORIA DE ADMINISTRAÇÃO - PROPLAD",
    titulo_base="CONTRATOS CONTÍNUOS",
    coluna_processo="processo_empenho",
    coluna_item_despesa="fornecedor",
    coluna_valor_mensal="despesa_mensal",
    coluna_itens="itens",
    coluna_valor_empenhado="valor_empenhado_autoritativo",
    coluna_inicio_execucao="inicio_execucao_efetivo",
    coluna_saldo="saldo_autoritativo",
    coluna_meses_no_ano="meses_no_ano",
)

@dataclass(frozen=True)
class TipoRelatorio:
    """O que varia entre os dois relatórios que reaproveitam este mesmo módulo — Reforço de
    Empenho e Anulação de Saldo de Empenho (pedido explícito posterior: "mesmo modelo" do
    Reforço, só que visando anular saldo em vez de reforçar) — independente da BASE (Bolsas ×
    Contratos Contínuos, essa é `EspecificacaoRelatorio`, acima). Nada da estrutura do
    relatório muda entre os dois tipos, só rótulos de coluna/título/nome de arquivo — ver
    `TIPO_REFORCO`/`TIPO_ANULACAO` logo abaixo, os dois já prontos."""

    id: str
    #: linha extra no cabeçalho do PDF, embaixo de `titulo_base` (ver `_novo_documento`) —
    #: maiúsculo, mesmo estilo de `titulo_base`.
    titulo_relatorio: str
    #: rótulo do botão de escolha do relatório (`src/ui_relatorio_reforco_empenho.py`) — mesmo
    #: texto de `titulo_relatorio`, só que em capitalização de leitura normal (não maiúsculo).
    rotulo_escolha: str
    #: última coluna das duas tabelas (detalhado/resumido) — "EMPENHAR (R$)"/"ANULAR (R$)".
    rotulo_coluna_valor: str
    #: rótulo da coluna editável de meses na tela (`src/ui_relatorio_reforco_empenho.py`) —
    #: "Meses a Empenhar"/"Meses a Anular".
    rotulo_coluna_meses: str
    #: rótulo do `st.metric` de total na tela — "Total a Empenhar"/"Total a Anular".
    rotulo_total: str
    #: prefixo do nome do arquivo baixado — "reforco_empenho"/"anulacao_saldo_empenho".
    prefixo_arquivo: str


TIPO_REFORCO = TipoRelatorio(
    id="reforco",
    titulo_relatorio="REFORÇO DE EMPENHO",
    rotulo_escolha="Reforço de Empenho",
    rotulo_coluna_valor="EMPENHAR (R$)",
    rotulo_coluna_meses="Meses a Empenhar",
    rotulo_total="Total a Empenhar",
    prefixo_arquivo="reforco_empenho",
)

TIPO_ANULACAO = TipoRelatorio(
    id="anulacao",
    titulo_relatorio="ANULAÇÃO DE SALDO DE EMPENHO",
    rotulo_escolha="Anulação de Saldo de Empenho (Cancelamento)",
    rotulo_coluna_valor="ANULAR (R$)",
    rotulo_coluna_meses="Meses a Anular",
    rotulo_total="Total a Anular",
    prefixo_arquivo="anulacao_saldo_empenho",
)


def _cabecalho_detalhado(tipo: TipoRelatorio) -> list[str]:
    """Colunas do modelo detalhado, já com o nome final de exibição — nesta ordem. "ITEM
    LIC." (pedido explícito: "o item da licitação tem que ser uma coluna do modelo
    detalhado") — só no modelo detalhado; o modelo resumido (`_cabecalho_resumido`) não pediu
    essa coluna. Em branco para Bolsas e Auxílios (sem esse conceito, ver `item_licitacao` em
    `linhas_para_processo`) e para contrato de item único (não chega a ficar redundante porque
    "ITEM DE DESPESA" só ganha o sufixo "— Item N" quando o contrato tem mais de um item)."""

    return [
        "PROCESSO", "ITEM DE DESPESA", "ITEM LIC.", "UNIDADE", "AÇÃO", "PTRES", "FONTE", "ND",
        "UGR", "PI", "EMPENHO", tipo.rotulo_coluna_valor,
    ]


def processos_disponiveis(df: pd.DataFrame, spec: EspecificacaoRelatorio) -> list[str]:
    """Processos distintos da base, com NE reconhecível (sem NE não há o que reforçar) —
    para popular o seletor da página, ordenados do mais frequente para o menos frequente
    (processo que agrupa mais itens de reforço primeiro, atalho útil no dia a dia)."""

    com_ne = df[df["ne_curta"].notna() & df[spec.coluna_processo].notna()]
    return com_ne[spec.coluna_processo].value_counts().index.tolist()


_COLUNAS_LINHAS = [
    "processo", "item_despesa", "item_despesa_base", "unidade_cod", "acao_cod", "ptres",
    "fonte_cod", "natureza_despesa_cod", "ugr_cod", "pi_cod", "ne_curta", "valor_mensal",
    "saldo", "meses_sugeridos", "item_licitacao",
]

#: colunas intermediárias, usadas só por `_com_sugestao_por_calendario` — descartadas do
#: resultado final de `linhas_para_processo` (ver docstring de `coluna_valor_empenhado`).
_COLUNAS_CALENDARIO = ["_valor_empenhado_item", "_inicio_execucao_mes", "_meses_no_ano"]


def _linha_base(linha: pd.Series, spec: EspecificacaoRelatorio) -> dict:
    return {
        "processo": linha[spec.coluna_processo],
        "unidade_cod": linha["unidade_cod"],
        "acao_cod": linha["acao_cod"],
        "ptres": linha["ptres"],
        "fonte_cod": linha["fonte_cod"],
        "natureza_despesa_cod": linha["natureza_despesa_cod"],
        "ugr_cod": linha["ugr_cod"],
        "pi_cod": linha["pi_cod"],
        "ne_curta": linha["ne_curta"],
        # saldo, igual a meses_sugeridos logo abaixo, é sempre no nível da NE inteira — nunca
        # rateado por item (a liquidação não é dividida por item, ver docstring de
        # `coluna_itens`/`coluna_saldo`), mesmo valor repetido em toda linha expandida do mesmo
        # contrato.
        "saldo": linha.get(spec.coluna_saldo) if spec.coluna_saldo else None,
        # meses_sugeridos é sempre no nível da NE (liquidação não é dividida por item, ver
        # docstring de `coluna_itens`) — igual em toda linha expandida do mesmo contrato. Pode
        # ser substituído pela sugestão "por calendário" logo abaixo, ver
        # `_com_sugestao_por_calendario`.
        "meses_sugeridos": linha["meses_a_empenhar"],
        "item_licitacao": None,
        # "ITEM DE DESPESA" sem o sufixo "— Item N" — usado só pelo modelo detalhado do PDF
        # (`gerar_pdf_detalhado`), que já tem "ITEM LIC." como coluna própria (pedido
        # explícito de correção: o sufixo ali ficou redundante com a coluna nova). O editor na
        # tela e o modelo resumido (sem essa coluna) continuam usando `item_despesa` (com
        # sufixo) — ver `_linhas_expandidas_por_item`.
        "item_despesa_base": None,
        "_valor_empenhado_item": linha.get(spec.coluna_valor_empenhado) if spec.coluna_valor_empenhado else None,
        "_inicio_execucao_mes": linha.get(spec.coluna_inicio_execucao) if spec.coluna_inicio_execucao else None,
        # meses_no_ano, como saldo/meses_sugeridos acima, nunca é rateado por item — é o total
        # de meses que o CONTRATO/NE inteiro é pago no exercício, não do item de licitação.
        "_meses_no_ano": linha.get(spec.coluna_meses_no_ano) if spec.coluna_meses_no_ano else None,
    }


def _linhas_expandidas_por_item(filtrado: pd.DataFrame, spec: EspecificacaoRelatorio) -> list[dict]:
    """Uma linha por item de licitação do contrato — o item não existe como registro próprio
    no cadastro (`spec.coluna_itens`, lista de `{"numero","percentual"}` dentro do registro do
    contrato/NE), só aqui na hora do relatório: `valor_mensal` do item é o valor mensal do
    contrato inteiro rateado pelo percentual daquele item. "Fornecedor" vira
    "Fornecedor — Item N" só quando o contrato tem mais de um item (senão o número só
    acrescentaria ruído a uma informação que já é óbvia). `_valor_empenhado_item` (usado só
    pela sugestão "por calendário") é rateado pelo mesmo percentual, mesmo critério de
    `valor_mensal`."""

    linhas = []
    for _, linha in filtrado.iterrows():
        itens = linha[spec.coluna_itens]
        if not isinstance(itens, list) or not itens:
            itens = [{"numero": 1, "percentual": 100.0}]
        rotulo_base = str(linha[spec.coluna_item_despesa])
        valor_mensal_total = linha[spec.coluna_valor_mensal]
        varios = len(itens) > 1
        for item in itens:
            percentual = float(item.get("percentual", 100.0))
            rotulo = f"{rotulo_base} — Item {item.get('numero')}" if varios else rotulo_base
            base = _linha_base(linha, spec)
            base["item_despesa"] = rotulo
            base["item_despesa_base"] = rotulo_base
            base["item_licitacao"] = item.get("numero")
            base["valor_mensal"] = (
                float(valor_mensal_total) * percentual / 100 if pd.notna(valor_mensal_total) else float("nan")
            )
            valor_empenhado_total = base["_valor_empenhado_item"]
            base["_valor_empenhado_item"] = (
                float(valor_empenhado_total) * percentual / 100
                if valor_empenhado_total is not None and pd.notna(valor_empenhado_total) else None
            )
            linhas.append(base)
    return linhas


def _com_sugestao_por_calendario(resultado: pd.DataFrame, ano_referencia: int) -> pd.DataFrame:
    """Substitui `meses_sugeridos` pela sugestão "por calendário" (pedido explícito: "fique
    pronto para empenhar o que falta para o mês vigente" — ver
    `necessidade_ate_mes_vigente`) em toda linha com mês de início conhecido; linha sem
    início conhecido mantém `meses_sugeridos` como estava (execução: empenhado − liquidado).
    As colunas intermediárias (`_COLUNAS_CALENDARIO`) nunca aparecem no resultado final.

    `ano_referencia` é o exercício do cadastro em tela (não necessariamente o ano corrente do
    calendário) — repassado a `necessidade_ate_mes_vigente` para não misturar o mês real de
    hoje com um `inicio_execucao_mes` de um exercício diferente (ver docstring de lá).

    `_meses_no_ano` (teto da sugestão, pedido explícito — ver docstring de
    `coluna_meses_no_ano`) é sempre repassado como Series, mesmo em Contratos Contínuos (sem
    esse conceito): fica inteira `NA` nesse caso, e `Series.clip(upper=NA)` não recorta nada
    (NaN no limite = sem limite), então o comportamento de lá não muda."""

    if resultado.empty or "_inicio_execucao_mes" not in resultado.columns:
        return resultado.drop(columns=_COLUNAS_CALENDARIO, errors="ignore")

    meses_calendario, _ = necessidade_ate_mes_vigente(
        resultado["valor_mensal"], resultado["_valor_empenhado_item"], resultado["_inicio_execucao_mes"],
        ano_referencia, meses_no_ano=resultado["_meses_no_ano"],
    )
    resultado["meses_sugeridos"] = meses_calendario.where(meses_calendario.notna(), resultado["meses_sugeridos"])
    return resultado.drop(columns=_COLUNAS_CALENDARIO, errors="ignore")


def linhas_para_processo(
    df: pd.DataFrame, spec: EspecificacaoRelatorio, processo: str, ano_referencia: int
) -> pd.DataFrame:
    """Linhas do processo escolhido, no esquema comum do relatório (independente da base de
    origem) — `meses_sugeridos` vem de `meses_a_empenhar` (já calculado na leitura da base),
    ponto de partida para a edição por linha na página, não o valor final. Linhas sem NE
    reconhecível ficam de fora — não há empenho para reforçar (a bolsa/contrato ainda não foi
    empenhado), mesmo critério de `processos_disponiveis`.

    `ano_referencia` é o exercício do cadastro em tela — ver docstring de
    `_com_sugestao_por_calendario`/`necessidade_ate_mes_vigente`.

    Um contrato pode virar mais de uma linha aqui — um item de licitação por linha (ver
    `_linhas_expandidas_por_item`/`coluna_itens`), cada uma com o valor mensal do contrato
    rateado pelo percentual daquele item, nunca agregados nem colapsados: o relatório precisa
    mostrar o valor a empenhar de cada item separadamente (pedido explícito). Em Bolsas e
    Auxílios (sem `coluna_itens`), continua uma linha por processo/NE, sem expansão.

    `meses_sugeridos` pode ser substituído pela sugestão "por calendário" quando o mês de
    início da execução é conhecido — ver `_com_sugestao_por_calendario`/
    `necessidade_ate_mes_vigente` (pedido explícito, só afeta a sugestão inicial)."""

    filtrado = df[(df[spec.coluna_processo] == processo) & df["ne_curta"].notna()]

    if spec.coluna_itens and spec.coluna_itens in filtrado.columns:
        resultado = pd.DataFrame(
            _linhas_expandidas_por_item(filtrado, spec), columns=[*_COLUNAS_LINHAS, *_COLUNAS_CALENDARIO]
        )
    else:
        resultado = pd.DataFrame(
            {
                "processo": filtrado[spec.coluna_processo],
                "item_despesa": filtrado[spec.coluna_item_despesa],
                # sem `coluna_itens` nunca tem sufixo "— Item N" pra tirar — mesmo texto de
                # "item_despesa" (ver docstring de `_linha_base`).
                "item_despesa_base": filtrado[spec.coluna_item_despesa],
                "unidade_cod": filtrado["unidade_cod"],
                "acao_cod": filtrado["acao_cod"],
                "ptres": filtrado["ptres"],
                "fonte_cod": filtrado["fonte_cod"],
                "natureza_despesa_cod": filtrado["natureza_despesa_cod"],
                "ugr_cod": filtrado["ugr_cod"],
                "pi_cod": filtrado["pi_cod"],
                "ne_curta": filtrado["ne_curta"],
                "valor_mensal": filtrado[spec.coluna_valor_mensal],
                "saldo": (
                    filtrado[spec.coluna_saldo]
                    if spec.coluna_saldo and spec.coluna_saldo in filtrado.columns else pd.NA
                ),
                "meses_sugeridos": filtrado["meses_a_empenhar"],
                # sem `coluna_itens` (Bolsas e Auxílios) não há número de item — coluna
                # presente mas sempre nula, pro esquema ficar igual ao de Contratos Contínuos
                # (`gerar_pdf_detalhado` lê essa coluna pelas duas bases).
                "item_licitacao": pd.NA,
                "_valor_empenhado_item": (
                    filtrado[spec.coluna_valor_empenhado]
                    if spec.coluna_valor_empenhado and spec.coluna_valor_empenhado in filtrado.columns else pd.NA
                ),
                "_inicio_execucao_mes": (
                    filtrado[spec.coluna_inicio_execucao]
                    if spec.coluna_inicio_execucao and spec.coluna_inicio_execucao in filtrado.columns else pd.NA
                ),
                "_meses_no_ano": (
                    filtrado[spec.coluna_meses_no_ano]
                    if spec.coluna_meses_no_ano and spec.coluna_meses_no_ano in filtrado.columns else pd.NA
                ),
            }
        )
    resultado = _com_sugestao_por_calendario(resultado, ano_referencia)
    return resultado.reset_index(drop=True)


def excluir_linhas_zeradas(linhas: pd.DataFrame) -> pd.DataFrame:
    """Remove linhas com `meses` OU `empenhar` igual a zero (pedido explícito) — zero não é
    "sem dado" (`NaN`, que continua na saída — ver `_formatar_valor`), é "não há o que
    reforçar/anular aqui" (mesmo critério para os dois tipos de relatório — em Anulação, toda
    linha começa zerada por padrão, ver `TIPO_ANULACAO`, então só entra no PDF quem foi
    editado), então não deve entrar no PDF final. A tela de edição continua mostrando essas
    linhas (a exclusão é só para gerar o relatório, ver `render_botao_relatorio`)."""

    return linhas[(linhas["meses"] != 0) & (linhas["empenhar"] != 0)]


def _formatar_valor(valor: float) -> str:
    # NaN acontece quando "Meses a Empenhar" fica sem preencher (linha cujo cálculo de
    # necessidade não deu um número — dado incompleto na origem, ver `meses_a_empenhar` em
    # `necessidade_empenho.py`) — "—" em vez de "nan" no PDF, mesmo critério de nulo ≠ zero
    # do resto do projeto.
    if pd.isna(valor):
        return "—"
    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


#: larguras de coluna (pt) calibradas para landscape(A4) com margem de 15mm dos dois lados
#: (~756pt úteis) — soma abaixo fica dentro desse limite. Sem largura explícita, o reportlab
#: dimensiona cada coluna pelo conteúdo mais largo (a descrição do item de despesa, em geral
#: bem mais longa que as demais colunas), empurrando "EMPENHAR (R$)" para fora da página —
#: por isso "Item de Despesa" (e "Processo", mais curto mas por segurança) usam `Paragraph`
#: em vez de string simples, para quebrar linha dentro da largura fixa, não estourá-la.
_LARGURAS_COLUNA_DETALHADO = [66, 175, 36, 42, 38, 42, 34, 38, 38, 62, 62, 62]

#: Modelo "resumido" (ver `gerar_pdf_resumido`): sem Unidade/Empenho, Item de Despesa ganha o
#: espaço que sobra.
#: pedido explícito de correção: o modelo resumido tinha virado quase idêntico ao detalhado (1
#: linha por item, só 2 colunas a menos) — "tabela dinâmica" aqui significa de volta ao que
#: era: um rollup orçamentário (Ação/PTRES/Fonte/ND/PI/UGR), sem coluna de fornecedor/item de
#: despesa — ver `_agrupado_por_classificacao`.
def _cabecalho_resumido(tipo: TipoRelatorio) -> list[str]:
    return ["AÇÃO", "PTRES", "FONTE", "ND", "PI", "UGR", tipo.rotulo_coluna_valor]


_LARGURAS_COLUNA_RESUMIDO = [85, 95, 85, 95, 135, 95, 140]
_COLUNAS_CLASSIFICACAO_RESUMIDO = ["acao_cod", "ptres", "fonte_cod", "natureza_despesa_cod", "pi_cod", "ugr_cod"]


def _agrupado_por_classificacao(linhas: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por combinação única de Ação/PTRES/Fonte/ND/PI/UGR, com "empenhar" somado
    entre todos os itens/fornecedores daquele grupo — visão orçamentária pura (pedido
    explícito: "tabela dinâmica", "só com as informações orçamentárias"), diferente das linhas
    de `linhas_para_processo` (1 por item/fornecedor, usadas pelo editor na tela e pelo modelo
    detalhado). Ordenada pelas próprias colunas de classificação, não por valor — mesmo
    critério de leitura de uma Tabela Dinâmica do Excel (agrupada, não ordenada por
    magnitude)."""

    # min_count=1: grupo cujas linhas são todas NaN (sem despesa mensal cadastrada, ver
    # `_formatar_valor`) soma NaN, não 0 — sem isso, "sem dado" (que `excluir_linhas_zeradas`
    # deixa passar de propósito, distinto de zero) virava silenciosamente "0,00" aqui.
    agrupado = linhas.groupby(_COLUNAS_CLASSIFICACAO_RESUMIDO, dropna=False, as_index=False)["empenhar"].sum(
        min_count=1
    )
    return agrupado.sort_values(_COLUNAS_CLASSIFICACAO_RESUMIDO)


def _celula_texto(texto: str, estilo) -> Paragraph:
    return Paragraph(str(texto), estilo)


def _novo_documento(
    spec: EspecificacaoRelatorio, tipo: TipoRelatorio, processo: str
) -> tuple[BytesIO, SimpleDocTemplate, list, object]:
    """Base comum aos dois modelos de PDF — página paisagem, cabeçalho com título/base/tipo, e
    o estilo de célula usado nas colunas de texto livre (quebra de linha dentro da largura
    fixa da coluna, ver `_LARGURAS_COLUNA_*`). `tipo.titulo_relatorio` ("REFORÇO DE EMPENHO"/
    "ANULAÇÃO DE SALDO DE EMPENHO") aparece como uma terceira linha de cabeçalho, embaixo de
    `titulo_base` — só isso muda entre os dois tipos de relatório neste cabeçalho."""

    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
    )
    estilos = getSampleStyleSheet()
    estilo_celula = estilos["Normal"].clone("celula")
    estilo_celula.fontSize = 7
    estilo_celula.leading = 8.5

    elementos = [
        Paragraph(spec.titulo_orgao, estilos["Heading3"]),
        Paragraph(spec.titulo_base, estilos["Heading3"]),
        Paragraph(tipo.titulo_relatorio, estilos["Heading4"]),
        Paragraph(f"Processo: {processo}", estilos["Normal"]),
        Spacer(1, 8),
    ]
    return buffer, documento, elementos, estilo_celula


def _estilo_tabela(indice_inicio_alinhamento_direita: int) -> TableStyle:
    return TableStyle(
        [
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDDDDD")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (indice_inicio_alinhamento_direita, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F5F5")]),
        ]
    )


def gerar_pdf_detalhado(spec: EspecificacaoRelatorio, tipo: TipoRelatorio, processo: str, linhas: pd.DataFrame) -> bytes:
    """PDF "modelo detalhado" da PROPLAD — uma linha por item, com Processo/Unidade/Empenho
    repetidos em cada linha, em ordem alfabética por "Item de Despesa" (pedido explícito) —
    case-insensitive (`str.casefold`, mesmo critério de
    `app_pages/contratos_continuos.py`::"Carteira de contratos"), sem alterar a ordem da
    tabela editável na tela nem do modelo resumido (`gerar_pdf_resumido`, não pedido). A
    ordenação usa `item_despesa` (com sufixo "— Item N", que também ordena os itens de um
    mesmo fornecedor entre si), mas a célula exibida é `item_despesa_base` (sem o sufixo —
    pedido explícito de correção: com "ITEM LIC." como coluna própria aqui, o sufixo no nome
    ficou redundante; o editor na tela e o modelo resumido, sem essa coluna, continuam com o
    sufixo). `linhas` já traz a coluna `empenhar` final (após edição por linha na página) —
    esta função só formata e desenha, não recalcula nada. `tipo` só troca o rótulo da última
    coluna e a linha de título (Reforço/Anulação, ver `_novo_documento`) — a estrutura em si é
    idêntica para os dois."""

    buffer, documento, elementos, estilo_celula = _novo_documento(spec, tipo, processo)

    linhas = linhas.sort_values("item_despesa", key=lambda coluna: coluna.str.casefold())

    dados = [_cabecalho_detalhado(tipo)]
    for linha in linhas.itertuples():
        item_lic = getattr(linha, "item_licitacao", None)
        item_despesa_exibido = getattr(linha, "item_despesa_base", None) or linha.item_despesa
        dados.append(
            [
                _celula_texto(linha.processo, estilo_celula),
                _celula_texto(item_despesa_exibido, estilo_celula),
                str(int(item_lic)) if pd.notna(item_lic) else "—",
                str(linha.unidade_cod), str(linha.acao_cod), str(linha.ptres),
                str(linha.fonte_cod), str(linha.natureza_despesa_cod), str(linha.ugr_cod),
                str(linha.pi_cod), str(linha.ne_curta), _formatar_valor(float(linha.empenhar)),
            ]
        )
    total = float(linhas["empenhar"].sum())
    dados.append(["", "", "", "", "", "", "", "", "", "", "TOTAL", _formatar_valor(total)])

    tabela = Table(dados, colWidths=_LARGURAS_COLUNA_DETALHADO, repeatRows=1)
    tabela.setStyle(_estilo_tabela(indice_inicio_alinhamento_direita=2))
    elementos.append(tabela)
    documento.build(elementos)
    return buffer.getvalue()


def gerar_pdf_resumido(spec: EspecificacaoRelatorio, tipo: TipoRelatorio, processo: str, linhas: pd.DataFrame) -> bytes:
    """PDF "modelo resumido" da PROPLAD — layout de Tabela Dinâmica do Excel impresso (pedido
    explícito de correção): uma linha por combinação única de Ação/PTRES/Fonte/ND/PI/UGR, com
    o valor da última coluna somado entre todos os itens/fornecedores daquele grupo — visão
    orçamentária, não por credor (sem coluna de fornecedor/item de despesa, sem Unidade/
    Empenho). Processo aparece uma vez só no cabeçalho da página, não repetido linha a linha.
    `linhas` já traz a coluna `empenhar` final (após edição por linha na página) — esta função
    só agrupa/soma e desenha, não recalcula o valor de cada linha original (ver
    `_agrupado_por_classificacao`). `tipo` só troca o rótulo da última coluna e a linha de
    título (Reforço/Anulação, ver `_novo_documento`)."""

    buffer, documento, elementos, estilo_celula = _novo_documento(spec, tipo, processo)

    agrupado = _agrupado_por_classificacao(linhas)

    dados = [_cabecalho_resumido(tipo)]
    for linha in agrupado.itertuples():
        dados.append(
            [
                str(linha.acao_cod), str(linha.ptres), str(linha.fonte_cod),
                str(linha.natureza_despesa_cod), str(linha.pi_cod), str(linha.ugr_cod),
                # sem float(...) antes: grupo "sem dado" (min_count=1 em
                # `_agrupado_por_classificacao`) chega aqui como `None`, não `float('nan')` —
                # `float(None)` levanta TypeError; `_formatar_valor` já trata `pd.isna` sozinho.
                _formatar_valor(linha.empenhar),
            ]
        )
    total = float(agrupado["empenhar"].sum())
    dados.append(["", "", "", "", "", "TOTAL", _formatar_valor(total)])

    tabela = Table(dados, colWidths=_LARGURAS_COLUNA_RESUMIDO, repeatRows=1)
    tabela.setStyle(_estilo_tabela(indice_inicio_alinhamento_direita=0))
    elementos.append(tabela)
    documento.build(elementos)
    return buffer.getvalue()
