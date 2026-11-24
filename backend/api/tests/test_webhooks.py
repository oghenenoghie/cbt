"""Webhooks (ADR 0008 decisions 12 to 16): managing endpoints, which changes send which events,
IDs-only bodies, signatures, retries, the public-address rule, cancelling, and the exams:read
endpoints events point to.

No real network: a mock transport stands in for receivers and a stub resolver for DNS. The school
is tests/test_attempts.py's: JSS1 A (amy, ben) and JSS1 B (cara), dan in no class."""

import hashlib
import hmac
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from test_attempts import build_school, published
from test_results import close_exam, release

from app.core.config import get_settings
from app.integrations import webhooks
from app.models import (
    AuditLog,
    Candidate,
    IntegrationScope,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)
from app.models.tenant import utc_now

V1 = "/api/v1"
INT = f"{V1}/school/integrations"
ALL_SCOPES = ["classes:read", "candidates:read", "candidates:write", "results:read", "exams:read"]
ALL_EVENTS = [
    "candidate.created",
    "candidate.updated",
    "enrolment.changed",
    "exam.published",
    "exam.withdrawn",
    "result.released",
]
URL = "https://hooks.school.example/cbt?token=abc"
PUBLIC_IP = "93.184.216.34"


@pytest.fixture
def school(admin, db: Session, make_user, sign_in):
    return build_school(admin, db, make_user, sign_in)


@pytest.fixture
def receiver(monkeypatch):
    """Records what's sent; `answers` lists what to answer, in order (status codes or errors)."""
    state = SimpleNamespace(requests=[], answers=[], resolved=[PUBLIC_IP])

    def handler(request: httpx.Request) -> httpx.Response:
        state.requests.append(request)
        answer = state.answers.pop(0) if state.answers else 200
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer)

    monkeypatch.setattr(webhooks, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(webhooks, "resolve", lambda host, port: list(state.resolved))
    return state


def bodies(state) -> list[dict]:
    return [json.loads(r.content) for r in state.requests]


def make_integration(who, name="Synthetic SIS", scopes=ALL_SCOPES) -> dict:
    response = who.client.post(INT, json={"name": name, "scopes": scopes}, headers=who.headers)
    assert response.status_code == 201, response.text
    return response.json()


def make_webhook(who, integration_id, url=URL, events=ALL_EVENTS):
    return who.client.post(
        f"{INT}/{integration_id}/webhooks", json={"url": url, "events": events}, headers=who.headers
    )


@pytest.fixture
def hook(school):
    """An integration with every permission and one endpoint for every event."""
    integration = make_integration(school.head)
    response = make_webhook(school.head, integration["id"])
    assert response.status_code == 201, response.text
    return SimpleNamespace(integration=integration, endpoint=response.json())


def deliver(db: Session, later: timedelta = timedelta(0)) -> int:
    return webhooks.deliver_due(db, now=utc_now() + later)


def event_types(state) -> list[str]:
    return [b["type"] for b in bodies(state)]


def api_key(who, integration_id) -> str:
    response = who.client.post(
        f"{INT}/{integration_id}/keys", json={"name": "Synthetic server"}, headers=who.headers
    )
    assert response.status_code == 201, response.text
    return response.json()["key"]


# --- Managing endpoints ---------------------------------------------------------------------------


def test_registering_a_webhook_shows_its_secret_once(school, hook, db: Session) -> None:
    secret = hook.endpoint["secret"]
    assert secret.startswith("whsec_") and len(secret) > 40
    assert hook.endpoint["events"] == sorted(ALL_EVENTS)
    listed = school.head.client.get(f"{INT}/{hook.integration['id']}/webhooks").json()
    assert len(listed) == 1 and "secret" not in listed[0]
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "integration.webhook.created"))
    assert entry.resource_id == hook.integration["id"]
    assert secret not in json.dumps(entry.details)


