"""
Diário Oficial da União via INLABS (Imprensa Nacional) — download, leitura e filtro das
matérias que citam a UFRPE. Usado pela página `app_pages/diario_oficial.py` (botão de
atualização incremental, `atualizar`) e pela linha de comando
(`python -m src.dou_inlabs AAAA-MM-DD`) — ver `docs/dou_inlabs.md`.

Único módulo do projeto que acessa a rede para o DOU. Não importa Streamlit. Não conhece
contratos, TEDs nem prazos: devolve as matérias como DataFrame, e qualquer conciliação com
outras bases fica fora daqui.

Origem: o INLABS publica, por dia, um ZIP por seção (`AAAA-MM-DD-DO1.zip`, ...), cada um com
um XML por matéria (`<article>` com atributos de metadados e um `<body>` com `Identifica`,
`Data`, `Ementa`, `Titulo`, `SubTitulo` e `Texto` em HTML). O fluxo de login e o formato da
URL de download seguem o exemplo oficial da Imprensa Nacional (repositório
`Imprensa-Nacional/inlabs`) e o projeto `gestaogovbr/dou-api` (arquivado, sem licença — nada
foi copiado dele, só o conhecimento do formato).

Persistência — sem banco: os ZIPs baixados são gravados intactos em
`DIRETORIO_PADRAO/<data>/` (nunca sobrescritos — `destino_sem_sobrescrever`) com um
`manifesto.json` (sha256, tamanho e momento do download de cada um). A leitura abre os XML
direto do ZIP, em memória, sem extraí-los.

Credenciais: conta pessoal do INLABS, lida das variáveis de ambiente `INLABS_EMAIL` e
`INLABS_SENHA` — nunca do código, nunca registrada em log nem em mensagem de erro.

Dúvidas de negócio em aberto (sinalizadas, não presumidas):
  * Os termos que identificam a UFRPE (`TERMOS_UFRPE_PADRAO`) — nome, sigla, UG 153165 e
    UO 26248 — são um ponto de partida, a confirmar com o uso real (falsos positivos/negativos).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Sequence

import pandas as pd
import requests

from src.importacao_versionada import destino_sem_sobrescrever

URL_BASE = "https://inlabs.in.gov.br"
URL_LOGIN = f"{URL_BASE}/logar.php"
#: cabeçalho exigido pelo INLABS nos downloads (valor do exemplo oficial).
CABECALHO_ORIGEM = {"origem": "736372697074"}
COOKIE_SESSAO = "inlabs_session_cookie"
#: presente só na página de quem está logado (link "Sair").
MARCADOR_SESSAO = 'href="logout.php"'
DIRETORIO_PADRAO = Path("data/raw/dou")
ARQUIVO_MANIFESTO = "manifesto.json"
VARIAVEL_EMAIL = "INLABS_EMAIL"
VARIAVEL_SENHA = "INLABS_SENHA"
TEMPO_LIMITE = 60

#: códigos como texto (identificadores, não números) — ver docstring do módulo.
TERMOS_UFRPE_PADRAO = ("Universidade Federal Rural de Pernambuco", "UFRPE", "153165", "26248")

#: atributo do `<article>` → coluna. Todos ficam como texto (ids e páginas são identificadores).
ATRIBUTOS = {
    "id": "id",
    "name": "name",
    "idOficio": "id_oficio",
    "pubName": "pub_name",
    "artType": "art_type",
    "pubDate": "pub_date",
    "artClass": "art_class",
    "artCategory": "art_category",
    "artSize": "art_size",
    "artNotes": "art_notes",
    "numberPage": "number_page",
    "pdfPage": "pdf_page",
    "editionNumber": "edition_number",
    "highlightType": "highlight_type",
    "highlightPriority": "highlight_priority",
    "highlight": "highlight",
    "highlightimage": "highlight_image",
    "highlightimagename": "highlight_image_name",
    "idMateria": "id_materia",
}
#: filho do `<body>` → coluna.
CORPO = {
    "Identifica": "identifica",
    "Data": "data",
    "Ementa": "ementa",
    "Titulo": "titulo",
    "SubTitulo": "sub_titulo",
    "Texto": "texto",
}
COLUNAS = [
    *ATRIBUTOS.values(),
    *CORPO.values(),
    "data_publicacao",
    "atributos_extras",
    "corpo_extras",
    "arquivo_origem",
    "membro_origem",
]
#: campos em que o filtro procura os termos.
CAMPOS_BUSCA = ("art_category", "identifica", "ementa", "titulo", "sub_titulo", "texto")


class ErroInlabs(RuntimeError):
    """Falha de login, download ou formato inesperado do INLABS. Nunca carrega a senha."""


# --- Leitura (sem rede) ---------------------------------------------------------------------


def _data_publicacao(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return datetime.strptime(valor.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _artigos(raiz: ET.Element) -> list[ET.Element]:
    if raiz.tag == "article":
        return [raiz]
    return raiz.findall("article")


def ler_xml(conteudo: bytes, arquivo_origem: str = "", membro_origem: str = "") -> list[dict]:
    """XML de uma matéria do INLABS → um dicionário por `<article>`. Nenhum campo é
    descartado: atributos e filhos do `<body>` fora do esquema conhecido vão para
    `atributos_extras`/`corpo_extras`. Campo ausente → `None`; presente e vazio → `""`."""

    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError as erro:
        raise ErroInlabs(f"XML inválido em {arquivo_origem or '?'}:{membro_origem or '?'} ({erro}).") from erro

    registros = []
    for artigo in _artigos(raiz):
        registro: dict = {coluna: None for coluna in COLUNAS}
        extras_atrib = {}
        for nome, valor in artigo.attrib.items():
            if nome in ATRIBUTOS:
                registro[ATRIBUTOS[nome]] = valor
            else:
                extras_atrib[nome] = valor

        extras_corpo = {}
        corpo = artigo.find("body")
        if corpo is not None:
            for filho in corpo:
                texto = filho.text if filho.text is not None else ""
                if filho.tag in CORPO:
                    registro[CORPO[filho.tag]] = texto
                else:
                    extras_corpo[filho.tag] = texto

        registro["data_publicacao"] = _data_publicacao(registro["pub_date"])
        registro["atributos_extras"] = extras_atrib
        registro["corpo_extras"] = extras_corpo
        registro["arquivo_origem"] = arquivo_origem
        registro["membro_origem"] = membro_origem
        registros.append(registro)
    return registros


def ler_zip(caminho: str | Path) -> pd.DataFrame:
    """Todas as matérias de um ZIP do INLABS, lidas em memória (o ZIP não é alterado nem
    extraído). Membros que não são XML são ignorados (o ZIP também traz imagens)."""

    caminho = Path(caminho)
    registros: list[dict] = []
    with zipfile.ZipFile(caminho) as arquivo:
        for membro in sorted(arquivo.namelist()):
            if membro.lower().endswith(".xml"):
                registros.extend(ler_xml(arquivo.read(membro), caminho.name, membro))
    return pd.DataFrame(registros, columns=COLUNAS)


def ler_zips(caminhos: Iterable[str | Path]) -> pd.DataFrame:
    quadros = [ler_zip(caminho) for caminho in caminhos]
    if not quadros:
        return pd.DataFrame(columns=COLUNAS)
    return pd.concat(quadros, ignore_index=True)


# --- Filtro ---------------------------------------------------------------------------------

_TAG_HTML = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"\s+")


def normalizar_texto(texto: str | None) -> str:
    """Para busca: sem tags HTML, entidades resolvidas, sem acentos, minúsculas e espaços
    colapsados. Só usado para comparar — o texto original da matéria nunca é alterado."""

    if not texto:
        return ""
    sem_tags = html.unescape(_TAG_HTML.sub(" ", texto))
    decomposto = unicodedata.normalize("NFKD", sem_tags)
    sem_acentos = "".join(c for c in decomposto if not unicodedata.combining(c))
    return _ESPACOS.sub(" ", sem_acentos.casefold()).strip()


def _padrao(termo: str) -> re.Pattern:
    normalizado = normalizar_texto(termo)
    if not normalizado:
        raise ValueError("Termo de busca vazio.")
    # Código numérico não casa dentro de outro número (153165 ≠ 1531650); texto casa palavra
    # inteira (UFRPE ≠ UFRPEX).
    if normalizado.isdigit():
        return re.compile(rf"(?<!\d){re.escape(normalizado)}(?!\d)")
    return re.compile(rf"\b{re.escape(normalizado)}\b")


def limpar_termos(termos: Iterable[str]) -> tuple[str, ...]:
    """Termos digitados pelo usuário: sem espaços nas pontas, sem vazios e sem repetição
    (dois termos iguais a menos de acento/caixa contam uma vez — fica a primeira grafia)."""

    vistos, resultado = set(), []
    for termo in termos:
        termo = (termo or "").strip()
        chave = normalizar_texto(termo)
        if chave and chave not in vistos:
            vistos.add(chave)
            resultado.append(termo)
    return tuple(resultado)


class _Busca:
    """Regra de busca: a matéria precisa citar algum dos `termos` E, se houver `refinar`,
    também algum dos termos de `refinar`. Ex.: termos = nome/sigla/códigos da UFRPE,
    refinar = ("pregão", "dispensa") → só pregões ou dispensas da UFRPE."""

    def __init__(self, termos: Sequence[str], refinar: Sequence[str] = ()):
        self.termos = [(termo, _padrao(termo)) for termo in termos]
        self.refinar = [(termo, _padrao(termo)) for termo in refinar]

    def __call__(self, registro, campos: Sequence[str]) -> tuple[str, ...]:
        """Termos encontrados (dos dois grupos, na grafia dada) se a matéria passa na regra;
        senão, tupla vazia."""

        texto = " \n ".join(normalizar_texto(registro[campo]) for campo in campos)
        principais = tuple(termo for termo, padrao in self.termos if padrao.search(texto))
        if not principais:
            return ()
        if not self.refinar:
            return principais
        refinados = tuple(termo for termo, padrao in self.refinar if padrao.search(texto))
        return principais + refinados if refinados else ()


def filtrar_por_termos(
    df: pd.DataFrame,
    termos: Sequence[str] = TERMOS_UFRPE_PADRAO,
    refinar: Sequence[str] = (),
) -> pd.DataFrame:
    """Só as matérias que passam na regra de `_Busca` (sem diferenciar acento nem caixa) em
    `CAMPOS_BUSCA`, com a coluna `termos_encontrados` (tupla dos termos, na grafia dada).
    Devolve uma cópia; o DataFrame de entrada não é modificado."""

    busca = _Busca(termos, refinar)
    campos = [campo for campo in CAMPOS_BUSCA if campo in df.columns]

    encontrados = [busca(linha, campos) for _, linha in df[campos].iterrows()]

    resultado = df.copy()
    resultado["termos_encontrados"] = pd.Series(encontrados, index=df.index, dtype=object)
    return resultado.loc[resultado["termos_encontrados"].map(bool).astype(bool)]


def ler_e_filtrar_zip(
    caminho: str | Path,
    termos: Sequence[str] = TERMOS_UFRPE_PADRAO,
    refinar: Sequence[str] = (),
) -> pd.DataFrame:
    """Como `filtrar_por_termos(ler_zip(caminho), termos, refinar)`, mas filtrando XML a XML:
    só as matérias encontradas ficam em memória (um dia do DOU tem milhares de matérias)."""

    caminho = Path(caminho)
    busca = _Busca(termos, refinar)
    registros: list[dict] = []
    with zipfile.ZipFile(caminho) as arquivo:
        for membro in sorted(arquivo.namelist()):
            if not membro.lower().endswith(".xml"):
                continue
            for registro in ler_xml(arquivo.read(membro), caminho.name, membro):
                achados = busca(registro, CAMPOS_BUSCA)
                if achados:
                    registro["termos_encontrados"] = achados
                    registros.append(registro)
    return pd.DataFrame(registros, columns=[*COLUNAS, "termos_encontrados"])


# --- Termos de busca salvos -----------------------------------------------------------------
# Persistência aprovada pelo usuário em 09/10/2026: a lista de termos da página Diário Oficial
# sobrevive a reiniciar o sistema. Um JSON pequeno, fora do git (`.gitignore`).

DIRETORIO_TERMOS = Path("data/dou")
ARQUIVO_TERMOS = "termos.json"


@dataclass(frozen=True)
class TermosSalvos:
    termos: tuple[str, ...]
    refinar: tuple[str, ...]
    #: preenchido quando o arquivo existia mas não pôde ser lido — a página avisa e usa o padrão.
    aviso: str | None = None


def carregar_termos(diretorio: str | Path = DIRETORIO_TERMOS) -> TermosSalvos:
    """Termos salvos; sem arquivo, os padrões. Arquivo ilegível nunca derruba a página: volta
    aos padrões com `aviso` (e o arquivo não é apagado — só a próxima gravação o substitui)."""

    caminho = Path(diretorio) / ARQUIVO_TERMOS
    if not caminho.exists():
        return TermosSalvos(TERMOS_UFRPE_PADRAO, ())
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        termos, refinar = dados["termos"], dados.get("refinar", [])
        if not all(isinstance(lista, list) and all(isinstance(t, str) for t in lista) for lista in (termos, refinar)):
            raise ValueError("listas de termos inválidas")
    except (OSError, ValueError, KeyError, TypeError) as erro:
        return TermosSalvos(
            TERMOS_UFRPE_PADRAO, (),
            aviso=f"Não foi possível ler os termos salvos ({caminho}: {type(erro).__name__}); usando os padrões.",
        )
    return TermosSalvos(limpar_termos(termos), limpar_termos(refinar))


def salvar_termos(termos: Iterable[str], refinar: Iterable[str] = (), diretorio: str | Path = DIRETORIO_TERMOS) -> Path:
    pasta = Path(diretorio)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / ARQUIVO_TERMOS
    dados = {
        "termos": list(limpar_termos(termos)),
        "refinar": list(limpar_termos(refinar)),
        "atualizado_em": datetime.now().replace(microsecond=0).isoformat(),
    }
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(caminho)
    return caminho


# --- Rede -----------------------------------------------------------------------------------


MANUAL_CONFIGURACAO_LOGIN = """**1. Conta no INLABS.** O acesso é gratuito e pessoal: crie a conta em https://inlabs.in.gov.br (se já tem, confirme que consegue entrar por lá com o mesmo e-mail e senha).

