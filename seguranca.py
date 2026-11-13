"""Política determinística e comprovantes de aprovação; nunca depende da decisão do LLM."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

from contratos import FERRAMENTAS, validar_campos


class Bloqueado(Exception):
    pass


ESCOPO_USUARIO = frozenset({"cobertura:ler", "guias:ler", "rede:ler", "autorizacao:solicitar"})
ESCOPO_AGENTE = frozenset({"cobertura:ler", "guias:ler", "rede:ler", "autorizacao:solicitar"})
TAREFAS = {
    "cobertura": frozenset({"cobertura:ler"}),
    "guias": frozenset({"guias:ler"}),
    "rede": frozenset({"rede:ler"}),
    "autorizacao": frozenset({"cobertura:ler", "autorizacao:solicitar"}),
    "ataque": frozenset({"guias:ler"}),
    "geral": ESCOPO_USUARIO,
}


@dataclass(frozen=True)
class Contexto:
    usuario: str
    sessao: str
    agente: str
    tarefa: str


def carregar_contexto() -> Contexto:
    """Identidade vinda do processo host, não de argumentos MCP nem do prompt."""
    usuario = os.getenv("ARQVORA_USUARIO", "")
    sessao = os.getenv("ARQVORA_SESSAO", "")
    tarefa = os.getenv("ARQVORA_TAREFA", "")
    if usuario not in ("P001", "P002") or not sessao or tarefa not in TAREFAS:
        raise Bloqueado("Contexto confiável ausente ou inválido: falha fechada")
    return Contexto(usuario, sessao, "agente-beneficiario-v1", tarefa)


def autorizar(ctx: Contexto, nome: str, params: dict) -> None:
    if nome not in FERRAMENTAS:
        raise Bloqueado("Ferramenta fora da allowlist")
    try:
        validar_campos(nome, params)
    except ValueError as exc:
        raise Bloqueado(str(exc)) from exc
    escopo = FERRAMENTAS[nome]["acao"]
    if escopo not in (ESCOPO_USUARIO & ESCOPO_AGENTE & TAREFAS.get(ctx.tarefa, frozenset())):
        raise Bloqueado("Fora do escopo da tarefa ou dos privilégios do usuário/agente")
    # Controle de objeto: ID fornecido pelo LLM NÃO é fonte de autorização.
    if "beneficiario_id" in params and params["beneficiario_id"] != ctx.usuario:
        raise Bloqueado("Acesso negado: beneficiário não pertence à sessão")
    if nome in ("consultar_cobertura", "solicitar_autorizacao"):
        if params["procedimento_codigo"] not in {"CONS-001", "IMG-001", "LAB-001", "EST-999"}:
            raise Bloqueado("Código de procedimento não reconhecido")
    if nome == "consultar_rede":
        if not all(len(params[k]) <= 80 for k in ("especialidade", "cidade")):
            raise Bloqueado("Consulta muito extensa")


def serializar_acao(ctx: Contexto, ferramenta: str, params: dict) -> bytes:
    obj = {"usuario": ctx.usuario, "sessao": ctx.sessao, "agente": ctx.agente,
           "ferramenta": ferramenta, "params": params}
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _desb64(valor: str) -> bytes:
    return base64.urlsafe_b64decode(valor + "=" * (-len(valor) % 4))


def criar_comprovante(ctx: Contexto, ferramenta: str, params: dict,
                      chave: bytes, *, agora: int | None = None) -> str:
    """Somente o HOST cria após o usuário digitar APROVAR para os parâmetros exatos."""
    autorizar(ctx, ferramenta, params)
    if ferramenta != "solicitar_autorizacao":
        raise Bloqueado("Comprovante somente para ações sensíveis")
    instante = int(time.time()) if agora is None else agora
    payload = {"hash_acao": hashlib.sha256(serializar_acao(ctx, ferramenta, params)).hexdigest(),
               "exp": instante + 120, "nonce": secrets.token_hex(16)}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assinatura = hmac.new(chave, body, hashlib.sha256).digest()
    return _b64(body) + "." + _b64(assinatura)


def validar_comprovante(ctx: Contexto, ferramenta: str, params: dict,
                       comprovante: str, chave: bytes, *, agora: int | None = None) -> str:
    if not isinstance(comprovante, str) or len(comprovante) > 2048:
        raise Bloqueado("Comprovante de aprovação inválido")
    try:
        body64, ass64 = comprovante.split(".")
        body, assinatura = _desb64(body64), _desb64(ass64)
        if len(body) > 512 or len(assinatura) != 32:
            raise ValueError("Token fora do formato")
        esperado = hmac.new(chave, body, hashlib.sha256).digest()
        if not hmac.compare_digest(assinatura, esperado):
            raise ValueError("Assinatura divergente")
        payload = json.loads(body)
        instante = int(time.time()) if agora is None else agora
        if type(payload["exp"]) is not int or not (instante < payload["exp"] <= instante + 120):
            raise ValueError("Comprovante expirado ou fora da janela")
        if (not isinstance(payload["nonce"], str)
                or len(payload["nonce"]) != 32 or not all(c in "0123456789abcdef" for c in payload["nonce"])):
            raise ValueError("Nonce inválido")
        hash_acao = hashlib.sha256(serializar_acao(ctx, ferramenta, params)).hexdigest()
        if not hmac.compare_digest(payload["hash_acao"], hash_acao):
            raise ValueError("Aprovação de outra ação, sessão ou usuário")
        return payload["nonce"]
    except (ValueError, KeyError, TypeError, UnicodeError, binascii.Error) as exc:
        raise Bloqueado("Comprovante inválido, expirado ou modificado") from exc


def chave_ambiental() -> bytes:
    raw = os.getenv("ARQVORA_HMAC_KEY", "")
    try:
        chave = bytes.fromhex(raw)
    except ValueError as exc:
        raise Bloqueado("Chave do HOST ausente") from exc
    if len(chave) < 32:
        raise Bloqueado("Chave do HOST ausente ou curta")
    return chave
