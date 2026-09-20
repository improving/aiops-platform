"""Relay one MCP (streamable HTTP) request to where the tools are.

``McpUpstream`` is the seam: today the LiteLLM MCP gateway, which
aggregates every server of the organization behind one endpoint. A
direct connection to one server is another implementation of the same
protocol, for a server LiteLLM cannot serve the way the platform needs.

The relay keeps no session state: LiteLLM answers ``tools/list`` and
``tools/call`` with or without ``Mcp-Session-Id``, and the header is
copied both ways for the clients that send it.
"""

from collections.abc import Iterator
from typing import Protocol

import httpx
from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import iterate_in_threadpool

from logger import setup_logger
from utils.litellm import LiteLLMClient, LiteLLMError

logger = setup_logger(__name__)

# Only these go upstream. Never Authorization, Cookie or X-Org: LiteLLM
# reads a key from Authorization too, so a forwarded platform token
# would be taken for a LiteLLM key.
REQUEST_HEADERS = (
    "accept",
    "content-type",
    "mcp-session-id",
    "mcp-protocol-version",
    "last-event-id",
)
RESPONSE_HEADERS = ("content-type", "mcp-session-id", "allow")
SERVERS_HEADER = "x-mcp-servers"
LITELLM_KEY_HEADER = "x-litellm-api-key"
# The proxy writes this into the spend-log row of an MCP call as its
# ``end_user`` (measured on v1.99.1), the same field a chat request's
# ``user`` fills, so a tool call is attributed like a model request.
END_USER_HEADER = "x-litellm-end-user-id"
EVENT_STREAM = "text/event-stream"
STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class McpUpstream(Protocol):
    def send(
        self, method: str, headers: dict[str, str], body: bytes | None
    ) -> httpx.Response:
        """A streamed response; the caller closes it with ``close``."""
        ...


class LiteLLMUpstream:
    """The organization's servers behind LiteLLM ``/mcp``: the
    organization's virtual key, limited to ``aliases``, plus the headers
    the credential resolver produced for this caller."""

    def __init__(
        self,
        client: LiteLLMClient,
        org_key: str,
        aliases: list[str],
        extra_headers: dict[str, str] | None = None,
        end_user: str | None = None,
    ):
        self._end_user = end_user
        self._client = client
        self._org_key = org_key
        self._aliases = aliases
        self._extra = extra_headers or {}

    def send(
        self, method: str, headers: dict[str, str], body: bytes | None
    ) -> httpx.Response:
        return self._client.request(
            method,
            "/mcp",
            content=body,
            stream=True,
            raise_for_status=False,
            # The organization's key in both places the proxy reads one,
            # so the master key never travels on a member's request.
            api_key=self._org_key,
            headers={
                **headers,
                **self._extra,
                **(
                    {END_USER_HEADER: self._end_user} if self._end_user else {}
                ),
                LITELLM_KEY_HEADER: f"Bearer {self._org_key}",
                SERVERS_HEADER: ",".join(self._aliases),
            },
        )


def forwarded_headers(headers) -> dict[str, str]:
    return {name: headers[name] for name in REQUEST_HEADERS if name in headers}


def close(response: httpx.Response) -> None:
    response.close()
    client = response.extensions.get("aiops_client")
    if client is not None:
        client.close()


def _chunks(response: httpx.Response) -> Iterator[bytes]:
    """The upstream bytes as they come. A stream that breaks just ends:
    an MCP client treats a closed stream as a lost connection, and an
    error frame of another protocol would not parse."""
    try:
        yield from response.iter_bytes()
    except httpx.HTTPError as e:
        logger.warning("MCP upstream stream broke: %s", e)
    finally:
        close(response)


def relay(upstream: McpUpstream, method: str, headers, body: bytes | None):
    """Blocking until the upstream's headers arrive; run it in a
    thread. The upstream's status passes through: a 404 (session gone),
    a 405 or a 202 is an answer of the protocol."""
    try:
        response = upstream.send(method, forwarded_headers(headers), body)
    except LiteLLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    passed = {
        name: response.headers[name]
        for name in RESPONSE_HEADERS
        if name in response.headers
    }
    content_type = response.headers.get("content-type", "")
    if content_type.startswith(EVENT_STREAM):
        return StreamingResponse(
            iterate_in_threadpool(_chunks(response)),
            status_code=response.status_code,
            headers={**passed, **STREAM_HEADERS},
        )
    try:
        content = response.read()
    finally:
        close(response)
    return Response(
        content=content, status_code=response.status_code, headers=passed
    )
