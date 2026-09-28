# Integração com o Google Agenda — Gerenciamento de Prazos

Data: 27/09/2026
Status: design aprovado em conversa; spec aguardando revisão do usuário.

## Objetivo

Ligar a aba **Gerenciamento de Prazos** (`app_pages/painel_prazos.py`) ao calendário
principal do Google do usuário, com duas funcionalidades que compartilham a mesma conexão:

- **A. Visualizar a agenda** — ver no BudgetLab os eventos do calendário principal
  (inclusive reuniões em que o usuário é convidado) dos próximos 30 dias.
- **B. Sincronizar prazos nos dois sentidos** — cada prazo cadastrado vira um evento no
  calendário principal; alterações feitas em qualquer um dos lados são refletidas no outro.

## Decisões confirmadas com o usuário

| Tema | Decisão |
|---|---|
| Direção | Bidirecional para prazos; somente leitura para os demais eventos. |
| Escopo | Todos os prazos (`Calendário anual` e `Solicitação`). |
| Calendário | Calendário principal (`primary`) — necessário para ver reuniões. |
| Evento excluído no Google | Marca o prazo como **concluído** (não exclui o cadastro). |
| Disparo | Ao abrir a página (com intervalo mínimo) e pelo botão "Sincronizar agora". Sem sincronização em segundo plano nem webhooks (app local, sem endereço público). |
| Lembrete | Antecedência do lembrete no Google limitada a 28 dias (limite da API). A criticidade "Vencendo" do BudgetLab continua usando `dias_antecedencia` integral. |
| Persistência nova | Aprovada: token OAuth e credenciais do cliente em `data/google_agenda/`, fora do git. |
| Dependências novas | Aprovadas: `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`. |

## Fora de escopo

- Outros calendários além do principal; calendários compartilhados.
- Sincronização de Contratos, Bolsas, TEDs ou qualquer outra base.
- Importação automática de eventos comuns como prazos (só via botão explícito, ver A).
- Uso por mais de uma máquina/usuário sobre a mesma pasta de dados.
- Sincronização em segundo plano, webhooks ou notificações push.

## Arquitetura

```
app_pages/painel_prazos.py          (UI: bloco "Google Agenda" + seção "Agenda")
        │
        ├── src/prazos_sincronizacao.py   (conciliação prazo ↔ evento; sem rede, testável)
        │         │
        │         └── src/prazos_orcamentarios.py   (cadastro; ganha campos de sincronização)
        │
        └── src/google_agenda.py          (OAuth + chamadas à API; único módulo com rede)
```

- `src/google_agenda.py` não conhece prazos: expõe eventos como dicionários simples.
- `src/prazos_sincronizacao.py` não conhece a API do Google: recebe um objeto cliente com
  a interface abaixo, o que permite testar toda a conciliação com um cliente falso em memória.
- Nenhum dos dois importa Streamlit (mesmo padrão dos demais módulos de `src/`).

### `src/google_agenda.py`

Constantes:

- `DIRETORIO_PADRAO = Path("data/google_agenda")`
- `ARQUIVO_CREDENCIAIS = "credentials.json"` — cliente OAuth "Desktop app", colocado pelo
  usuário (passo a passo em `docs/google_agenda.md`).
- `ARQUIVO_TOKEN = "token.json"` — gravado após a autorização.
- `ESCOPOS = ["https://www.googleapis.com/auth/calendar.events"]` — leitura e escrita de
  eventos; um único escopo para as duas fases, evitando nova autorização ao entrar na fase B.
- `CALENDARIO = "primary"`, `FUSO = "America/Recife"`.
- `MARCADOR = "budgetlab_prazo_id"` — chave de `extendedProperties.private`.

Contrato público:

