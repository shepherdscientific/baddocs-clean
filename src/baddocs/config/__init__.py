"""Configuration module."""

from baddocs.config.loader import load_config
from baddocs.config.providers import ProviderConfig

__all__ = [
    'load_config',
    'ProviderConfig',
]
