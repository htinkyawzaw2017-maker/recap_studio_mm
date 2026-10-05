#!/usr/bin/env python3
"""Phase 2 — auth, DB security and multi-user isolation (offline, no ffmpeg).

    python tests/test_auth.py

Covers the three modes the studio can run in (open → legacy shared key →
accounts) and, most importantly, that one account can never read, download,
cancel or delete another account's work.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="recap_auth_"))
os.environ["RECAP_DATA_DIR"] = str(TMP / "data")
os.environ.setdefault("RECAP_DEMO_MODE", "1")
os.environ.setdefault("RECAP_FAKE_TTS", "1")
os.environ.setdefault("RECAP_LOG_LEVEL", "ERROR")
os.environ.setdefault("RECAP_SECRET_KEY", "test-secret-key-for-the-suite-0123456789")
os.environ.setdefault("RECAP_PBKDF2_ITERATIONS", "60000")      # keep the suite fast

failures: list[str] = []
checks = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


def section(name: str) -> None:
    print(f"\n=== {name} ===")


def main() -> int:
    from fastapi.testclient import TestClient

    from recapstudio import auth, config, db
    from recapstudio.config import ensure_dirs
    ensure_dirs()
    import app as webapp

    def set_setting(**kwargs):
        config.settings = dataclasses.replace(config.settings, **kwargs)

    def reset_limits():
        webapp._api_limiter.reset()
        webapp._login_limiter.reset()

    # ── 1. open mode (fresh install, no accounts) ─────────────────────
    section("open mode (backwards compatible)")
    client = TestClient(webapp.app)
    check("auth mode is open", auth.auth_mode() == "open")
    res = client.get("/api/system")
    check("/api/system reachable without credentials", res.status_code == 200)
    check("system payload advertises the auth mode",
          res.json().get("auth", {}).get("mode") == "open")
    check("/api/keys open without a login", client.get("/api/keys").status_code == 200)

    # ── 2. legacy shared-key mode ─────────────────────────────────────
    section("legacy shared access key")
    set_setting(access_password="s3cret-shared-key", auth_mode="auto")
    reset_limits()
    check("auth mode is legacy", auth.auth_mode() == "legacy")
    check("no key → 401", client.get("/api/keys").status_code == 401)
    check("wrong key → 401",
          client.get("/api/keys", headers={"X-Access-Key": "nope"}).status_code == 401)
    check("correct key → 200",
          client.get("/api/keys",
                     headers={"X-Access-Key": "s3cret-shared-key"}).status_code == 200)
    set_setting(access_password="")

    # ── 3. first account bootstraps multi-user mode ───────────────────
    section("accounts: first admin")
    reset_limits()
    admin = TestClient(webapp.app)
    weak = admin.post("/api/auth/register", json={"username": "owner", "password": "12345678"})
    check("weak password rejected", weak.status_code == 400, weak.text[:70])
    bad_name = admin.post("/api/auth/register",
                          json={"username": "a b", "password": "Str0ng-Pass-9x"})
    check("invalid username rejected", bad_name.status_code == 400)
    res = admin.post("/api/auth/register",
                     json={"username": "owner", "password": "Str0ng-Pass-9x"})
    check("first account created", res.status_code == 200, res.text[:80])
    body = res.json()
    check("first account is an admin", body["auth"]["user"]["role"] == "admin")
    check("session cookie issued",
          config.settings.session_cookie in admin.cookies, str(list(admin.cookies.keys())))
    admin_csrf = body.get("csrf_token", "")
    check("csrf token issued", bool(admin_csrf))
    check("auth mode switched to users", auth.auth_mode() == "users")

    anon = TestClient(webapp.app)
    check("anonymous request now 401", anon.get("/api/keys").status_code == 401)
    check("/api/system still reachable (login screen needs it)",
          anon.get("/api/system").status_code == 200)
    check("/healthz stays public", anon.get("/healthz").status_code == 200)

    # ── 4. login / logout / throttling ────────────────────────────────
    section("login, logout, brute-force protection")
    reset_limits()
    guest = TestClient(webapp.app)
    bad = guest.post("/api/auth/login", json={"username": "owner", "password": "wrong-pass"})
    check("wrong password → 401", bad.status_code == 401)
    check("error does not leak whether the user exists",
          "မမှန်ကန်ပါ" in bad.json().get("detail", ""), bad.json().get("detail", "")[:40])
    inject = guest.post("/api/auth/login",
                        json={"username": "owner' OR '1'='1", "password": "x"})
    check("SQL injection attempt is just a failed login", inject.status_code == 401)
    ok = guest.post("/api/auth/login", json={"username": "owner", "password": "Str0ng-Pass-9x"})
    check("correct login → 200", ok.status_code == 200)
    check("me reports the account",
          guest.get("/api/auth/me").json()["user"]["username"] == "owner")
    csrf = ok.json()["csrf_token"]
    guest.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    check("logout invalidates the session",
          guest.get("/api/keys").status_code == 401)

    reset_limits()
    locker = TestClient(webapp.app)
    attempts = int(config.settings.login_max_attempts) + 1
    last = None
    for _ in range(attempts):
        last = locker.post("/api/auth/login", json={"username": "owner", "password": "nope"})
    check("account locks after repeated failures",
          "စောင့်" in last.json().get("detail", ""), last.json().get("detail", "")[:60])
    blocked = locker.post("/api/auth/login",
                          json={"username": "owner", "password": "Str0ng-Pass-9x"})
    check("correct password is refused while locked out", blocked.status_code == 401)
    auth.clear_attempts("owner", "testclient")
    auth.clear_attempts("owner", "")
    reset_limits()

    # ── 5. CSRF ───────────────────────────────────────────────────────
    section("CSRF protection on cookie sessions")
    admin = TestClient(webapp.app)
    login = admin.post("/api/auth/login",
                       json={"username": "owner", "password": "Str0ng-Pass-9x"})
    admin_csrf = login.json()["csrf_token"]
    admin_token = login.json()["token"]
    no_csrf = admin.post("/api/keys", json={"keys": []})
    check("cookie POST without a CSRF header → 403", no_csrf.status_code == 403,
          str(no_csrf.status_code))
    with_csrf = admin.post("/api/keys", json={"keys": []},
                           headers={"X-CSRF-Token": admin_csrf})
    check("cookie POST with the CSRF header → 200", with_csrf.status_code == 200)
    bearer = TestClient(webapp.app)
    bearer_res = bearer.post("/api/keys", json={"keys": []},
                             headers={"Authorization": f"Bearer {admin_token}"})
    check("bearer token clients are exempt from CSRF", bearer_res.status_code == 200)
    default_prefs = admin.get("/api/me/preferences")
    check("account preferences have the 42px caption default",
          default_prefs.status_code == 200
          and default_prefs.json()["preferences"]["sub_font_size"] == 42)
    prefs_no_csrf = admin.put("/api/me/preferences", json={"sub_width_percent": 76})
    check("preference writes require CSRF", prefs_no_csrf.status_code == 403)
    prefs_saved = admin.put("/api/me/preferences", json={"sub_width_percent": 76,
                                                           "sub_font_size": 54},
                            headers={"X-CSRF-Token": admin_csrf})
    check("caption width/size save into the signed-in account", prefs_saved.status_code == 200
          and prefs_saved.json()["preferences"]["sub_width_percent"] == 76
          and prefs_saved.json()["preferences"]["sub_font_size"] == 54)

    # ── 6. admin can manage accounts ──────────────────────────────────
    section("admin: account management")
    created = admin.post("/api/admin/users",
                         json={"username": "editor", "password": "Cl1p-Craft-77",
                               "must_change_password": False},
                         headers={"X-CSRF-Token": admin_csrf})
    check("admin creates an account", created.status_code == 200, created.text[:80])
    editor_id = created.json()["user"]["id"]
    listing = admin.get("/api/admin/users")
    check("admin lists accounts", listing.status_code == 200 and
          len(listing.json()["users"]) == 2, str(len(listing.json().get("users", []))))

    editor = TestClient(webapp.app)
    elogin = editor.post("/api/auth/login",
                         json={"username": "editor", "password": "Cl1p-Craft-77"})
    check("new account can sign in", elogin.status_code == 200, elogin.text[:70])
    editor_csrf = elogin.json()["csrf_token"]
    editor_defaults = editor.get("/api/me/preferences")
    check("new admin-created user receives their own defaults",
          editor_defaults.status_code == 200
          and editor_defaults.json()["preferences"]["sub_width_percent"] == 90)
    editor_saved = editor.put("/api/me/preferences", json={"sub_width_percent": 64},
                              headers={"X-CSRF-Token": editor_csrf})
    check("new user can persist their own slider setting", editor_saved.status_code == 200
          and editor_saved.json()["preferences"]["sub_width_percent"] == 64)
    check("user preferences remain isolated from the admin",
          admin.get("/api/me/preferences").json()["preferences"]["sub_width_percent"] == 76)
    check("non-admin blocked from /api/admin/users",
          editor.get("/api/admin/users").status_code == 403)
    check("non-admin cannot change server defaults",
          editor.post("/api/config", json={"model": "gemini-2.5-pro"},
                      headers={"X-CSRF-Token": editor_csrf}).status_code == 403)

    # ── 7. multi-user isolation ───────────────────────────────────────
    section("isolation: one account cannot touch another's work")
    owner_user = auth.get_user_by_name("owner")
    owner_scope = owner_user["id"]
    editor_scope = editor_id

    # a job + its artefacts owned by the admin
    job = webapp.store.create(kind="recap", request={"mode": "auto"},
                              user_id=owner_scope, username="owner")
    out_dir = config.user_output_dir(owner_scope)
    artefact = out_dir / f"recap_{job.id}.mp4"
    artefact.write_bytes(b"\x00" * 2048)
    webapp.store.update(job.id, status="completed", output_video=config.rel(artefact),
                        download_url=f"/api/download/{artefact.name}")
    auth.register_job(job.id, owner_scope, "recap", "completed")

    secret_upload = config.user_workspace_dir(owner_scope) / "private_clip.mp4"
    secret_upload.write_bytes(b"\x00" * 1024)

    check("owner sees the job", admin.get(f"/api/tasks/{job.id}").status_code == 200)
    check("other account gets 404 for the job",
          editor.get(f"/api/tasks/{job.id}").status_code == 404)
    check("other account cannot cancel it",
          editor.post(f"/api/tasks/{job.id}/cancel",
                      headers={"X-CSRF-Token": editor_csrf}).status_code == 404)
    check("other account cannot delete it",
          editor.delete(f"/api/tasks/{job.id}",
                        headers={"X-CSRF-Token": editor_csrf}).status_code == 404)
    check("other account cannot download the render",
          editor.get(f"/api/download/{artefact.name}").status_code == 404)
    check("owner can download the render",
          admin.get(f"/api/download/{artefact.name}").status_code == 200)
    check("other account cannot stream the upload",
          editor.get(f"/api/asset?path={config.rel(secret_upload)}").status_code in (400, 403),
          str(editor.get(f"/api/asset?path={config.rel(secret_upload)}").status_code))
    check("owner can stream their own upload",
          admin.get(f"/api/asset?path={config.rel(secret_upload)}").status_code == 200)
    check("job list is scoped to the account",
          all(t["id"] != job.id for t in editor.get("/api/tasks").json()["tasks"]))
    check("owner's job list contains it",
          any(t["id"] == job.id for t in admin.get("/api/tasks").json()["tasks"]))
    check("path traversal still blocked",
          editor.get("/api/asset?path=../../etc/passwd").status_code == 400)
    check("absolute path outside the data dir blocked",
          editor.get("/api/asset?path=/etc/passwd").status_code == 400)
    check("upload session of another account is refused",
          editor.get(f"/api/upload/status?upload_id=up_fake").status_code in (403, 404))

    # editor's own job for the opposite direction
    ejob = webapp.store.create(kind="recap", request={}, user_id=editor_scope,
                               username="editor")
    check("admin may inspect any job (support role)",
          admin.get(f"/api/tasks/{ejob.id}").status_code == 200)
    check("admin sees all jobs with ?all=1",
          len(admin.get("/api/tasks?all=1").json()["tasks"]) >= 2)

    # ── 8. per-user API keys are encrypted at rest ────────────────────
    section("DB security: secrets at rest")
    plaintext_key = "AIzaSyTESTKEY-personal-0123456789abcdefg"
    saved = editor.post("/api/keys", json={"keys": [{"slot": 1, "key": plaintext_key}]},
                        headers={"X-CSRF-Token": editor_csrf})
    check("user saves a personal key", saved.status_code == 200, saved.text[:70])
    raw_db = Path(config.DB_PATH).read_bytes()
    check("plaintext key is NOT in the database file",
          plaintext_key.encode() not in raw_db)
    check("key round-trips through decryption",
          auth.get_user_keys(editor_scope) == [plaintext_key])
    check("other account cannot see it",
          not any(k["set"] for k in admin.get("/api/keys").json()["keys"]))
    masked = editor.get("/api/keys").json()
    check("own key is returned masked",
          masked["keys"][0]["set"] and plaintext_key not in json.dumps(masked),
          masked["keys"][0]["masked"])
    mode = oct(os.stat(config.DB_PATH).st_mode & 0o777)
    check("database file is 0600", mode == "0o600", mode)
    row = sqlite3.connect(str(config.DB_PATH)).execute(
        "SELECT password_hash FROM users LIMIT 1").fetchone()
    check("passwords stored as PBKDF2 hashes", str(row[0]).startswith("pbkdf2_sha256$"),
          str(row[0])[:24])

    # ── 9. quotas ─────────────────────────────────────────────────────
    section("per-account quotas")
    set_setting(user_max_concurrent_jobs=1)
    webapp.store.update(ejob.id, status="running")
    editor_clip = config.user_workspace_dir(editor_scope) / "clip.mp4"
    editor_clip.write_bytes(b"\x00" * 4096)
    busy = editor.post("/api/tasks", json={"input_video": config.rel(editor_clip)},
                       headers={"X-CSRF-Token": editor_csrf})
    check("second concurrent job is refused (429)", busy.status_code == 429,
          f"{busy.status_code} {busy.json().get('detail', '')[:50]}")
    webapp.store.update(ejob.id, status="completed")
    set_setting(user_daily_jobs=1, user_max_concurrent_jobs=0)
    first = editor.post("/api/tasks", json={"input_video": config.rel(editor_clip)},
                        headers={"X-CSRF-Token": editor_csrf})
    second = editor.post("/api/tasks", json={"input_video": config.rel(editor_clip)},
                         headers={"X-CSRF-Token": editor_csrf})
    check("daily job limit enforced on the next job",
          first.status_code == 200 and second.status_code == 429,
          f"{first.status_code} then {second.status_code}")
    set_setting(user_daily_jobs=0)
    webapp.store.update(ejob.id, status="completed")
    set_setting(user_max_concurrent_jobs=0)

    # ── 10. audit trail ───────────────────────────────────────────────
    section("audit log")
    entries = admin.get("/api/admin/audit?limit=50").json()["entries"]
    actions = {e["action"] for e in entries}
    check("logins are recorded", "login" in actions, ",".join(sorted(actions))[:90])
    check("failed logins are recorded", "login_failed" in actions)
    check("account creation is recorded", "user_create" in actions or "register" in actions)
    check("audit rows carry the username",
          any(e["username"] for e in entries))
    security = admin.get("/api/admin/audit").json()["security"]
    check("security report exposes the mode", security["auth_mode"] == "users")
    check("security report counts accounts", security["users"] == 2)

    # ── 11. password change invalidates sessions ──────────────────────
    section("password change")
    changed = editor.post("/api/auth/password",
                          json={"current_password": "Cl1p-Craft-77",
                                "new_password": "Cl1p-Craft-88"},
                          headers={"X-CSRF-Token": editor_csrf})
    check("password changed", changed.status_code == 200, changed.text[:70])
    check("old session is dead", editor.get("/api/keys").status_code == 401)
    relogin = TestClient(webapp.app).post("/api/auth/login",
                                          json={"username": "editor",
                                                "password": "Cl1p-Craft-88"})
    check("new password works", relogin.status_code == 200)

    # ── 12. disabled accounts ─────────────────────────────────────────
    section("disabled accounts")
    admin.patch(f"/api/admin/users/{editor_id}", json={"status": "disabled"},
                headers={"X-CSRF-Token": admin_csrf})
    denied = TestClient(webapp.app).post("/api/auth/login",
                                         json={"username": "editor",
                                               "password": "Cl1p-Craft-88"})
    check("disabled account cannot sign in", denied.status_code == 401)
    check("message explains why", "ပိတ်ထား" in denied.json().get("detail", ""),
          denied.json().get("detail", "")[:40])

    print("\n" + "=" * 58)
    print(f"{checks - len(failures)}/{checks} checks passed")
    if failures:
        print("FAILED: " + ", ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
