"""Standalone LIMA Guardian modules.

This package contains decoupled Guardian components extracted from Sparkbot's
working implementation. Sparkbot remains the source of truth while modules are
ported behind explicit configuration and standalone tests.
"""

from lima_guardian.config import GuardianConfig, configure, get_config

__all__ = ["GuardianConfig", "configure", "get_config"]
