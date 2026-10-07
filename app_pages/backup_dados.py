"""Backup dos dados — gera e recebe um `.zip` com os dados locais de `data/` (ver
`src/backup_dados.py` para as regras: manifesto com SHA-256, segredos fora por padrão, restauração
validada antes de gravar e sem sobrescrever em silêncio).

Mesmo padrão de "mensagem sobrevive a um rerun" + key com contador de `atualizar_planilhas.py`:
sem isso o `st.file_uploader` continua mostrando o arquivo já processado depois da restauração.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from src import backup_dados
from src.ui_theme import render_page_header

render_page_header(
    "Backup dos dados",
    "Gere um .zip com os dados locais para levar a outra máquina e restaure-o lá. "
    "Nada é alterado na origem; a restauração é validada antes de gravar.",
    "Administração",
)

_CHAVE_PACOTE = "backup_dados_pacote"
_CHAVE_MENSAGEM = "backup_dados_mensagem"
_CHAVE_GERACAO = "backup_dados_geracao"

if _CHAVE_MENSAGEM in st.session_state:
    nivel, texto = st.session_state.pop(_CHAVE_MENSAGEM)
    getattr(st, nivel)(texto)

# ---------------------------------------------------------------- exportar
with st.container(border=True):
    st.subheader("Gerar backup")
    st.caption(
        "O `token.json` do Google Agenda nunca entra (fica fora de `data/` de propósito). "
        "`.env` e `.streamlit/secrets.toml` também não são incluídos."
    )
    grupos = st.multiselect(
        "Pastas a incluir",
        options=list(backup_dados.GRUPOS),
        default=list(backup_dados.GRUPOS),
        format_func=lambda g: f"{g} — {backup_dados.GRUPOS[g]}",
    )
    incluir_credenciais = st.checkbox(
        "Incluir `credentials.json` do Google Agenda (segredo do cliente OAuth)",
        value=False,
        help="O arquivo do backup passa a conter esse segredo — guarde-o com o mesmo cuidado.",
    )
    senha = st.text_input(
        "Senha do backup (opcional)",
        type="password",
        help=(
            f"Mínimo de {backup_dados.TAMANHO_MINIMO_SENHA} caracteres. Cifra o arquivo inteiro "
            "(AES-256). Quem perder a senha perde o backup: ela não pode ser recuperada."
        ),
    )
    confirmacao = st.text_input("Repita a senha", type="password", disabled=not senha)
    if incluir_credenciais and not senha:
        st.warning("O `credentials.json` vai em texto legível dentro do .zip. Defina uma senha.")
    if senha and (len(senha) < backup_dados.TAMANHO_MINIMO_SENHA or senha != confirmacao):
        st.caption(
            f"A senha precisa ter ao menos {backup_dados.TAMANHO_MINIMO_SENHA} caracteres e ser "
            "igual nos dois campos."
        )
    senha_invalida = bool(senha) and (
        len(senha) < backup_dados.TAMANHO_MINIMO_SENHA or senha != confirmacao
    )
    if st.button("Gerar backup", type="primary", disabled=not grupos or senha_invalida):
        try:
            agora = datetime.now()
            with st.spinner("Gerando o backup..."):
                conteudo = backup_dados.gerar_backup(
                    backup_dados.BASE_PADRAO, grupos, incluir_credenciais, agora, senha or None
                )
            extensao = "zip.enc" if senha else "zip"
            st.session_state[_CHAVE_PACOTE] = (
                f"backup_budgetlab_{agora.strftime('%Y-%m-%d-%Hh%Mm')}.{extensao}",
                conteudo,
            )
        except (backup_dados.ErroBackup, OSError) as exc:
            st.error(f"Não foi possível gerar o backup: {exc}")
    if _CHAVE_PACOTE in st.session_state:
        nome, conteudo = st.session_state[_CHAVE_PACOTE]
        protegido = " protegido por senha" if backup_dados.esta_criptografado(conteudo) else ""
        st.success(f"Backup{protegido} pronto: {len(conteudo) / 1024 / 1024:.1f} MB.")
        st.download_button(
            "Baixar backup", data=conteudo, file_name=nome, mime="application/octet-stream"
        )

# ---------------------------------------------------------------- importar
with st.container(border=True):
    st.subheader("Restaurar backup")
    st.caption(
        "O pacote é conferido inteiro (estrutura, tamanhos e hashes) antes de qualquer gravação. "
        "Arquivos novos são criados; arquivos diferentes dos atuais só são substituídos se você "
        "escolher, e a cópia atual é preservada em `data/_backup_restauracao/`."
    )
    geracao = st.session_state.setdefault(_CHAVE_GERACAO, 0)
    enviado = st.file_uploader(
        "Arquivo de backup (.zip ou .zip.enc)", type=["zip", "enc"], key=f"backup_dados_upload_{geracao}"
    )
    if enviado is not None:
        conteudo = enviado.getvalue()
        senha_restauracao = None
        if backup_dados.esta_criptografado(conteudo):
            senha_restauracao = st.text_input(
                "Senha do backup", type="password", key=f"backup_dados_senha_{geracao}"
            ) or None
        try:
            if backup_dados.esta_criptografado(conteudo) and senha_restauracao is None:
                st.info("Este backup está protegido por senha: informe-a para continuar.")
                st.stop()
            previa = backup_dados.analisar_backup(
                conteudo, backup_dados.BASE_PADRAO, senha_restauracao
            )
        except backup_dados.ErroBackup as exc:
            st.error(f"Backup recusado, nada foi gravado: {exc}")
        else:
            novos = previa.com_situacao("novo")
            diferentes = previa.com_situacao("diferente")
            identicos = previa.com_situacao("identico")
            criado = previa.criado_em
            try:
                criado = datetime.fromisoformat(criado).strftime("%d/%m/%Y %H:%M")
            except ValueError:
                pass
            st.write(
                f"Backup de **{criado}** — {len(previa.itens)} arquivo(s): "
                f"**{len(novos)}** novo(s), **{len(diferentes)}** diferente(s) do atual, "
                f"{len(identicos)} idêntico(s)."
            )
            if previa.credenciais_incluidas:
                st.warning("Este backup contém o `credentials.json` do Google Agenda.")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Arquivo": i.caminho,
                            "Situação": {
                                "novo": "novo",
                                "diferente": "diferente do atual",
                                "identico": "idêntico",
                            }[i.situacao],
                            "Tamanho (KB)": round(i.tamanho / 1024, 1),
                        }
                        for i in previa.itens
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
            substituir = False
            if diferentes:
                opcao = st.radio(
                    f"{len(diferentes)} arquivo(s) já existem e são diferentes. O que fazer?",
                    options=["manter", "substituir"],
                    format_func={
                        "manter": "Manter os atuais (restaurar só os novos)",
                        "substituir": "Substituir pelos do backup (guardando cópia dos atuais)",
                    }.get,
                    key=f"backup_dados_politica_{geracao}",
                )
                substituir = opcao == "substituir"
            if st.button("Restaurar", type="primary", disabled=not (novos or (diferentes and substituir))):
                try:
                    resultado = backup_dados.restaurar_backup(
                        conteudo, backup_dados.BASE_PADRAO, substituir=substituir,
                        senha=senha_restauracao,
                    )
                except (backup_dados.ErroBackup, OSError) as exc:
                    st.error(f"Restauração desfeita, nada foi alterado: {exc}")
                else:
                    texto = (
                        f"Restauração concluída: {len(resultado.novos)} novo(s), "
                        f"{len(resultado.substituidos)} substituído(s), "
                        f"{len(resultado.mantidos_diferentes)} mantido(s) como estavam."
                    )
                    if resultado.pasta_copias is not None:
                        texto += f" Cópias dos substituídos em `{resultado.pasta_copias}`."
                    st.session_state[_CHAVE_MENSAGEM] = ("success", texto)
                    st.session_state[_CHAVE_GERACAO] = geracao + 1
                    st.rerun()
