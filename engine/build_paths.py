"""Share the source root and build configuration among the engine generators."""
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent
CONFIG = {}


def source_path(relative):
    return SOURCE_ROOT / relative
