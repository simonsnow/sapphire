"""URL-safety corpus runner — shells out to node to execute the JS test corpus.

The corpus lives in interfaces/web/static/shared/url-safety.js and runs via
Node when the file is executed directly. This Python wrapper makes the same
corpus visible to pytest so future loops modifying the URL gate can't silently
regress it.

The URL gate (`isSafeHref`) is the trust boundary for community-authored URL
fields (author_url, github_url, screenshot_url) before they're rendered into
href/src attributes on dashboard cards and store listings. Regressions here
are stored-XSS-class — keep the gate test corpus comprehensive.

Skips cleanly if Node isn't available — the JS file's self-test is still
runnable manually.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
URL_SAFETY_PATH = (
    PROJECT_ROOT / "interfaces" / "web" / "static" / "shared" / "url-safety.js"
)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_url_safety_corpus_passes():
    """All entries in the JS file's _CORPUS must pass.

    See interfaces/web/static/shared/url-safety.js for the full corpus —
    covers javascript:/data:/file:/vbscript: schemes (incl. mixed-case,
    whitespace smuggle, embedded newlines/tabs), non-https schemes
    (mailto/tel/http), protocol-relative and relative URLs, non-string
    inputs (null/undefined/object/array), and a handful of must-still-work
    cases (plain https, https+path+query, https with port).
    """
    assert URL_SAFETY_PATH.exists(), f"url-safety not found at {URL_SAFETY_PATH}"
    result = subprocess.run(
        ["node", str(URL_SAFETY_PATH)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        pytest.fail(
            f"url-safety corpus failed (exit {result.returncode}):\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
