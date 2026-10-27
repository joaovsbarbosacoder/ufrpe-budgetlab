"""DDP do SIAPE como realizado provisório do mês no painel de Pessoal (27/10/2026).

Prioridade por mês, definida pelo usuário: 1) liquidação na Execução Mensal; 2) DDP guardada,
só até a liquidação aparecer; 3) projeção. `aplicar_ddp` devolve uma CÓPIA da base mensal em
que o mês da DDP ganhou linhas provisórias; o painel então trata o mês como realizado e recalcula
os meses seguintes com as fórmulas de sempre. Nada é gravado nem alterado na base original.

Regras (todas visíveis na tela e no `ResultadoDdp`):

- Só vale se o mês anterior já fechou na Execução Mensal e o mês da DDP ainda não
  (`ultimo_mes_fechado`, o mesmo critério do painel, com os parâmetros da sessão). Com o mês da
  DDP já fechado pela liquidação, a liquidação prevalece e a DDP não é usada — nunca soma as duas.
- A DDP precisa ter servidor e pensionista (senão usaria só metade da folha).
- Natureza da DDP: valor do mês = DDP líquida (servidor + pensionista), distribuída pelas linhas
  (NE, PO, Iduso...) da folha do mês anterior, na proporção do que cada uma liquidou; sem o mês
  anterior, pelo mês mais recente em que a natureza teve linha; sem nenhum, pelos empenhos
  (partes iguais). Sem nenhuma linha-modelo, a natureza NÃO entra no painel e fica listada em
  `sem_destino` com o valor (nada é descartado em silêncio).
- Natureza do painel que a DDP não traz (RPPS patronal, rubricas que não vieram): o mês fica
  com a projeção que o painel já faria para ele (referência no mês anterior).
- Linhas da natureza da DDP em empenhos que não são da folha (favorecido ≠ UG, ex. GEAP direto):
  repetem o mês anterior.
- A liquidação parcial já lançada no mês, nas naturezas tratadas aqui, é substituída pela DDP ou
  pela projeção; o valor aparece em `liquidado_parcial_substituido`.
- A DDP é líquida (bruto − descontos), não a liquidação do SIAFI: em set/2026 a diferença foi de
  R$ 6.971,93 em R$ 54,87 mi (reposição ao erário, cota-parte da creche e diferenças ainda sem
  explicação). Quando a liquidação chegar, ela prevalece.
- Pagamento único (ex.: exercícios anteriores) fica só no mês da DDP: a projeção de nov/dez usa as
  regras de cada rubrica sobre o mês de referência, como sempre — hoje só o 31909211 (ver
  README) é tratado assim, e ele já é projetado sem repetição.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.ddp_siape import ddp_por_natureza, separar_competencias
from src.ddp_siape_arquivos import tem_ddp_completa
from src.despesas_pessoal import PARAMETROS_PADRAO, ParametrosProjecao, grade_mensal, ultimo_mes_fechado

ORIGEM_DDP = "DDP SIAPE (provisório)"
ORIGEM_PROJECAO = "Projeção do painel (DDP aplicada ao mês)"


@dataclass
class ResultadoDdp:
    mensal: pd.DataFrame
    aplicada: bool
    competencia: int | None
    motivo: str
    total_ddp: float | None = None
    total_no_painel: float | None = None
    liquidado_parcial_substituido: float = 0.0
    sem_destino: list[tuple[str, float]] = field(default_factory=list)
    detalhe: pd.DataFrame = field(default_factory=pd.DataFrame)


def _competencia_anterior(ano_mes: int) -> int | None:
    return ano_mes - 1 if ano_mes % 100 > 1 else None


def _mascara_folha(linhas: pd.DataFrame) -> pd.Series:
    if "ne_favorecido" not in linhas or "ug_executora_desc" not in linhas:
        return pd.Series(True, index=linhas.index)  # base sem favorecido: todas as linhas contam como folha
    favorecido = linhas["ne_favorecido"].astype("string").str.strip()
    executora = linhas["ug_executora_desc"].astype("string").str.strip()
    return (favorecido == executora).fillna(False).astype(bool)


def _parcelas_em_centavos(total: float, pesos: pd.Series) -> pd.Series:
    """`total` repartido pelos pesos em centavos; a soma fecha exatamente."""
    base = pesos.clip(lower=0).fillna(0.0)
    parte = base / base.sum() if base.sum() > 0 else pd.Series(1.0 / len(base), index=base.index)
    valores = (parte * total).round(2)
    valores.iloc[int(np.argmax(valores.to_numpy()))] += round(total - valores.sum(), 2)
    return valores


def aplicar_ddp(mensal_df: pd.DataFrame, anual_df: pd.DataFrame, relatorios: list | None,
                parametros: ParametrosProjecao | None = None) -> ResultadoDdp:
    """Ver o docstring do módulo. `relatorios`: DDP/Crédito Bancário de UMA competência (a mais
    recente, se vierem duas). Sem relatórios, devolve a base como está."""
    parametros = parametros or PARAMETROS_PADRAO
    if not relatorios:
        return ResultadoDdp(mensal_df, False, None, "Nenhuma DDP guardada.")
    atuais, _ = separar_competencias(relatorios)
    competencia = atuais[0].competencia

    def nao(motivo: str) -> ResultadoDdp:
        return ResultadoDdp(mensal_df, False, competencia, motivo)

    if not tem_ddp_completa(atuais):
        return nao("A DDP guardada não tem servidor e pensionista; não foi usada no painel.")
    anterior = _competencia_anterior(competencia)
    if anterior is None:
        return nao("DDP de janeiro: não há mês anterior para distribuir a folha; não foi usada no painel.")
    fechado = ultimo_mes_fechado(mensal_df, parametros)
    if fechado is not None and fechado >= competencia:
        return nao("A liquidação do mês já consta na Execução Mensal e prevalece; a DDP guardada não é usada.")
    if fechado != anterior:
        return nao("O mês anterior ainda não fechou na Execução Mensal; a DDP não foi usada no painel.")

    ano, mes = divmod(competencia, 100)
    ddp = ddp_por_natureza(atuais).groupby("natureza_detalhada")["liquido"].sum().round(2)

    # projeção que o painel faria para o mês da DDP, com referência no mês anterior
    grade1 = grade_mensal(mensal_df, anual_df, ano, anterior, parametros).linhas
    projetado: dict[str, float] = {}
    for linha in grade1.itertuples(index=False):
        valor = linha.meses[mes - 1]
        if valor is not None and not pd.isna(valor):
            chave = str(linha.natureza_detalhada_cod)
            projetado[chave] = projetado.get(chave, 0.0) + float(valor)

    do_ano = mensal_df["ano_mes"] // 100 == ano
    itens = mensal_df.loc[do_ano & (mensal_df["tipo_linha"] == "item_execucao")]
    empenhos = mensal_df.loc[do_ano & (mensal_df["tipo_linha"] == "empenho")]
    por_natureza = {str(n): g for n, g in itens.groupby(itens["natureza_detalhada_cod"].astype(str))}
    empenho_por_natureza = {str(n): g for n, g in empenhos.groupby(empenhos["natureza_detalhada_cod"].astype(str))}

    def modelo(natureza: str, so_folha: bool) -> pd.DataFrame | None:
        """Linhas-modelo do mês anterior (ou o mais recente com linha); `None` se não houver."""
        base = por_natureza.get(natureza)
        if base is not None:
            if so_folha:
                base = base.loc[_mascara_folha(base)]
            meses = sorted((m for m in base["ano_mes"].unique() if m <= anterior), reverse=True)
            for m in meses:
                linhas = base.loc[base["ano_mes"] == m]
                if float(linhas["liquidada"].fillna(0).clip(lower=0).sum()) > 0:
                    return linhas
            if meses:
                return base.loc[base["ano_mes"] == meses[0]]
        emp = empenho_por_natureza.get(natureza)
        if emp is not None:
            if so_folha:
                emp = emp.loc[_mascara_folha(emp)]
            if len(emp):
                emp = emp.drop_duplicates("ne_ccor").copy()
                emp["tipo_linha"], emp["ne_item_cod"], emp["liquidada"] = "item_execucao", "-9", np.nan
                return emp
        return None

    novas: list[pd.DataFrame] = []
    detalhe: list[dict] = []
    sem_destino: list[tuple[str, float]] = []
    tratadas = set(ddp.index) | set(projetado)

    def adicionar(linhas: pd.DataFrame, valores: pd.Series, origem: str, natureza: str) -> None:
        nova = linhas.copy()
        nova["liquidada"] = valores.to_numpy()
        nova["paga"] = np.nan
        nova["ano_mes"], nova["mes"] = competencia, mes
        nova["arquivo_origem"], nova["aba_origem"], nova["linha_origem"] = origem, origem, np.nan
        nova["provisorio"] = True  # o painel distingue do liquidado real (ex.: razão do patronal do RPPS)
        novas.append(nova)
        detalhe.append({"natureza_detalhada": natureza, "origem": origem, "valor": round(float(valores.sum()), 2),
                        "linhas": len(nova)})

    for natureza in sorted(tratadas):
        if natureza in ddp.index:
            alvo = float(ddp[natureza])
            linhas = modelo(natureza, so_folha=True)
            if linhas is None:
                sem_destino.append((natureza, alvo))
            else:
                adicionar(linhas, _parcelas_em_centavos(alvo, linhas["liquidada"].reset_index(drop=True)).set_axis(linhas.index),
                          ORIGEM_DDP, natureza)
            # empenhos fora da folha (ex. GEAP direto) repetem o mês anterior
            base = por_natureza.get(natureza)
            if base is not None:
                fora = base.loc[(base["ano_mes"] == anterior) & ~_mascara_folha(base)]
                if len(fora):
                    adicionar(fora, fora["liquidada"].fillna(0.0).reset_index(drop=True).set_axis(fora.index),
                              ORIGEM_PROJECAO, natureza)
        else:
            alvo = projetado[natureza]
            linhas = modelo(natureza, so_folha=False)
            if linhas is None:
                if abs(alvo) >= 0.005:
                    sem_destino.append((natureza, alvo))
                continue
            adicionar(linhas, _parcelas_em_centavos(alvo, linhas["liquidada"].reset_index(drop=True)).set_axis(linhas.index),
                      ORIGEM_PROJECAO, natureza)

    do_mes = (mensal_df["ano_mes"] == competencia) & (mensal_df["tipo_linha"] == "item_execucao")
    substituidas = do_mes & mensal_df["natureza_detalhada_cod"].astype(str).isin(tratadas)
    parcial = float(mensal_df.loc[substituidas, "liquidada"].sum(min_count=1) or 0.0)
    final = pd.concat([mensal_df.loc[~substituidas], *novas], ignore_index=True) if novas else mensal_df.loc[~substituidas]

    detalhe_df = pd.DataFrame(detalhe, columns=["natureza_detalhada", "origem", "valor", "linhas"])
    total_ddp = float(ddp.sum())
    alocado = float(detalhe_df.loc[detalhe_df["origem"] == ORIGEM_DDP, "valor"].sum())
    return ResultadoDdp(
        mensal=final, aplicada=True, competencia=competencia,
        motivo="Liquidação do mês ainda não fechou; valores da DDP (naturezas fora da DDP, pela projeção).",
        total_ddp=total_ddp, total_no_painel=alocado, liquidado_parcial_substituido=round(parcial, 2),
        sem_destino=sem_destino, detalhe=detalhe_df,
    )
