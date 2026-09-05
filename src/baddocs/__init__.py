"""BadDocs - incremental, local-first documentation (with Verilog/RTL support)."""

__version__ = '1.0.0'
__author__ = 'Shepherd Scientific'

__all__ = ['FileDiscovery', 'get_session']


def __getattr__(name):
    # Lazy re-exports (PEP 562): importing ``baddocs`` -- e.g. to use the
    # incremental engine or a language processor -- must not drag in the
    # storage/DB layer (SQLAlchemy) unless the caller actually needs it.
    if name == 'FileDiscovery':
        from baddocs.core.file_discovery import FileDiscovery
        return FileDiscovery
    if name == 'get_session':
        from baddocs.storage.connection import get_session
        return get_session
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
