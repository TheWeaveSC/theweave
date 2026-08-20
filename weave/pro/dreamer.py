"""Sleep-time dreamer (W4) — nightly anticipatory morning brief.

Reads the day's LearningLayer signals + the highest-salience entities (W3
bookkeeping), reasons in a SCRATCH file inside the cortex, and writes the
brief AS MARKDOWN into the vault through the normal write path — the ONE
sanctioned vault write in the whole cortex, exactly as CORTEX-PLAN W4
specifies. The scratch is deleted after the brief lands (tested); no latent
episodic content survives outside markdown (I4).

LLM: qwen3:14b via Ollama, think disabled (24GB discipline). The LLM step is
injectable; when Ollama is down the dreamer fails LOUDLY (a silent template
brief would be a fake artifact — the launchd job just retries next night).
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from ..vault import Note, Vault
from .cortex import cortex_dir
from .bookkeeping import BOOKKEEPING_DB
from .consolidator import signal_files

DREAM_MODEL = "qwen3:14b"
SALIENT_ENTITIES = 6
SIGNAL_LOOKBACK_DAYS = 3   # "the day's signals", tolerant of quiet days


class DreamError(RuntimeError):
    """Loud failure: missing LLM / empty vault. Never a fabricated brief."""


# ---------------------------------------------------------------------------
# Gather
# ---------------------------------------------------------------------------


def _note_day(n: Note) -> str:
    for key in ("valid_from", "date"):
        v = str(n.metadata.get(key) or "")[:10]
        if re.match(r"\d{4}-\d{2}-\d{2}", v):
            return v
    m = re.search(r"(\d{4}-\d{2}-\d{2})", n.name)
    return m.group(1) if m else ""


def gather(vault: Vault, day: date) -> dict:
    """Collect the brief's raw material. Read-only.

    Window is a LOWER bound only: monthly signal files carry a valid_from at
    month END (the committed fixture's own convention), so an upper bound of
    `day` would exclude the current month's file for most of the month."""
    cutoff = (day - timedelta(days=SIGNAL_LOOKBACK_DAYS)).isoformat()
    sigs = [n for n in signal_files(vault) if _note_day(n) >= cutoff]

    salient: list[tuple[str, int]] = []
    bkdb = cortex_dir(vault) / BOOKKEEPING_DB
    if bkdb.is_file():
        import sqlite3
        db = sqlite3.connect(bkdb)
        try:
            salient = db.execute(
                "SELECT note_name, recall_count FROM salience "
                "ORDER BY recall_count DESC, note_name LIMIT ?",
                (SALIENT_ENTITIES,)).fetchall()
        finally:
            db.close()

    # One heading-convention parser for the whole engine (hydrate owns it) —
    # a private copy here already drifted at birth (dropped 'recent activity').
    from .hydrate import _entity_memory_threads
    notes_by_name = {n.name: n for n in vault.iter_notes()}
    threads: list[tuple[str, str]] = []
    for name, _count in salient:
        n = notes_by_name.get(name)
        if n is None:
            continue
        for t in _entity_memory_threads(n):
            threads.append((name, t))

    return {"day": day.isoformat(), "signals": sigs, "salient": salient,
            "threads": threads}


# ---------------------------------------------------------------------------
# LLM step (injectable; qwen3:14b think:false by default)
# ---------------------------------------------------------------------------


def _ollama_llm(prompt: str, *, model: str = DREAM_MODEL,
                url: str = "http://localhost:11434", timeout: int = 300) -> str:
    body = json.dumps({
        "model": model, "stream": False, "think": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.3},
    }).encode("utf-8")
    req = urllib.request.Request(f"{url}/api/chat", body,
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        content = (data.get("message") or {}).get("content", "").strip()
    except (OSError, ValueError, AttributeError, KeyError) as e:
        # ValueError covers JSONDecodeError (proxy/truncated 200 responses) —
        # anything short of a usable synthesis takes the LOUD path.
        raise DreamError(f"Ollama unusable for the dream step ({e}); "
                         "no brief written — will retry next night") from e
    if not content:
        raise DreamError("LLM returned an empty synthesis; no brief written")
    return content


def _dream_prompt(material: dict) -> str:
    lines = [
        "Output contract — follow EXACTLY:",
        "- Output ONLY 3 to 6 lines.",
        "- Every line starts with '- ' (a markdown bullet). Nothing else: "
        "no headings, no emoji, no tables, no intro, no closing question.",
        "- Each bullet <= 30 words: one thing likely to need attention "
        "tomorrow and WHY, grounded in the evidence below.",
        "- Plain operational tone. Never address the reader.",
        "",
        "Task: from the evidence, write the ANTICIPATIONS bullets for "
        "tomorrow's morning brief of this working-memory vault.",
        f"\n## Recent signals (last {SIGNAL_LOOKBACK_DAYS} days)"]
    for n in material["signals"]:
        lines.append(f"### {n.name}")
        lines.append(n.content.strip()[:1500])
    lines.append("\n## Open threads on the most-recalled notes")
    for name, t in material["threads"][:20]:
        lines.append(f"- ({name}) {t}")
    if not material["threads"] and not material["signals"]:
        lines.append("- (quiet period — say so honestly in one bullet)")
    return "\n".join(lines)


def _extract_bullets(raw: str, prompt_text: str = "", cap: int = 6) -> list[str]:
    """Enforce the output contract: keep only top-level '- ' lines, cap at 6,
    and DROP any bullet that is a verbatim echo of the evidence in the prompt
    (a model quoting yesterday's open-thread lines back is a fabricated
    anticipation that would otherwise pass the shape check)."""
    bullets = [ln.strip() for ln in raw.splitlines()
               if ln.startswith("- ") and len(ln.strip()) > 4]  # TOP-LEVEL only
    if prompt_text:
        bullets = [b for b in bullets
                   if b[2:].strip() and b[2:].strip() not in prompt_text]
    return bullets[:cap]


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------


@dataclass
class DreamResult:
    brief_rel_path: str
    scratch_deleted: bool
    signals_used: int
    threads_used: int


def resolve_brief_dir(vault: Vault) -> str:
    """GENERIC resolution — the engine carries zero institutional vault names
    (hydrate.py doctrine). Order: WEAVE_BRIEF_DIR env override; an existing
    dir literally named `briefs` at root or one level deep; else vault-root
    `briefs/`."""
    env = os.environ.get("WEAVE_BRIEF_DIR")
    if env:
        return env.strip("/")
    if (vault.root / "briefs").is_dir():
        return "briefs"
    hits = sorted(p for p in vault.root.glob("*/briefs") if p.is_dir())
    if hits:
        return f"{hits[0].parent.name}/briefs"
    return "briefs"


def dream(vault: Vault, *, day: date | None = None, llm=None,
          brief_dir: str | None = None, dry_run: bool = False) -> DreamResult:
    """Run the sleep-time job once. The ONLY vault write is the brief itself,
    through vault.write_text (the normal write path)."""
    day = day or date.today()
    llm = llm or _ollama_llm
    brief_dir = brief_dir or resolve_brief_dir(vault)
    material = gather(vault, day)

    cdir = cortex_dir(vault, create=True)
    scratch = cdir / "scratch" / f"dream-{day.isoformat()}.md"
    scratch.write_text(_dream_prompt(material), encoding="utf-8")

    try:
        prompt_text = scratch.read_text(encoding="utf-8")
        raw = llm(prompt_text)
        bullets = _extract_bullets(raw, prompt_text)
        if not bullets:
            # one retry with the violation named; then loud failure
            raw = llm("Your previous output violated the contract (no "
                      "original markdown bullets found — do not quote the "
                      "evidence lines back). Re-answer with ONLY 3-6 lines, "
                      "each starting with '- '.\n\n" + prompt_text)
            bullets = _extract_bullets(raw, prompt_text)
        if not bullets:
            raise DreamError("LLM would not honor the bullets-only contract "
                             "after retry; no brief written")
        anticipations = "\n".join(bullets)

        lines = [
            "---",
            f"type: morning-brief",
            f"date: '{day.isoformat()}'",
            f"generated_by: weave-cortex dreamer ({DREAM_MODEL}, think:false)",
            "status: current",
            "---",
            "",
            f"# Morning brief — {day.isoformat()}",
            "",
            "## Anticipations",
            anticipations.strip(),
            "",
            "## Evidence",
            f"- signals in window ({SIGNAL_LOOKBACK_DAYS}d): "
            + (", ".join(f"[[{n.name}]]" for n in material["signals"]) or "(none)"),
            "- most-recalled: "
            + (", ".join(f"[[{name}]] ({c}×)" for name, c in material["salient"])
               or "(no bookkeeping yet)"),
            "",
            "*Derived brief — written via the normal write path; scratch "
            "reasoning deleted from the cortex after this file landed (W4/I4).*",
        ]
        rel = f"{brief_dir}/brief-{day.isoformat()}.md"
        if not dry_run:
            vault.write_text(rel, "\n".join(lines) + "\n")
    finally:
        deleted = False
        if scratch.exists():
            scratch.unlink()
            deleted = True

    return DreamResult(brief_rel_path=rel, scratch_deleted=deleted,
                       signals_used=len(material["signals"]),
                       threads_used=len(material["threads"]))


# ---------------------------------------------------------------------------
# launchd install (macOS)
# ---------------------------------------------------------------------------

PLIST_LABEL = "com.theweave.cortex.nightly"


def launchd_plist(vault_path: str, python_bin: str, hour: int, minute: int,
                  log_path: str) -> str:
    """plistlib, not string interpolation: a vault path containing '&' (legal
    on macOS, common in iCloud folders) must not produce invalid XML that
    launchd silently rejects."""
    import plistlib
    env = {"WEAVE_VAULT_PATH": vault_path}
    cortex_base = os.environ.get("WEAVE_CORTEX_DIR")
    if cortex_base:
        # the nightly job must read the SAME cortex the sessions write
        env["WEAVE_CORTEX_DIR"] = cortex_base
    return plistlib.dumps({
        "Label": PLIST_LABEL,
        "ProgramArguments": [python_bin, "-m", "weave", "cortex", "dream"],
        "EnvironmentVariables": env,
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
    }, sort_keys=False).decode("utf-8")


__all__ = ["dream", "gather", "DreamResult", "DreamError", "launchd_plist",
           "resolve_brief_dir", "PLIST_LABEL", "DREAM_MODEL"]
