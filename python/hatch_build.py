from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name == "sdist":
            return

        build_data["pure_python"] = False
        build_data["infer_tag"] = True

        root = Path(self.root)
        source_dir = self._find_libbibleit(root)
        lib_name = self._library_name()

        subprocess.run(["make", "clean"], cwd=source_dir, check=True)
        subprocess.run(["make"], cwd=source_dir, check=True)

        output_dir = root / "src" / "bibleit" / "_native"
        output_dir.mkdir(parents=True, exist_ok=True)

        source_lib = source_dir / lib_name
        target_lib = output_dir / lib_name
        shutil.copy2(source_lib, target_lib)

        if platform.system() == "Darwin":
            self._codesign(target_lib)

    def _find_libbibleit(self, root: Path) -> Path:
        candidates = [
            root / "native" / "libbibleit",
            root.parent / "libbibleit",
        ]

        for candidate in candidates:
            if (candidate / "Makefile").exists():
                return candidate

        raise RuntimeError("libbibleit source directory not found")

    def _library_name(self) -> str:
        if platform.system() == "Darwin":
            return "libbibleit.dylib"
        return "libbibleit.so"

    def _codesign(self, path: Path) -> None:
        if not shutil.which("codesign"):
            return

        subprocess.run(
            ["codesign", "--force", "--sign", "-", os.fspath(path)],
            check=True,
        )
