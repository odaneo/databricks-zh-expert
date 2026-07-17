from pathlib import Path
from typing import Final

WORKSPACE_ROOT: Final = Path("examples/workspaces")
WORKSPACE_SOURCE_MAX_BYTES: Final = 256_000
WORKSPACE_CONTEXT_TOP_K: Final = 6
WORKSPACE_CONTEXT_MAX_TOKENS: Final = 4_000
WORKSPACE_ALLOWED_SUFFIXES: Final = frozenset({".md", ".yml", ".yaml", ".sql", ".py"})
