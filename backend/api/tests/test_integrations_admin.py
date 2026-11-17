"""School admins managing integrations (ADR 0008, Integrations A): access, keys shown once and
stored only as hashes, revoking and disabling, permissions, audit, other schools, rate limits."""

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.manage import MAX_ACTIVE_KEYS
from app.models import ApiCredential, AuditLog, Integration, IntegrationRateWindow

BASE = "/api/v1/school/integrations"
ME = "/api/v1/integrations/me"


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def create(admin, name="School portal", scopes=("candidates:read",), **extra) -> dict:
    response = admin.client.post(
        BASE, json={"name": name, "scopes": list(scopes), **extra}, headers=admin.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def issue(admin, integration_id: str, name="Server key") -> dict:
    response = admin.client.post(
        f"{BASE}/{integration_id}/keys", json={"name": name}, headers=admin.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def teacher(admin, make_user, sign_in):
    make_user(tenant=admin.school, username="mrs.okafor", role="teacher", password="correct horse battery")
    return sign_in(admin.school, "mrs.okafor", "correct horse battery")


@pytest.fixture
def other_admin(make_tenant, make_user, sign_in):
    school = make_tenant()
    make_user(tenant=school, username="head", role="school_admin", password="correct horse battery")
    session = sign_in(school, "head", "correct horse battery")
    session.school = school
    return session


# --- Who can manage integrations -------------------------------------------------------------


def test_only_school_admins_can_see_or_manage_integrations(
    admin, teacher, make_user, sign_in, client: TestClient
) -> None:
    integration = create(admin)
    make_user(tenant=admin.school, username="amy", role="student", password="student pass")
    student = sign_in(admin.school, "amy", "student pass")

    assert client.get(BASE).status_code == 401
    for person in (teacher, student):
        assert person.client.get(BASE).status_code == 403
        assert person.client.get(f"{BASE}/scopes").status_code == 403
        assert person.client.get(f"{BASE}/{integration['id']}").status_code == 403
        assert person.client.get(f"{BASE}/{integration['id']}/activity").status_code == 403
        assert person.client.post(BASE, json={"name": "Mine"}, headers=person.headers).status_code == 403
        assert (
            person.client.post(
                f"{BASE}/{integration['id']}/keys", json={"name": "k"}, headers=person.headers
            ).status_code
            == 403
        )


def test_changes_need_the_csrf_token(admin) -> None:
    integration = create(admin)

    assert admin.client.post(BASE, json={"name": "Other"}).status_code == 403
    assert admin.client.post(f"{BASE}/{integration['id']}/keys", json={"name": "k"}).status_code == 403
    assert admin.client.post(f"{BASE}/{integration['id']}/disable").status_code == 403
    assert admin.client.patch(f"{BASE}/{integration['id']}", json={"name": "x"}).status_code == 403


def test_the_permission_catalogue(admin) -> None:
    scopes = admin.client.get(f"{BASE}/scopes").json()

    assert [s["name"] for s in scopes] == [
        "classes:read",
        "candidates:read",
        "candidates:write",
        "results:read",
    ]
    assert all(s["description"] for s in scopes)


# --- Registering and changing an integration --------------------------------------------------


def test_register_an_integration(admin, db: Session) -> None:
    body = create(
        admin,
        name="  Greenfield SIS ",
        scopes=["results:read", "candidates:read", "results:read"],
        description="Nightly student sync",
    )

    assert body["name"] == "Greenfield SIS"
    assert body["description"] == "Nightly student sync"
    assert body["status"] == "active"
    assert body["scopes"] == ["candidates:read", "results:read"]
    assert body["keys"] == []
    assert body["last_used_at"] is None
    assert body["created_by_name"] == admin.user.display_name

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "integration.created"))
    assert entry.tenant_id == admin.school.id
    assert entry.actor_id == admin.user.id
    assert entry.resource_id == body["id"]
    assert entry.details == {"name": "Greenfield SIS", "scopes": ["candidates:read", "results:read"]}
    assert admin.client.get(BASE).json()[0]["id"] == body["id"]


@pytest.mark.parametrize(
    "payload",
    [
        {"name": ""},
        {"name": "x" * 161},
        {"name": "Portal", "scopes": ["exams:delete"]},
        {"name": "Portal", "scopes": ["candidates:read", "everything"]},
        {"name": "Portal", "tenant_id": "someone-else"},
    ],
)
def test_bad_registrations_are_refused(admin, payload) -> None:
    response = admin.client.post(BASE, json=payload, headers=admin.headers)

    assert response.status_code == 422


