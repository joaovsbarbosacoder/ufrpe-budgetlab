"""Testes de `src/sincronizacao_drive.py` — sincronização das decisões por uma pasta no Drive (21/10/2026).

O Drive é trocado por um armazenamento em memória; cada "dispositivo" é uma árvore `data/` + um diretório de estado em
`tmp_path`. Nada toca a rede.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src import sincronizacao_drive as sd
from src.sincronizacao_drive import (
    ACAO_CONFLITO,
    ACAO_EM_DIA,
    ACAO_ENVIADO,
    ACAO_ERRO,
    ACAO_NADA,
    ACAO_TRAZIDO,
    ErroSincronizacao,
    VersaoRemota,
)

T0 = datetime(2026, 10, 21, 9, 0, 0)


class Memoria:
    """Drive de mentira: compartilhado entre os dispositivos do teste."""

    def __init__(self) -> None:
        self.arquivos: dict[str, tuple[str, bytes]] = {}
        self.sequencia = 0
        self.falhar = False

    def _checar(self) -> None:
        if self.falhar:
            raise ErroSincronizacao("Sem conexão com o Google Drive: teste")

    def listar(self) -> list[VersaoRemota]:
        self._checar()
        return [VersaoRemota(i, n) for i, (n, _) in self.arquivos.items()]

    def enviar(self, nome: str, conteudo: bytes) -> str:
        self._checar()
        self.sequencia += 1
        self.arquivos[f"id{self.sequencia}"] = (nome, conteudo)
        return f"id{self.sequencia}"

    def baixar(self, id_versao: str) -> bytes:
        self._checar()
        return self.arquivos[id_versao][1]

    def apagar(self, id_versao: str) -> None:
        self._checar()
        del self.arquivos[id_versao]


class Dispositivo:
    def __init__(self, raiz: Path, nome: str) -> None:
        self.base = raiz / nome / "data"
        self.estado = self.base / "sincronizacao"
        self.base.mkdir(parents=True)

    def gravar(self, relativo: str, texto: str) -> None:
        caminho = self.base / relativo
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto, encoding="utf-8")

    def ler(self, relativo: str) -> str:
        return (self.base / relativo).read_text(encoding="utf-8")

    def sincronizar(self, drive: Memoria, minuto: int):
        return sd.sincronizar(drive, self.base, self.estado, agora=T0 + timedelta(minutes=minuto))

    def resolver(self, escolha: str, drive: Memoria, minuto: int):
        return sd.resolver_conflito(escolha, drive, self.base, self.estado, agora=T0 + timedelta(minutes=minuto))


@pytest.fixture(autouse=True)
def _ciclo_ligado(monkeypatch: pytest.MonkeyPatch) -> None:
    """O conftest desliga o ciclo automático para a suíte; aqui ele é o objeto do teste."""

    monkeypatch.delenv(sd.VARIAVEL_AMBIENTE, raising=False)


@pytest.fixture
def drive() -> Memoria:
    return Memoria()


@pytest.fixture
def a(tmp_path: Path) -> Dispositivo:
    return Dispositivo(tmp_path, "a")


@pytest.fixture
def b(tmp_path: Path) -> Dispositivo:
    return Dispositivo(tmp_path, "b")


def test_sem_dados_em_lugar_nenhum_nao_faz_nada(drive, a):
    assert a.sincronizar(drive, 0).acao == ACAO_NADA
    assert drive.arquivos == {}


def test_primeiro_envio_e_depois_em_dia_sem_novo_envio(drive, a):
    a.gravar("resultado_orcamentario/2026/despesas_manuais.json", '{"x": 1}')
    assert a.sincronizar(drive, 0).acao == ACAO_ENVIADO
    assert len(drive.arquivos) == 1
    assert a.sincronizar(drive, 1).acao == ACAO_EM_DIA
    assert len(drive.arquivos) == 1  # nada mudou: nada a enviar


def test_alteracao_local_gera_uma_versao_nova_sem_sobrescrever_a_anterior(drive, a):
    a.gravar("resultado_orcamentario/2026/celulas.json", '{"v": 1}')
    a.sincronizar(drive, 0)
    a.gravar("resultado_orcamentario/2026/celulas.json", '{"v": 2}')
    assert a.sincronizar(drive, 1).acao == ACAO_ENVIADO
    assert len(drive.arquivos) == 2
    nomes = sorted(n for n, _ in drive.arquivos.values())
    assert nomes[0] < nomes[1] and all(n.startswith("decisoes-") and n.endswith(".zip") for n in nomes)


def test_pacote_leva_so_as_pastas_de_decisoes(drive, a):
    a.gravar("resultado_orcamentario/2026/celulas.json", "{}")
    a.gravar("raw/planilha.xlsx", "pesado")
    a.gravar("processed/cache.parquet", "derivado")
    a.gravar("teds/teds.db", "banco")
    a.gravar("google_agenda/token.json", "segredo")
    a.gravar("google_agenda/credentials.json", "segredo")
    a.sincronizar(drive, 0)
    (_, pacote), = drive.arquivos.values()
    with zipfile.ZipFile(io.BytesIO(pacote)) as zf:
        nomes = [n for n in zf.namelist() if n != "MANIFESTO_BACKUP.json"]
    assert nomes == ["resultado_orcamentario/2026/celulas.json"]
    assert len(pacote) < 100_000


def test_segundo_dispositivo_sem_dados_traz_automaticamente(drive, a, b):
    a.gravar("resultado_orcamentario/2026/despesas_manuais.json", '{"de": "a"}')
    a.sincronizar(drive, 0)
    resultado = b.sincronizar(drive, 1)
    assert resultado.acao == ACAO_TRAZIDO and resultado.novos == 1
    assert b.ler("resultado_orcamentario/2026/despesas_manuais.json") == '{"de": "a"}'
    assert b.sincronizar(drive, 2).acao == ACAO_EM_DIA


def test_drive_mais_novo_e_nada_mudou_aqui_traz_guardando_o_que_substitui(drive, a, b):
    a.gravar("resultado_orcamentario/2026/celulas.json", '{"v": 1}')
    a.sincronizar(drive, 0)
    b.sincronizar(drive, 1)  # b traz a v1
    a.gravar("resultado_orcamentario/2026/celulas.json", '{"v": 2}')
    a.sincronizar(drive, 2)

    resultado = b.sincronizar(drive, 3)
    assert resultado.acao == ACAO_TRAZIDO and resultado.substituidos == 1
    assert b.ler("resultado_orcamentario/2026/celulas.json") == '{"v": 2}'
    copias = list((b.base / "_backup_restauracao").rglob("celulas.json"))
    assert len(copias) == 1 and copias[0].read_text(encoding="utf-8") == '{"v": 1}'


def test_dados_identicos_nos_dois_lados_nao_sao_conflito(drive, a, b):
    a.gravar("preferencias/ui.json", '{"p": 1}')
    b.gravar("preferencias/ui.json", '{"p": 1}')
    a.sincronizar(drive, 0)
    assert b.sincronizar(drive, 1).acao == ACAO_EM_DIA
    assert len(drive.arquivos) == 1


def test_os_dois_lados_mudaram_e_conflito_e_nada_e_alterado(drive, a, b):
    a.gravar("resultado_orcamentario/2026/celulas.json", '{"v": 1}')
    a.sincronizar(drive, 0)
    b.sincronizar(drive, 1)
    a.gravar("resultado_orcamentario/2026/celulas.json", '{"v": "a"}')
    a.sincronizar(drive, 2)
    b.gravar("resultado_orcamentario/2026/celulas.json", '{"v": "b"}')

    resultado = b.sincronizar(drive, 3)
    assert resultado.acao == ACAO_CONFLITO and resultado.versao is not None
    assert b.ler("resultado_orcamentario/2026/celulas.json") == '{"v": "b"}'
    assert len(drive.arquivos) == 2  # nada foi enviado nem apagado


def test_resolver_conflito_trazendo_a_do_drive_guarda_a_local(drive, a, b):
    a.gravar("resultado_orcamentario/2026/celulas.json", '{"v": 1}')
    a.sincronizar(drive, 0)
    b.sincronizar(drive, 1)
    a.gravar("resultado_orcamentario/2026/celulas.json", '{"v": "a"}')
    a.sincronizar(drive, 2)
    b.gravar("resultado_orcamentario/2026/celulas.json", '{"v": "b"}')
    assert b.sincronizar(drive, 3).acao == ACAO_CONFLITO

    assert b.resolver("trazer", drive, 4).acao == ACAO_TRAZIDO
    assert b.ler("resultado_orcamentario/2026/celulas.json") == '{"v": "a"}'
    copias = list((b.base / "_backup_restauracao").rglob("celulas.json"))
    assert [c.read_text(encoding="utf-8") for c in copias] == ['{"v": "b"}']
    assert b.sincronizar(drive, 5).acao == ACAO_EM_DIA


def test_resolver_conflito_mantendo_a_local_ela_vira_a_mais_nova(drive, a, b):
    a.gravar("resultado_orcamentario/2026/celulas.json", '{"v": 1}')
    a.sincronizar(drive, 0)
    b.sincronizar(drive, 1)
    a.gravar("resultado_orcamentario/2026/celulas.json", '{"v": "a"}')
    a.sincronizar(drive, 2)
    b.gravar("resultado_orcamentario/2026/celulas.json", '{"v": "b"}')
    assert b.sincronizar(drive, 3).acao == ACAO_CONFLITO

    assert b.resolver("manter", drive, 4).acao == ACAO_ENVIADO
    assert b.ler("resultado_orcamentario/2026/celulas.json") == '{"v": "b"}'
    assert len(drive.arquivos) == 3
    # o outro dispositivo, sem alteração local, recebe a decisão
    assert a.sincronizar(drive, 5).acao == ACAO_TRAZIDO
    assert a.ler("resultado_orcamentario/2026/celulas.json") == '{"v": "b"}'


def test_resolver_com_escolha_invalida_levanta(drive, a):
    with pytest.raises(ValueError):
        a.resolver("apagar tudo", drive, 0)


def test_guarda_so_as_ultimas_versoes_e_apaga_as_mais_antigas(drive, a, monkeypatch):
    monkeypatch.setattr(sd, "LIMITE_VERSOES", 5)
    for i in range(8):
        a.gravar("preferencias/ui.json", f'{{"i": {i}}}')
        assert a.sincronizar(drive, i).acao == ACAO_ENVIADO
    nomes = sorted(n for n, _ in drive.arquivos.values())
    assert len(nomes) == 5
    # as que ficaram são as 5 mais recentes (carimbos de 3 a 7 minutos depois de T0)
    assert nomes[0].startswith("decisoes-20261021-090300")
    assert nomes[-1].startswith("decisoes-20261021-090700")


def test_falha_de_rede_levanta_e_nao_altera_nada(drive, a):
    a.gravar("preferencias/ui.json", '{"p": 1}')
    drive.falhar = True
    with pytest.raises(ErroSincronizacao):
        a.sincronizar(drive, 0)
    assert a.ler("preferencias/ui.json") == '{"p": 1}'
    estado = sd.carregar_estado(a.estado)  # só a identidade do dispositivo foi gravada: nada foi sincronizado
    assert estado.ultima_versao_id is None and estado.ultimo_hash is None
    assert sd.carregar_estado(a.estado).dispositivo_id == estado.dispositivo_id  # estável entre cargas


def test_pacote_adulterado_no_drive_e_recusado_sem_gravar(drive, a, b):
    a.gravar("preferencias/ui.json", '{"p": 1}')
    a.sincronizar(drive, 0)
    id_versao, (nome, pacote) = next(iter(drive.arquivos.items()))
    drive.arquivos[id_versao] = (nome, pacote[:-20] + b"x" * 20)  # corrompe o zip
    with pytest.raises(ErroSincronizacao):
        b.sincronizar(drive, 1)
    assert not (b.base / "preferencias" / "ui.json").exists()


def test_estado_ilegivel_levanta_e_nao_e_sobrescrito(drive, a):
    a.estado.mkdir(parents=True)
    (a.estado / "estado.json").write_text("{não é json", encoding="utf-8")
    a.gravar("preferencias/ui.json", "{}")
    with pytest.raises(ErroSincronizacao):
        a.sincronizar(drive, 0)
    assert (a.estado / "estado.json").read_text(encoding="utf-8") == "{não é json"
    assert drive.arquivos == {}


def test_nomes_de_versao_trazem_dispositivo_e_data():
    versao = VersaoRemota("x", "decisoes-20261021-093015-000123-ab12cd34.zip")
    assert versao.dispositivo == "ab12cd34" and versao.criado_em == "21/10/2026 09:30:15"


# ---------------------------------------------------------------------------------------- ciclo da sessão
def test_ciclo_ao_iniciar_roda_e_depois_respeita_o_intervalo(drive, a):
    a.gravar("preferencias/ui.json", "{}")
    sessao: dict = {}
    relogio = iter([100.0, 110.0, 200.0]).__next__

    primeiro = sd.executar_ciclo_na_sessao(sessao, lambda: drive, a.base, a.estado, relogio=relogio)
    assert primeiro.acao == ACAO_ENVIADO
    a.gravar("preferencias/ui.json", '{"mudou": true}')
    # 10 s depois: dentro do intervalo, não roda (devolve o último resultado)
    assert sd.executar_ciclo_na_sessao(sessao, lambda: drive, a.base, a.estado, relogio=relogio).acao == ACAO_ENVIADO
    assert len(drive.arquivos) == 1
    # 100 s depois: roda de novo e envia a alteração
    assert sd.executar_ciclo_na_sessao(sessao, lambda: drive, a.base, a.estado, relogio=relogio).acao == ACAO_ENVIADO
    assert len(drive.arquivos) == 2


def test_ciclo_sem_conexao_nao_faz_nada(a):
    sessao: dict = {}
    assert sd.executar_ciclo_na_sessao(sessao, lambda: None, a.base, a.estado, relogio=lambda: 1.0) is None
    assert "sinc_resultado" not in sessao


def test_ciclo_com_falha_de_rede_vira_erro_e_o_app_segue(drive, a):
    a.gravar("preferencias/ui.json", "{}")
    drive.falhar = True
    sessao: dict = {}
    resultado = sd.executar_ciclo_na_sessao(sessao, lambda: drive, a.base, a.estado, relogio=lambda: 1.0)
    assert resultado.acao == ACAO_ERRO and "Sem conexão" in resultado.mensagem


def test_ciclo_desligado_nao_sincroniza(drive, a):
    a.gravar("preferencias/ui.json", "{}")
    estado = sd.carregar_estado(a.estado)
    estado.automatica = False
    sd.salvar_estado(estado, a.estado)
    sd.executar_ciclo_na_sessao({}, lambda: drive, a.base, a.estado, relogio=lambda: 1.0)
    assert drive.arquivos == {}


def test_pacote_com_arquivo_fora_das_decisoes_e_recusado(drive, b):
    from src import backup_dados

    origem = b.base.parent / "origem"
    (origem / "raw").mkdir(parents=True)
    (origem / "raw" / "planilha.xlsx").write_text("não deveria entrar", encoding="utf-8")
    pacote = backup_dados.gerar_backup(origem, grupos=["raw"])
    drive.enviar("decisoes-20261021-090000-000000-zzzzzzzz.zip", pacote)

    with pytest.raises(ErroSincronizacao, match="fora das decisões"):
        b.sincronizar(drive, 1)
    assert not (b.base / "raw").exists()


def test_variavel_de_ambiente_desliga_o_ciclo(drive, a, monkeypatch):
    a.gravar("preferencias/ui.json", "{}")
    monkeypatch.setenv(sd.VARIAVEL_AMBIENTE, "desligado")
    assert sd.executar_ciclo_na_sessao({}, lambda: drive, a.base, a.estado, relogio=lambda: 1.0) is None
    assert drive.arquivos == {}


def test_duas_sessoes_ao_mesmo_tempo_enviam_uma_unica_versao(drive, a):
    import threading
    import time

    a.gravar("preferencias/ui.json", '{"p": 1}')
    original = drive.enviar

    def enviar_lento(nome, conteudo):  # alarga a janela da corrida
        time.sleep(0.2)
        return original(nome, conteudo)

    drive.enviar = enviar_lento
    acoes: list[str] = []
    fios = [threading.Thread(target=lambda: acoes.append(a.sincronizar(drive, 0).acao)) for _ in range(4)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()

    assert len(drive.arquivos) == 1
    assert sorted(acoes) == [ACAO_EM_DIA] * 3 + [ACAO_ENVIADO]
