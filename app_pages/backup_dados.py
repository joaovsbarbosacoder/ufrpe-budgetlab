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

from src import backup_dados, sincronizacao_drive as sinc
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


# ---------------------------------------------------------------- sincronização com o Google Drive
# Pedido de 21/10/2026 (src/sincronizacao_drive.py): pacote pequeno só com as decisões do usuário, enviado a cada mudança e
# buscado ao iniciar; conflito nunca é resolvido sozinho.
def _executar_sincronizacao(funcao, *args) -> None:
    """Roda uma operação de sincronização; guarda o resultado (ou o erro) para a próxima execução da página."""

    try:
        armazenamento = sinc.criar_armazenamento_drive()
        if armazenamento is None:
            st.session_state[_CHAVE_MENSAGEM] = ("warning", "Google Drive não conectado.")
        else:
            resultado = funcao(armazenamento, *args)
            st.session_state["sinc_resultado"] = resultado
            st.session_state[_CHAVE_MENSAGEM] = ("success", resultado.mensagem)
    except sinc.ErroSincronizacao as erro:
        st.session_state[_CHAVE_MENSAGEM] = ("error", str(erro))
    st.rerun()


with st.container(border=True):
    st.subheader("Sincronização com o Google Drive")
    st.caption(
        "Envia ao Drive um pacote pequeno (poucos KB) só com as decisões do usuário — Resultado Orçamentário, ajustes de "
        "projeção, preferências, Limite de Empenho, decisões de conciliação e cadastros de Contratos e Bolsas — e, ao abrir o "
        "sistema, busca a versão mais nova de outro dispositivo. Planilhas, cache e bancos ficam de fora. Cada envio é um "
        f"arquivo novo; ficam as {sinc.LIMITE_VERSOES} mais recentes. O acesso é só à pasta que o próprio sistema cria no seu Drive."
    )
    situacao_drive = sinc.situacao_conexao_drive()
    if situacao_drive == "sem_credenciais":
        st.info(
            "Falta o `credentials.json` do Google em `data/google_agenda/` (o mesmo da Agenda, ver `docs/google_agenda.md`); "
            "ative também a **API do Google Drive** no mesmo projeto do Google Cloud. Use o MESMO arquivo em todos os "
            "dispositivos: é ele que faz um dispositivo enxergar o que o outro enviou."
        )
    elif situacao_drive == "desconectado":
        if st.button("Conectar ao Google Drive", key="sinc_conectar", type="primary"):
            try:
                with st.spinner("Autorize o acesso na janela do navegador que se abriu..."):
                    sinc.conectar_drive()
                st.session_state[_CHAVE_MENSAGEM] = ("success", "Google Drive conectado.")
                st.session_state.pop("sinc_ultimo_ciclo", None)  # o próximo ciclo roda já, sem esperar o intervalo
            except sinc.ErroSincronizacao as erro:
                st.session_state[_CHAVE_MENSAGEM] = ("error", str(erro))
            st.rerun()
    else:
        try:
            estado_sinc = sinc.carregar_estado()
        except sinc.ErroSincronizacao as erro:
            estado_sinc = None
            st.error(str(erro))
        if estado_sinc is not None:
            ultimo = st.session_state.get("sinc_resultado")
            linhas = [f"Dispositivo: **{estado_sinc.dispositivo_nome or estado_sinc.dispositivo_id}** (`{estado_sinc.dispositivo_id}`)"]
            if estado_sinc.ultima_sincronizacao_em:
                linhas.append(f"Última sincronização: {datetime.fromisoformat(estado_sinc.ultima_sincronizacao_em):%d/%m/%Y %H:%M:%S}")
            if ultimo is not None:
                linhas.append(f"Situação: {ultimo.mensagem}")
            st.markdown("  \n".join(linhas))
            if ultimo is not None and ultimo.acao == sinc.ACAO_ERRO:
                st.warning("A sincronização não foi concluída; nada foi alterado. O sistema segue funcionando normalmente.")
            if ultimo is not None and ultimo.acao == sinc.ACAO_CONFLITO:
                st.warning(ultimo.mensagem)
                col_trazer, col_manter = st.columns(2)
                if col_trazer.button("Trazer a versão do Drive (a local fica guardada)", key="sinc_trazer", width="stretch"):
                    _executar_sincronizacao(lambda arm: sinc.resolver_conflito("trazer", arm))
                if col_manter.button("Manter a local e enviar", key="sinc_manter", width="stretch"):
                    _executar_sincronizacao(lambda arm: sinc.resolver_conflito("manter", arm))
            col_auto, col_agora, col_desconectar = st.columns([3, 2, 2], vertical_alignment="center")
            automatica = col_auto.toggle(
                "Sincronizar automaticamente (ao abrir e a cada alteração)", value=estado_sinc.automatica, key="sinc_automatica",
            )
            if automatica != estado_sinc.automatica:
                estado_sinc.automatica = automatica
                sinc.salvar_estado(estado_sinc)
                st.rerun()
            if col_agora.button("Sincronizar agora", key="sinc_agora", width="stretch"):
                _executar_sincronizacao(lambda arm: sinc.sincronizar(arm))
            if col_desconectar.button("Desconectar", key="sinc_desconectar", width="stretch"):
                revogado = sinc.desconectar_drive()
                st.session_state.pop("sinc_resultado", None)
                st.session_state[_CHAVE_MENSAGEM] = (
                    ("success", "Google Drive desconectado.") if revogado else
                    ("warning", "Desconectado aqui, mas o acesso não pôde ser revogado no Google (sem internet). Revogue em myaccount.google.com/permissions.")
                )
                st.rerun()
