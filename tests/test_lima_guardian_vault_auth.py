from __future__ import annotations

import sqlite3
import time

import pytest
from cryptography.fernet import Fernet

from lima_guardian.auth import (
    close_privileged_session,
    create_pin_hash,
    get_active_session,
    is_locked_out,
    is_operator_identity,
    is_operator_privileged,
    open_privileged_session,
    pin_configured,
    reset_state,
    set_operator_pin,
    verify_pin,
)
from lima_guardian.config import GuardianConfig
from lima_guardian.vault import (
    init_vault_db,
    vault_add,
    vault_delete,
    vault_get_metadata,
    vault_list,
    vault_reveal,
    vault_update,
    vault_use,
)


@pytest.fixture(autouse=True)
def clear_auth_state():
    reset_state()
    yield
    reset_state()


@pytest.fixture
def cfg(tmp_path):
    return GuardianConfig(
        env_prefix="TEST_LIMA",
        data_dir=tmp_path,
        vault_key=Fernet.generate_key().decode("utf-8"),
        session_ttl=1,
        pin_max_attempts=2,
        pin_lockout_window=60,
    )


def test_vault_uses_fernet_and_never_stores_plaintext(cfg):
    init_vault_db(cfg)

    vault_add(
        "openai",
        "sk-test-secret",
        category="api",
        policy="privileged_reveal",
        operator="tester",
        cfg=cfg,
    )

    with sqlite3.connect(cfg.data_dir / "vault.db") as conn:
        encrypted = conn.execute(
            "SELECT encrypted_value FROM vault_entries WHERE alias = ?",
            ("openai",),
        ).fetchone()[0]

    assert encrypted != b"sk-test-secret"
    assert b"sk-test-secret" not in encrypted
    assert Fernet(cfg.vault_key.encode("utf-8")).decrypt(encrypted).decode("utf-8") == "sk-test-secret"
    assert vault_use("openai", user_id="user-1", operator="tester", cfg=cfg) == "sk-test-secret"
    assert vault_reveal("openai", user_id="user-1", operator="tester", cfg=cfg) == "sk-test-secret"


def test_vault_policy_metadata_update_delete_and_audit(cfg):
    init_vault_db(cfg)
    vault_add("tool", "initial", notes="old", operator="tester", cfg=cfg)

    with pytest.raises(ValueError, match="use_only"):
        vault_reveal("tool", user_id="user-1", operator="tester", cfg=cfg)

    updated = vault_update(
        "tool",
        "rotated",
        notes="new",
        policy="privileged_reveal",
        operator="tester",
        session_id="session-1",
        cfg=cfg,
    )

    assert updated["notes"] == "new"
    assert updated["access_policy"] == "privileged_reveal"
    assert vault_get_metadata("tool", cfg)["alias"] == "tool"
    assert [item["alias"] for item in vault_list(cfg)] == ["tool"]
    assert vault_use("tool", user_id="user-1", operator="tester", cfg=cfg) == "rotated"
    assert vault_delete("tool", operator="tester", cfg=cfg) is True
    assert vault_delete("missing", operator="tester", cfg=cfg) is False

    with sqlite3.connect(cfg.data_dir / "vault.db") as conn:
        actions = [row[0] for row in conn.execute("SELECT action FROM vault_audit ORDER BY id")]

    assert actions == ["add", "reveal", "update", "use", "delete", "delete"]


def test_vault_event_callback_is_optional_and_non_blocking(cfg):
    events: list[tuple[str, str, dict]] = []
    cfg.on_vault_event = lambda event_type, alias, payload: events.append(
        (event_type, alias, payload)
    )

    init_vault_db(cfg)
    vault_add("evented", "secret", operator="tester", cfg=cfg)
    vault_use("evented", user_id="user-1", operator="tester", cfg=cfg)
    vault_delete("evented", operator="tester", cfg=cfg)

    assert [event[0] for event in events] == [
        "vault.secret_added",
        "vault.secret_used",
        "vault.secret_deleted",
    ]
    assert all(event[1] == "evented" for event in events)

    cfg.on_vault_event = lambda *_args: (_ for _ in ()).throw(RuntimeError("sink down"))
    vault_add("still-ok", "secret", operator="tester", cfg=cfg)


