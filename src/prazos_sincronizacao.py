"""
Sincronização bidirecional entre o cadastro de Prazos Orçamentários e o Google Agenda.

Camada: regra de negócio da integração. Não acessa a rede diretamente — recebe um cliente com
a interface de `src.google_agenda.ClienteGoogleAgenda` (injeção), o que permite testar toda a
conciliação com um cliente falso. Não importa Streamlit.

Regras (decididas com o usuário em 27/09/2026 — ver
`docs/superpowers/specs/2026-09-27-google-agenda-design.md`):
- todo prazo vira um evento de DIA INTEIRO no calendário principal;
- só título, data e descrição são editáveis pelo Google; tipo, categoria, prioridade,
  responsável e antecedência viajam em `extendedProperties.private` e só se editam aqui;
- lembrete do Google limitado a 28 dias (limite da API); a criticidade "Vencendo" do
  BudgetLab continua usando `dias_antecedencia` integral;
- evento excluído no Google → prazo CONCLUÍDO (nunca excluído);
- prazo excluído no BudgetLab → evento excluído no Google;
- os dois lados alterados → vence o mais recente, sempre registrado no resumo com o valor
  descartado (rastreabilidade: nada é sobrescrito sem registro).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from src.google_agenda import MARCADOR, MARCADOR_BUDGETLAB
from src.prazos_orcamentarios import DIAS_ANTECEDENCIA_PADRAO, PRIORIDADE_PADRAO, TIPO_PADRAO

#: limite da Calendar API para lembretes (40320 minutos = 4 semanas).
DIAS_MAXIMOS_LEMBRETE = 28
#: só visual: acrescentá-lo ou removê-lo no Google NÃO altera `concluido`.
PREFIXO_CONCLUIDO = "✓ "
INTERVALO_SINCRONIZACAO_AUTOMATICA = timedelta(minutes=5)


class ErroSincronizacao(ValueError):
    """Evento do Google que não pode ser aplicado ao prazo (ex.: título vazio)."""


def corpo_evento(prazo: dict) -> dict:
    data = date.fromisoformat(prazo["data_prazo"])
    dias_antecedencia = int(prazo.get("dias_antecedencia", DIAS_ANTECEDENCIA_PADRAO))
    minutos = min(dias_antecedencia, DIAS_MAXIMOS_LEMBRETE) * 1440
    return {
        "summary": (PREFIXO_CONCLUIDO if prazo.get("concluido") else "") + prazo["titulo"],
        "description": prazo.get("descricao", ""),
        "start": {"date": data.isoformat()},
        "end": {"date": (data + timedelta(days=1)).isoformat()},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutos}]},
        "extendedProperties": {"private": {
            MARCADOR_BUDGETLAB: "1",
            MARCADOR: str(prazo["id"]),
            "tipo": str(prazo.get("tipo", TIPO_PADRAO)),
            "categoria": str(prazo.get("categoria", "")),
            "prioridade": str(prazo.get("prioridade", PRIORIDADE_PADRAO)),
            "responsavel": str(prazo.get("responsavel", "")),
            "dias_antecedencia": str(dias_antecedencia),
        }},
    }


def campos_do_evento(evento: dict) -> dict:
    """Os 3 campos editáveis pelo Google, prontos para gravação. Rejeita evento sem título ou
    sem data (o prazo local fica intacto e o erro vai para o resumo)."""

    titulo = evento["titulo"].strip()
    if titulo.startswith(PREFIXO_CONCLUIDO.strip()):
        titulo = titulo[len(PREFIXO_CONCLUIDO.strip()):].strip()
    if not titulo:
        raise ErroSincronizacao("evento sem título no Google Agenda — alteração não aplicada.")
    if evento["data_inicio"] is None:
        raise ErroSincronizacao("evento sem data no Google Agenda — alteração não aplicada.")
    return {
        "titulo": titulo,
        "data_prazo": evento["data_inicio"].isoformat(),
        "descricao": evento["descricao"],
    }


def sincronizacao_devida(
    ultima: datetime | None, agora: datetime,
    intervalo: timedelta = INTERVALO_SINCRONIZACAO_AUTOMATICA,
) -> bool:
    """Controle da sincronização automática ao abrir a página (o Streamlit reexecuta o
    script a cada clique — sem este limite cada interação chamaria a API)."""

    return ultima is None or agora - ultima >= intervalo
