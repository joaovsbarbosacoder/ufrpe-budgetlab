# Diário Oficial (DOU) via INLABS

`src/dou_inlabs.py` baixa o Diário Oficial da União pelo
[INLABS](https://inlabs.in.gov.br) (Imprensa Nacional) e lista as matérias que
citam a UFRPE. Uso principal: a página **Diário Oficial (DOU)** do app. Também
funciona pela linha de comando.

## 1. Conta no INLABS

O INLABS exige cadastro gratuito, pessoal: crie a conta em
<https://inlabs.in.gov.br> com o seu e-mail.

## 2. Credenciais

As credenciais são lidas **só** de variáveis de ambiente — nunca do código nem
de arquivo versionado, e nunca aparecem em log ou mensagem de erro.

No PowerShell, para a sessão atual:

```powershell
$env:INLABS_EMAIL = "seu.email@ufrpe.br"
$env:INLABS_SENHA = "sua senha"
```

Para deixar gravado no seu usuário do Windows (vale nas próximas sessões):

```powershell
[Environment]::SetEnvironmentVariable("INLABS_EMAIL", "seu.email@ufrpe.br", "User")
[Environment]::SetEnvironmentVariable("INLABS_SENHA", "sua senha", "User")
```

Gravadas assim, o BudgetLab as lê direto do perfil do usuário do Windows,
mesmo que o sistema tenha sido aberto antes (o Windows só repassa variáveis
novas a programas abertos depois de sair e entrar na conta) — basta reiniciar o
BudgetLab.

## 3. Uso na página

- **Baixar atualizações do DOU**: consulta os dias que faltam, do dia seguinte
  ao último consultado até hoje (na primeira vez, os últimos 7 dias). No máximo
  30 dias por clique — se faltarem mais, a página avisa e o próximo clique
  continua. Se o último dia consultado já é hoje, hoje é consultado de novo
  (pega edição extra publicada mais tarde). Um erro no meio interrompe a
  atualização, mas o que já foi baixado fica gravado.
- **Termos de busca**: a matéria precisa citar algum destes. Os padrões vêm
  preenchidos; digite um termo novo e tecle Enter para acrescentar.
- **Refinar** (opcional): se preenchido, a matéria também precisa citar algum
  destes. Ex.: termos da UFRPE + refinar "pregão" → só pregões da UFRPE (um
  termo geral sozinho em "Termos de busca" traz o país inteiro).
- As duas listas são salvas automaticamente em `data/dou/termos.json` e voltam
  na próxima vez que o sistema abrir; **Restaurar termos padrão** volta aos
  padrões. Se o arquivo estiver ilegível, a página avisa e usa os padrões (o
  arquivo só é substituído na próxima mudança). Os termos procuram em todos os
  dias já baixados do período, sem novo download.
- **Período** e **Seção** filtram a tabela; a coluna **Link** abre a página no
  DOU.

Sem as variáveis de ambiente, o botão fica desabilitado e a página mostra o que
já foi baixado.

## 4. Uso pela linha de comando

```bash
python -m src.dou_inlabs 2026-10-08
```

Termos próprios (repetível; substituem os padrões):

```bash
python -m src.dou_inlabs 2026-10-08 --termo "UFRPE" --termo "153165"
```

Saída: quantos arquivos e matérias foram lidos e, para cada matéria encontrada,
a seção, a identificação e os termos que casaram.

## 5. O que é gravado

`data/dou/termos.json` (fora do git, incluído no backup): as duas listas de
termos.

`data/raw/dou/<data>/` (fora do git):

- os ZIPs de cada seção publicada (`DO1`, `DO2`, `DO3` e edições extras
  `DO1E`, `DO2E`, `DO3E`), **intactos** — nunca sobrescritos; um ZIP
  republicado com o mesmo nome e conteúdo diferente é gravado ao lado
  (`<nome>__<sha256[:8]>.zip`);
- `manifesto.json`: arquivo, seção, sha256, tamanho e momento do download.

Não há banco de dados: a leitura abre os XML direto do ZIP, em memória.

## 6. Busca

Ignora acentos, caixa e tags HTML. Procura em órgão (`art_category`),
identificação, ementa, título, subtítulo e texto. Códigos numéricos não casam
dentro de outro número (`153165` ≠ `1531650`); textos casam palavra inteira
(`UFRPE` ≠ `UFRPEX`).

Termos padrão: `Universidade Federal Rural de Pernambuco`, `UFRPE`, `153165`
(UG/UASG) e `26248` (UO).

## Dúvidas em aberto

- Os termos padrão são um ponto de partida — ajustar conforme os falsos
  positivos/negativos observados no uso real (ex.: abreviações como
  "Univ. Fed. Rural de Pernambuco" não são cobertas pelo nome por extenso).
- Os nomes dos arquivos de edição extra seguem o exemplo oficial da Imprensa
  Nacional; uma edição extra com outro nome não seria baixada.
- O formato do XML foi implementado a partir da documentação pública; os
  testes usam uma fixture **sintética** (`tests/fixtures/dou_inlabs_sintetico.xml`).
  Ao baixar o primeiro dia real, vale conferir se algum campo caiu em
  `atributos_extras`/`corpo_extras` (sinal de diferença de formato).