def test_the_event_catalogue(school) -> None:
    catalogue = school.head.client.get(f"{INT}/webhook-events").json()
    assert {e["type"]: e["scope"] for e in catalogue} == {
        "candidate.created": "candidates:read",
        "candidate.updated": "candidates:read",
        "enrolment.changed": "candidates:read",
        "exam.published": "exams:read",
        "exam.withdrawn": "exams:read",
        "result.released": "results:read",
    }


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.school.example/cbt",
        "ftp://hooks.school.example/cbt",
        "https://localhost/cbt",
        "https://printer.local/cbt",
        "https://10.0.0.5/cbt",
        "https://192.168.1.10/cbt",
        "https://127.0.0.1/cbt",
        "https://169.254.169.254/latest",
        "https://[::1]/cbt",
        "https://[::ffff:10.0.0.1]/cbt",
        "https://user:pass@hooks.school.example/cbt",
        "https:///nohost",
        "not a url",
    ],
)
def test_webhook_addresses_must_be_public_https(school, url) -> None:
    integration = make_integration(school.head)
    response = make_webhook(school.head, integration["id"], url=url)
    assert response.status_code == 422, url


def test_development_can_allow_local_addresses(school, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "webhook_allow_private_urls", True)
    integration = make_integration(school.head)
    response = make_webhook(school.head, integration["id"], url="http://localhost:9000/hook")
    assert response.status_code == 201, response.text


def test_events_need_their_permission(school) -> None:
    integration = make_integration(school.head, scopes=["results:read"])
    refused = make_webhook(school.head, integration["id"], events=["candidate.created"])
    assert refused.status_code == 422
    assert "candidates:read" in refused.json()["detail"]
    unknown = make_webhook(school.head, integration["id"], events=["result.deleted"])
    assert unknown.status_code == 422
    assert make_webhook(school.head, integration["id"], events=["result.released"]).status_code == 201


def test_an_integration_has_at_most_five_webhooks(school) -> None:
    integration = make_integration(school.head)
    for n in range(5):
        url = f"https://hooks{n}.school.example/cbt"
        assert make_webhook(school.head, integration["id"], url=url).status_code == 201
    sixth = make_webhook(school.head, integration["id"], url="https://six.school.example/cbt")
    assert sixth.status_code == 409


def test_only_this_schools_admins_manage_webhooks(
    school, hook, make_tenant, make_user, sign_in
) -> None:
    base = f"{INT}/{hook.integration['id']}/webhooks"
    teacher = school.teacher
    assert teacher.client.get(base).status_code == 403
    assert make_webhook(teacher, hook.integration["id"]).status_code == 403
    assert school.head.client.post(base, json={"url": URL, "events": ["exam.published"]}).status_code == 403

    other = make_tenant()
    make_user(tenant=other, username="head", role="school_admin", password="correct horse battery staple")
    elsewhere = sign_in(other, "head")
    assert elsewhere.client.get(base).status_code == 404
    endpoint = f"{base}/{hook.endpoint['id']}"
    assert elsewhere.client.patch(endpoint, json={"url": URL}, headers=elsewhere.headers).status_code == 404
    assert elsewhere.client.delete(endpoint, headers=elsewhere.headers).status_code == 404
    assert elsewhere.client.get(f"{endpoint}/deliveries").status_code == 404


def test_changing_disabling_and_deleting_a_webhook(school, hook, db: Session) -> None:
    base = f"{INT}/{hook.integration['id']}/webhooks/{hook.endpoint['id']}"
    head = school.head
    changed = head.client.patch(
        base, json={"events": ["result.released"], "description": "Report cards"}, headers=head.headers
    )
    assert changed.status_code == 200
    assert changed.json()["events"] == ["result.released"]
    assert head.client.patch(base, json={"url": "http://x.example"}, headers=head.headers).status_code == 422
    assert head.client.post(f"{base}/disable", headers=head.headers).json()["status"] == "disabled"
    assert head.client.post(f"{base}/enable", headers=head.headers).json()["status"] == "active"
    assert head.client.delete(base, headers=head.headers).status_code == 204
    assert db.scalar(select(func.count()).select_from(WebhookEndpoint)) == 0
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.resource_id == hook.integration["id"])))
    assert {
        "integration.webhook.updated",
        "integration.webhook.disabled",
        "integration.webhook.enabled",
        "integration.webhook.deleted",
    } <= actions


