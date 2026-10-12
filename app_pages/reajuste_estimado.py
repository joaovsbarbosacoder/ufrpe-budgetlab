"""Reajuste estimado — página própria no grupo "Contratos" (12/10/2026).

Antes era uma seção dentro de Contratos Contínuos (11/10/2026); a pedido do usuário virou página independente, repaginada
(`src/ui_reajuste.py` + `src/ui_reajuste_visual.py`). Os cálculos continuam em `src/estimativa_reajuste.py` e o cenário
continua SEPARADO: nada aqui altera a Necessidade de Empenho, a Projeção nem os aditivos, exceto por ação explícita do
usuário (configurar o reajuste do contrato ou registrar o aditivo previsto).

Dados: cadastro nativo de Contratos Contínuos do exercício escolhido, fotografia atual do Contratos.gov.br (opcional:
liga o contrato ao gov, traz o início da vigência e os reajustes formalizados) e a Liquidação por Competência (opcional:
base do reajuste; sem ela o liquidado fica vazio e a base é o valor contratado). Sem `main()`/`st.set_page_config`
próprios (`app.py` já chama isso).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src import contratosgov_extracao
from src.contratos_cadastro import montar_contratos, montar_empenhos, montar_termos
from src.contratos_continuos import com_contratosgov
from src.contratos_continuos_cadastro import anos_disponiveis, carregar_contratos, como_dataframe
from src.estimativa_reajuste import termos_do_gov
from src.execucao_ne_utils import ne_curta
from src.liquidacao_competencia import ler_liquidacao_competencia, liquidado_por_ne_e_mes
from src.ui_reajuste import render_estimativa_reajuste
from src.ui_theme import render_page_header

CAMINHO_LIQUIDACAO_COMPETENCIA = Path("data/raw") / "Liquidação por Competência.xlsx"


@st.cache_data(show_spinner="Lendo a Liquidação por Competência (mensal)...")
def _liquidacao_competencia_por_mes(caminho: str, mtime: float) -> pd.DataFrame:
    """Liquidado por (NE, mês de referência), com `ne_curta`. `mtime` só participa da chave de cache."""

    tempo = liquidado_por_ne_e_mes(ler_liquidacao_competencia(caminho))
    tempo["ne_curta"] = tempo["ne_ccor"].apply(ne_curta)
    return tempo


def _referencia() -> date:
    """Data de referência: hoje, ou `contratos_referencia` em `st.session_state` (gancho só para testes determinísticos,
    o mesmo de `app_pages/contratos.py` e `app_pages/contratos_continuos.py`)."""

    valor = st.session_state.get("contratos_referencia")
    return valor if isinstance(valor, date) else date.today()


render_page_header(
    "Reajuste estimado",
    "Quanto os contratos devem subir com os reajustes previstos, por competência. Cenário separado: não altera nada do resto.",
)

anos = anos_disponiveis()
if not anos:
    st.warning("Nenhum exercício cadastrado ainda em Contratos Contínuos — cadastre os contratos antes de estimar o reajuste.")
    st.stop()

ano = st.selectbox("Exercício", sorted(anos, reverse=True), key="reajuste_estimado_ano")

try:
    registros = carregar_contratos(ano)
    dataframe = como_dataframe(registros, ano)
    todos_registros = [r for _ano in anos for r in carregar_contratos(_ano)]
except Exception as erro:
    st.error(f"Não foi possível ler o cadastro de Contratos Contínuos: {erro}")
    st.stop()

liquidacao_por_mes = None
if CAMINHO_LIQUIDACAO_COMPETENCIA.exists():
    try:
        liquidacao_por_mes = _liquidacao_competencia_por_mes(
            str(CAMINHO_LIQUIDACAO_COMPETENCIA), CAMINHO_LIQUIDACAO_COMPETENCIA.stat().st_mtime
        )
    except Exception as erro:  # arquivo travado pelo Drive, layout novo...
        st.warning(f"Não foi possível ler a Liquidação por Competência ({erro}) — a base do reajuste fica sem liquidado.")

inicio_por_gov: dict = {}
vigencias_por_gov: dict = {}
empenhos_gov = None
try:
    fotografia, _manifesto = contratosgov_extracao.carregar_atual()
    if fotografia is None:
        st.info(
            "Nenhuma fotografia do Contratos.gov.br foi gravada ainda — sem ela os contratos não são ligados ao gov, e as "
            "datas-base e os reajustes formalizados não aparecem. Faça a carga na página Contratos (aba Atualizar)."
        )
    else:
        contratos_gov, termos_gov = montar_contratos(fotografia, _referencia()), montar_termos(fotografia)
        empenhos_gov = montar_empenhos(fotografia)
        inicio_por_gov = dict(zip(contratos_gov["contrato_id"].astype(str), contratos_gov["vigencia_inicio"]))
        # reajustes formalizados (termo aditivo com REAJUSTE) e apostilamentos retroativos de cada contrato do gov
        vigencias_por_gov = termos_do_gov(termos_gov)
        dataframe = com_contratosgov(dataframe, contratos_gov, termos_gov, empenhos_gov)
except Exception as erro:  # manifesto incompleto, arquivo travado pelo Drive, dado inválido...
    st.warning(f"Não foi possível ler a fotografia do Contratos.gov.br ({erro}) — seguindo sem a ligação com o gov.")

render_estimativa_reajuste(
    dataframe, registros, todos_registros, int(ano), liquidacao_por_mes, inicio_por_gov, str(ano), _referencia(),
    vigencias_por_gov, empenhos_gov,
)
