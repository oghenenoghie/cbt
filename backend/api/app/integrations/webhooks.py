"""Sending webhook deliveries (ADR 0008 decisions 14 and 15).

- Each delivery is an HTTPS POST of its fixed JSON body, signed with the endpoint's secret:
  `CBT-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<body>">`, with `CBT-Event-Id` and
  `CBT-Event-Type`. Receivers check the signature, reject old timestamps, and deduplicate by the
  event ID: delivery is at least once.
- Any 2xx answer within `WEBHOOK_TIMEOUT_SECONDS` counts as delivered. Anything else is retried
  after 1 minute, 5 minutes, 30 minutes, 2, 6, 12 and 24 hours, then given up as failed. A school
  admin can send it again from the delivery log.
- The receiver must be a public internet address: the host is resolved before each attempt, every
  address must be public, and the connection goes to the address that was checked, so a name
  can't be switched to an internal address in between. Redirects aren't followed. Only for
  development, `WEBHOOK_ALLOW_PRIVATE_URLS` lifts this.
- A delivery whose endpoint was disabled, whose integration was disabled, or whose integration
  lost the scope the event needs is cancelled instead of sent.
- `run_once` does one round: sends what's due, records once-only events for exams that show
  results at once and have just closed, and prunes old history. `python -m app.worker` calls it,
  and with `WEBHOOK_DELIVERY=inline` a thread in the API process does (`start_background`).
"""

import hashlib
import hmac
import ipaddress
import logging
import socket
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.attempts.service import GRACE
from app.core.config import get_settings
from app.integrations import events
from app.models import (
    Exam,
    Integration,
    IntegrationScope,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)
from app.models.tenant import utc_now

logger = logging.getLogger("app.webhooks")

RETRY_DELAYS = [
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
    timedelta(hours=12),
    timedelta(hours=24),
]
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
# A delivery left "sending" this long (the sender stopped part-way) is taken back.
STUCK_AFTER = timedelta(minutes=5)
KEEP_HISTORY = timedelta(days=30)
# Exams that show results at once get their result.released event when they close; older ones
# (closed before webhooks existed, or while the school had none) are left alone.
CLOSED_LOOKBACK = timedelta(days=7)
USER_AGENT = "IntelligentCBT-Webhooks/1"

# Tests swap these: an httpx transport instead of the network, and a resolver instead of DNS.
transport: httpx.BaseTransport | None = None


def resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


# --- Addresses -----------------------------------------------------------------------------------


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def url_problem(url: str, allow_private: bool | None = None) -> str | None:
    """Why this URL can't receive webhooks, or None. Checked when it's saved and before sending."""
    if allow_private is None:
        allow_private = get_settings().webhook_allow_private_urls
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "That isn't a valid web address."
    if parts.scheme != "https" and not (allow_private and parts.scheme == "http"):
        return "The address must start with https://."
    if not parts.hostname:
        return "The address needs a host name, such as https://portal.school.example/hooks."
    if parts.username or parts.password:
        return "The address can't contain a username or password."
    if port == 0:
        return "That isn't a valid port."
    if allow_private:
        return None
    host = parts.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan")):
        return "The address must be on the public internet, not a local network."
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        return None
    if not _public(str(literal)):
        return "The address must be on the public internet, not a local network."
    return None


# --- Signing and sending -------------------------------------------------------------------------