# --- What's sent -----------------------------------------------------------------------------------


def test_nothing_is_recorded_for_a_school_without_webhooks(school, db: Session) -> None:
    published(school)
    head = school.head
    head.client.post(
        f"{V1}/school/arms/{school.jss1a.id}/enrolments",
        json={"user_ids": [school.people["dan"].id]},
        headers=head.headers,
    )
    assert db.scalar(select(func.count()).select_from(WebhookEvent)) == 0


def test_a_delivery_is_signed_and_carries_ids_only(school, hook, receiver, db: Session) -> None:
    exam_id = published(school)
    assert deliver(db) == 1
    request = receiver.requests[0]

    body = json.loads(request.content)
    assert body["type"] == "exam.published"
    assert body["data"] == {"exam_id": exam_id}
    assert body["id"].startswith("evt_") and body["triggered_by_you"] is False
    assert set(body) == {"id", "type", "created_at", "triggered_by_you", "data"}

    # Sent to the checked address, for the named host, with a signature over "<t>.<body>".
    assert request.url.host == PUBLIC_IP and request.url.path == "/cbt"
    assert request.url.query == b"token=abc"
    assert request.headers["host"] == "hooks.school.example"
    assert request.extensions["sni_hostname"] == "hooks.school.example"
    assert request.headers["cbt-event-id"] == body["id"]
    assert request.headers["cbt-event-type"] == "exam.published"
    parts = dict(p.split("=", 1) for p in request.headers["cbt-signature"].split(","))
    signed = f"{parts['t']}.".encode() + request.content
    expected = hmac.new(hook.endpoint["secret"].encode(), signed, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(parts["v1"], expected)

    delivery = db.scalar(select(WebhookDelivery))
    assert (delivery.status, delivery.attempts, delivery.last_status_code) == ("delivered", 1, 200)
    assert deliver(db) == 0  # delivered once


def test_exam_withdrawn_and_results_released(school, hook, receiver, db: Session) -> None:
    later = published(school, opens_in=60, closes_in=240)
    t = school.teacher
    response = t.client.post(f"{V1}/exams/{later}/withdraw", json={"note": "Clash"}, headers=t.headers)
    assert response.status_code == 200, response.text
    now = published(school)
    close_exam(db, now)
    assert release(t, now).status_code == 200
    deliver(db)
    assert event_types(receiver) == ["exam.published", "exam.withdrawn", "exam.published", "result.released"]
    assert bodies(receiver)[-1]["data"] == {"exam_id": now}


def test_exams_showing_results_at_once_announce_when_they_close(school, hook, receiver, db: Session) -> None:
    exam_id = published(school, results_release="immediate")
    assert webhooks.announce_closed_exams(db) == 0  # still open
    close_exam(db, exam_id)
    assert webhooks.announce_closed_exams(db) == 1
    assert webhooks.announce_closed_exams(db) == 0  # once only
    deliver(db)
    assert event_types(receiver)[-1] == "result.released"


def test_school_admin_changes_to_students(school, hook, receiver, db: Session) -> None:
    head = school.head
    dan = school.people["dan"]
    response = head.client.post(
        f"{V1}/school/arms/{school.jss1a.id}/enrolments",
        json={"user_ids": [dan.id]},
        headers=head.headers,
    )
    assert response.status_code == 201, response.text
    enrolment_id = response.json()[0]["id"]
    candidate_id = db.scalar(select(Candidate.id).where(Candidate.user_id == dan.id))
    assert head.client.patch(
        f"{V1}/school/enrolments/{enrolment_id}", json={"arm_id": school.jss1b.id}, headers=head.headers
    ).status_code == 200
    assert head.client.delete(f"{V1}/school/enrolments/{enrolment_id}", headers=head.headers).status_code == 204
    assert head.client.patch(
        f"{V1}/school/users/{dan.id}", json={"display_name": "Daniel Synthetic"}, headers=head.headers
    ).status_code == 200
    deliver(db)

    sent = bodies(receiver)
    assert [b["type"] for b in sent] == [
        "candidate.created",
        "enrolment.changed",
        "enrolment.changed",
        "enrolment.changed",
        "candidate.updated",
    ]
    session_id = school.jss1a.session_id
    a, b = school.jss1a.id, school.jss1b.id
    assert sent[0]["data"] == {"candidate_id": candidate_id, "external_id": None}
    assert [s["data"]["class_id"] for s in sent[1:4]] == [a, b, None]
    assert [s["data"]["previous_class_id"] for s in sent[1:4]] == [None, a, b]
    assert all(s["data"]["session_id"] == session_id for s in sent[1:4])
    assert sent[4]["data"]["changed"] == ["display_name"]
    # No names travel: only IDs.
    assert "Daniel" not in json.dumps(sent)


def test_class_list_imports_send_events(school, hook, receiver, db: Session) -> None:
    head = school.head
    csv = b"Username,Name,Class\nzed,Zed Synthetic,JSS1 B\namy,Amaka Synthetic,JSS1 B\n"
    response = head.client.post(
        f"{V1}/school/sessions/{school.jss1a.session_id}/class-list",
        files={"file": ("list.csv", csv, "text/csv")},
        data={"generate_passwords": "false"},
        headers=head.headers,
    )
    assert response.status_code == 201, response.text
    deliver(db)
    assert sorted(event_types(receiver)) == ["candidate.created", "enrolment.changed", "enrolment.changed"]
    moved = [b for b in bodies(receiver) if b["data"].get("previous_class_id")]
    assert moved and moved[0]["data"]["previous_class_id"] == school.jss1a.id


def test_student_sync_events_carry_each_integrations_own_ids(
    school, hook, receiver, db: Session, client
) -> None:
    other = make_integration(school.head, name="Synthetic portal", scopes=["candidates:read"])
    assert make_webhook(
        school.head, other["id"], url="https://portal.school.example/in", events=["candidate.created"]
    ).status_code == 201
    key = api_key(school.head, hook.integration["id"])
    response = client.put(
        f"{V1}/candidates/SIS-001",
        json={"display_name": "Zara Synthetic", "username": "zara", "class_id": school.jss1a.id},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 201, response.text
    deliver(db)

    by_host = {}
    for request in receiver.requests:
        by_host.setdefault(request.headers["host"], []).append(json.loads(request.content))
    sis = by_host["hooks.school.example"]
    portal = by_host["portal.school.example"]
    assert [b["type"] for b in sis] == ["candidate.created", "enrolment.changed"]
    assert sis[0]["data"]["external_id"] == "SIS-001" and sis[0]["triggered_by_you"] is True
    assert [b["type"] for b in portal] == ["candidate.created"]
    assert portal[0]["data"]["external_id"] is None and portal[0]["triggered_by_you"] is False
    assert portal[0]["id"] == sis[0]["id"]  # one event, two deliveries


# --- Retries, failures and cancelling -------------------------------------------------------------


def test_failures_are_retried_then_given_up(school, hook, receiver, db: Session) -> None:
    published(school)
    receiver.answers.extend([500] * webhooks.MAX_ATTEMPTS)
    delivery = None
    for n in range(webhooks.MAX_ATTEMPTS):
        assert deliver(db, later=timedelta(days=2 * n)) == 1
        db.expire_all()
        delivery = db.scalar(select(WebhookDelivery))
        if n < webhooks.MAX_ATTEMPTS - 1:
            assert delivery.status == "pending"
            assert delivery.next_attempt_at is not None
    assert (delivery.status, delivery.attempts) == ("failed", webhooks.MAX_ATTEMPTS)
    assert delivery.last_error == "The receiver answered 500."
    assert deliver(db, later=timedelta(days=60)) == 0
    # The first retry waits a minute, not longer.
    assert webhooks.RETRY_DELAYS[0] == timedelta(minutes=1)


def test_a_retry_waits_for_its_time(school, hook, receiver, db: Session) -> None:
    published(school)
    receiver.answers.append(503)
    deliver(db)
    assert deliver(db) == 0  # not yet due
    assert deliver(db, later=timedelta(minutes=2)) == 1
    assert db.scalar(select(WebhookDelivery.status)) == "delivered"


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (httpx.ReadTimeout("slow"), "didn't answer within"),
        (httpx.ConnectError("refused"), "Couldn't connect"),
        (302, "a redirect"),
        (404, "answered 404"),
    ],
)
def test_what_counts_as_a_failure(school, hook, receiver, db: Session, answer, message) -> None:
    published(school)
    receiver.answers.append(answer)
    deliver(db)
    delivery = db.scalar(select(WebhookDelivery))
    assert delivery.status == "pending" and message in delivery.last_error


