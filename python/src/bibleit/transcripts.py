from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from bibleit.config import CONFIG_DIR


RECORDINGS_DIR = CONFIG_DIR / "recordings"


@dataclass(frozen=True)
class TranscriptFile:
    path: Path
    label: str


class TranscriptRecorder:
    def __init__(self, recordings_dir: Path = RECORDINGS_DIR) -> None:
        self.recordings_dir = recordings_dir
        self.path: Path | None = None

    def write(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        path = self._path()
        timestamp = datetime.now().strftime("%H:%M:%S")
        with path.open("a", encoding="utf-8") as file:
            file.write(f"[{timestamp}] {text}\n")

    def close(self) -> None:
        self.path = None

    def _path(self) -> Path:
        if self.path is None:
            self.recordings_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.path = self.recordings_dir / f"listening-{stamp}.txt"
        return self.path


def list_transcripts(recordings_dir: Path = RECORDINGS_DIR) -> list[TranscriptFile]:
    if not recordings_dir.exists():
        return []

    files = sorted(recordings_dir.glob("*.txt"), key=lambda path: path.stat().st_mtime, reverse=True)
    return [TranscriptFile(path=path, label=_label_for(path)) for path in files]


def read_transcript(path: Path, *, limit: int = 400) -> list[str]:
    if not path.exists():
        return []

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-limit:]


def _label_for(path: Path) -> str:
    name = path.stem.removeprefix("listening-")
    if len(name) == 15 and name[8] == "-":
        return f"{name[:4]}-{name[4:6]}-{name[6:8]} {name[9:11]}:{name[11:13]}:{name[13:15]}"
    return path.name