```python
situacao_conexao(diretorio=DIRETORIO_PADRAO) -> str
    # "sem_credenciais" | "desconectado" | "conectado"
conectar(diretorio=DIRETORIO_PADRAO) -> None
    # InstalledAppFlow.run_local_server: abre o navegador, grava token.json atomicamente
desconectar(diretorio=DIRETORIO_PADRAO) -> None
    # apaga token.json (credentials.json permanece)
cliente(diretorio=DIRETORIO_PADRAO) -> ClienteGoogleAgenda
    # renova o token quando expirado; ErroGoogleAgenda se não conectado

class ClienteGoogleAgenda:
    listar_eventos(inicio: datetime, fim: datetime) -> list[dict]
        # singleEvents=True, orderBy=startTime; percorre todas as páginas
    listar_eventos_de_prazos() -> list[dict]
        # privateExtendedProperty=MARCADOR presente, showDeleted=True, sem limite de data;
        # percorre todas as páginas — só retorna se a listagem completou
    criar_evento(corpo: dict) -> dict
    atualizar_evento(event_id: str, corpo: dict) -> dict
    excluir_evento(event_id: str) -> None

class ErroGoogleAgenda(RuntimeError)
```

`listar_eventos_de_prazos` precisa filtrar pela existência da chave. A API só filtra por
`chave=valor`; por isso todo evento de prazo também recebe `budgetlab = "1"` em
`extendedProperties.private`, e o filtro usado é `privateExtendedProperty=budgetlab=1`.

Evento normalizado devolvido pelo cliente (independente do formato bruto da API):

```python
{
    "id": str, "titulo": str, "descricao": str,
    "data_inicio": date, "hora_inicio": time | None,   # None = dia inteiro
    "data_fim": date, "hora_fim": time | None,
    "cancelado": bool,                                 # status == "cancelled"
    "atualizado_em": str,                              # campo `updated` (ISO, UTC)
    "prazo_id": str | None,                            # extendedProperties.private[MARCADOR]
    "propriedades": dict,                              # extendedProperties.private completo
    "organizador": str, "minha_resposta": str | None,  # responseStatus do attendee `self`
    "link": str,                                       # htmlLink
}
```

### Campos novos em `src/prazos_orcamentarios.py`

| Campo | Significado |
|---|---|
| `google_event_id` | ID do evento correspondente; `None` se ainda não criado. |
| `sincronizado_em` | Valor de `atualizado_em` do prazo no momento da última sincronização bem-sucedida. |
| `google_atualizado_em` | Campo `updated` do evento no momento da última sincronização. |
| `removido_no_google` | `True` quando o evento foi excluído no Google (e o prazo foi concluído por isso). |

- Cadastro legado (sem esses campos) é lido com `None`/`False`, como já ocorre com
  `dias_antecedencia`/`tipo`/`categoria`/`prioridade`. `_COLUNAS` passa a incluí-los.
- Função nova `gravar_estado_sincronizacao(prazo, diretorio=DIRETORIO_PADRAO)`: grava o
  registro **sem** alterar `atualizado_em` (diferente de `atualizar`, que sempre carimba a
  hora atual — usar `atualizar` aqui faria toda sincronização parecer alteração local).
- `novo_prazo` passa a devolver os 4 campos com valores iniciais (`None`, `None`, `None`,
  `False`).
- Reabrir um prazo (concluído → não concluído) pela tela limpa `removido_no_google`, para
  que o evento seja recriado na próxima sincronização.

## Mapeamento prazo → evento

| Evento Google | Origem no prazo |
|---|---|
| `summary` | `titulo`, prefixado por `"✓ "` quando `concluido` |
| `description` | `descricao` (texto puro, sem metadados anexados) |
| `start.date` / `end.date` | evento de dia inteiro: `data_prazo` / `data_prazo + 1 dia` |
| `reminders` | `useDefault=False`, um `popup` a `min(dias_antecedencia, 28) × 1440` minutos |
| `extendedProperties.private` | `budgetlab="1"`, `budgetlab_prazo_id`, `tipo`, `categoria`, `prioridade`, `responsavel`, `dias_antecedencia` |

## Mapeamento evento → prazo (alteração feita no Google)

Só três campos são editáveis pelo Google:

- `titulo` ← `summary` sem o prefixo `"✓ "`. O prefixo é apenas visual: acrescentá-lo ou
  removê-lo no Google **não** altera `concluido`.
- `data_prazo` ← data de início do evento. Se o usuário transformou o evento em evento com
  horário, usa-se a data de início no fuso `America/Recife`.
- `descricao` ← `description` (vazio se ausente).

`tipo`, `categoria`, `prioridade`, `responsavel` e `dias_antecedencia` só se editam no
BudgetLab; valores divergentes em `extendedProperties` são sobrescritos pelo prazo local.

Título vazio vindo do Google não é aplicado (o prazo exige título): o item vai para o
resumo como erro e o prazo local fica intacto.

## Algoritmo de conciliação — `src/prazos_sincronizacao.py`

```python
sincronizar(cliente, diretorio=DIRETORIO_PADRAO, agora=None) -> ResumoSincronizacao
```

1. Carrega os prazos locais e chama `cliente.listar_eventos_de_prazos()`. Se a listagem
   falhar, **aborta sem alterar nada** (nunca interpretar "evento ausente" a partir de uma
   listagem incompleta).
2. Indexa eventos por `prazo_id`. Para cada prazo local:

   | Situação | Ação |
   |---|---|
   | Sem `google_event_id`, `removido_no_google = False` | Criar evento. |
   | Sem `google_event_id`, `removido_no_google = True` | Nada (o usuário já tirou do Google; reabrir no BudgetLab recria). |
   | Com `google_event_id`, evento não encontrado na listagem ou `cancelado` | `concluido = True`, `removido_no_google = True`, `google_event_id = None`. Registrado no resumo. |
   | Evento existe; só o prazo mudou (`atualizado_em > sincronizado_em`) | Atualizar evento. |
   | Evento existe; só o evento mudou (`evento.atualizado_em > google_atualizado_em`) | Aplicar os 3 campos ao prazo (via `atualizar`). |
   | Os dois mudaram | Vence o mais recente (`atualizado_em` do prazo × `updated` do evento). Registrado no resumo como conflito, com o valor descartado. |
   | Nenhum mudou | Nada. |

   Depois de cada ação bem-sucedida, grava `sincronizado_em`, `google_atualizado_em` e
   `google_event_id` via `gravar_estado_sincronizacao`.
3. Eventos com marcador cujo `prazo_id` não existe mais localmente (prazo excluído no
   BudgetLab) e não cancelados → `excluir_evento`.
4. Erro em um item (HTTP, validação) é registrado no resumo e **não interrompe** os demais;
   o prazo desse item fica como estava, e será tentado de novo na próxima sincronização.

`ResumoSincronizacao` (dataclass): listas `criados`, `atualizados_no_google`,
`atualizados_no_budgetlab`, `concluidos_por_exclusao`, `eventos_excluidos`, `conflitos`
(com os dois valores e o vencedor), `erros`; mais `executado_em`.

A última execução é guardada em `data/google_agenda/ultima_sincronizacao.json` para ser
exibida na tela (a lista de conflitos inclui o valor descartado, garantindo
rastreabilidade — nada é sobrescrito sem registro).

## Interface — `app_pages/painel_prazos.py`

### Bloco "Google Agenda" (abaixo do cabeçalho)

- `sem_credenciais`: aviso com link para `docs/google_agenda.md`.
- `desconectado`: botão "Conectar ao Google Agenda" (abre o navegador para autorizar).
- `conectado`: botão "Sincronizar agora", hora da última sincronização, resumo da última
  execução (contagens + expansor com conflitos e erros) e botão "Desconectar".

Sincronização automática ao abrir a página: no máximo uma vez a cada **5 minutos** por
sessão (controle em `st.session_state`), porque o Streamlit reexecuta o script a cada
interação — sem esse limite cada clique chamaria a API.

Falha de rede ou de autenticação exibe `render_alert` e **não impede** o uso normal da
página: o cadastro local continua funcionando sem o Google.

### Seção "Agenda — próximos 30 dias" (fase A)

