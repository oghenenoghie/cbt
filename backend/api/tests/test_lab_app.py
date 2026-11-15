"""Publishing the lab app to lab computers (ADR 0007, decision 10)."""

import json
from pathlib import Path

import pytest
import test_offline
from test_offline import SD, D, Lab, registered

from app import cli
from app.offline import crypto, releases

school = test_offline.school
offline_settings = test_offline.offline_settings


@pytest.fixture
def release_dir(tmp_path, offline_settings, monkeypatch):
    directory = tmp_path / "lab-app"
    monkeypatch.setattr(offline_settings, "lab_app_dir", str(directory))
    return directory


def an_installer(tmp_path, content: bytes = b"MZ fake installer") -> str:
    path = tmp_path / "Intelligent CBT Lab Setup.exe"
    path.write_bytes(content)
    return str(path)


def test_publishing_signs_a_manifest_lab_computers_can_check(
    school, client, tmp_path, release_dir, capsys
) -> None:
    lab: Lab = registered(school, client)
    assert lab.get("/app/latest").status_code == 404

    assert (
        cli.main(
            ["publish-lab-app", an_installer(tmp_path), "--version", "0.2.0", "--notes", "Faster"]
        )
        == 0
    )
    assert "Published lab app 0.2.0" in capsys.readouterr().out

    response = lab.get("/app/latest")
    assert response.status_code == 200
    envelope = response.json()
    assert envelope["format"] == releases.APP_FORMAT
    # Signed with the key the computer trusted when it registered.
    assert crypto.verify(envelope, lab.signing_public_key)
    body = json.loads(envelope["body"])
    assert (body["version"], body["notes"], body["size"]) == ("0.2.0", "Faster", 17)
    installer = lab.get("/app/installer")
    assert installer.status_code == 200
    assert installer.content == b"MZ fake installer"
    assert crypto.sha256_hex(installer.content) == body["sha256"]
    assert "Intelligent-CBT-Lab-Setup-0.2.0.exe" in installer.headers["content-disposition"]


def test_only_newer_versions_and_the_newest_two_installers_are_kept(
    tmp_path, release_dir, capsys
) -> None:
    for version in ("0.2.0", "0.3.0", "0.10.0"):
        assert cli.main(["publish-lab-app", an_installer(tmp_path), "--version", version]) == 0
    assert sorted(p.name for p in release_dir.glob("*.exe")) == [
        "Intelligent-CBT-Lab-Setup-0.10.0.exe",
        "Intelligent-CBT-Lab-Setup-0.3.0.exe",
    ]
    capsys.readouterr()
    assert cli.main(["publish-lab-app", an_installer(tmp_path), "--version", "0.9.0"]) == 1
    assert "0.10.0 is already published" in capsys.readouterr().err
    assert cli.main(["publish-lab-app", an_installer(tmp_path), "--version", "1.0"]) == 1
    assert cli.main(["publish-lab-app", str(tmp_path / "missing.exe"), "--version", "1.0.0"]) == 1
    assert releases.latest()[1]["version"] == "0.10.0"


def test_school_admins_download_the_installer(school, client, tmp_path, release_dir) -> None:
    head = school.head
    assert head.client.get(f"{SD}/app").status_code == 404
    releases.publish(Path(an_installer(tmp_path)), "1.0.0")
    info = head.client.get(f"{SD}/app")
    assert info.status_code == 200
    assert info.json()["version"] == "1.0.0"
    assert head.client.get(f"{SD}/app/installer").content == b"MZ fake installer"
    # Only school admins, and only with a session; lab computers use their own endpoints.
    assert school.teacher.client.get(f"{SD}/app").status_code == 403
    assert school.amy.client.get(f"{SD}/app/installer").status_code == 403
    assert client.get(f"{D}/app/latest").status_code == 401
    assert (
        client.get(f"{D}/app/installer", headers={"Authorization": "Device nope"}).status_code
        == 401
    )
