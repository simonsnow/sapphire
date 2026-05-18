"""Sanitizer corpus runner — shells out to node to execute the JS test corpus.

The corpus lives in interfaces/web/static/shared/markdown.js and runs via Node
when the file is executed directly. This Python wrapper makes the same corpus
visible to pytest so future loops modifying the sanitizer can't silently
regress it.

Skips cleanly if Node isn't available — the JS file's self-test is still
runnable manually.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SANITIZER_PATH = PROJECT_ROOT / "interfaces" / "web" / "static" / "shared" / "markdown.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_sanitizer_corpus_passes():
    """All entries in the JS file's _CORPUS must pass.

    See interfaces/web/static/shared/markdown.js for the full corpus —
    covers raw script/iframe/object/embed/form/svg, javascript:/data:/file:
    links (incl. mixed case + whitespace smuggle), markdown image stripping,
    and a handful of must-still-work cases (https links, headings, bold, etc).
    """
    assert SANITIZER_PATH.exists(), f"sanitizer not found at {SANITIZER_PATH}"
    result = subprocess.run(
        ["node", str(SANITIZER_PATH)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        pytest.fail(
            f"sanitizer corpus failed (exit {result.returncode}):\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
    # Sanity check on output shape so we know the runner actually ran corpus.
    assert "passed" in result.stdout.lower(), (
        f"unexpected output:\n{result.stdout}"
    )
