"""Backends for deepanalysts middleware storage."""

from deepanalysts.backends.composite import CompositeBackend
from deepanalysts.backends.filesystem import FilesystemBackend, LocalFilesystemBackend
from deepanalysts.backends.protocol import (
    BACKEND_TYPES,
    BackendProtocol,
    EditResult,
    ExecuteResponse,
    FileData,
    FileDownloadResponse,
    FileFormat,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    SandboxBackendProtocol,
    WriteResult,
)
from deepanalysts.backends.sandbox import BaseSandbox, RestrictedSubprocessBackend
from deepanalysts.backends.state import StateBackend
from deepanalysts.backends.store import (
    BackendContext,
    NamespaceFactory,
    StoreBackend,
    _validate_namespace,
)

__all__ = [
    # Protocols and types
    "BACKEND_TYPES",
    "BackendProtocol",
    "SandboxBackendProtocol",
    # Result types
    "EditResult",
    "ExecuteResponse",
    "FileData",
    "FileDownloadResponse",
    "FileFormat",
    "FileInfo",
    "FileUploadResponse",
    "GlobResult",
    "GrepMatch",
    "GrepResult",
    "LsResult",
    "ReadResult",
    "WriteResult",
    # Store types
    "BackendContext",
    "NamespaceFactory",
    "_validate_namespace",
    # Backend implementations
    "BaseSandbox",
    "CompositeBackend",
    "FilesystemBackend",
    "LocalFilesystemBackend",
    "RestrictedSubprocessBackend",
    "StateBackend",
    "StoreBackend",
]

# Optional imports that require additional dependencies (Basement API loaders)
try:
    from deepanalysts.backends.basement import BasementMemoryLoader, BasementSkillsLoader

    __all__.extend(["BasementMemoryLoader", "BasementSkillsLoader"])
except ImportError:
    pass
