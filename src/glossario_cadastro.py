"""
Cadastro editável do Glossário — inclusão, edição e exclusão de verbetes pela interface.

Camada: regra de negócio de uma base própria (cadastro manual). Depende só de `src.glossario`
e da stdlib. Não importa Streamlit.

Modelo: `src.glossario.GLOSSARIO` continua sendo a base fixa versionada no código (MCASP/MTO e
siglas do sistema). Enquanto `CAMINHO_PADRAO` não existe, o cadastro É a base fixa — nada é
gravado só por abrir a página. A primeira inclusão, edição ou exclusão materializa o cadastro
completo (base + a mudança) em um único JSON; a partir daí ele é a fonte lida pela página. Como
a base fixa nunca é alterada, apagar o arquivo restaura o glossário original.

Data de alteração: `atualizado_em` (AAAA-MM-DD) é gravada em toda inclusão e edição, e nos
verbetes cujo "Ver também" foi ajustado por um renomeio. Não há data de criação. Verbetes da base
fixa nunca alterados, e cadastros anteriores a este campo, ficam sem data (None) — a data não é
presumida. Na importação, o verbete vem com a data do arquivo e a data não conta para decidir se
dois verbetes são idênticos.

Identidade do verbete: o próprio `termo`, único sem distinguir caixa nem acentos (mesma
normalização de `src.glossario.buscar`). Não há id separado.

Integridade de `ver_tambem` (referências entre verbetes):
- incluir/editar exige que toda referência aponte para um verbete existente (e nunca para o
  próprio verbete);
- renomear um verbete atualiza as referências a ele nos demais — devolvido por `atualizar` para
  a interface informar o usuário, nunca em silêncio;
- excluir um verbete referenciado por outro é recusado, listando quem o referencia.

Exportar/importar: `exportar` gera o mesmo JSON do cadastro. A importação é uma mesclagem,
nunca uma substituição do glossário: acrescenta os verbetes novos, deixa intactos os idênticos e
só troca os que diferem se o chamador pedir explicitamente (`substituir_conflitos`); verbete
ausente do arquivo nunca é removido. `analisar_importacao` mostra o efeito sem gravar.

Persistência: um único arquivo JSON, gravação atômica (arquivo temporário + rename), mesmo
padrão de `src.prazos_orcamentarios`. Arquivo ilegível/inválido levanta `ErroGlossario` — nunca
cai silenciosamente na base fixa, para não esconder (nem sobrescrever depois) as edições do
usuário. Dado de trabalho, não versionado (ver `.gitignore`).

Contrato público:
    carregar(caminho=None) -> tuple[TermoGlossario, ...]
    incluir(dados, caminho=None) -> TermoGlossario
    atualizar(nome_original, dados, caminho=None) -> tuple[str, ...]
    excluir(nome, caminho=None) -> None
    exportar(caminho=None) -> str
    analisar_importacao(conteudo, caminho=None) -> PlanoImportacao
    aplicar_importacao(conteudo, substituir_conflitos, caminho=None) -> PlanoImportacao
`dados` é um mapeamento com as chaves de `TermoGlossario` (`termo`, `definicao`, `fonte`, `tema`
e, opcionais, `sigla`, `uso_no_sistema`, `aliases`, `ver_tambem`).
"""

from __future__ import annotations

import json
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from src.glossario import GLOSSARIO, TEMAS, TermoGlossario

CAMINHO_PADRAO = Path("data/glossario/cadastro.json")
_VERSAO = 1


class ErroGlossario(ValueError):
    """Verbete inválido ou cadastro ilegível — nunca gravar/ler pela metade."""


def _caminho(caminho: str | Path | None) -> Path:
    # Resolvido na chamada (não como default do parâmetro) para os testes poderem trocar
    # `CAMINHO_PADRAO` sem tocar no arquivo real.
    return Path(caminho) if caminho is not None else Path(CAMINHO_PADRAO)


def _chave(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.casefold().split())


def _opcional(valor: Any) -> str | None:
    texto = str(valor).strip() if valor is not None else ""
    return texto or None


def _lista(valor: Any) -> tuple[str, ...]:
    itens: list[str] = []
    vistos: set[str] = set()
    for item in valor or ():
        texto = str(item).strip()
        if texto and _chave(texto) not in vistos:
            vistos.add(_chave(texto))
            itens.append(texto)
    return tuple(itens)


def _hoje() -> str:
    return date.today().isoformat()


def _data_valida(valor: Any) -> str | None:
    texto = _opcional(valor)
    if texto is None:
        return None
    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError as erro:
        raise ErroGlossario(f"Data de alteração inválida: {texto!r}.") from erro


