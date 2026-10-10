#!/usr/bin/env python3
"""Run native race tests and expose failure diagnostics in CI annotations."""
import os
import subprocess
import sys

result = subprocess.run(["go", "test", "-race", "-count=1", "./..."],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace")
print(result.stdout, end="", flush=True)
if result.returncode and os.environ.get("GITHUB_ACTIONS") == "true":
    # Only this repository's disposable test fixtures are involved. Escape
    # workflow-command delimiters so test output cannot inject CI commands.
    message = result.stdout[-24000:].replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print("::error title=Native race test diagnostics::" + message, flush=True)
sys.exit(result.returncode)
