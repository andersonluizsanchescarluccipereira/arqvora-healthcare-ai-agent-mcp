"""Contrato revisado pelo HOST: não aceitar novas tools descobertas dinamicamente."""

FERRAMENTAS = {
    "consultar_cobertura": {
        "acao": "cobertura:ler",
        "campos": ("beneficiario_id", "procedimento_codigo"),
        "descricao": "Consulta se o plano fictício cobre um procedimento; não equivale a autorização.",
    },
    "listar_guias": {
        "acao": "guias:ler",
        "campos": ("beneficiario_id",),
        "descricao": "Lista guias simuladas do beneficiário autenticado.",
    },
    "consultar_rede": {
        "acao": "rede:ler",
        "campos": ("especialidade", "cidade"),
        "descricao": "Pesquisa rede credenciada fictícia, sem acesso a dados de saúde.",
    },
    "solicitar_autorizacao": {
        "acao": "autorizacao:solicitar",
        "campos": ("beneficiario_id", "procedimento_codigo", "justificativa"),
        "descricao": "Registra solicitação simulada somente após aprovação humana vinculada à ação.",
    },
}

SCHEMAS_LLM = {
    "consultar_cobertura": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "beneficiario_id": {"type": "string", "description": "ID fictício, por exemplo P001"},
            "procedimento_codigo": {"type": "string", "description": "CONS-001, IMG-001 ou LAB-001"},
        }, "required": ["beneficiario_id", "procedimento_codigo"],
    },
    "listar_guias": {
        "type": "object", "additionalProperties": False,
        "properties": {"beneficiario_id": {"type": "string"}},
        "required": ["beneficiario_id"],
    },
    "consultar_rede": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "especialidade": {"type": "string", "description": "Ex.: cardiologia"},
            "cidade": {"type": "string", "description": "Ex.: São Paulo"},
        }, "required": ["especialidade", "cidade"],
    },
    "solicitar_autorizacao": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "beneficiario_id": {"type": "string"},
            "procedimento_codigo": {"type": "string"},
            "justificativa": {"type": "string", "maxLength": 160},
        }, "required": ["beneficiario_id", "procedimento_codigo", "justificativa"],
    },
}


def validar_campos(nome: str, params: dict, *, incluir_comprovante: bool = False) -> None:
    if nome not in FERRAMENTAS or not isinstance(params, dict):
        raise ValueError("Ferramenta ou argumentos inválidos")
    esperados = set(FERRAMENTAS[nome]["campos"])
    if incluir_comprovante and nome == "solicitar_autorizacao":
        esperados.add("comprovante_aprovacao")
    if set(params) != esperados:
        raise ValueError("Parâmetros ausentes ou não autorizados")
    for campo, valor in params.items():
        if not isinstance(valor, str) or not (1 <= len(valor.strip()) <= 160):
            raise ValueError(f"Campo inválido: {campo}")


def opcoes_llm() -> list[dict]:
    return [
        {"type": "function", "function": {"name": nome, "description": meta["descricao"],
                                       "parameters": SCHEMAS_LLM[nome]}}
        for nome, meta in FERRAMENTAS.items()
    ]


def verificar_catalogo_mcp(tools: list) -> None:
    """Deny-by-default: verificamos nomes e parâmetros contra manifesto local."""
    vistos = {tool.name for tool in tools}
    if vistos != set(FERRAMENTAS):
        raise RuntimeError("O servidor MCP anunciou ferramenta não aprovada/ausente")
    for tool in tools:
        props = set(tool.inputSchema.get("properties", {}))
        esperado = set(FERRAMENTAS[tool.name]["campos"])
        if tool.name == "solicitar_autorizacao":
            esperado.add("comprovante_aprovacao")
        if props != esperado:
            raise RuntimeError(f"Contrato MCP alterado: {tool.name}")
