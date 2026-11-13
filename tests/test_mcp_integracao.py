"""Teste REAL de handshake MCP e tools; exige instalar requirements.txt."""
import asyncio
import os
import secrets
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from contratos import verificar_catalogo_mcp
    from assistente import retorno_da_tool
except ImportError:
    ClientSession = None


@unittest.skipIf(ClientSession is None, "SDK MCP não instalado; pip install -r requirements.txt")
class IntegracaoMCPTest(unittest.TestCase):
    def test_mcp_stdio_handshake_e_controle_por_objeto(self):
        async def teste():
            with tempfile.TemporaryDirectory() as pasta:
                env = {
                    "ARQVORA_USUARIO": "P001", "ARQVORA_SESSAO": "sessao-mcp-teste",
                    "ARQVORA_TAREFA": "guias", "ARQVORA_HMAC_KEY": secrets.token_hex(32),
                    "ARQVORA_DB": str(Path(pasta) / "db.sqlite"), "PYTHONUNBUFFERED": "1",
                }
                process = StdioServerParameters(command=sys.executable, args=[str(BASE / "mcp_server.py")], env=env)
                async with stdio_client(process) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        verificar_catalogo_mcp(tools.tools)
                        ok = retorno_da_tool(await session.call_tool("listar_guias", {"beneficiario_id": "P001"}))
                        self.assertTrue(ok["ok"])
                        negado = retorno_da_tool(await session.call_tool("listar_guias", {"beneficiario_id": "P002"}))
                        self.assertFalse(negado["ok"])
                        self.assertTrue(negado["bloqueado"])
        asyncio.run(teste())