def _montar(
    dados: Mapping[str, Any], *, personalizado: bool, atualizado_em: str | None = None
) -> TermoGlossario:
    termo = str(dados.get("termo") or "").strip()
    definicao = str(dados.get("definicao") or "").strip()
    fonte = str(dados.get("fonte") or "").strip()
    tema = str(dados.get("tema") or "").strip()
    if not termo:
        raise ErroGlossario("Informe o termo.")
    if not definicao:
        raise ErroGlossario("Informe a definição.")
    if not fonte:
        raise ErroGlossario(
            "Informe a fonte (manual e página, ou declare que é contexto do sistema)."
        )
    if tema not in TEMAS:
        raise ErroGlossario(f"Tema inválido: {tema!r}.")
    return TermoGlossario(
        termo=termo,
        definicao=definicao,
        fonte=fonte,
        tema=tema,
        sigla=_opcional(dados.get("sigla")),
        ver_tambem=_lista(dados.get("ver_tambem")),
        aliases=_lista(dados.get("aliases")),
        uso_no_sistema=_opcional(dados.get("uso_no_sistema")),
        personalizado=personalizado,
        atualizado_em=atualizado_em,
    )


def _validar_conjunto(termos: tuple[TermoGlossario, ...]) -> None:
    nomes = {_chave(termo.termo): termo.termo for termo in termos}
    if len(nomes) != len(termos):
        raise ErroGlossario("Já existe um verbete com esse termo.")
    for termo in termos:
        for referencia in termo.ver_tambem:
            if _chave(referencia) not in nomes:
                raise ErroGlossario(
                    f"“{termo.termo}” refere-se a “{referencia}”, que não existe no glossário."
                )
            if _chave(referencia) == _chave(termo.termo):
                raise ErroGlossario(f"“{termo.termo}” não pode referir-se a si mesmo.")


def _indice(termos: tuple[TermoGlossario, ...], nome: str) -> int:
    for posicao, termo in enumerate(termos):
        if _chave(termo.termo) == _chave(nome):
            return posicao
    raise ErroGlossario(f"Verbete não encontrado: {nome!r}.")


def _ler_termos(texto: str) -> tuple[TermoGlossario, ...]:
    conteudo = json.loads(texto)
    termos = tuple(
        _montar(
            item,
            personalizado=bool(item.get("personalizado", False)),
            atualizado_em=_data_valida(item.get("atualizado_em")),
        )
        for item in conteudo["termos"]
    )
    _validar_conjunto(termos)
    return termos


