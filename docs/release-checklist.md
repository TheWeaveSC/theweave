# Release checklist

The workflow to cut a tagged release of TheWeave that the installer can fetch.

## Pre-release

- [ ] All intended changes committed on `main`
- [ ] [`CHANGELOG.md`](../CHANGELOG.md) `[Unreleased]` section moved to the new version's heading
- [ ] [`pyproject.toml`](../pyproject.toml) `version = "X.Y.Z"` bumped
- [ ] `README.md` version badge bumped (line with `version-X.Y.Z-orange`)
- [ ] `install-weave.sh` default `WEAVE_VERSION="X.Y.Z"` bumped
- [ ] `weave-cli doctor` green on `seed-vault/` and `personas/sonnet/`
- [ ] `pytest` passes

## Tag + push

```bash
git add -p   # review hunks
git commit -m "Release vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z — <one-line summary>"
git push origin main vX.Y.Z
```

## GitHub release

The auto-generated source tarball at `/archive/refs/tags/vX.Y.Z.tar.gz` is what `install-weave.sh` downloads — it's created automatically when the tag is pushed and requires no manual upload. The installer itself also needs to be attached as a release asset so users can fetch it from `/releases/latest/download/install-weave.sh`.

**This is now automated.** Pushing a `vX.Y.Z` tag triggers [`.github/workflows/release.yml`](../.github/workflows/release.yml), which creates the release (with generated notes) if it doesn't exist and attaches `install-weave.sh`.

- [ ] **Verify the asset attached** after the tag push — the workflow run is green AND `gh release view vX.Y.Z --json assets -q '.assets[].name'` lists `install-weave.sh`.

Manual fallback (if the workflow is unavailable, or you rewrote the tag without re-triggering it — e.g. a force-pushed tag):

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes-file <(awk '/^## \['"X.Y.Z"'\]/,/^## \[/' CHANGELOG.md | head -n -1) \
  install-weave.sh
# or, if the release already exists:
gh release upload vX.Y.Z install-weave.sh --clobber
```

## Smoke-test the public install

From a clean machine (or VM), with no clone of the repo:

```bash
curl -sSL https://github.com/TheWeaveSC/theweave/releases/latest/download/install-weave.sh | bash
```

Should:
1. Pass preflight (Python ≥3.11, curl, tar)
2. Download tarball from `/archive/refs/tags/vX.Y.Z.tar.gz`
3. Create venv, install package
4. Symlink `weave-cli` into `~/.local/bin/` if on PATH
5. Run `weave-cli doctor` — all green

If any step fails, the user sees the failure point and the script exits non-zero.

## Visibility note

The auto-generated `/archive/refs/tags/` tarball is **public-readable only if the repo is public**. While the repo is private, the install path will not work for outside testers — even with the install script in hand. The public flip and the install path are coupled.