def test_names_are_unique_within_a_school_only(admin, other_admin) -> None:
    create(admin, name="School portal")

    clash = admin.client.post(BASE, json={"name": "SCHOOL PORTAL"}, headers=admin.headers)
    assert clash.status_code == 409
    other = other_admin.client.post(BASE, json={"name": "School portal"}, headers=other_admin.headers)
    assert other.status_code == 201


def test_changing_permissions_applies_to_the_next_request(admin, client: TestClient, db: Session) -> None:
    integration = create(admin, scopes=["candidates:read", "results:read"])
    key = issue(admin, integration["id"])["key"]
    assert client.get(ME, headers=bearer(key)).json()["scopes"] == ["candidates:read", "results:read"]

    response = admin.client.patch(
        f"{BASE}/{integration['id']}",
        json={"scopes": ["classes:read", "results:read"], "name": "Portal v2"},
        headers=admin.headers,
    )

    assert response.status_code == 200
    assert response.json()["scopes"] == ["classes:read", "results:read"]
    assert response.json()["name"] == "Portal v2"
    assert client.get(ME, headers=bearer(key)).json()["scopes"] == ["classes:read", "results:read"]
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "integration.updated"))
    assert entry.details == {
        "name": {"from": "School portal", "to": "Portal v2"},
        "scopes_added": ["classes:read"],
        "scopes_removed": ["candidates:read"],
    }


def test_an_update_that_changes_nothing_writes_no_audit_entry(admin, db: Session) -> None:
    integration = create(admin)

    response = admin.client.patch(
        f"{BASE}/{integration['id']}",
        json={"name": "School portal", "scopes": ["candidates:read"]},
        headers=admin.headers,
    )

    assert response.status_code == 200
    assert db.scalar(select(AuditLog).where(AuditLog.action == "integration.updated")) is None


def test_renaming_to_another_integrations_name_is_refused(admin) -> None:
    create(admin, name="Portal")
    second = create(admin, name="SIS")

    response = admin.client.patch(
        f"{BASE}/{second['id']}", json={"name": "portal"}, headers=admin.headers
    )

    assert response.status_code == 409


# --- Keys ----------------------------------------------------------------------------------------


def test_a_key_is_shown_once_and_stored_only_as_a_hash(admin, client: TestClient, db: Session) -> None:
    integration = create(admin)

    issued = issue(admin, integration["id"], name="Production")

    raw = issued["key"]
    assert raw.startswith("cbt_live_")
    assert issued["prefix"] == raw[:16]
    assert issued["status"] == "active"
    assert issued["created_by_name"] == admin.user.display_name
    stored = db.get(ApiCredential, issued["id"])
    assert stored.secret_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert stored.created_by_id == admin.user.id
    assert raw not in {str(value) for value in stored.__dict__.values()}
    # Never again: not in the integration, the listing or the activity.
    for url in (BASE, f"{BASE}/{integration['id']}", f"{BASE}/{integration['id']}/activity"):
        assert raw[16:] not in admin.client.get(url).text
    entries = db.scalars(select(AuditLog)).all()
    assert all(raw[16:] not in str(e.details) for e in entries)
    # And it works.
    me = client.get(ME, headers=bearer(raw))
    assert me.status_code == 200
    assert me.json()["integration_id"] == integration["id"]
    assert me.json()["tenant_id"] == admin.school.id


def test_replacing_a_key_without_downtime(admin, client: TestClient) -> None:
    integration = create(admin)
    old = issue(admin, integration["id"], name="2026")
    new = issue(admin, integration["id"], name="2027")

    assert client.get(ME, headers=bearer(old["key"])).status_code == 200
    assert client.get(ME, headers=bearer(new["key"])).status_code == 200

    revoked = admin.client.post(
        f"{BASE}/{integration['id']}/keys/{old['id']}/revoke", headers=admin.headers
    )

    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["revoked_by_name"] == admin.user.display_name
    assert client.get(ME, headers=bearer(old["key"])).status_code == 401
    assert client.get(ME, headers=bearer(new["key"])).status_code == 200
    keys = admin.client.get(f"{BASE}/{integration['id']}").json()["keys"]
    assert [(k["name"], k["status"]) for k in keys] == [("2027", "active"), ("2026", "revoked")]


def test_revoking_twice_is_harmless_and_audited_once(admin, db: Session) -> None:
    integration = create(admin)
    key = issue(admin, integration["id"])
    url = f"{BASE}/{integration['id']}/keys/{key['id']}/revoke"

    assert admin.client.post(url, headers=admin.headers).status_code == 200
    assert admin.client.post(url, headers=admin.headers).status_code == 200

    revocations = db.scalars(select(AuditLog).where(AuditLog.action == "integration.key.revoked")).all()
    assert len(revocations) == 1
    assert revocations[0].details == {"key_id": key["id"], "key_name": "Server key", "prefix": key["prefix"]}