def test_a_name_pointing_to_a_private_address_gets_nothing(school, hook, receiver, db: Session) -> None:
    published(school)
    receiver.resolved = [PUBLIC_IP, "10.1.2.3"]
    deliver(db)
    assert receiver.requests == []
    delivery = db.scalar(select(WebhookDelivery))
    assert delivery.status == "pending" and "private address" in delivery.last_error


@pytest.mark.parametrize("change", ["endpoint", "integration", "scope"])
def test_deliveries_are_cancelled_when_they_may_no_longer_go(
    school, hook, receiver, db: Session, change
) -> None:
    published(school)
    if change == "endpoint":
        db.execute(update(WebhookEndpoint).values(status="disabled"))
    elif change == "integration":
        response = school.head.client.post(
            f"{INT}/{hook.integration['id']}/disable", headers=school.head.headers
        )
        assert response.status_code == 200
    else:
        db.execute(
            update(IntegrationScope)
            .where(IntegrationScope.scope == "exams:read")
            .values(granted=False)
        )
    db.commit()
    deliver(db)
    assert receiver.requests == []
    assert db.scalar(select(WebhookDelivery.status)) == "cancelled"


def test_two_senders_never_send_the_same_delivery(school, hook, receiver, db: Session) -> None:
    published(school)
    db.execute(update(WebhookDelivery).values(status="sending", claimed_at=utc_now()))
    db.commit()
    assert deliver(db) == 0
    # A sender that stopped part-way is taken over after a while.
    assert deliver(db, later=webhooks.STUCK_AFTER + timedelta(seconds=1)) == 1
    assert len(receiver.requests) == 1


