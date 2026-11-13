"""Chamada HTTP confinada à API local do Ollama, sem cliente de nuvem."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

ENDPOINT = "http://127.0.0.1:11434/api/chat"


def conversar(modelo: str, mensagens: list[dict], ferramentas: list[dict]) -> dict:
    corpo = {"model": modelo, "messages": mensagens, "tools": ferramentas,
             "stream": False, "options": {"temperature": 0, "num_ctx": 4096},
             "keep_alive": "5m"}
    request = Request(ENDPOINT, data=json.dumps(corpo, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    # Ignora configurações globais de proxy para esta conexão local.
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=180) as resposta:
            payload = json.loads(resposta.read(512_000))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("Ollama indisponível em 127.0.0.1:11434. Rode: ollama serve; "
                           "ollama pull qwen2.5:1.5b") from exc
    mensagem = payload.get("message")
    if not isinstance(mensagem, dict):
        raise RuntimeError("Ollama retornou resposta sem mensagem")
    return mensagem
