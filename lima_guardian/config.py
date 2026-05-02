"""
LIMA Guardian configuration.

Provides a single GuardianConfig that all modules read from.
Env prefix and data_dir are configurable so downstream projects
(e.g. Sparkbot) can slot their own conventions in.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class GuardianConfig:
    """Central configuration for all LIMA Guardian modules.

    Parameters
    ----------
    env_prefix : str
        Prefix for all environment variables.  Default ``"LIMA_GUARDIAN"``.
        The prefix is joined with an underscore, so ``"LIMA_GUARDIAN"``
        means the vault key env var is ``LIMA_GUARDIAN_VAULT_KEY``.
    data_dir : Path | str | None
        Root directory for Guardian data files (vault.db, operator_pin.hash).
        Falls back to ``<env_prefix>_DATA_DIR`` env var, then ``./data/guardian``.
    vault_key : str | None
        Fernet key for vault encryption.
        Falls back to ``<env_prefix>_VAULT_KEY`` env var.
    session_ttl : int
        Break-glass privileged session TTL in seconds. Default 900 (15 min).
    pin_max_attempts : int
        Failed PIN attempts before lockout. Default 5.
    pin_lockout_window : int
        Lockout window in seconds. Default 300 (5 min).
    pending_approval_ttl : int
        Default pending approval TTL in seconds. Default 600 (10 min).
    token_budget_review_threshold : float
        Review threshold for estimated token request cost. Default 1.0.
    token_model_registry_path : Path | str | None
        Optional path to a JSON model registry for Token Guardian.
    improvement_store_path : Path | str | None
        Optional path to the JSON improvement loop store.
    operator_usernames : set[str]
        Allowed operator usernames. Empty set = open mode (any user is operator).
    on_vault_event : callable | None
        Optional callback ``(event_type: str, alias: str, payload: dict) -> None``
        called on vault mutations. Replaces the Sparkbot Spine integration.
    on_approval_event : callable | None
        Optional callback ``(event_type: str, confirm_id: str, payload: dict) -> None``
        called on pending approval lifecycle changes.
    on_verification_event : callable | None
        Optional callback ``(event_type: str, subject: str, payload: dict) -> None``
        called when the verifier produces a result.
    """

    env_prefix: str = "LIMA_GUARDIAN"
    data_dir: Path | str | None = None
    vault_key: Optional[str] = None
    session_ttl: int = 900
    pin_max_attempts: int = 5
    pin_lockout_window: int = 300
    pending_approval_ttl: int = 600
    token_budget_review_threshold: float = 1.0
    token_model_registry_path: Path | str | None = None
    improvement_store_path: Path | str | None = None
    operator_usernames: set[str] = field(default_factory=set)
    on_vault_event: Callable[[str, str, dict], None] | None = None
    on_approval_event: Callable[[str, str, dict], None] | None = None
    on_verification_event: Callable[[str, str, dict], None] | None = None

    def __post_init__(self) -> None:
        # Resolve data_dir from env if not explicitly set
        if self.data_dir is None:
            env_dir = os.getenv(f"{self.env_prefix}_DATA_DIR", "").strip()
            if env_dir:
                self.data_dir = Path(env_dir).expanduser()
            else:
                self.data_dir = Path("data") / "guardian"
        else:
            self.data_dir = Path(self.data_dir).expanduser()

        # Resolve vault_key from env if not explicitly set
        if self.vault_key is None:
            self.vault_key = os.getenv(f"{self.env_prefix}_VAULT_KEY", "").strip() or None

        # Resolve session_ttl from env
        env_ttl = os.getenv(f"{self.env_prefix}_BREAKGLASS_TTL_SECONDS", "").strip()
        if env_ttl:
            self.session_ttl = int(env_ttl)

        # Resolve pin limits from env
        env_max = os.getenv(f"{self.env_prefix}_PIN_MAX_ATTEMPTS", "").strip()
        if env_max:
            self.pin_max_attempts = int(env_max)
        env_lockout = os.getenv(f"{self.env_prefix}_PIN_LOCKOUT_WINDOW_SECONDS", "").strip()
        if env_lockout:
            self.pin_lockout_window = int(env_lockout)
        env_pending_ttl = os.getenv(f"{self.env_prefix}_PENDING_APPROVAL_TTL_SECONDS", "").strip()
        if env_pending_ttl:
            self.pending_approval_ttl = int(env_pending_ttl)
        env_token_review_threshold = os.getenv(f"{self.env_prefix}_TOKEN_BUDGET_REVIEW_THRESHOLD", "").strip()
        if env_token_review_threshold:
            self.token_budget_review_threshold = float(env_token_review_threshold)

        # Resolve operator usernames from env
        if not self.operator_usernames:
            env_users = os.getenv(f"{self.env_prefix}_OPERATOR_USERNAMES", "").strip()
            if env_users:
                self.operator_usernames = {
                    name.strip().lower() for name in env_users.split(",") if name.strip()
                }

        if self.token_model_registry_path is None:
            env_registry_path = os.getenv(f"{self.env_prefix}_TOKEN_MODEL_REGISTRY_PATH", "").strip()
            self.token_model_registry_path = Path(env_registry_path).expanduser() if env_registry_path else self.data_dir / "token_guardian_models.json"
        else:
            self.token_model_registry_path = Path(self.token_model_registry_path).expanduser()

        if self.improvement_store_path is None:
            env_store_path = os.getenv(f"{self.env_prefix}_IMPROVEMENT_STORE_PATH", "").strip()
            self.improvement_store_path = Path(env_store_path).expanduser() if env_store_path else self.data_dir / "improvement_events.json"
        else:
            self.improvement_store_path = Path(self.improvement_store_path).expanduser()

    def env(self, suffix: str) -> str:
        """Return the full env var name for a given suffix."""
        return f"{self.env_prefix}_{suffix}"


# Module-level default instance — modules import this unless overridden
_default_config: Optional[GuardianConfig] = None


def get_config() -> GuardianConfig:
    """Return the active GuardianConfig, creating a default if needed."""
    global _default_config
    if _default_config is None:
        _default_config = GuardianConfig()
    return _default_config


def configure(config: GuardianConfig) -> None:
    """Set the module-level GuardianConfig. Call once at app startup."""
    global _default_config
    _default_config = config