def test_old_history_is_pruned(school, hook, receiver, db: Session) -> None:
    published(school)
    deliver(db)
    webhooks.prune(db, now=utc_now() + timedelta(days=31))
    assert db.scalar(select(func.count()).select_from(WebhookDelivery)) == 0
    assert db.scalar(select(func.count()).select_from(WebhookEvent)) == 0


# --- Test events, the delivery log, retrying and new secrets ---------------------------------------


def test_test_events_the_log_and_sending_again(school, hook, receiver, db: Session) -> None:
    head = school.head
    base = f"{INT}/{hook.integration['id']}/webhooks/{hook.endpoint['id']}"
    test = head.client.post(f"{base}/test", headers=head.headers)
    assert test.status_code == 201
    assert test.json()["event_type"] == "webhook.test" and test.json()["status"] == "pending"
    receiver.answers.append(500)
    deliver(db)

    log = head.client.get(f"{base}/deliveries").json()["deliveries"]
    assert [(d["event_type"], d["status"]) for d in log] == [("webhook.test", "pending")]
    assert log[0]["last_error"] == "The receiver answered 500."
    assert head.client.get(f"{base}/deliveries", params={"status": "delivered"}).json()["deliveries"] == []

    again = head.client.post(f"{base}/deliveries/{log[0]['id']}/retry", headers=head.headers)
    assert again.status_code == 200
    deliver(db)
    assert [r.headers["cbt-event-id"] for r in receiver.requests] == [log[0]["event_id"]] * 2
    listed = head.client.get(f"{INT}/{hook.integration['id']}/webhooks").json()[0]
    assert listed["last_success_at"] is not None and listed["failed"] == 0