def carregar(caminho: str | Path | None = None) -> tuple[TermoGlossario, ...]:
    """Verbetes vigentes: o cadastro gravado ou, se ainda não existir, a base fixa."""

    arquivo = _caminho(caminho)
    if not arquivo.exists():
        return GLOSSARIO
    try:
        return _ler_termos(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as erro:
        raise ErroGlossario(
            f"Não foi possível ler o cadastro do glossário em {arquivo}: {erro}. "
            "O arquivo não foi alterado; corrija-o ou renomeie-o para voltar à base padrão."
        ) from erro


def _serializar(termos: tuple[TermoGlossario, ...]) -> str:
    carga = {"versao": _VERSAO, "termos": [asdict(termo) for termo in termos]}
    return json.dumps(carga, ensure_ascii=False, indent=2)


def _gravar(termos: tuple[TermoGlossario, ...], arquivo: Path) -> None:
    _validar_conjunto(termos)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.parent / f".{arquivo.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(_serializar(termos), encoding="utf-8")
        temporario.replace(arquivo)
    finally:
        if temporario.exists():
            temporario.unlink()


def incluir(dados: Mapping[str, Any], caminho: str | Path | None = None) -> TermoGlossario:
    """Acrescenta um verbete novo (marcado `personalizado`) e grava o cadastro."""

    arquivo = _caminho(caminho)
    atuais = carregar(arquivo)
    novo = _montar(dados, personalizado=True, atualizado_em=_hoje())
    _gravar(atuais + (novo,), arquivo)
    return novo


def atualizar(
    nome_original: str, dados: Mapping[str, Any], caminho: str | Path | None = None
) -> tuple[str, ...]:
    """Substitui os campos de um verbete existente.

    Devolve os termos cujas referências `ver_tambem` foram ajustadas por causa de um
    renomeio (vazio se o nome não mudou ou ninguém o referenciava).
    """

    arquivo = _caminho(caminho)
    atuais = carregar(arquivo)
    posicao = _indice(atuais, nome_original)
    antigo = atuais[posicao]
    editado = _montar(dados, personalizado=antigo.personalizado, atualizado_em=_hoje())

    ajustados: list[str] = []
    resultado = list(atuais)
    resultado[posicao] = editado
    if editado.termo != antigo.termo:
        for indice, outro in enumerate(resultado):
            if indice == posicao or not any(
                _chave(ref) == _chave(antigo.termo) for ref in outro.ver_tambem
            ):
                continue
            referencias = tuple(
                editado.termo if _chave(ref) == _chave(antigo.termo) else ref
                for ref in outro.ver_tambem
            )
            resultado[indice] = replace(outro, ver_tambem=referencias, atualizado_em=_hoje())
            ajustados.append(outro.termo)

    _gravar(tuple(resultado), arquivo)
    return tuple(ajustados)


def excluir(nome: str, caminho: str | Path | None = None) -> None:
    """Remove um verbete, salvo se outro ainda o referenciar em `ver_tambem`."""

    arquivo = _caminho(caminho)
    atuais = carregar(arquivo)
    posicao = _indice(atuais, nome)
    alvo = atuais[posicao]
    referenciam = [
        termo.termo
        for termo in atuais
        if termo is not alvo and any(_chave(ref) == _chave(alvo.termo) for ref in termo.ver_tambem)
    ]
    if referenciam:
        raise ErroGlossario(
            f"“{alvo.termo}” não pode ser excluído: é citado em “Ver também” por "
            + ", ".join(f"“{nome_ref}”" for nome_ref in referenciam)
            + ". Remova essas referências antes."
        )
    _gravar(atuais[:posicao] + atuais[posicao + 1 :], arquivo)


def exportar(caminho: str | Path | None = None) -> str:
    """JSON dos verbetes vigentes (base + edições), no mesmo formato do cadastro — pronto
    para ser importado em outra máquina com `analisar_importacao`/`aplicar_importacao`."""

    return _serializar(carregar(caminho))


@dataclass(frozen=True)
class PlanoImportacao:
    """Resultado de `analisar_importacao`, sem gravar nada."""

    novos: tuple[TermoGlossario, ...]
    iguais: tuple[TermoGlossario, ...]
    #: pares (verbete atual, verbete do arquivo) com o mesmo termo e conteúdo diferente.
    conflitos: tuple[tuple[TermoGlossario, TermoGlossario], ...]
    _importados: tuple[TermoGlossario, ...] = field(repr=False, default=())


def _mesmo_conteudo(a: TermoGlossario, b: TermoGlossario) -> bool:
    return replace(a, personalizado=False, atualizado_em=None) == replace(
        b, personalizado=False, atualizado_em=None
    )


def analisar_importacao(conteudo: str | bytes, caminho: str | Path | None = None) -> PlanoImportacao:
    """Compara um arquivo exportado com o cadastro vigente. Nada é gravado.

    Levanta `ErroGlossario` se o arquivo for ilegível ou inconsistente por si só (campos
    obrigatórios, tema, duplicidade, referências quebradas dentro do próprio arquivo).
    """

    texto = conteudo.decode("utf-8-sig") if isinstance(conteudo, bytes) else conteudo
    try:
        importados = _ler_termos(texto)
    except ErroGlossario:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as erro:
        raise ErroGlossario(f"Arquivo de glossário inválido: {erro}.") from erro

    atuais = {_chave(termo.termo): termo for termo in carregar(caminho)}
    novos: list[TermoGlossario] = []
    iguais: list[TermoGlossario] = []
    conflitos: list[tuple[TermoGlossario, TermoGlossario]] = []
    for termo in importados:
        atual = atuais.get(_chave(termo.termo))
        if atual is None:
            novos.append(termo)
        elif _mesmo_conteudo(atual, termo):
            iguais.append(termo)
        else:
            conflitos.append((atual, termo))
    return PlanoImportacao(tuple(novos), tuple(iguais), tuple(conflitos), importados)


def aplicar_importacao(
    conteudo: str | bytes, substituir_conflitos: bool, caminho: str | Path | None = None
) -> PlanoImportacao:
    """Mescla o arquivo no cadastro: acrescenta os verbetes novos e, só se
    `substituir_conflitos`, troca os que já existem com conteúdo diferente. Nunca remove
    verbete que não esteja no arquivo. O resultado precisa ser consistente (referências
    `ver_tambem` resolvidas); se não for, nada é gravado."""

    arquivo = _caminho(caminho)
    plano = analisar_importacao(conteudo, arquivo)
    substituicoes = {_chave(novo.termo): novo for _, novo in plano.conflitos} if substituir_conflitos else {}
    resultado = [
        replace(substituicoes[_chave(termo.termo)], personalizado=termo.personalizado)
        if _chave(termo.termo) in substituicoes
        else termo
        for termo in carregar(arquivo)
    ]
    resultado.extend(plano.novos)
    if not plano.novos and not substituicoes:
        return plano
    _gravar(tuple(resultado), arquivo)
    return plano
