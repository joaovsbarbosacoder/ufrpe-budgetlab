"""Vínculos manuais de Emendas: auditoria, reversão e absorção oficial."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.emendas_parlamentares import (
    ErroPoliticaImportacao,
    ErroVinculoEmenda,
    carregar_emendas_cadastradas,
    compor_relatorio_com_cadastros,
    nova_emenda_acompanhamento,
    vincular_execucao_emendas,
)
from src.vinculos_emendas import (
    carregar_eventos_vinculo,
    compor_relatorio_com_vinculos,
    desfazer_vinculo_manual,
    historico_eventos_dataframe,
    registrar_nova_emenda_vinculada,
    registrar_vinculo_manual,
)


def _relatorio(linhas: list[dict]) -> pd.DataFrame:
    padrao = {
        "arquivo_origem": "relatorio.xlsx",
        "aba_origem": "Emendas",
        "linha_origem": 4,
        "resultado_primario_cod": "6",
        "ptres": "P1",
        "emenda_numero": "202600000001",
        "autor_emenda": "PARLAMENTAR / Emenda 1",
        "parlamentar": "PARLAMENTAR",
        "gnd_cod": "4",
        "ano": 2026,
        "dotacao_atualizada": 100.0,
        "empenhada_relatorio": pd.NA,
        "liquidada_relatorio": pd.NA,
        "paga_relatorio": pd.NA,
    }
    return pd.DataFrame([{**padrao, **linha} for linha in linhas])


def _execucao(linhas: list[dict]) -> pd.DataFrame:
    padrao = {
        "ano": 2026,
        "resultado_primario_cod": "6",
        "ptres": "U1",
        "empenhada": 209.0,
        "liquidada": 0.0,
        "paga": pd.NA,
    }
    return pd.DataFrame([{**padrao, **linha} for linha in linhas])


class VinculosEmendasTests(unittest.TestCase):
    def test_vinculo_existente_e_aplicado_e_desfeito_sem_apagar_historico(self) -> None:
        relatorio = _relatorio([{}])
        execucao = _execucao([{}])
        pendencias = vincular_execucao_emendas(relatorio, execucao).execucao_sem_vinculo
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp) / "vinculos"
            criado = registrar_vinculo_manual(
                ano=2026,
                resultado_primario_cod="6",
                ptres="U1",
                emenda_numero="202600000001",
                pendencias=pendencias,
                relatorio=relatorio,
                cadastros=[],
                observacao="Conferido no processo",
                diretorio=pasta,
            )

            eventos = carregar_eventos_vinculo(pasta)
            composicao = compor_relatorio_com_vinculos(relatorio, [], eventos)
            resultado = vincular_execucao_emendas(composicao.relatorio, execucao)
            emenda = resultado.emendas.iloc[0]
            self.assertEqual(tuple(emenda["ptres"]), ("P1", "U1"))
            self.assertEqual(emenda["empenhada"], 209.0)
            self.assertEqual(emenda["liquidada"], 0.0)
            self.assertTrue(pd.isna(emenda["paga"]))
            self.assertEqual(composicao.ativos.iloc[0]["status"], "ativo")

            desfazer_vinculo_manual(
                criado["vinculo_id"], observacao="Correção", diretorio=pasta
            )
            eventos = carregar_eventos_vinculo(pasta)
            apos_desfazer = compor_relatorio_com_vinculos(relatorio, [], eventos)
            resultado = vincular_execucao_emendas(apos_desfazer.relatorio, execucao)

            self.assertTrue(apos_desfazer.ativos.empty)
            self.assertEqual(set(resultado.execucao_sem_vinculo["ptres"]), {"U1"})
            self.assertEqual(len(list(pasta.glob("*.json"))), 2)
            historico = historico_eventos_dataframe(eventos)
            self.assertEqual(set(historico["acao"]), {"vincular", "desfazer"})

    def test_relatorio_posterior_absorve_vinculo_sem_dupla_contagem(self) -> None:
        inicial = _relatorio([{}])
        execucao = _execucao([{}])
        pendencias = vincular_execucao_emendas(inicial, execucao).execucao_sem_vinculo
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp) / "vinculos"
            registrar_vinculo_manual(
                ano=2026,
                resultado_primario_cod="6",
                ptres="U1",
                emenda_numero="202600000001",
                pendencias=pendencias,
                relatorio=inicial,
                cadastros=[],
                diretorio=pasta,
            )
            oficial_atualizado = _relatorio(
                [{}, {"ptres": "U1", "linha_origem": 5, "dotacao_atualizada": 50.0}]
            )
            composicao = compor_relatorio_com_vinculos(
                oficial_atualizado, [], carregar_eventos_vinculo(pasta)
            )
            resultado = vincular_execucao_emendas(composicao.relatorio, execucao)

            self.assertEqual(len(composicao.relatorio), len(oficial_atualizado))
            self.assertEqual(len(composicao.absorvidos), 1)
            self.assertEqual(resultado.emendas.iloc[0]["empenhada"], 209.0)
            self.assertEqual(resultado.emendas.iloc[0]["ptres_total"], 2)

    def test_um_ptres_nao_pode_ter_dois_vinculos_manuais_ativos(self) -> None:
        relatorio = _relatorio(
            [
                {},
                {
                    "ptres": "P2",
                    "emenda_numero": "202600000002",
                    "autor_emenda": "OUTRA / Emenda 2",
                    "parlamentar": "OUTRA",
                    "linha_origem": 5,
                },
            ]
        )
        pendencias = vincular_execucao_emendas(
            relatorio, _execucao([{}])
        ).execucao_sem_vinculo
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp) / "vinculos"
            argumentos = {
                "ano": 2026,
                "resultado_primario_cod": "6",
                "ptres": "U1",
                "pendencias": pendencias,
                "relatorio": relatorio,
                "cadastros": [],
                "diretorio": pasta,
            }
            registrar_vinculo_manual(
                **argumentos, emenda_numero="202600000001"
            )
            with self.assertRaisesRegex(ErroVinculoEmenda, "já possui"):
                registrar_vinculo_manual(
                    **argumentos, emenda_numero="202600000002"
                )

    def test_vinculo_historico_e_bloqueado(self) -> None:
        relatorio = _relatorio([{}])
        pendencias = _execucao([{"ano": 2025}]).rename(
            columns={
                "empenhada": "empenhada_execucao",
                "liquidada": "liquidada_execucao",
                "paga": "paga_execucao",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ErroPoliticaImportacao):
                registrar_vinculo_manual(
                    ano=2025,
                    resultado_primario_cod="6",
                    ptres="U1",
                    emenda_numero="202600000001",
                    pendencias=pendencias,
                    relatorio=relatorio,
                    cadastros=[],
                    diretorio=Path(tmp),
                )

    def test_conflito_com_atualizacao_oficial_nao_e_aplicado(self) -> None:
        inicial = _relatorio(
            [
                {},
                {
                    "ptres": "P2",
                    "emenda_numero": "202600000002",
                    "autor_emenda": "OUTRA / Emenda 2",
                    "parlamentar": "OUTRA",
                    "linha_origem": 5,
                },
            ]
        )
        execucao = _execucao([{}])
        pendencias = vincular_execucao_emendas(inicial, execucao).execucao_sem_vinculo
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp) / "vinculos"
            registrar_vinculo_manual(
                ano=2026,
                resultado_primario_cod="6",
                ptres="U1",
                emenda_numero="202600000001",
                pendencias=pendencias,
                relatorio=inicial,
                cadastros=[],
                diretorio=pasta,
            )
            oficial = _relatorio(
                [
                    {},
                    {
                        "ptres": "U1",
                        "emenda_numero": "202600000002",
                        "autor_emenda": "OUTRA / Emenda 2",
                        "parlamentar": "OUTRA",
                        "linha_origem": 5,
                    },
                ]
            )
            composicao = compor_relatorio_com_vinculos(
                oficial, [], carregar_eventos_vinculo(pasta)
            )
            resultado = vincular_execucao_emendas(composicao.relatorio, execucao)

            self.assertEqual(len(composicao.conflitos), 1)
            self.assertEqual(len(composicao.relatorio), len(oficial))
            vinculada = resultado.emendas[
                resultado.emendas["emenda_numero"].eq("202600000002")
            ].iloc[0]
            self.assertEqual(vinculada["empenhada"], 209.0)

    def test_nova_emenda_e_controlada_pelo_evento_e_reversivel(self) -> None:
        relatorio = _relatorio([{}])
        execucao = _execucao([{}])
        pendencias = vincular_execucao_emendas(relatorio, execucao).execucao_sem_vinculo
        nova = nova_emenda_acompanhamento(
            exercicio=2026,
            parlamentar="NOVA PARLAMENTAR",
            numero="000000000002",
            rp_codigo="6",
            ptres=["U1"],
            gnd_codigo="03",
            dotacao_atualizada=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            emendas_dir = raiz / "emendas"
            vinculos_dir = raiz / "vinculos"
            gerenciada, evento = registrar_nova_emenda_vinculada(
                emenda=nova,
                pendencias=pendencias,
                relatorio=relatorio,
                cadastros=[],
                diretorio_emendas=emendas_dir,
                diretorio_vinculos=vinculos_dir,
            )
            cadastros = carregar_emendas_cadastradas(emendas_dir)
            cadastro_composto = compor_relatorio_com_cadastros(relatorio, cadastros)
            self.assertEqual(len(cadastro_composto.relatorio), len(relatorio))
            self.assertEqual(
                gerenciada["gerenciada_por_vinculo_id"], evento["vinculo_id"]
            )

            com_vinculo = compor_relatorio_com_vinculos(
                cadastro_composto.relatorio,
                cadastros,
                carregar_eventos_vinculo(vinculos_dir),
            )
            resultado = vincular_execucao_emendas(com_vinculo.relatorio, execucao)
            criada = resultado.emendas[
                resultado.emendas["emenda_numero"].eq("000000000002")
            ].iloc[0]
            self.assertEqual(tuple(criada["gnds"]), ("03",))
            self.assertEqual(criada["empenhada"], 209.0)

            desfazer_vinculo_manual(evento["vinculo_id"], diretorio=vinculos_dir)
            sem_vinculo = compor_relatorio_com_vinculos(
                cadastro_composto.relatorio,
                cadastros,
                carregar_eventos_vinculo(vinculos_dir),
            )
            self.assertEqual(len(sem_vinculo.relatorio), len(relatorio))
            self.assertTrue((emendas_dir / f"{gerenciada['id']}.json").exists())


if __name__ == "__main__":
    unittest.main()
