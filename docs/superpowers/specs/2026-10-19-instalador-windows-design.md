# Instalador Windows do UFRPE BudgetLab — design

Data: 19/10/2026 · Status: aguardando revisão do usuário.

## Objetivo

Gerar instaladores `.exe` para Windows que instalem o sistema em um computador
**sem exigir Python, Git ou internet** na instalação e no uso. O sistema segue
rodando localmente (Streamlit em `localhost`), como hoje; muda apenas a forma de
distribuí-lo.

Decisões do usuário (19/10/2026):

- dois instaladores separados: **leve (sem dados)** e **completo (com os dados
  atuais de `data/`)**, ambos para uso interno da UFRPE;
- **atualização do código pelo GitHub, opcional**: usada quando houver internet;
  sem internet o sistema abre normalmente na versão instalada;
- abordagem **A**: Python embeddable + dependências + código, empacotados com
  Inno Setup.

Fora do escopo: assinatura digital do `.exe`, instalação compartilhada entre
usuários do PC, instalador para macOS/Linux, qualquer mudança nas regras de
negócio, nas páginas ou nos módulos de `src/`.

## Estrutura instalada

Instalação **por usuário** (sem administrador):

```
%LOCALAPPDATA%\UFRPE BudgetLab\
  python\      Python embeddable + dependências (site-packages)
  app\         código: app.py, app_pages, src, assets, scripts\instalador, requirements.txt, versao.txt
  dados\       bases do usuário
  app\data  →  junção de diretório (mklink /J) para ..\dados
```

O sistema usa caminhos relativos (`Path("data/...")`) em ~57 módulos. A junção
`app\data → dados\` preserva esse contrato **sem alterar nenhum módulo**, e
mantém as bases fora da pasta de código. Instalar, atualizar ou reinstalar nunca
substitui `dados\`.

## Componentes

1. **`scripts/build_instalador.ps1 [-ComDados]`** (roda só na máquina de build,
   que precisa de internet, do Inno Setup 6 e do Python 3.13 igual ao do projeto):
   - baixa o Python embeddable (versão do `requirements.txt`/ambiente de dev) e
     habilita `site-packages` (`python313._pth`) e o pip;
   - instala o `requirements.txt` em `python\` (build, não na instalação);
   - copia o código versionado (`git ls-files`, sem `data/`), grava `versao.txt`
     com o SHA do commit e o hash do `requirements.txt`;
   - chama `iscc` com `installer\budgetlab.iss`, gerando
     `dist\BudgetLab-Setup.exe` ou, com `-ComDados`,
     `dist\BudgetLab-Setup-Completo.exe`. `dist\` fica no `.gitignore`.
2. **`installer\budgetlab.iss`** (Inno Setup): instala em
   `{localappdata}\UFRPE BudgetLab`, cria atalhos (menu Iniciar e área de
   trabalho), cria `dados\` com a estrutura de subpastas, cria a junção
   `app\data → dados` e registra o desinstalador. Na variante completa, inclui
   `data\` com `Flags: onlyifdoesntexist recursesubdirs`: **só copia o que ainda
   não existe**, nunca sobrescreve dado de um usuário que já tem o sistema. O
   desinstalador remove `python\` e `app\` e **pergunta** antes de remover
   `dados\` (padrão: manter). A junção é removida antes da remoção de `app\`
   (ver risco 1).
3. **`scripts/instalador/iniciar.py`**: executado pelo Python embutido (atalho).
   Tenta a atualização (item 4) com tempo
   limite curto, depois inicia `streamlit run app.py --server.headless true
   --server.port 8501 --browser.gatherUsageStats false` com a pasta de trabalho
   em `app\` e abre o navegador quando `/_stcore/health` responder (mesma lógica
   do `atualizar_e_iniciar.ps1`). Se o sistema já estiver aberto na porta, só
   abre o navegador.
4. **`scripts/instalador/atualizar.py`**: atualização opcional.
   - consulta o SHA do `master` via API pública do GitHub
     (`joaovsbarbosacoder/ufrpe-budgetlab`; repositório público, sem token); se
     for igual ao de `versao.txt`, nada a fazer;
   - baixa o `.zip` do `master` para uma pasta temporária, extrai e copia **arquivo
     a arquivo** para `app\`, **excluindo `data\`**; remove de `app\` apenas
     arquivos de código que sumiram da nova versão, nunca `data` nem
     `versao.txt` antes do fim; só grava o novo `versao.txt` ao concluir;
   - se o hash do `requirements.txt` mudou, roda `pip install -r` no Python
     embutido; se isso falhar (sem internet), avisa e mantém a versão anterior
     do código (a atualização é **tudo ou nada**: código novo só entra com as
     dependências compatíveis);
   - qualquer falha (sem internet, GitHub indisponível, zip inválido) apenas
     avisa e o sistema abre na versão instalada.

## Fluxo de dados e integridade

- Os arquivos originais importados nunca são alterados: o instalador só
  **copia** `data\` (variante completa) e só se o destino não existir.
- Nenhuma persistência nova é criada além de `dados\`, que é a `data/` atual
  apenas relocada; `versao.txt` guarda só versão do código.
- O instalador completo é uma fotografia de `data/` no momento do build; ele
  não substitui a atualização das bases pelo próprio sistema.

## Riscos e mitigações

1. **Remoção recursiva atravessando a junção apagaria `dados\`.** Mitigação: o
   atualizador nunca faz `rmtree` em `app\`; o desinstalador remove a junção
   (`rmdir`, que não segue o link) antes de apagar `app\`; teste cobre isso.
2. **Antivírus/TI pode bloquear `.exe` sem assinatura.** Mitigação: plano B, a
   mesma pasta empacotada em `.zip` portátil com o atalho; assinatura fica fora
   do escopo.
3. **Tamanho** (`pyarrow`, `duckdb`): instalador leve esperado na faixa de
   150–250 MB; o completo soma os ~256 MB de dados (compactados).
4. **Mudança de dependências entre versões** pode falhar sem internet:
   tratada pelo "tudo ou nada" do atualizador.
5. **Inno Setup não está instalado nesta máquina**; é pré-requisito do build.

## Testes

- `tests/test_instalador_atualizar.py` (pytest, sem rede, com zip e pastas
  temporárias): extração exclui `data\`; arquivo removido do código some e
  `data\` permanece intacta; falha no meio não troca `versao.txt`; SHA igual não
  faz nada; hash do `requirements.txt` igual/diferente decide o `pip`.
- `tests/test_instalador_iniciar.py`: montagem do comando e detecção de
  "sistema já aberto" (com a verificação de saúde simulada).
- Verificação manual de ponta a ponta em máquina/pasta limpa: instalar o leve,
  abrir o sistema, importar uma base; instalar o completo sobre um `dados\`
  existente e confirmar que nada foi sobrescrito; atualizar; desinstalar
  mantendo e removendo `dados\`.
- A suíte atual (`python -m pytest tests -n 8 --dist loadfile`) deve continuar
  passando sem alterações.

## Documentação

Nova seção no `README.md` ("Instalação por instalador Windows"), com como gerar
os instaladores, o que cada um contém e como atualizar/desinstalar, ao lado da
seção do `Iniciar BudgetLab.bat` (que continua válido para quem roda a partir do
repositório).
