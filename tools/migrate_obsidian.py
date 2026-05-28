#!/usr/bin/env python3
"""
Obsidian → TheWeave migration tool.

Reads one or more source vaults (an Obsidian-style markdown directory plus
optional auxiliary directories like an agent's identity home) and writes a
fresh TheWeave-shaped vault: entities/, sessions/, wiki/, LearningLayer/,
_archive/.

For each source file the script:

  1. Skips auto-heal stubs (frontmatter type=stub or source=auto-heal, or
     content matching the "auto-generated because... did not exist" template).
  2. Looks up a rule for the source path. The rule decides the destination
     subdirectory, the TheWeave type, and the target filename strategy.
  3. Rewrites frontmatter — name, type, valid_from, valid_until, status,
     plus origin_path for back-reference. Existing tags are preserved.
     Existing wikilinks in the body are preserved as-is.
  4. Writes the new file under the destination root.

Rule sets are defined inline at the bottom of this file. Adapt the
TimmyMemory rules to migrate a different vault; the engine is generic.

Usage:
    python migrate_obsidian.py --dry-run
    python migrate_obsidian.py --apply
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import pathlib
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import frontmatter

HOME = pathlib.Path.home()
TODAY = dt.date.today().isoformat()


def slugify(s: str) -> str:
    s = re.sub(r"\.md$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[^a-zA-Z0-9\s_-]", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-").lower()
    s = re.sub(r"-+", "-", s)
    return s or "untitled"


def extract_date(fm: dict, path: pathlib.Path) -> str:
    for key in ("date", "created", "valid_from"):
        v = fm.get(key)
        if v:
            s = str(v)
            m = re.match(r"\d{4}-\d{2}-\d{2}", s)
            if m:
                return m.group(0)
    m = re.search(r"\d{4}-\d{2}-\d{2}", path.name)
    if m:
        return m.group(0)
    return TODAY


def is_stub(fm: dict, content: str) -> bool:
    if fm.get("type") == "stub":
        return True
    if fm.get("source") == "auto-heal":
        return True
    head = content[:400]
    if "auto-generated because" in head and "did not exist" in head:
        return True
    return False


@dataclass
class Rule:
    name: str
    pattern: str
    target_dir: Optional[str]
    target_type: Optional[str]
    filename: str
    description: str = ""


def _resolve_filename(strategy: str, rel: pathlib.Path, fm: dict) -> str:
    stem = rel.stem
    if strategy == "preserve_name":
        return f"{slugify(stem)}.md"
    if strategy == "date_prefixed":
        date = extract_date(fm, rel)
        return f"{date}-{slugify(stem)}.md"
    if strategy == "entity_prefix":
        parts = [slugify(p) for p in rel.parts[1:]]
        if parts:
            parts[-1] = slugify(pathlib.Path(parts[-1]).stem)
        flat = "-".join(p for p in parts if p) if parts else slugify(stem)
        return f"entity-{flat}.md"
    if strategy.startswith("rename:"):
        # Supports `rename:foo.md` and `rename:signals-{stem}-deep.md`
        # where {stem} is replaced with the source filename stem (e.g. "2026-05-27").
        tpl = strategy.split(":", 1)[1]
        return tpl.format(stem=rel.stem)
    if strategy == "preserve_subpath":
        parts = list(rel.parts[1:])
        if not parts:
            return f"{slugify(rel.stem)}.md"
        out_parts = []
        for i, p in enumerate(parts):
            if i < len(parts) - 1:
                out_parts.append(slugify(p))
            else:
                out_parts.append(f"{slugify(pathlib.Path(p).stem)}.md")
        return "/".join(out_parts)
    raise ValueError(f"Unknown filename strategy: {strategy}")


@dataclass
class Report:
    written: Counter = field(default_factory=Counter)
    stubs_skipped: int = 0
    obsidian_artefacts: int = 0
    unmatched: list[str] = field(default_factory=list)
    drops: Counter = field(default_factory=Counter)
    wikilinks_preserved: int = 0
    parse_errors: list[str] = field(default_factory=list)
    # Per-rule sample paths for debugging — first 10 paths matched by each rule
    rule_samples: dict[str, list[str]] = field(default_factory=dict)

    def print(self) -> None:
        print()
        print("=" * 60)
        print("Migration report")
        print("=" * 60)
        for rule, n in sorted(self.written.items()):
            print(f"  ✓ {rule:35} {n:>4} files written")
        for rule, n in sorted(self.drops.items()):
            print(f"  ⨯ {rule:35} {n:>4} files dropped (by rule)")
        print(f"  ⨯ {'auto-heal stubs':35} {self.stubs_skipped:>4} files dropped")
        artefact_label = "Obsidian artefacts (escaped)"
        print(f"  ⨯ {artefact_label:35} {self.obsidian_artefacts:>4} files dropped")
        print(f"  ⊙ {'wikilinks preserved':35} {self.wikilinks_preserved:>4}")
        if self.parse_errors:
            print(f"\n  ⚠ {len(self.parse_errors)} frontmatter parse error(s):")
            for p in self.parse_errors[:10]:
                print(f"      {p}")
            if len(self.parse_errors) > 10:
                print(f"      ... and {len(self.parse_errors) - 10} more")
        if self.unmatched:
            print(f"\n  ⚠ {len(self.unmatched)} unmatched files (no rule applied):")
            for p in self.unmatched[:20]:
                print(f"      {p}")
            if len(self.unmatched) > 20:
                print(f"      ... and {len(self.unmatched) - 20} more")
        print()


WIKILINK_RE = re.compile(r"\[\[([^\]]+?)\]\]")


def migrate_file(abs_path: pathlib.Path, rel_path: pathlib.Path, rule: Rule,
                 dest_root: pathlib.Path, report: Report, apply: bool,
                 source_label: str) -> None:
    try:
        post = frontmatter.load(abs_path)
    except Exception as e:
        report.parse_errors.append(f"{source_label}:{rel_path} — {e}")
        return

    if is_stub(post.metadata, post.content):
        report.stubs_skipped += 1
        return

    if rule.target_dir is None:
        report.drops[rule.name] += 1
        return

    target_leaf = _resolve_filename(rule.filename, rel_path, post.metadata)
    target = dest_root / rule.target_dir / target_leaf

    new_fm = {
        "name": pathlib.Path(target_leaf).stem,
        "type": rule.target_type if rule.target_type else post.metadata.get("type", "wiki"),
        "valid_from": extract_date(post.metadata, rel_path),
        "valid_until": None,
        "status": "current",
        "origin_path": f"{source_label}:{rel_path.as_posix()}",
    }
    if "tags" in post.metadata:
        new_fm["tags"] = post.metadata["tags"]
    if "source" in post.metadata:
        new_fm["origin_source"] = post.metadata["source"]

    body = post.content
    report.wikilinks_preserved += len(WIKILINK_RE.findall(body))

    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        out_post = frontmatter.Post(content=body, **new_fm)
        target.write_text(frontmatter.dumps(out_post) + "\n", encoding="utf-8")

    report.written[rule.name] += 1
    samples = report.rule_samples.setdefault(rule.name, [])
    if len(samples) < 10:
        samples.append(f"{source_label}:{rel_path.as_posix()}")


def glob_match(pattern: str, path: str) -> bool:
    """Glob matcher where `**/` matches zero or more directory segments.

    Unlike fnmatch.fnmatch, this means `projects/**/*.md` matches both
    `projects/index.md` (zero subdirs) and `projects/foo/bar.md` (one subdir).
    `*` matches any chars except `/`. `?` matches one char except `/`.
    """
    re_pattern = ""
    i = 0
    while i < len(pattern):
        if pattern[i:i + 3] == "**/":
            re_pattern += r"(?:[^/]+/)*"
            i += 3
        elif pattern[i] == "*":
            re_pattern += r"[^/]*"
            i += 1
        elif pattern[i] == "?":
            re_pattern += r"[^/]"
            i += 1
        else:
            re_pattern += re.escape(pattern[i])
            i += 1
    return bool(re.match(f"^{re_pattern}$", path))


def find_rule(rel: pathlib.Path, rules: list[Rule]) -> Optional[Rule]:
    posix = rel.as_posix()
    for r in rules:
        if glob_match(r.pattern, posix):
            return r
    return None


def walk_source(source_root: pathlib.Path, source_label: str,
                rules: list[Rule], dest_root: pathlib.Path,
                report: Report, apply: bool) -> None:
    if not source_root.exists():
        print(f"  skip: source not found — {source_root}", file=sys.stderr)
        return
    for abs_path in sorted(source_root.rglob("*.md")):
        if any(p.startswith(".") for p in abs_path.relative_to(source_root).parts):
            continue
        # Skip Obsidian backslash-escaped duplicates (e.g. `CORE\.md` sitting
        # alongside `CORE.md`). These are not real content, just file-system
        # artefacts from Obsidian's renaming/aliasing.
        if "\\" in abs_path.name:
            report.obsidian_artefacts += 1
            continue
        rel = abs_path.relative_to(source_root)
        rule = find_rule(rel, rules)
        if rule is None:
            report.unmatched.append(f"{source_label}:{rel.as_posix()}")
            continue
        migrate_file(abs_path, rel, rule, dest_root, report, apply, source_label)


TIMMYMEMORY_RULES: list[Rule] = [
    Rule("daily logs",          "daily/*.md",                  "sessions",  "session",  "date_prefixed"),
    Rule("weekly logs",         "weekly/*.md",                 "sessions",  "session",  "date_prefixed"),
    Rule("wiki notes",          "wiki/**/*.md",                "wiki",      "wiki",     "preserve_subpath"),
    Rule("projects",            "projects/**/*.md",            "entities",  "project",  "entity_prefix"),
    Rule("topics",              "topics/**/*.md",              "entities",  "concept",  "entity_prefix"),
    Rule("agents (team)",       "agents/**/*.md",              "entities",  "agent",    "entity_prefix"),
    Rule("archive",             "archive/**/*.md",             "_archive",  None,       "preserve_subpath"),
    Rule("_shared CORE",        "_shared/CORE.md",             "wiki",      "wiki",     "rename:core.md"),
    Rule("_shared identity",    "_shared/identity.md",         "wiki",      "wiki",     "rename:shared-identity.md"),
    Rule("_shared people",      "_shared/people/**/*.md",      "entities",  "person",   "entity_prefix"),
    Rule("_shared facts",       "_shared/facts/**/*.md",       "entities",  "concept",  "entity_prefix"),
    Rule("_shared decisions",   "_shared/decisions/**/*.md",   "entities",  "decision", "entity_prefix"),
    Rule("_shared diamond",     "_shared/diamond-to-timmy.md", "wiki",      "wiki",     "rename:diamond-to-timmy.md"),
    Rule("_system runtime",     "_system/**/*.md",             "_archive",  None,       "preserve_subpath"),
    Rule("Claude Memory",       "Claude Memory/*.md",          "wiki",      "wiki",     "preserve_name"),
    Rule("Sonnet briefs",       "Sonnet Input/briefs/*.md",    "sessions",  "session",  "date_prefixed"),
    Rule("Sonnet Input other",  "Sonnet Input/**/*.md",        "wiki",      "wiki",     "preserve_subpath"),
    Rule("TagsRoutes drop",     "TagsRoutes/**/*.md",          None,        None,       "preserve_name",
         description="Obsidian plugin output — not knowledge"),
    Rule("loose boot",          "00-START-HERE.md",            "",          "boot",     "rename:TIMMY-BOOT.md"),
    Rule("loose diamond gw",    "DiamondMemory Gateway.md",    "wiki",      "wiki",     "rename:diamondmemory-gateway.md"),
    # Catch-all: anything not matched above goes to _archive/unmatched/ with
    # the original subpath preserved. Beats silent loss; lets us audit.
    Rule("unmatched fallthrough", "**/*.md",                   "_archive/unmatched",  None, "preserve_subpath",
         description="Anything not matched by a more specific rule"),
]


IDENTITY_RULES: list[Rule] = [
    Rule("identity template",   "IDENTITY.md",                 None,        None,       "preserve_name",
         description="Empty unfilled template at root — drop"),
    Rule("user entity",         "USER.md",                     "entities",  "person",   "rename:entity-user.md"),
    Rule("timmy entity",        "SOUL.md",                     "entities",  "agent",    "rename:entity-timmy.md"),
    Rule("agents wiki",         "AGENTS.md",                   "wiki",      "wiki",     "rename:agents.md"),
    Rule("blueprint",           "BLUEPRINT_INDEX.md",          "wiki",      "wiki",     "rename:blueprint-index.md"),
    Rule("dreams",              "DREAMS.md",                   "wiki",      "wiki",     "rename:dreams.md"),
    Rule("heartbeat",           "HEARTBEAT.md",                "wiki",      "wiki",     "rename:heartbeat.md"),
    Rule("memory protocol",     "MEMORY.md",                   "wiki",      "wiki",     "rename:memory-protocol.md"),
    Rule("session-end",         "SESSION_END_PROTOCOL.md",     "wiki",      "wiki",     "rename:session-end-protocol.md"),
    Rule("sonnet-brief",        "Sonnet-Brief-Protocol.md",    "wiki",      "wiki",     "rename:sonnet-brief-protocol.md"),
    Rule("tools wiki",          "TOOLS.md",                    "wiki",      "wiki",     "rename:tools.md"),
    Rule("agent/ superseded",   "agent/*.md",                  "_archive/agent-old",  None,    "preserve_name",
         description="Older filled-in versions of root identity files — archive as superseded"),
    Rule("brain lessons",       "brain/lessons/*.md",          "wiki/lessons",        "wiki",  "preserve_name"),
    Rule("brain other",         "brain/**/*.md",               "wiki",                "wiki",  "preserve_subpath"),
    Rule("memory sessions",     "memory/*.md",                 "sessions",            "session", "date_prefixed",
         description="Historical session-end snapshots from Timmy's memory dir"),
    Rule("dreaming deep",       "memory/dreaming/deep/*.md",   "LearningLayer",       "learning-signals", "rename:signals-{stem}-deep.md",
         description="Pattern-4 consolidator output — durable reflections"),
    Rule("dreaming rem",        "memory/dreaming/rem/*.md",    "LearningLayer",       "learning-signals", "rename:signals-{stem}-rem.md"),
    Rule("dreaming light",      "memory/dreaming/light/*.md",  "LearningLayer",       "learning-signals", "rename:signals-{stem}-light.md"),
    Rule("sessions dir",        "sessions/**/*.md",            "sessions",            "session", "date_prefixed"),
    # Catch-all
    Rule("unmatched fallthrough", "**/*.md",                   "_archive/unmatched",  None,    "preserve_subpath"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Plan only, do not write")
    parser.add_argument("--apply", action="store_true", help="Actually write to destination")
    parser.add_argument("--dest", default=str(HOME / "Documents" / "TimmyMemory-v2"),
                        help="Destination vault root")
    args = parser.parse_args()

    if not (args.dry_run or args.apply):
        parser.error("Pass --dry-run or --apply")

    dest_root = pathlib.Path(args.dest).expanduser()
    apply = args.apply

    if apply and dest_root.exists():
        print(f"ERROR: destination already exists: {dest_root}", file=sys.stderr)
        print("Refusing to overwrite. Move it aside or pass --dest <other-path>.", file=sys.stderr)
        return 1

    print(f"Source 1: ~/Documents/TimmyMemory/    ({len(TIMMYMEMORY_RULES)} rules)")
    print(f"Source 2: ~/.openclaw/agents/timmy/   ({len(IDENTITY_RULES)} rules)")
    print(f"Dest:     {dest_root}")
    print(f"Mode:     {'APPLY (writing)' if apply else 'DRY-RUN (no writes)'}")
    print()

    report = Report()

    walk_source(HOME / "Documents" / "TimmyMemory", "TimmyMemory",
                TIMMYMEMORY_RULES, dest_root, report, apply)
    walk_source(HOME / ".openclaw" / "agents" / "timmy", "agent-timmy",
                IDENTITY_RULES, dest_root, report, apply)

    report.print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
