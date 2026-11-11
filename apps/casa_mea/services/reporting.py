"""Small shared boundary for safely publishing generated audit artifacts."""

from pathlib import Path
from tempfile import NamedTemporaryFile


def write_text_atomically(path: Path, contents: str) -> None:
    """Replace a text artifact only after its complete contents are written."""

    if not path.parent.is_dir():
        raise OSError(f"Directorul raportului nu există: {path.parent}")
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(contents)
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
