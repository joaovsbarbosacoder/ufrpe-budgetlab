"""
Leitura e normalização da base de vigência de Contratos (BASE_CONTRATOS).

Camada: regra específica de base (não é leitor genérico, não é analítica, não é interface).
Depende só de pandas/openpyxl. Não importa Streamlit.

Origem: planilha "CONTRATOS UFRPE (planilhas Google)", aba "BASE_CONTRATOS" — mantida
manualmente (exportação de Google Sheets), casamento de colunas por NOME normalizado (sem
acento, maiúsculo), mesmo motivo de `src/contratos_continuos.py`/`src/bolsas_auxilios.py`.

Cada linha da aba é um TERMO/evento contratual (contrato inicial, aditivo, apostilamento,
etc.), não um contrato — `ler_contratos_vigencia` devolve essa granularidade bruta, uma linha
por termo (histórico completo, para auditoria). `consolidar_por_contrato` agrega para uma
linha por contrato, usando o termo com maior `termo_final` válido (desempate por
`data_assinatura`, depois pela ordem da linha de origem).

Colunas da origem fora deste esquema (não usadas pela tela): SEQUENCIAL CONTRATO, UASG DA
LICITAÇÃO, LICITAÇÃO, Nº PROCESSO FÍSICO/ELETRÔNICO, TERMO INICIAL, DURAÇÃO, MÊS/ANO DO
VENCIMENTO, SITUAÇÃO, DATA DA PUBLICAÇÃO, VALOR TOTAL ACUMULADO, EMPENHOS, CLASSIFICAÇÃO
CONTÁBIL, UNIDADES BENEFICIÁRIAS, VALOR/VALIDADE DA GARANTIA, DIAS PARA O VENCIMENTO/STATUS
DE CRITICIDADE (recalculados aqui a partir da data de hoje, não lidos da planilha — ver
`classificar_criticidade`), OBSERVAÇÕES, PROVIDÊNCIAS N DIAS, telefone/celular/gestor
substituto, portaria de fiscalização.

Valor mensal/anual do termo mais recente com valor não nulo no histórico do contrato — NÃO
foi homologado pela área responsável (segundo a planilha de origem); tratar como referência
de vigência contratual, não como fonte oficial de execução orçamentária (essa vem de
`src/execucao_anual.py`, cruzada por NE em `src/contratos_continuos.py`).

Contrato público:
    ler_contratos_vigencia(caminho) -> pd.DataFrame      (uma linha por termo)
    consolidar_por_contrato(termos) -> pd.DataFrame      (uma linha por contrato)
    termos_do_contrato(termos, numero_contrato) -> pd.DataFrame
    classificar_criticidade(dias) -> str
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from src.cache_bases import em_cache
from src.leitura_excel import motor_excel

NOME_ABA = "BASE_CONTRATOS"
_EPOCA_EXCEL = datetime(1899, 12, 30)


class ErroLayoutBase(ValueError):
    """Cabeçalho da planilha sem as colunas esperadas — falhar cedo, nunca adivinhar."""


def _normalizar(texto: object) -> str:
    if texto is None:
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem_acento).strip().upper()


#: cabeçalho normalizado (sem acento, maiúsculo) da origem -> nome interno da coluna.
COLUNAS_ORIGEM = {
    "NUMERO CONTRATO": "numero_contrato_raw",
    "ANO DO CONTRATO": "ano_contrato",
    "NOME DO CONTRATADO": "contratado",
    "CNPJ/ CPF DO CONTRATADO": "cnpj_cpf_raw",
    "CLASSIFICACAO DO OBJETO": "classificacao_objeto",
    "NATUREZA DO OBJETO": "natureza_objeto",
    "OBJETO DA CONTRATACAO": "objeto",
    "TERMO": "termo",
    "ARQUIVO PDF": "arquivo_pdf",
    "FINALIDADE DO TERMO": "finalidade_termo",
    "DATA DA ASSINATURA": "data_assinatura_raw",
    "TERMO FINAL": "termo_final_raw",
    "VALOR DO TERMO (R$)": "valor_termo",
    "VALOR MENSAL (R$)": "valor_mensal_planilha",
    "VALOR ANUAL (R$)": "valor_anual_planilha",
    "TIPO DE DESPESA": "tipo_despesa",
    "UNIDADE GESTORA": "unidade_gestora",
    "GARANTIA": "garantia_status",
    "GESTOR": "gestor",
    "E-MAIL": "email_gestor",
}

_COLUNAS_TEXTO = {
    "contratado", "classificacao_objeto", "natureza_objeto", "objeto", "termo", "arquivo_pdf",
    "finalidade_termo", "tipo_despesa", "unidade_gestora", "garantia_status", "gestor", "email_gestor",
}
_COLUNAS_NUMERICAS = {
    "ano_contrato", "valor_termo", "valor_mensal_planilha", "valor_anual_planilha",
}


def _analisar_data(valor: object) -> date | None:
    """Converte serial do Excel, datetime ou texto dd/mm/aaaa em date. None se inválido —
    a origem tem ao menos uma célula de data corrompida (serial fora da faixa válida:
    conferido na extração de 15/08/2026), não pode estourar a leitura inteira."""

    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor == "":
        return None
    if isinstance(valor, (datetime, date)):
        return valor.date() if isinstance(valor, datetime) else valor
    if isinstance(valor, (int, float)):
        try:
            return (_EPOCA_EXCEL + timedelta(days=float(valor))).date()
        except (OverflowError, ValueError):
            return None
    texto = str(valor).strip()
    if not texto or not re.match(r"^\d", texto):
        return None
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    try:
        return (_EPOCA_EXCEL + timedelta(days=float(texto))).date()
    except (ValueError, OverflowError):
        return None


def _ou_vazio(valor: object) -> str:
    return "" if pd.isna(valor) else str(valor)


def classificar_criticidade(dias: int | None) -> str:
    """Classifica a partir dos dias até o vencimento calculados a partir de HOJE — não lida
    da coluna "STATUS DE CRITICIDADE" da planilha, que é um instantâneo desatualizado."""

    if dias is None:
        return "Indeterminado"
    if dias < 0:
        return "Vencido"
    if dias <= 60:
        return "Crítico"
    if dias <= 120:
        return "Atenção"
    return "No prazo"


@em_cache
def ler_contratos_vigencia(caminho: str | Path) -> pd.DataFrame:
    """Lê a aba "BASE_CONTRATOS" e devolve o DataFrame normalizado, uma linha por termo/evento
    contratual — não por contrato (ver `consolidar_por_contrato`)."""

    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(caminho)

    bruto = pd.read_excel(caminho, sheet_name=NOME_ABA, header=0, dtype=object, engine=motor_excel())

    normalizados = {coluna: _normalizar(coluna) for coluna in bruto.columns}
    faltando = set(COLUNAS_ORIGEM) - set(normalizados.values())
    if faltando:
        raise ErroLayoutBase(
            f"Colunas ausentes na aba {NOME_ABA!r} de {caminho.name}: {sorted(faltando)}. "
            "O layout da planilha mudou."
        )

    mapa = {origem: COLUNAS_ORIGEM[norm] for origem, norm in normalizados.items() if norm in COLUNAS_ORIGEM}
    df = bruto.rename(columns=mapa)[list(mapa.values())].copy()
    df["linha_origem"] = df.index + 2  # linha real na planilha (1-indexada, após o cabeçalho)

    # linhas sem número de contrato não são linha de termo válida (não há esse caso na
    # extração de 15/08/2026, mas a regra é a mesma das demais bases deste projeto: nunca
    # tratar como dado uma linha sem a chave principal preenchida).
    df = df[df["numero_contrato_raw"].notna() & (df["numero_contrato_raw"].astype(str).str.strip() != "")]

    for coluna in ("data_assinatura_raw", "termo_final_raw"):
        df[coluna.replace("_raw", "")] = df[coluna].apply(_analisar_data)

    for coluna in _COLUNAS_TEXTO:
        df[coluna] = df[coluna].astype("string").str.strip()

    for coluna in _COLUNAS_NUMERICAS:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")

    df["cnpj_cpf"] = df["cnpj_cpf_raw"].astype("string").str.replace(r"\D", "", regex=True)
    df["numero_contrato"] = df["numero_contrato_raw"].astype("string").str.strip()

    return df.reset_index(drop=True)


def _escolher_termo_atual(grupo: pd.DataFrame) -> pd.Series:
    """Termo com maior `termo_final` válido; desempate por `data_assinatura`, depois pela
    ordem da linha de origem."""

    com_final = grupo[grupo["termo_final"].notna()]
    if len(com_final):
        ordenado = com_final.sort_values(["termo_final", "data_assinatura", "linha_origem"])
        return ordenado.iloc[-1]
    ordenado = grupo.sort_values(["data_assinatura", "linha_origem"])
    return ordenado.iloc[-1]


def consolidar_por_contrato(termos: pd.DataFrame, hoje: date | None = None) -> pd.DataFrame:
    """Uma linha por contrato (`numero_contrato`), a partir do termo atual de cada um (ver
    `_escolher_termo_atual`) — dias/criticidade calculados a partir de `hoje` (padrão:
    `date.today()`, parametrizável para os testes ficarem determinísticos), não da planilha.

    `alertas` é a lista de pendências de qualidade de dado encontradas no termo atual do
    contrato — usada pela tela para a fila de conciliação/qualidade dos dados, não descarta
    nem esconde nenhum contrato com problema.
    """

    hoje = hoje or date.today()
    linhas = []
    for numero, grupo in termos.groupby("numero_contrato", sort=False):
        atual = _escolher_termo_atual(grupo)
        termo_final = atual["termo_final"]
        dias = (termo_final - hoje).days if termo_final else None
        criticidade = classificar_criticidade(dias)

        ordenado = grupo.sort_values(["data_assinatura", "linha_origem"])
        valor_mensal_serie = ordenado["valor_mensal_planilha"].dropna()
        valor_anual_serie = ordenado["valor_anual_planilha"].dropna()
        valor_mensal = float(valor_mensal_serie.iloc[-1]) if len(valor_mensal_serie) else None
        valor_anual = float(valor_anual_serie.iloc[-1]) if len(valor_anual_serie) else None
        if valor_mensal is None and valor_anual is not None:
            valor_mensal = valor_anual / 12
        if valor_anual is None and valor_mensal is not None:
            valor_anual = valor_mensal * 12

        alertas = []
        if termo_final is None:
            alertas.append("Sem termo final")
        if not _ou_vazio(atual.get("gestor")).strip():
            alertas.append("Sem gestor")
        if not _ou_vazio(atual.get("arquivo_pdf")).strip():
            alertas.append("Sem documento")
        cnpj_cpf = atual.get("cnpj_cpf")
        if pd.notna(cnpj_cpf) and len(str(cnpj_cpf)) not in (11, 14):
            alertas.append("CNPJ/CPF suspeito")
        if valor_mensal is None:
            alertas.append("Sem valor mensal")
        if _normalizar(atual.get("garantia_status")) in ("PENDENTE", "NAO REGULARIZADA"):
            alertas.append("Garantia pendente")

        linhas.append(
            {
                "numero_contrato": numero,
                "ano_contrato": atual.get("ano_contrato"),
                "contratado": atual.get("contratado"),
                "cnpj_cpf": cnpj_cpf,
                "objeto": atual.get("objeto"),
                "classificacao_objeto": atual.get("classificacao_objeto"),
                "natureza_objeto": atual.get("natureza_objeto"),
                "tipo_despesa": atual.get("tipo_despesa"),
                "unidade_gestora": atual.get("unidade_gestora"),
                "termo_atual": atual.get("termo"),
                "finalidade_termo_atual": atual.get("finalidade_termo"),
                "termo_final": termo_final,
                "dias_para_vencer": dias,
                "criticidade": criticidade,
                "valor_mensal": valor_mensal,
                "valor_anual": valor_anual,
                "gestor": atual.get("gestor"),
                "email_gestor": atual.get("email_gestor"),
                "garantia_status": atual.get("garantia_status"),
                "arquivo_pdf": atual.get("arquivo_pdf"),
                "qtd_termos": len(grupo),
                "alertas": alertas,
                "linha_origem_atual": atual.get("linha_origem"),
            }
        )

    return pd.DataFrame.from_records(linhas).reset_index(drop=True)


def termos_do_contrato(termos: pd.DataFrame, numero_contrato: str) -> pd.DataFrame:
    grupo = termos[termos["numero_contrato"] == numero_contrato]
    return grupo.sort_values(["data_assinatura", "linha_origem"])
