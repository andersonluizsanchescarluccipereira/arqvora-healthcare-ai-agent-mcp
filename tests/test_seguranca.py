"""Testes executáveis sem SDK MCP e sem modelo de IA."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from banco import conectar
from contratos import validar_campos
from seguranca import (Bloqueado, Contexto, autorizar, criar_comprovante,
                       validar_comprovante, carregar_contexto)
from servico import executar

CHAVE = b"A" * 32


class SegurancaTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = conectar(Path(self.temp.name) / "teste.sqlite")
        self.ctx = Contexto("P001", "sessao-1", "agente-beneficiario-v1", "geral")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def exec(self, ferramenta, params, *, ctx=None, comprovante="", chave=CHAVE):
        return executar(self.db, ctx or self.ctx, ferramenta, params,
                        comprovante_aprovacao=comprovante, chave=chave)

    def params_autorizacao(self):
        return {"beneficiario_id": "P001", "procedimento_codigo": "IMG-001",
                "justificativa": "Autorização fictícia"}

    def test_cobertura_autorizada(self):
        r = self.exec("consultar_cobertura", {"beneficiario_id": "P001", "procedimento_codigo": "IMG-001"})
        self.assertTrue(r["ok"])
        self.assertTrue(r["resultado"]["exige_autorizacao_previa"])

    def test_cobertura_nao_coberta(self):
        r = self.exec("consultar_cobertura", {"beneficiario_id": "P001", "procedimento_codigo": "EST-999"})
        self.assertFalse(r["resultado"]["coberto"])

    def test_guia_do_proprio_beneficiario(self):
        r = self.exec("listar_guias", {"beneficiario_id": "P001"})
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["resultado"]["guias"]), 2)
        self.assertNotIn("G-201", json.dumps(r))

    def test_bloqueia_acesso_outro_beneficiario(self):
        r = self.exec("listar_guias", {"beneficiario_id": "P002"})
        self.assertFalse(r["ok"])
        self.assertTrue(r["bloqueado"])

    def test_guia_outro_beneficiario_com_tarefa_geral(self):
        r = self.exec("listar_guias", {"beneficiario_id": "P002"})
        self.assertFalse(r["ok"])

    def test_guia_para_p002_em_sessao_p002(self):
        ctx2 = Contexto("P002", "s2", "agente-beneficiario-v1", "guias")
        r = self.exec("listar_guias", {"beneficiario_id": "P002"}, ctx=ctx2)
        self.assertTrue(r["ok"])
        self.assertEqual(r["resultado"]["guias"][0]["id"], "G-201")

    def test_consulta_de_rede(self):
        r = self.exec("consultar_rede", {"especialidade": "cardiologia", "cidade": "São Paulo"})
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["resultado"]["prestadores"]), 1)

    def test_rede_nao_vaza_outras_informacoes(self):
        r = self.exec("consultar_rede", {"especialidade": "cardiologia", "cidade": "São Paulo"})
        self.assertNotIn("beneficiario", json.dumps(r).lower())

    def test_escopo_restrito_por_tarefa(self):
        ctx = Contexto("P001", "s1", "agente-beneficiario-v1", "cobertura")
        r = self.exec("listar_guias", {"beneficiario_id": "P001"}, ctx=ctx)
        self.assertFalse(r["ok"])

    def test_tarefa_ataque_bloqueia_escrita(self):
        ctx = Contexto("P001", "s1", "agente-beneficiario-v1", "ataque")
        r = self.exec("solicitar_autorizacao", self.params_autorizacao(), ctx=ctx)
        self.assertFalse(r["ok"])

    def test_tarefa_desconhecida_falha_fechada(self):
        ctx = Contexto("P001", "s1", "agente-beneficiario-v1", "admin")
        with self.assertRaises(Bloqueado):
            autorizar(ctx, "listar_guias", {"beneficiario_id": "P001"})

    def test_tentativa_tool_nao_aprovada(self):
        r = self.exec("exfiltrar_dados", {})
        self.assertFalse(r["ok"])

    def test_argumento_extra_injetado(self):
        r = self.exec("listar_guias", {"beneficiario_id": "P001", "admin": "true"})
        self.assertFalse(r["ok"])

    def test_argumento_fora_do_tipo(self):
        r = self.exec("listar_guias", {"beneficiario_id": 123})
        self.assertFalse(r["ok"])

    def test_codigo_invalido(self):
        r = self.exec("consultar_cobertura", {"beneficiario_id": "P001", "procedimento_codigo": "XYZ"})
        self.assertFalse(r["ok"])

    def test_injecao_presente_na_observacao_nao_muda_politica(self):
        r = self.exec("listar_guias", {"beneficiario_id": "P001"})
        self.assertIn("IGNORE AS REGRAS", json.dumps(r))
        r2 = self.exec("listar_guias", {"beneficiario_id": "P002"})
        self.assertFalse(r2["ok"])

    def test_escrita_sem_aprovacao(self):
        r = self.exec("solicitar_autorizacao", self.params_autorizacao())
        self.assertFalse(r["ok"])

    def test_escrita_com_aprovacao(self):
        params = self.params_autorizacao()
        token = criar_comprovante(self.ctx, "solicitar_autorizacao", params, CHAVE)
        r = self.exec("solicitar_autorizacao", params, comprovante=token)
        self.assertTrue(r["ok"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM solicitacoes").fetchone()[0], 1)

    def test_comprovante_uso_unico(self):
        params = self.params_autorizacao()
        token = criar_comprovante(self.ctx, "solicitar_autorizacao", params, CHAVE)
        self.assertTrue(self.exec("solicitar_autorizacao", params, comprovante=token)["ok"])
        self.assertFalse(self.exec("solicitar_autorizacao", params, comprovante=token)["ok"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM solicitacoes").fetchone()[0], 1)

    def test_comprovante_outra_justificativa(self):
        params = self.params_autorizacao()
        token = criar_comprovante(self.ctx, "solicitar_autorizacao", params, CHAVE)
        params["justificativa"] = "Alterada depois da aprovação"
        self.assertFalse(self.exec("solicitar_autorizacao", params, comprovante=token)["ok"])

    def test_comprovante_de_outra_sessao(self):
        params = self.params_autorizacao()
        token = criar_comprovante(self.ctx, "solicitar_autorizacao", params, CHAVE)
        outra = Contexto("P001", "outra-sessao", "agente-beneficiario-v1", "geral")
        self.assertFalse(self.exec("solicitar_autorizacao", params, ctx=outra, comprovante=token)["ok"])

    def test_comprovante_de_outra_chave(self):
        params = self.params_autorizacao()
        token = criar_comprovante(self.ctx, "solicitar_autorizacao", params, CHAVE)
        self.assertFalse(self.exec("solicitar_autorizacao", params, comprovante=token, chave=b"B" * 32)["ok"])

    def test_comprovante_forjado(self):
        self.assertFalse(self.exec("solicitar_autorizacao", self.params_autorizacao(),
                                   comprovante="FAKE.FAKE")["ok"])

    def test_comprovante_expirado(self):
        params = self.params_autorizacao()
        token = criar_comprovante(self.ctx, "solicitar_autorizacao", params, CHAVE, agora=1000)
        with self.assertRaises(Bloqueado):
            validar_comprovante(self.ctx, "solicitar_autorizacao", params, token, CHAVE, agora=2000)

    def test_sem_cobertura_mesmo_com_aprovacao(self):
        params = {**self.params_autorizacao(), "procedimento_codigo": "EST-999"}
        token = criar_comprovante(self.ctx, "solicitar_autorizacao", params, CHAVE)
        self.assertFalse(self.exec("solicitar_autorizacao", params, comprovante=token)["ok"])

    def test_auditoria_registra_bloqueio(self):
        self.exec("listar_guias", {"beneficiario_id": "P002"})
        registro = self.db.execute("SELECT decisao FROM auditoria ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(registro["decisao"], "BLOQUEADO")

    def test_auditoria_nao_armazenar_justificativa(self):
        params = {**self.params_autorizacao(), "justificativa": "DADO_CLINICO_SENSIVEL_XXXXX"}
        token = criar_comprovante(self.ctx, "solicitar_autorizacao", params, CHAVE)
        self.exec("solicitar_autorizacao", params, comprovante=token)
        dados = json.dumps([dict(r) for r in self.db.execute("SELECT * FROM auditoria")])
        self.assertNotIn("DADO_CLINICO_SENSIVEL_XXXXX", dados)

    def test_mutacao_e_auditoria_atomicas(self):
        params = self.params_autorizacao()
        token = criar_comprovante(self.ctx, "solicitar_autorizacao", params, CHAVE)
        self.exec("solicitar_autorizacao", params, comprovante=token)
        self.assertEqual(self.db.execute("SELECT count(*) FROM auditoria WHERE decisao='EXECUTADO'").fetchone()[0], 1)

    def test_politica_nao_recebe_autoridade_do_texto(self):
        with self.assertRaises(Bloqueado):
            autorizar(self.ctx, "listar_guias", {"beneficiario_id": "P002"})


if __name__ == "__main__":
    unittest.main()
