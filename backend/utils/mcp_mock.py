"""The MCP surface of ``AIOPS_CHAT_MOCK=true``, for the Playwright fast
tier: the tools a mocked discovery finds, and a stateless MCP server
with one tool, ``echo``, which the chat route's MCP client connects to
as to the real endpoint. Test doubles, kept out of the routers."""

import json

from fastapi.responses import JSONResponse, Response

MOCK_LITELLM_SERVER_ID = "mock"
MOCK_TOOLS = [
    {
        "name": "echo",
        "description": "Say it again",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        "annotations": {"readOnlyHint": True},
    }
]


def jsonrpc(id, result) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": id, "result": result})


def mock_endpoint(
    method: str, body: bytes | None, aliases: list[str] | None = None
) -> Response:
    """A stateless MCP server with one tool, for the fast tier: the
    chat route's MCP client connects to it as to the real endpoint."""
    if method != "POST":
        return Response(status_code=405, headers={"Allow": "POST"})
    try:
        message = json.loads(body or b"")
    except ValueError:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            },
            status_code=400,
        )
    rpc = message.get("method", "")
    if "id" not in message:
        return Response(status_code=202)
    params = message.get("params") or {}
    if rpc == "initialize":
        return jsonrpc(
            message["id"],
            {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "aiops-mock-mcp", "version": "1"},
            },
        )
    if rpc == "ping":
        return jsonrpc(message["id"], {})
    if rpc == "tools/list":
        # Named as the proxy names them, ``<alias>-<tool>``, one set for
        # each selected server: a client tells the servers apart by it.
        tools = [
            {**tool, "name": f"{alias}-{tool['name']}"}
            for alias in (aliases or [])
            for tool in MOCK_TOOLS
        ] or MOCK_TOOLS
        return jsonrpc(message["id"], {"tools": tools})
    if rpc == "tools/call":
        text = str((params.get("arguments") or {}).get("message", ""))
        return jsonrpc(
            message["id"],
            {"content": [{"type": "text", "text": text}], "isError": False},
        )
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32601, "message": f"Method not found: {rpc}"},
        }
    )