**2. Gravar e-mail e senha no seu usuário do Windows.** Abra o **PowerShell** e cole os dois comandos abaixo, um de cada vez. A senha é pedida em campo oculto, então não fica no histórico nem na tela, e é gravada só no seu perfil do Windows (nunca no código nem no git).

```powershell
[Environment]::SetEnvironmentVariable("INLABS_EMAIL", (Read-Host "E-mail do INLABS"), "User")
```

```powershell
$s = Read-Host "Senha do INLABS" -AsSecureString
[Environment]::SetEnvironmentVariable("INLABS_SENHA", [System.Net.NetworkCredential]::new("", $s).Password, "User")
```

**3. Reiniciar o BudgetLab.** Feche o servidor e abra de novo. Não precisa sair da conta do Windows: o sistema lê as variáveis direto do seu perfil.

**4. Conferir.** Ao recarregar esta página, o aviso de credenciais some e o botão **Baixar atualizações do DOU** fica habilitado.

**Trocar a senha depois:** repita o passo 2 com a nova senha e reinicie o BudgetLab.

**Se continuar o aviso:** confira se o e-mail e a senha foram digitados sem erro (rode o passo 2 de novo) e se o BudgetLab foi mesmo reiniciado. Se o botão habilitar mas o download falhar com erro de login, a conta ou a senha do INLABS está incorreta.
"""


def _variavel_do_usuario_windows(nome: str) -> str:
    """Variável gravada no perfil do usuário do Windows (`HKCU\\Environment`). Um processo só
    recebe essas variáveis no ambiente se foi aberto depois que o Explorer as recarregou —
    na prática, depois de sair e entrar de novo na conta. Caso real (08/10/2026): variáveis
    gravadas, BudgetLab reiniciado pelo atalho, e o processo novo ainda sem elas."""

    if sys.platform != "win32":
        return ""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as chave:
            valor, _ = winreg.QueryValueEx(chave, nome)
    except OSError:
        return ""
    return valor if isinstance(valor, str) else ""


def credenciais_do_ambiente() -> tuple[str, str]:
    """Do ambiente do processo; na falta, do perfil do usuário do Windows."""

    email = (os.environ.get(VARIAVEL_EMAIL) or _variavel_do_usuario_windows(VARIAVEL_EMAIL)).strip()
    senha = os.environ.get(VARIAVEL_SENHA) or _variavel_do_usuario_windows(VARIAVEL_SENHA)
    if not email or not senha:
        raise ErroInlabs(
            f"Credenciais do INLABS ausentes: defina {VARIAVEL_EMAIL} e {VARIAVEL_SENHA} "
            "(ver docs/dou_inlabs.md)."
        )
    return email, senha


class ClienteInlabs:
    def __init__(self, sessao: requests.Session | None = None):
        self.sessao = sessao or requests.Session()

    def autenticar(self, email: str, senha: str) -> None:
        try:
            self.sessao.post(
                URL_LOGIN,
                data={"email": email, "password": senha},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=TEMPO_LIMITE,
            )
        except requests.RequestException as erro:
            raise ErroInlabs(f"Falha de conexão no login do INLABS ({type(erro).__name__}).") from None
        if not self.sessao.cookies.get(COOKIE_SESSAO):
            raise ErroInlabs("Login no INLABS recusado: confira e-mail e senha.")

    def _get(self, url: str, descricao: str) -> requests.Response:
        try:
            resposta = self.sessao.get(url, headers=CABECALHO_ORIGEM, timeout=TEMPO_LIMITE)
        except requests.RequestException as erro:
            raise ErroInlabs(f"Falha de conexão ao {descricao} ({type(erro).__name__}).") from None
        if resposta.status_code != 200:
            raise ErroInlabs(f"INLABS respondeu {resposta.status_code} ao {descricao}.")
        return resposta

    def listar_arquivos(self, dia: date) -> list[str]:
        """ZIPs publicados no dia, conforme a página do dia no INLABS. Lista vazia = dia sem
        edição. Para um dia sem edição, pedir um ZIP direto devolve uma página HTML com status
        200 (não 404) — indistinguível de sessão expirada; por isso a lista vem antes do
        download (constatado em 08/10/2026). Também cobre edições extras sem presumir o nome."""

        texto = self._get(f"{URL_BASE}/index.php?p={dia.isoformat()}", f"listar {dia.isoformat()}").text
        if MARCADOR_SESSAO not in texto:
            raise ErroInlabs("Sessão do INLABS não está ativa (login expirado ou site alterado).")
        padrao = re.compile(rf"dl=({re.escape(dia.isoformat())}-[A-Za-z0-9_]+\.zip)")
        return list(dict.fromkeys(padrao.findall(texto)))

    def baixar_arquivo(self, dia: date, nome: str) -> bytes:
        """Conteúdo de um ZIP listado por `listar_arquivos`."""

        resposta = self._get(f"{URL_BASE}/index.php?p={dia.isoformat()}&dl={nome}", f"baixar {nome}")
        if not resposta.content.startswith(b"PK"):
            # O arquivo estava na lista, mas veio HTML: sessão expirada ou mudança no site.
            raise ErroInlabs(f"{nome}: o INLABS não devolveu um ZIP (sessão expirada ou site alterado).")
        return resposta.content


def _gravar(diretorio: Path, nome: str, conteudo: bytes) -> tuple[Path, str]:
    sha256 = hashlib.sha256(conteudo).hexdigest()
    destino, ja_existe = destino_sem_sobrescrever(diretorio, nome, sha256)
    if not ja_existe:
        temporario = destino.with_name(destino.name + ".parcial")
        temporario.write_bytes(conteudo)
        temporario.replace(destino)
    return destino, sha256


def _atualizar_manifesto(diretorio: Path, dia: date, gravados: list[dict]) -> Path:
    caminho = diretorio / ARQUIVO_MANIFESTO
    anterior = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
    arquivos = {item["arquivo"]: item for item in anterior.get("arquivos", [])}
    for item in gravados:
        arquivos.setdefault(item["arquivo"], item)
    manifesto = {
        "data_publicacao": dia.isoformat(),
        # última consulta ao INLABS para o dia — também marca dia consultado sem publicação.
        "verificado_em": datetime.now().replace(microsecond=0).isoformat(),
        "arquivos": sorted(arquivos.values(), key=lambda i: i["arquivo"]),
    }
    caminho.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def baixar_dia(cliente: ClienteInlabs, dia: date, diretorio: str | Path = DIRETORIO_PADRAO) -> list[Path]:
    """Baixa os ZIPs publicados no dia (`listar_arquivos`) para `diretorio/<data>/` e atualiza
    o manifesto — também num dia sem edição, que fica registrado como consultado. Um ZIP
    idêntico já baixado é reaproveitado; um ZIP diferente com o mesmo nome (republicação) é
    gravado ao lado, nunca por cima."""

    nomes = cliente.listar_arquivos(dia)
    pasta = Path(diretorio) / dia.isoformat()
    pasta.mkdir(parents=True, exist_ok=True)
    caminhos, gravados = [], []
    for nome in nomes:
        conteudo = cliente.baixar_arquivo(dia, nome)
        destino, sha256 = _gravar(pasta, nome, conteudo)
        caminhos.append(destino)
        gravados.append({
            "arquivo": destino.name,
            "secao": nome.removeprefix(f"{dia.isoformat()}-").removesuffix(".zip"),
            "sha256": sha256,
            "bytes": len(conteudo),
            "baixado_em": datetime.now().replace(microsecond=0).isoformat(),
        })
    _atualizar_manifesto(pasta, dia, gravados)
    return caminhos


# --- Atualização incremental (usada pela página Diário Oficial) ----------------------------

#: primeira atualização: quantos dias para trás (contando hoje).
DIAS_INICIAIS = 7
#: máximo de dias consultados por atualização — os demais ficam para a próxima.
LIMITE_DIAS_POR_ATUALIZACAO = 30


def dias_baixados(diretorio: str | Path = DIRETORIO_PADRAO) -> dict[date, dict]:
    """Manifesto de cada dia já consultado (com ou sem publicação), por data."""

    resultado: dict[date, dict] = {}
    pasta = Path(diretorio)
    if not pasta.is_dir():
        return resultado
    for manifesto in pasta.glob(f"*/{ARQUIVO_MANIFESTO}"):
        try:
            dia = date.fromisoformat(manifesto.parent.name)
        except ValueError:
            continue
        resultado[dia] = json.loads(manifesto.read_text(encoding="utf-8"))
    return dict(sorted(resultado.items()))


def dias_pendentes(
    hoje: date,
    diretorio: str | Path = DIRETORIO_PADRAO,
    dias_iniciais: int = DIAS_INICIAIS,
    limite: int = LIMITE_DIAS_POR_ATUALIZACAO,
) -> list[date]:
    """Dias a consultar, do mais antigo ao mais recente: do dia seguinte ao último consultado
    até `hoje` (na primeira vez, os últimos `dias_iniciais`). Se o último consultado já é hoje,
    hoje é consultado de novo (edição extra publicada mais tarde no dia). No máximo `limite`."""

    baixados = dias_baixados(diretorio)
    if not baixados:
        inicio = hoje - timedelta(days=dias_iniciais - 1)
    else:
        ultimo = max(baixados)
        inicio = hoje if ultimo >= hoje else ultimo + timedelta(days=1)
    dias = [inicio + timedelta(days=n) for n in range((hoje - inicio).days + 1)]
    return dias[:limite]


@dataclass
class ResumoAtualizacao:
    dias_consultados: list[date] = field(default_factory=list)
    dias_sem_publicacao: list[date] = field(default_factory=list)
    arquivos: list[Path] = field(default_factory=list)
    restantes: int = 0
    erro: str | None = None


def atualizar(
    cliente: ClienteInlabs,
    hoje: date,
    diretorio: str | Path = DIRETORIO_PADRAO,
    progresso: Callable[[int, int, date], None] | None = None,
) -> ResumoAtualizacao:
    """Baixa os `dias_pendentes`. Um erro interrompe a atualização, mas o que já foi baixado
    fica gravado (e consta no resumo); a próxima atualização recomeça do dia que falhou."""

    pendentes = dias_pendentes(hoje, diretorio)
    total_sem_limite = len(dias_pendentes(hoje, diretorio, limite=10**6))
    resumo = ResumoAtualizacao(restantes=total_sem_limite - len(pendentes))
    for indice, dia in enumerate(pendentes):
        if progresso:
            progresso(indice, len(pendentes), dia)
        try:
            caminhos = baixar_dia(cliente, dia, diretorio)
        except ErroInlabs as erro:
            resumo.erro = str(erro)
            resumo.restantes += len(pendentes) - indice
            break
        resumo.dias_consultados.append(dia)
        resumo.arquivos.extend(caminhos)
        if not caminhos:
            resumo.dias_sem_publicacao.append(dia)
    return resumo


def arquivos_baixados(
    diretorio: str | Path = DIRETORIO_PADRAO,
    inicio: date | None = None,
    fim: date | None = None,
) -> list[tuple[Path, str]]:
    """(caminho, sha256) de cada ZIP registrado nos manifestos dos dias no período — só o que
    o manifesto registra (um `.parcial` interrompido nunca entra)."""

    resultado = []
    for dia, manifesto in dias_baixados(diretorio).items():
        if (inicio and dia < inicio) or (fim and dia > fim):
            continue
        for item in manifesto.get("arquivos", []):
            caminho = Path(diretorio) / dia.isoformat() / item["arquivo"]
            if caminho.exists():
                resultado.append((caminho, item["sha256"]))
    return resultado


# --- Linha de comando -----------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Baixa o DOU do dia no INLABS e lista as matérias da UFRPE.")
    parser.add_argument("data", type=date.fromisoformat, help="data de publicação (AAAA-MM-DD)")
    parser.add_argument("--termo", action="append", dest="termos", help="termo de busca (repetível)")
    parser.add_argument("--diretorio", type=Path, default=DIRETORIO_PADRAO)
    args = parser.parse_args(argv)

    try:
        cliente = ClienteInlabs()
        cliente.autenticar(*credenciais_do_ambiente())
        caminhos = baixar_dia(cliente, args.data, args.diretorio)
    except ErroInlabs as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1

    materias = ler_zips(caminhos)
    achadas = filtrar_por_termos(materias, args.termos or TERMOS_UFRPE_PADRAO)
    print(f"{len(caminhos)} arquivo(s), {len(materias)} matéria(s), {len(achadas)} com os termos.")
    for _, linha in achadas.iterrows():
        titulo = linha["identifica"] or linha["titulo"] or linha["name"]
        print(f"- [{linha['pub_name']}] {titulo} — {', '.join(linha['termos_encontrados'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