def signature(secret: str, timestamp: int, body: bytes) -> str:
    signed = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def _send(url: str, body: str, secret: str, event_id: str, event_type: str) -> tuple[int | None, str | None]:
    """POST one delivery. Returns (status code, problem); problem is None when delivered."""
    settings = get_settings()
    allow_private = settings.webhook_allow_private_urls
    problem = url_problem(url, allow_private)
    if problem:
        return None, problem
    parts = urlsplit(url)
    host = parts.hostname
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addresses = resolve(host, port)
    except (OSError, UnicodeError):
        return None, "The receiver's host name couldn't be found."
    if not addresses:
        return None, "The receiver's host name couldn't be found."
    if not allow_private and not all(_public(a) for a in addresses):
        return None, "The receiver's host name points to a private address, so nothing was sent."

    data = body.encode()
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "CBT-Event-Id": event_id,
        "CBT-Event-Type": event_type,
        "CBT-Signature": f"t={timestamp},v1={signature(secret, timestamp, data)}",
        # The host the receiver expects, though the connection goes to the checked address.
        "Host": parts.netloc.rsplit("@", 1)[-1],
    }
    address = addresses[0]
    pinned = f"[{address}]" if ":" in address else address
    target = parts._replace(netloc=f"{pinned}:{port}").geturl()
    extensions = {"sni_hostname": host} if parts.scheme == "https" else {}
    try:
        with httpx.Client(
            transport=transport,
            timeout=settings.webhook_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.post(target, content=data, headers=headers, extensions=extensions)
    except httpx.TimeoutException:
        return None, f"The receiver didn't answer within {settings.webhook_timeout_seconds:g} seconds."
    except httpx.HTTPError:
        return None, "Couldn't connect to the receiver."
    code = response.status_code
    if 200 <= code < 300:
        return code, None
    if 300 <= code < 400:
        return code, f"The receiver answered {code} (a redirect), which isn't followed."
    return code, f"The receiver answered {code}."


# --- Deliveries ----------------------------------------------------------------------------------


def _cancel_reason(db: Session, endpoint: WebhookEndpoint, event: WebhookEvent) -> str | None:
    if endpoint.status != "active":
        return "The endpoint was disabled."
    integration = db.get(Integration, endpoint.integration_id)
    if integration is None or integration.status != "active":
        return "The integration was disabled."
    if event.type == events.TEST_EVENT:
        return None
    scope = events.EVENT_TYPES[event.type][0]
    granted = db.scalar(
        select(IntegrationScope.id).where(
            IntegrationScope.integration_id == integration.id,
            IntegrationScope.scope == scope,
            IntegrationScope.granted.is_(True),
        )
    )
    if granted is None:
        return f"The integration no longer has the {scope} permission."
    return None


def _attempt(db: Session, delivery_id: str) -> None:
    delivery = db.get(WebhookDelivery, delivery_id)
    if delivery is None:  # its endpoint was deleted meanwhile
        return
    endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
    event = db.get(WebhookEvent, delivery.event_id)
    reason = _cancel_reason(db, endpoint, event)
    if reason:
        delivery.status = "cancelled"
        delivery.last_error = reason
        delivery.claimed_at = None
        delivery.next_attempt_at = None
        db.commit()
        return
    url, secret, body, event_id, event_type = (
        endpoint.url,
        endpoint.secret,
        delivery.payload,
        event.id,
        event.type,
    )
    db.commit()  # hold no transaction open while waiting on the network

    code, problem = _send(url, body, secret, event_id, event_type)

    at = utc_now()
    db.expire_all()
    delivery = db.get(WebhookDelivery, delivery_id)
    if delivery is None:  # deleted with its endpoint while it was being sent
        return
    endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
    delivery.attempts += 1
    delivery.last_attempt_at = at
    delivery.last_status_code = code
    delivery.claimed_at = None
    if problem is None:
        delivery.status = "delivered"
        delivery.delivered_at = at
        delivery.last_error = None
        delivery.next_attempt_at = None
        endpoint.last_success_at = at
    else:
        delivery.last_error = problem[:300]
        endpoint.last_failure_at = at
        if delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = "failed"
            delivery.next_attempt_at = None
        else:
            delivery.status = "pending"
            delivery.next_attempt_at = at + RETRY_DELAYS[delivery.attempts - 1]
    db.commit()


def _recover_stuck(db: Session, now: datetime) -> None:
    db.execute(
        update(WebhookDelivery)
        .where(WebhookDelivery.status == "sending", WebhookDelivery.claimed_at < now - STUCK_AFTER)
        .values(status="pending", claimed_at=None, next_attempt_at=now)
    )
    db.commit()


def deliver_due(db: Session, *, now: datetime | None = None, limit: int = 20) -> int:
    """Send up to `limit` due deliveries, oldest first. Returns how many were tried."""
    now = now or utc_now()
    _recover_stuck(db, now)
    due = list(
        db.scalars(
            select(WebhookDelivery.id)
            .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= now)
            .order_by(WebhookDelivery.next_attempt_at)
            .limit(limit)
        )
    )
    tried = 0
    for delivery_id in due:
        # Take it with one conditional update, so two senders never send the same delivery.
        claimed = db.execute(
            update(WebhookDelivery)
            .where(WebhookDelivery.id == delivery_id, WebhookDelivery.status == "pending")
            .values(status="sending", claimed_at=now)
        ).rowcount
        db.commit()
        if claimed:
            _attempt(db, delivery_id)
            tried += 1
    return tried


