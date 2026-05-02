"""
LIMA Guardian Auth — Privileged session management and PIN verification.

Ported from Sparkbot Guardian v1.6.48 with:
- Configurable env prefix (default LIMA_GUARDIAN)
- Configurable data_dir for PIN hash file
- Removed is_operator_user_id (depends on Sparkbot ORM)
- Kept: PBKDF2-HMAC-SHA256 PIN, in-memory sessions, lockout

Break-glass flow:
  1. Operator calls verify_pin() with 6-digit PIN
  2. On success, open_privileged_session() returns a PrivilegedSession
  3. Session lives in-memory with TTL (default 15 min)
  4. Session dies with the process — intentional security choice
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lima_guardian.config import GuardianConfig, get_config

log = logging.getLogger(__name__)

_PBKDF2_ITERATIONS = 300_000
_PBKDF2_HASH = "sha256"
_PBKDF2_DK_LEN = 32


@dataclass
class PrivilegedSession:
    session_id: str
    user_id: str
    operator: str
    started_at: float
    expires_at: float
    justification: str = ""
    scopes: list = field(default_factory=lambda: ["vault", "service_control"])

    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    def ttl_remaining(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    def expires_at_local(self) -> str:
        """Human-readable local expiry time."""
        import datetime
        return datetime.datetime.fromtimestamp(self.expires_at).strftime("%H:%M:%S")


# In-memory state — intentionally not persisted (sessions die with the process)
_PRIVILEGED_SESSIONS: dict[str, PrivilegedSession] = {}
_FAILED_ATTEMPTS: dict[str, list[float]] = {}


def _pin_hash_path(cfg: GuardianConfig) -> Path:
    return cfg.data_dir / "operator_pin.hash"


def _stored_pin_hash(cfg: GuardianConfig) -> str:
    try:
        file_hash = _pin_hash_path(cfg).read_text(encoding="utf-8").strip()
        if file_hash:
            return file_hash
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("[guardian-auth] Failed to read persisted operator PIN hash")
    return os.getenv(cfg.env("OPERATOR_PIN_HASH"), "").strip()


def pin_configured(cfg: GuardianConfig | None = None) -> bool:
    """Return True when an operator PIN is configured in env or data dir."""
    if cfg is None:
        cfg = get_config()
    return bool(_stored_pin_hash(cfg))


def _validate_six_digit_pin(pin: str) -> str:
    normalized = (pin or "").strip()
    if len(normalized) != 6 or not normalized.isdigit():
        raise ValueError("Operator PIN must be exactly 6 digits.")
    return normalized


def set_operator_pin(
    *,
    user_id: str,
    new_pin: str,
    new_pin_confirm: str,
    current_pin: str | None = None,
    cfg: GuardianConfig | None = None,
) -> str:
    """Persist a 6-digit operator PIN hash.

    Fresh installs may set the first PIN with double entry only. Existing PINs
    require the current PIN before replacement.
    """
    if cfg is None:
        cfg = get_config()
    pin = _validate_six_digit_pin(new_pin)
    if pin != (new_pin_confirm or "").strip():
        raise ValueError("PIN confirmation does not match.")

    existing = _stored_pin_hash(cfg)
    if existing:
        if not current_pin:
            raise PermissionError("Current PIN is required to change the operator PIN.")
        if not _verify_pbkdf2(current_pin.strip(), existing):
            _record_failed_attempt(user_id)
            raise PermissionError("Incorrect current PIN.")

    next_hash = create_pin_hash(pin)
    path = _pin_hash_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(next_hash + "\n", encoding="utf-8")
    _FAILED_ATTEMPTS.pop(user_id, None)
    log.info("[guardian-auth] Operator PIN %s", "changed" if existing else "created")
    return next_hash


def is_operator_identity(
    *,
    username: str | None,
    user_type: object | None,
    is_superuser: bool = False,
    cfg: GuardianConfig | None = None,
) -> bool:
    """Return True if this user identity is a guardian operator.

    Resolution order:
    1. Non-HUMAN users (bots, etc.) are never operators.
    2. If is_superuser=True, always an operator.
    3. If operator_usernames configured, check membership.
    4. If NOT configured, any authenticated HUMAN is operator (open mode).
    """
    if cfg is None:
        cfg = get_config()
    normalized_type = getattr(user_type, "value", user_type)
    if str(normalized_type).upper() != "HUMAN":
        return False
    if is_superuser:
        return True
    configured = cfg.operator_usernames
    if not configured:
        return True
    return (username or "").strip().lower() in configured


def create_pin_hash(pin: str) -> str:
    """Hash a PIN for storage.
    Returns 'pbkdf2$sha256$300000$<salt_hex>$<dk_hex>'.
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(
        _PBKDF2_HASH,
        pin.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
        dklen=_PBKDF2_DK_LEN,
    )
    return f"pbkdf2$sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def _verify_pbkdf2(pin: str, stored_hash: str) -> bool:
    """Constant-time verification of a PIN against a stored PBKDF2 hash."""
    try:
        parts = stored_hash.split("$")
        if len(parts) != 5 or parts[0] != "pbkdf2" or parts[1] != "sha256":
            return False
        iterations = int(parts[2])
        salt = bytes.fromhex(parts[3])
        expected_dk = bytes.fromhex(parts[4])
        candidate_dk = hashlib.pbkdf2_hmac(
            _PBKDF2_HASH,
            pin.encode("utf-8"),
            salt,
            iterations,
            dklen=len(expected_dk),
        )
        return hmac.compare_digest(candidate_dk, expected_dk)
    except Exception:
        return False


