"""Domain-meaningful exceptions raised below the CLI layer."""

from __future__ import annotations


class ArenaError(Exception):
    """Base class for errors the CLI reports without a traceback."""


class ConfigError(ArenaError):
    """A model, experiment or scenario configuration is invalid."""


class CapabilityError(ConfigError):
    """A role was bound to a model that lacks a required capability (e.g. vision)."""


class RunConflictError(ArenaError):
    """A run id is already active."""


class RunLimitError(ArenaError):
    """The local runtime has reached its active-run limit."""