def test_at_most_five_active_keys(admin) -> None:
    integration = create(admin)
    keys = [issue(admin, integration["id"], name=f"Key {n}") for n in range(MAX_ACTIVE_KEYS)]

    refused = admin.client.post(
        f"{BASE}/{integration['id']}/keys", json={"name": "One more"}, headers=admin.headers
    )
    assert refused.status_code == 409

    admin.client.post(f"{BASE}/{integration['id']}/keys/{keys[0]['id']}/revoke", headers=admin.headers)
    issue(admin, integration["id"], name="One more")


def test_a_key_of_another_integration_isnt_found_through_this_one(admin) -> None:
    portal = create(admin, name="Portal")
    sis = create(admin, name="SIS")
    key = issue(admin, sis["id"])

    response = admin.client.post(
        f"{BASE}/{portal['id']}/keys/{key['id']}/revoke", headers=admin.headers
    )

    assert response.status_code == 404


def test_last_use_shows_on_the_integration(admin, client: TestClient) -> None:
    integration = create(admin)
    key = issue(admin, integration["id"])

    client.get(ME, headers=bearer(key["key"]))

    body = admin.client.get(f"{BASE}/{integration['id']}").json()
    assert body["last_used_at"] is not None
    assert body["keys"][0]["last_used_at"] == body["last_used_at"]


# --- Disabling --------------------------------------------------------------------------------


def test_disabling_stops_every_key_until_enabled(admin, client: TestClient, db: Session) -> None:
    integration = create(admin)
    first = issue(admin, integration["id"])["key"]
    second = issue(admin, integration["id"])["key"]

    disabled = admin.client.post(f"{BASE}/{integration['id']}/disable", headers=admin.headers)

    assert disabled.json()["status"] == "disabled"
    for key in (first, second):
        assert client.get(ME, headers=bearer(key)).status_code == 401
    refused = admin.client.post(
        f"{BASE}/{integration['id']}/keys", json={"name": "k"}, headers=admin.headers
    )
    assert refused.status_code == 409
    assert admin.client.get(BASE).json()[0]["status"] == "disabled"

    admin.client.post(f"{BASE}/{integration['id']}/enable", headers=admin.headers)

    assert client.get(ME, headers=bearer(first)).status_code == 200
    actions = db.scalars(select(AuditLog.action).where(AuditLog.resource_id == integration["id"])).all()
    assert "integration.disabled" in actions and "integration.enabled" in actions


def test_disabled_integrations_list_after_active_ones(admin) -> None:
    zebra = create(admin, name="Zebra portal")
    create(admin, name="Alpha LMS")
    admin.client.post(f"{BASE}/{zebra['id']}/disable", headers=admin.headers)
    create(admin, name="Beta SIS")

    names = [i["name"] for i in admin.client.get(BASE).json()]

    assert names == ["Alpha LMS", "Beta SIS", "Zebra portal"]


# --- Other schools --------------------------------------------------------------------------------


def test_another_schools_integration_is_not_found(admin, other_admin, client: TestClient) -> None:
    theirs = create(other_admin, name="Their portal")
    their_key = issue(other_admin, theirs["id"])
    item = f"{BASE}/{theirs['id']}"

    assert admin.client.get(BASE).json() == []
    assert admin.client.get(item).status_code == 404
    assert admin.client.get(f"{item}/activity").status_code == 404
    assert admin.client.patch(item, json={"name": "Mine"}, headers=admin.headers).status_code == 404
    assert admin.client.post(f"{item}/disable", headers=admin.headers).status_code == 404
    assert admin.client.post(f"{item}/keys", json={"name": "k"}, headers=admin.headers).status_code == 404
    revoke = f"{item}/keys/{their_key['id']}/revoke"
    assert admin.client.post(revoke, headers=admin.headers).status_code == 404
    # Untouched, and still working.
    assert client.get(ME, headers=bearer(their_key["key"])).status_code == 200
    assert other_admin.client.get(item).json()["name"] == "Their portal"


def test_a_key_only_ever_sees_its_own_school(admin, other_admin, client: TestClient) -> None:
    mine = issue(admin, create(admin, scopes=["results:read"])["id"])
    theirs = issue(other_admin, create(other_admin, scopes=["classes:read"])["id"])

    assert client.get(ME, headers=bearer(mine["key"])).json()["tenant_id"] == admin.school.id
    assert client.get(ME, headers=bearer(theirs["key"])).json()["tenant_id"] == other_admin.school.id