def retry_now(delivery: WebhookDelivery) -> None:
    """Send a failed, cancelled or waiting delivery again at the next round."""
    delivery.status = "pending"
    delivery.next_attempt_at = utc_now()
    delivery.claimed_at = None


# --- Exams that show results at once ---------------------------------------------------------------


def announce_closed_exams(db: Session, *, now: datetime | None = None) -> int:
    """result.released for exams that show results at once and have closed, once each."""
    now = now or utc_now()
    with_endpoints = select(WebhookEndpoint.tenant_id).where(WebhookEndpoint.status == "active")
    exams = db.execute(
        select(Exam.id, Exam.tenant_id).where(
            Exam.status == "published",
            Exam.results_release == "immediate",
            Exam.closes_at <= now - GRACE,
            Exam.closes_at > now - CLOSED_LOOKBACK,
            Exam.tenant_id.in_(with_endpoints),
        )
    ).all()
    announced = 0
    for exam_id, tenant_id in exams:
        already = db.scalar(
            select(
                exists().where(
                    WebhookEvent.tenant_id == tenant_id,
                    WebhookEvent.type == "result.released",
                    WebhookEvent.dedupe_key == f"exam:{exam_id}",
                )
            )
        )
        if already:
            continue
        if events.emit(
            db, tenant_id, "result.released", {"exam_id": exam_id}, dedupe_key=f"exam:{exam_id}"
        ):
            announced += 1
    db.commit()
    return announced


# --- Housekeeping and running ----------------------------------------------------------------------


def prune(db: Session, *, now: datetime | None = None) -> None:
    """Forget finished deliveries, and events nothing refers to, after `KEEP_HISTORY`."""
    cutoff = (now or utc_now()) - KEEP_HISTORY
    db.execute(
        delete(WebhookDelivery).where(
            WebhookDelivery.status.in_(("delivered", "failed", "cancelled")),
            WebhookDelivery.created_at < cutoff,
        )
    )
    # Once-only markers can go too: an exam is only announced within CLOSED_LOOKBACK of
    # closing, well inside KEEP_HISTORY, and a teacher releases results only once.
    db.execute(
        delete(WebhookEvent).where(
            WebhookEvent.created_at < cutoff,
            ~exists().where(WebhookDelivery.event_id == WebhookEvent.id),
        )
    )
    db.commit()


_last_prune: datetime | None = None


def run_once(db: Session) -> int:
    """One round of webhook work. Returns how many deliveries were tried."""
    global _last_prune
    now = utc_now()
    announce_closed_exams(db, now=now)
    tried = deliver_due(db, now=now)
    if _last_prune is None or now - _last_prune > timedelta(hours=1):
        prune(db, now=now)
        _last_prune = now
    return tried


def start_background(session_factory: sessionmaker, poll_seconds: float = 5.0) -> threading.Event:
    """Run `run_once` in a daemon thread until the returned event is set (WEBHOOK_DELIVERY=inline)."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            try:
                with session_factory() as db:
                    busy = run_once(db)
            except Exception:  # keep the loop alive; the next round tries again
                logger.exception("Webhook delivery round failed")
                busy = 0
            if not busy:
                stop.wait(poll_seconds)

    threading.Thread(target=loop, name="webhook-delivery", daemon=True).start()
    return stop
