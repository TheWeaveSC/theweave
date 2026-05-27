"""Bi-temporal resolver — Pattern 3.

Adds time-aware semantics on top of plain wikilinks. Convention:

    valid_from:   ISO date when this fact became true
    valid_until:  ISO date when superseded (null/absent = currently valid)
    superseded_by: "[[entity-foo-v2]]" — the wikilink that replaces this
    supersedes:    "[[entity-foo]]"    — what this replaces (optional, for bidirection)
    status:       "current" | "superseded" | ...  (informational)

Resolver follows the `superseded_by` chain to the latest valid version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterator

from ..vault import Note, Vault, WIKILINK_RE


@dataclass
class Resolution:
    """Result of resolving a name to a current note."""

    query: str
    chain: list[str]               # names walked, oldest -> newest
    current: Note | None
    notes_visited: list[Note]

    @property
    def hopped(self) -> bool:
        return len(self.chain) > 1


def _link_target(value: str | None) -> str | None:
    """Extract the bare name from a wikilink string like '[[entity-foo]]'."""
    if not value:
        return None
    m = WIKILINK_RE.search(value)
    return m.group(1).strip() if m else value.strip()


class BiTemporalResolver:
    """Walk the `superseded_by` chain to find the currently valid note."""

    def __init__(self, vault: Vault):
        self.vault = vault

    def resolve(self, name: str, as_of: date | None = None) -> Resolution:
        """Return the latest valid note in the supersession chain starting at `name`.

        If `as_of` is provided, returns the version that was current on that
        date (i.e. stops walking once we pass a `valid_from > as_of`).
        """
        chain: list[str] = []
        visited: list[Note] = []
        seen: set[str] = set()
        cur_name = name.strip()
        current: Note | None = None

        while cur_name and cur_name not in seen:
            seen.add(cur_name)
            chain.append(cur_name)
            note = self.vault.find_note_by_name(cur_name)
            if note is None:
                break
            visited.append(note)

            # Check if this version is valid at as_of
            if as_of is not None:
                vf = note.metadata.get("valid_from")
                vf_date = _coerce_date(vf)
                if vf_date and vf_date > as_of:
                    # this version is in the future relative to as_of; back up
                    current = visited[-2] if len(visited) > 1 else None
                    break

            current = note
            nxt = _link_target(note.metadata.get("superseded_by"))
            if nxt is None:
                break
            cur_name = nxt

        return Resolution(query=name, chain=chain, current=current, notes_visited=visited)

    def current_entities(self) -> Iterator[Note]:
        """Yield every entity note that is currently valid (no superseded_by)."""
        for note in self.vault.iter_notes():
            if note.metadata.get("type") in ("entity", "project", "person", "stakeholder", "research-project"):
                if not note.metadata.get("superseded_by"):
                    yield note


def _coerce_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v)
        except ValueError:
            return None
    return None