# --- Activity ----------------------------------------------------------------------------------


def test_activity_lists_changes_newest_first_in_pages(admin, db: Session) -> None:
    integration = create(admin)
    key = issue(admin, integration["id"])
    admin.client.post(f"{BASE}/{integration['id']}/keys/{key['id']}/revoke", headers=admin.headers)
    admin.client.post(f"{BASE}/{integration['id']}/disable", headers=admin.headers)
    # Another integration's entries stay out.
    create(admin, name="Elsewhere")

    first = admin.client.get(f"{BASE}/{integration['id']}/activity?limit=2").json()
    second = admin.client.get(
        f"{BASE}/{integration['id']}/activity?limit=2&after={first['next_after']}"
    ).json()

    actions = [e["action"] for e in first["entries"] + second["entries"]]
    assert actions == [
        "integration.disabled",
        "integration.key.revoked",
        "integration.key.created",
        "integration.created",
    ]
    assert second["next_after"] is None
    assert {e["actor_name"] for e in first["entries"]} == {admin.user.display_name}
    assert {e["actor_type"] for e in first["entries"]} == {"user"}


def test_activity_includes_what_the_integration_itself_did(admin, db: Session) -> None:
    integration = create(admin)
    db.add(
        AuditLog(
            tenant_id=admin.school.id,
            actor_type="integration",
            actor_id=integration["id"],
            action="candidate.created",
            resource_type="candidate",
            resource_id="c1",
            details={},
        )
    )
    db.commit()

    entries = admin.client.get(f"{BASE}/{integration['id']}/activity").json()["entries"]

    assert entries[0]["action"] == "candidate.created"
    assert entries[0]["actor_name"] == "School portal"


# --- Rate limits -------------------------------------------------------------------------------


@pytest.fixture
def limit_of_three(monkeypatch):
    monkeypatch.setattr(get_settings(), "integration_rate_limit_per_minute", 3)


def test_each_integration_is_limited_per_minute(
    admin, client: TestClient, db: Session, limit_of_three
) -> None:
    integration = create(admin)
    key = issue(admin, integration["id"])["key"]

    remaining = []
    for _ in range(3):
        response = client.get(ME, headers=bearer(key))
        assert response.status_code == 200
        assert response.headers["X-RateLimit-Limit"] == "3"
        remaining.append(response.headers["X-RateLimit-Remaining"])
    refused = client.get(ME, headers=bearer(key))

    assert remaining == ["2", "1", "0"]
    assert refused.status_code == 429
    assert 1 <= int(refused.headers["Retry-After"]) <= 60
    assert "too many requests" in refused.json()["detail"]

    # A new minute starts a new count.
    db.execute(
        update(IntegrationRateWindow)
        .where(IntegrationRateWindow.integration_id == integration["id"])
        .values(window_minute=IntegrationRateWindow.window_minute - 1)
    )
    db.commit()
    assert client.get(ME, headers=bearer(key)).headers["X-RateLimit-Remaining"] == "2"


def test_more_keys_dont_raise_the_limit_but_other_integrations_have_their_own(
    admin, client: TestClient, limit_of_three
) -> None:
    portal = create(admin, name="Portal")
    first = issue(admin, portal["id"])["key"]
    second = issue(admin, portal["id"])["key"]
    sis_key = issue(admin, create(admin, name="SIS")["id"])["key"]

    statuses = [client.get(ME, headers=bearer(k)).status_code for k in (first, second, first, second)]

    assert statuses == [200, 200, 200, 429]
    assert client.get(ME, headers=bearer(sis_key)).status_code == 200


def test_bad_keys_dont_use_up_the_limit(admin, client: TestClient, db: Session, limit_of_three) -> None:
    integration = create(admin)
    key = issue(admin, integration["id"])["key"]

    for _ in range(5):
        assert client.get(ME, headers=bearer(key[:-4] + "AAAA")).status_code == 401

    assert client.get(ME, headers=bearer(key)).status_code == 200
    assert db.get(IntegrationRateWindow, integration["id"]).request_count == 1


def test_an_integration_from_before_management_still_works(client: TestClient, make_credential, db: Session) -> None:
    """Integrations made before ADR 0008 have no creator and no rate window yet."""
    issued = make_credential(granted_scopes=("results:read",))

    assert client.get(ME, headers=bearer(issued.raw_key)).status_code == 200
    assert db.get(Integration, issued.integration.id).created_by_id is None
