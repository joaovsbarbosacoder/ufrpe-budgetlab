# Integração com o Google Agenda

A aba **Gerenciamento de Prazos** pode se conectar ao calendário principal da sua conta
Google para (a) mostrar os eventos dos próximos 30 dias, inclusive reuniões em que você é
convidado, e (b) sincronizar os prazos cadastrados nos dois sentidos.

## Configuração (uma única vez)

1. Acesse <https://console.cloud.google.com/> com a conta que tem a agenda.
2. Crie um projeto (ex.: "UFRPE BudgetLab").
3. Em **APIs e serviços → Biblioteca**, ative a **Google Calendar API**.
4. Em **APIs e serviços → Tela de permissão OAuth**: tipo **Externo**, preencha nome e
   e-mail, e adicione sua própria conta em **Usuários de teste**.
5. Em **APIs e serviços → Credenciais → Criar credenciais → ID do cliente OAuth**, escolha
   **App para computador (Desktop app)**.
6. Baixe o JSON e salve como `data/google_agenda/credentials.json` dentro do projeto.
7. Abra **Gerenciamento de Prazos** e clique em **Conectar ao Google Agenda**. O navegador
   abre para você autorizar; depois disso a página mostra "Conectado".

O `credentials.json` fica em `data/google_agenda/` (no `.gitignore`). O `token.json` — que dá
acesso de leitura e escrita à sua agenda — fica **fora da pasta do projeto**, em
`%APPDATA%\UFRPE BudgetLab\token.json`, para não ser copiado para a nuvem pelo Google Drive
(a pasta do projeto é sincronizada). Um token gravado no local antigo é movido para lá
automaticamente.

O botão **Desconectar** revoga o acesso na sua conta Google e apaga o token local. Sem
internet, o token local é apagado mesmo assim e a página avisa para remover o acesso
manualmente em <https://myaccount.google.com/permissions>.

Cada sincronização que altera algo, tem conflito ou erro é registrada, sem apagar as
anteriores, em `data/google_agenda/historico_sincronizacao.jsonl` — inclusive o valor
descartado quando os dois lados foram alterados.

## Observações

- **App em modo de teste:** enquanto a tela de permissão estiver em "Testing", o Google
  expira a autorização em 7 dias e a página pede para conectar de novo. Para evitar, em
  **Tela de permissão OAuth** clique em **Publicar app**; para uso próprio não é necessário
  passar pela verificação do Google (o aviso "app não verificado" continua aparecendo na
  autorização — clique em "Avançado → Acessar").
- **Conta institucional (Google Workspace):** o administrador pode bloquear apps não
  verificados. Nesse caso, use uma conta pessoal ou peça liberação ao administrador.
- **Lembretes:** o Google aceita lembretes até 28 dias antes. Prazos com antecedência maior
  recebem lembrete de 28 dias na agenda; o alerta "Vencendo" do BudgetLab continua usando a
  antecedência completa.