def test_a_new_secret_signs_from_then_on(school, hook, receiver, db: Session) -> None:
    head = school.head
    base = f"{INT}/{hook.integration['id']}/webhooks/{hook.endpoint['id']}"
    rotated = head.client.post(f"{base}/rotate-secret", headers=head.headers).json()["secret"]
    assert rotated != hook.endpoint["secret"]
    published(school)
    deliver(db)
    request = receiver.requests[0]
    parts = dict(p.split("=", 1) for p in request.headers["cbt-signature"].split(","))
    signed = f"{parts['t']}.".encode() + request.content
    assert parts["v1"] == hmac.new(rotated.encode(), signed, hashlib.sha256).hexdigest()
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "integration.webhook.secret_rotated"))
    assert rotated not in json.dumps(entry.details)


# --- Fetching what events point to -----------------------------------------------------------------


def test_exams_read_shows_published_exams_only(school, hook, db: Session, client, make_credential) -> None:
    key = api_key(school.head, hook.integration["id"])
    headers = {"Authorization": f"Bearer {key}"}
    exam_id = published(school)
    draft = published(school, publish=False)

    listed = client.get(f"{V1}/published-exams", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [e["id"] for e in listed.json()["exams"]] == [exam_id]
    one = client.get(f"{V1}/published-exams/{exam_id}", headers=headers).json()
    assert one["status"] == "published" and one["subject"]["name"] == "Basic Science"
    assert [c["id"] for c in one["classes"]] == [school.jss1a.id]
    assert "questions" not in one and "items" not in one
    assert client.get(f"{V1}/published-exams/{draft}", headers=headers).status_code == 404
    reads = db.scalars(select(AuditLog).where(AuditLog.action == "exams.read")).all()
    assert len(reads) == 2 and all(r.actor_type == "integration" for r in reads)

    without = make_credential(tenant=school.head.school, granted_scopes=["results:read"])
    denied = client.get(f"{V1}/published-exams/{exam_id}", headers={"Authorization": f"Bearer {without.raw_key}"})
    assert denied.status_code == 403
    elsewhere = make_credential(granted_scopes=["exams:read"])
    assert client.get(
        f"{V1}/published-exams/{exam_id}", headers={"Authorization": f"Bearer {elsewhere.raw_key}"}
    ).status_code == 404


def test_students_can_be_fetched_by_the_id_an_event_gives(school, hook, db: Session, client) -> None:
    key = api_key(school.head, hook.integration["id"])
    amy = db.scalar(select(Candidate.id).where(Candidate.user_id == school.people["amy"].id))
    response = client.get(
        f"{V1}/candidates", params={"candidate_id": [amy]}, headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 200
    assert [c["id"] for c in response.json()["candidates"]] == [amy]


def test_a_webhook_deleted_while_sending_is_skipped(school, hook, receiver, db: Session) -> None:
    published(school)
    delivery_id = db.scalar(select(WebhookDelivery.id))
    head = school.head
    base = f"{INT}/{hook.integration['id']}/webhooks/{hook.endpoint['id']}"
    assert head.client.delete(base, headers=head.headers).status_code == 204
    webhooks._attempt(db, delivery_id)  # its delivery went with it: nothing to send, no error
    assert receiver.requests == []
