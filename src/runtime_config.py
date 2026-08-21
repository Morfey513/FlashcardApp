"""Load machine-local runtime settings without committing secrets."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from src.config import BASE_DIR


@lru_cache(maxsize=1)
def load_runtime_environment(env_file: str | Path | None = None) -> bool:
    """Load ``.env`` once while preserving explicit process variables."""
    path = Path(env_file) if env_file is not None else BASE_DIR / ".env"
    return bool(load_dotenv(dotenv_path=path, override=False))
