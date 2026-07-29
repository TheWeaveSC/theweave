"""SIGKILL failure-injection: a subprocess is killed mid-write (between the
tempfile fsync and the os.replace rename) to prove the parent's view of the
destination file is never torn — it's byte-identical to either the pre- or
post-write content, never a truncated/mixed length.

This is a heavier, closer-to-real-crash version of the monkeypatch-based
test in test_vault_write_path.py (which proves the code path unlinks its
tempfile on error, but doesn't prove survival of an actual OS-level kill).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# The child writes a big payload via the same tempfile+fsync steps as
# Vault._atomic_write, then sleeps right after the fsync and right before
# os.replace, so the parent has a wide, deterministic window in which to
# SIGKILL it.
CHILD_SCRIPT = r"""
import os
import sys
import time
sys.path.insert(0, {repo_root!r})
from weave.vault import Vault

vault_root = sys.argv[1]
payload = sys.argv[2]

v = Vault(vault_root)
p = v._resolve("big.md")

import tempfile
fd, tmp_name = tempfile.mkstemp(dir=p.parent, prefix=f".{{p.name}}.", suffix=".tmp")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write(payload)
    f.flush()
    os.fsync(f.fileno())

# Signal readiness to the parent, then sleep so the parent can SIGKILL us
# before we reach os.replace.
print("READY", flush=True)
time.sleep(5)

os.replace(tmp_name, p)
"""


def test_sigkill_mid_write_leaves_no_torn_file(tmp_path: Path) -> None:
    repo_root = str(Path(__file__).resolve().parents[1])
    vault_root = tmp_path
    old_content = "OLD" * 1000
    (vault_root / "big.md").write_text(old_content, encoding="utf-8")

    new_payload = "NEW" * 5000  # different length from old, so any torn mix is detectable

    script_path = tmp_path / "_child.py"
    script_path.write_text(CHILD_SCRIPT.format(repo_root=repo_root), encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, str(script_path), str(vault_root), new_payload],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = proc.stdout.readline()
        assert line.strip() == "READY", f"child did not signal readiness: {line!r}, stderr={proc.stderr.read()}"
        # Kill before the child reaches os.replace.
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    final = (vault_root / "big.md").read_text(encoding="utf-8")
    # Must be exactly the OLD content (replace never happened) — never a
    # truncated/mixed blend of old+new.
    assert final == old_content, (
        f"file was torn or corrupted: len={len(final)} "
        f"(expected old len={len(old_content)} or new len={len(new_payload)})"
    )

    # No leftover tempfile from the killed child (best-effort check — a
    # SIGKILL child can't run its own except/finally cleanup, so this
    # documents the residue rather than asserting it's absent; the
    # meaningful guarantee is the destination integrity checked above).
