"""Pure-ASGI middleware: stamps X-Request-ID on every response (sending
the unhandled-exception 500 itself, since Starlette's ServerErrorMiddleware
sits outside it) and records the audit trail (spec 5.3)."""

import json
import re
import uuid

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from audit.events import action_for, parse_path, record, should_record
from db.database import get_db_direct
from logger import setup_logger

logger = setup_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
# A client-supplied request id is echoed only when it looks like an id: a
# value we would otherwise echo back verbatim into logs and the audit CSV.
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _client_request_id(scope: Scope) -> str | None:
    value = Headers(scope=scope).get(REQUEST_ID_HEADER)
    if value and REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return None


class AuditMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Starlette's request.state writes into scope["state"]; make sure
        # the dict exists before the app runs so the routes and this
        # middleware share it.
        state = scope.setdefault("state", {})
        request_id = _client_request_id(scope) or str(uuid.uuid4())
        state["request_id"] = request_id
        status = 500
        started = False
        aborted = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                MutableHeaders(scope=message).append(
                    REQUEST_ID_HEADER, request_id
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            if not started:
                # ServerErrorMiddleware wraps us and would otherwise
                # render this 500 itself, with no X-Request-ID: send it
                # here, then re-raise so ServerErrorMiddleware (which
                # skips sending its own response once one has started)
                # still sees the exception and propagates it.
                status = 500
                try:
                    await _send_internal_error(send, request_id)
                except Exception:
                    logger.warning(
                        "Could not send the internal-error response",
                        exc_info=True,
                    )
            else:
                # The response had already started (for example, a
                # streamed answer broke partway through): the client
                # already has the status we sent, we just never
                # finished the body.
                aborted = True
            raise
        finally:
            if should_record(scope["method"], scope["path"]):
                await run_in_threadpool(
                    _record_request, scope, state, status, aborted
                )


async def _send_internal_error(send: Send, request_id: str) -> None:
    body = json.dumps({"detail": "Internal server error"}).encode()
    start: Message = {
        "type": "http.response.start",
        "status": 500,
        "headers": [],
    }
    headers = MutableHeaders(scope=start)
    headers["content-type"] = "application/json"
    headers["content-length"] = str(len(body))
    headers.append(REQUEST_ID_HEADER, request_id)
    await send(start)
    await send({"type": "http.response.body", "body": body})


def _record_request(
    scope: Scope, state: dict, status: int, aborted: bool = False
) -> None:
    """One event per mutating call, with its own session; a failure here
    is logged and never reaches the user."""
    parsed = parse_path(scope["path"])
    if parsed is None:
        return
    kind, resource_id = parsed
    try:
        db = get_db_direct()
    except Exception:
        logger.warning(
            "Audit event not recorded: no database session", exc_info=True
        )
        return
    try:
        record(
            db,
            user=state.get("current_user"),
            action=action_for(scope["method"], scope["path"]),
            resource_kind=kind,
            resource_id=resource_id,
            outcome=status,
            request_id=state.get("request_id"),
            detail={"aborted": True} if aborted else None,
        )
        db.commit()
    except Exception:
        logger.warning("Audit event not recorded", exc_info=True)
        db.rollback()
    finally:
        db.close()