def is_locked_out(user_id: str, cfg: GuardianConfig | None = None) -> bool:
    """Return True if this user_id has too many recent failed PIN attempts."""
    if cfg is None:
        cfg = get_config()
    now = time.time()
    window = cfg.pin_lockout_window
    attempts = _FAILED_ATTEMPTS.get(user_id, [])
    recent = [t for t in attempts if now - t < window]
    _FAILED_ATTEMPTS[user_id] = recent
    return len(recent) >= cfg.pin_max_attempts


def _record_failed_attempt(user_id: str) -> None:
    now = time.time()
    attempts = _FAILED_ATTEMPTS.get(user_id, [])
    attempts.append(now)
    _FAILED_ATTEMPTS[user_id] = attempts


def verify_pin(user_id: str, submitted_pin: str, cfg: GuardianConfig | None = None) -> bool:
    """
    Verify submitted PIN against the stored hash. Records failed attempts.
    Returns True on success, False on failure or if not configured.
    """
    if cfg is None:
        cfg = get_config()
    stored = _stored_pin_hash(cfg)
    if not stored:
        log.warning("[guardian-auth] Operator PIN hash is not configured — PIN auth disabled")
        return False
    ok = _verify_pbkdf2(submitted_pin, stored)
    if not ok:
        _record_failed_attempt(user_id)
        log.warning("[guardian-auth] Failed PIN attempt for user_id=%s", user_id)
    return ok


def open_privileged_session(
    user_id: str,
    operator: str,
    justification: str = "",
    cfg: GuardianConfig | None = None,
) -> PrivilegedSession:
    """Open (or refresh) a privileged session for this user."""
    if cfg is None:
        cfg = get_config()
    now = time.time()
    ttl = cfg.session_ttl
    session = PrivilegedSession(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        operator=operator,
        started_at=now,
        expires_at=now + ttl,
        justification=justification.strip(),
    )
    _PRIVILEGED_SESSIONS[user_id] = session
    _FAILED_ATTEMPTS.pop(user_id, None)
    log.info(
        "[guardian-auth] Privileged session opened user_id=%s session_id=%s ttl=%ds justification=%r",
        user_id, session.session_id, ttl, session.justification,
    )
    return session


def get_active_session(user_id: str) -> Optional[PrivilegedSession]:
    """Return active non-expired session, or None."""
    session = _PRIVILEGED_SESSIONS.get(user_id)
    if session is None:
        return None
    if session.is_expired():
        _PRIVILEGED_SESSIONS.pop(user_id, None)
        return None
    return session


def is_operator_privileged(user_id: str) -> bool:
    """Return True if this user has an active privileged session."""
    return get_active_session(user_id) is not None


def close_privileged_session(user_id: str) -> None:
    """Explicitly close/revoke a privileged session."""
    session = _PRIVILEGED_SESSIONS.pop(user_id, None)
    if session:
        log.info(
            "[guardian-auth] Privileged session closed user_id=%s session_id=%s",
            user_id, session.session_id,
        )


def reset_state() -> None:
    """Clear all in-memory sessions and failed attempts. For testing only."""
    _PRIVILEGED_SESSIONS.clear()
    _FAILED_ATTEMPTS.clear()