- Lista `cliente.listar_eventos(agora, agora + 30 dias)`, agrupada por dia.
- Duas marcações visuais: **Prazo** (evento com marcador) e **Reunião/evento** (demais),
  com horário, organizador e a resposta do usuário ao convite (aceito/recusado/pendente).
- Botão "Transformar em prazo" nos eventos sem marcador: abre o diálogo "Novo prazo" já
  preenchido (título, data de início, descrição; tipo `Solicitação`). O evento original não
  é alterado; o prazo criado ganha seu próprio evento de dia inteiro na próxima
  sincronização.

## Tratamento de erros — resumo

| Falha | Comportamento |
|---|---|
| `credentials.json` ausente | Bloco mostra instrução; nada mais muda. |
| Token revogado/expirado sem refresh | Situação volta a `desconectado`; pede reconexão. |
| Listagem de prazos falha | Sincronização abortada, nenhum dado local alterado. |
| Erro em um item | Registrado no resumo; demais itens seguem. |
| Sem internet | Alerta; página segue funcionando só com dados locais. |

## Testes

Nenhum teste acessa a rede.

- `tests/test_prazos_sincronizacao.py` — cliente falso em memória cobrindo cada linha da
  tabela de conciliação, conflito nos dois sentidos, exclusão local → exclusão remota,
  exclusão remota → concluído, reabertura → recriação, falha de listagem → nada alterado,
  erro em um item não interrompe os demais, título vazio vindo do Google rejeitado,
  prefixo "✓" não altera `concluido`, lembrete limitado a 28 dias, evento com horário →
  data no fuso de Recife.
- `tests/test_prazos_orcamentarios.py` — campos novos em `novo_prazo`, leitura de cadastro
  legado sem os campos, `gravar_estado_sincronizacao` preserva `atualizado_em`, reabrir
  limpa `removido_no_google`.
- `tests/test_google_agenda.py` — normalização do evento bruto da API para o dicionário
  acima (dia inteiro × com horário, cancelado, sem attendees, `responseStatus` de `self`),
  montagem do corpo do evento, `situacao_conexao` com diretório temporário. Chamadas HTTP
  simuladas com objetos falsos; nenhuma credencial real.

## Documentação

- `docs/google_agenda.md` — passo a passo para criar o cliente OAuth "Desktop app" no
  Google Cloud Console, ativar a Google Calendar API, baixar o `credentials.json` para
  `data/google_agenda/`, e a observação sobre contas Google Workspace institucionais
  (administrador pode bloquear apps não verificados).
- `README.md` — seção curta na parte de Gerenciamento de Prazos.
- `.gitignore` — `data/google_agenda/*` com `!data/google_agenda/.gitkeep`.
- `requirements.txt` — as três dependências, com versões fixadas.

## Fases de entrega

1. **Fase A — conexão e visualização:** `src/google_agenda.py`, dependências, `.gitignore`,
   docs, bloco de conexão e seção "Agenda". Só leitura (o escopo já permite escrita, mas
   nada é escrito nesta fase).
2. **Fase B — sincronização de prazos:** campos novos no cadastro,
   `src/prazos_sincronizacao.py`, botão "Sincronizar agora", sincronização ao abrir a
   página e resumo.

Cada fase termina com a suíte completa de testes passando.

## Riscos

- **Conta institucional:** o administrador do Google Workspace da UFRPE pode bloquear o app
  não verificado. Mitigação: documentar; funciona com conta pessoal.
- **App em modo "Testing" no Google Cloud:** o refresh token expira em 7 dias até o app ser
  publicado. Mitigação: documentar como publicar o app (uso pessoal, sem verificação
  necessária para o próprio usuário) ou aceitar reconexão semanal.
- **Relógios:** a regra "vence o mais recente" compara o relógio local com o do Google;
  diferença de relógio pode escolher o lado errado em conflitos muito próximos. Mitigação:
  todo conflito fica registrado com o valor descartado.
- **`run_local_server` no Streamlit:** bloqueia a execução até a autorização terminar.
  Aceitável para uso local de um único usuário.