def test_auth_pin_file_hash_lockout_and_session_ttl(cfg):
    assert pin_configured(cfg) is False
    stored = set_operator_pin(
        user_id="user-1",
        new_pin="123456",
        new_pin_confirm="123456",
        cfg=cfg,
    )

    assert stored.startswith("pbkdf2$sha256$300000$")
    assert "123456" not in stored
    assert pin_configured(cfg) is True
    assert verify_pin("user-1", "000000", cfg) is False
    assert verify_pin("user-1", "000001", cfg) is False
    assert is_locked_out("user-1", cfg) is True
    assert verify_pin("user-1", "123456", cfg) is True

    session = open_privileged_session("user-1", "tester", "rotate secret", cfg)
    assert session.session_id
    assert is_operator_privileged("user-1") is True
    assert get_active_session("user-1") == session
    time.sleep(1.1)
    assert get_active_session("user-1") is None


def test_auth_pin_change_requires_current_pin(cfg):
    set_operator_pin(user_id="user-1", new_pin="123456", new_pin_confirm="123456", cfg=cfg)

    with pytest.raises(PermissionError, match="Current PIN"):
        set_operator_pin(user_id="user-1", new_pin="654321", new_pin_confirm="654321", cfg=cfg)

    with pytest.raises(PermissionError, match="Incorrect current PIN"):
        set_operator_pin(
            user_id="user-1",
            new_pin="654321",
            new_pin_confirm="654321",
            current_pin="000000",
            cfg=cfg,
        )

    set_operator_pin(
        user_id="user-1",
        new_pin="654321",
        new_pin_confirm="654321",
        current_pin="123456",
        cfg=cfg,
    )
    assert verify_pin("user-1", "654321", cfg) is True


def test_auth_operator_identity_modes_and_close_session(cfg):
    open_cfg = GuardianConfig(env_prefix="TEST_LIMA", data_dir="/tmp/lima-unused")
    restricted_cfg = GuardianConfig(
        env_prefix="TEST_LIMA",
        data_dir="/tmp/lima-unused",
        operator_usernames={"alice"},
    )

    assert is_operator_identity(username="anyone", user_type="HUMAN", cfg=open_cfg) is True
    assert is_operator_identity(username="service", user_type="BOT", cfg=open_cfg) is False
    assert is_operator_identity(username="root", user_type="BOT", is_superuser=True, cfg=open_cfg) is False
    assert is_operator_identity(username="alice", user_type="HUMAN", cfg=restricted_cfg) is True
    assert is_operator_identity(username="bob", user_type="HUMAN", cfg=restricted_cfg) is False

    open_privileged_session("user-2", "alice", cfg=restricted_cfg)
    assert is_operator_privileged("user-2") is True
    close_privileged_session("user-2")
    assert is_operator_privileged("user-2") is False


def test_auth_env_prefix_is_configurable(tmp_path, monkeypatch):
    pin_hash = create_pin_hash("111222")
    monkeypatch.setenv("CUSTOM_GUARDIAN_OPERATOR_PIN_HASH", pin_hash)
    monkeypatch.setenv("CUSTOM_GUARDIAN_BREAKGLASS_TTL_SECONDS", "3")
    monkeypatch.setenv("CUSTOM_GUARDIAN_PIN_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("CUSTOM_GUARDIAN_PIN_LOCKOUT_WINDOW_SECONDS", "5")
    monkeypatch.setenv("CUSTOM_GUARDIAN_OPERATOR_USERNAMES", "Alice, Bob")

    cfg = GuardianConfig(env_prefix="CUSTOM_GUARDIAN", data_dir=tmp_path)

    assert cfg.session_ttl == 3
    assert cfg.pin_max_attempts == 4
    assert cfg.pin_lockout_window == 5
    assert cfg.operator_usernames == {"alice", "bob"}
    assert verify_pin("user-1", "111222", cfg) is True


def test_vault_key_can_come_from_configured_env_prefix(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("CUSTOM_GUARDIAN_VAULT_KEY", key)

    cfg = GuardianConfig(env_prefix="CUSTOM_GUARDIAN", data_dir=tmp_path)
    init_vault_db(cfg)
    vault_add("from-env", "secret", operator="tester", cfg=cfg)

    assert vault_use("from-env", user_id="user-1", operator="tester", cfg=cfg) == "secret"
