"""What every endpoint an integration calls has in common (ADR 0008, Integrations C).

- **Errors** use the public contract's envelope (`docs/integrations/api-contract.md`):
  `{"error": {"code", "message", "request_id"}}`, plus `details` for a request that didn't
  validate (which field, and why; never the value sent). Status codes and headers such as
  `WWW-Authenticate` and `Retry-After` stay as they were.
- **Request ids.** The caller's `X-Request-ID` (up to 100 characters) or a new `req_...` one, echoed
  in the `X-Request-ID` response header, in errors and in audit entries.
- **Size.** A request body over `INTEGRATION_MAX_BODY_KB` is refused with 413 before it's parsed.

Integration routers use it with `APIRouter(route_class=EnvelopeRoute)`. Sign-in routes for people
keep FastAPI's `{"detail": ...}`.
"""

import logging
import secrets
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException

from app.core.config import get_settings

log = logging.getLogger(__name__)

CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_failed",
    429: "rate_limited",
}

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE"})


def request_id_of(request: Request) -> str:
    """This request's id: the caller's `X-Request-ID`, or one made up for it."""
    if not hasattr(request.state, "request_id"):
        given = (request.headers.get("X-Request-ID") or "").strip()
        request.state.request_id = given[:100] if given else f"req_{secrets.token_hex(12)}"
    return request.state.request_id


def error_response(
    status_code: int,
    message: str,
    request_id: str,
    headers: dict[str, str] | None = None,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    code = CODES.get(status_code, "internal_error" if status_code >= 500 else "request_failed")
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details:
        body["details"] = details
    return JSONResponse({"error": body}, status_code=status_code, headers=headers)


def _validation_details(error: RequestValidationError) -> list[dict[str, str]]:
    details = []
    for item in error.errors():
        location = [str(part) for part in item.get("loc", ())]
        # The first part says where (body, query, path); the rest is the field.
        field = ".".join(location[1:]) or (location[0] if location else "")
        details.append({"field": field, "message": str(item.get("msg", "Invalid value."))})
    return details


async def _read_limited_body(request: Request) -> None:
    """Read the body once, refusing it as soon as it's over the limit."""
    limit = get_settings().integration_max_body_kb * 1024
    too_large = HTTPException(413, detail=f"The request body is over {limit // 1024} KB.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_large
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise too_large
    # FastAPI parses the body from here, so it's never read twice.
    request._body = bytes(body)


class EnvelopeRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def envelope_handler(request: Request) -> Response:
            request_id = request_id_of(request)
            try:
                if request.method not in READ_METHODS:
                    await _read_limited_body(request)
                response = await handler(request)
            except RequestValidationError as error:
                response = error_response(
                    422,
                    "The request isn't valid.",
                    request_id,
                    details=_validation_details(error),
                )
            except HTTPException as error:
                message = error.detail if isinstance(error.detail, str) else "The request failed."
                response = error_response(
                    error.status_code, message, request_id, headers=error.headers
                )
            except Exception:
                log.exception("Integration request %s failed", request_id)
                response = error_response(500, "Something went wrong on our side.", request_id)
            response.headers["X-Request-ID"] = request_id
            return response

        return envelope_handler
