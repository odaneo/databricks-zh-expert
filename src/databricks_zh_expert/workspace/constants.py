from pathlib import Path
from typing import Final

WORKSPACE_ROOT: Final = Path("examples/workspaces")
WORKSPACE_SOURCE_MAX_BYTES: Final = 2 * 1024 * 1024
WORKSPACE_PACKAGE_MAX_BYTES: Final = 20 * 1024 * 1024
WORKSPACE_CONTEXT_TOP_K: Final = 8
WORKSPACE_CONTEXT_MAX_TOKENS: Final = 8_000
WORKSPACE_ALLOWED_SUFFIXES: Final = frozenset({".md", ".sql"})
