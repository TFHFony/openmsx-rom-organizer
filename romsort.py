#!/usr/bin/env python3
"""
openMSX system ROM organizer.

Place this script in a folder containing your loose/unsorted ROM dumps
(subfolders are fine, it scans recursively) and run it. It downloads the
machine and extension config files from the openMSX GitHub repo, uses the
SHA1 hashes declared in them to identify each ROM file, and sorts matches
into a "systemroms" folder it creates next to the script - renamed to the
filename openMSX expects, under systemroms/machines or
systemroms/extensions. Anything that doesn't match a known hash is moved
into a "Non-Match" folder instead.

This only concerns the *system* ROMs openMSX needs to emulate machines and
extensions (BIOS, sub-ROMs, disk ROMs, cartridge firmware, etc.) - it has
nothing to do with game ROMs / software list entries.

This script never touches an existing openMSX installation or systemroms
folder - it only creates and writes inside its own folder.

Usage:
    python romsort.py                 sort ROMs found next to this script
    python romsort.py --dry-run       preview without moving/renaming anything
    python romsort.py --copy          copy instead of move (source untouched)
    python romsort.py --refresh-cache force re-download of the config files
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

GITHUB_API_CONTENTS = "https://api.github.com/repos/openMSX/openMSX/contents/{path}?ref=master"
CACHE_DIRNAME = ".openmsx_config_cache"
OUTPUT_SYSTEMROMS = "systemroms"
OUTPUT_NONMATCH = "Non-Match"

# (github path, cache subfolder name, destination subdir under systemroms/)
# C-BIOS's configs live under Contrib/cbios in the repo rather than
# share/machines (they get copied into share/machines at release-packaging
# time), so it's pulled in separately here and merged into "machines".
CONFIG_SOURCES = [
    ("share/machines", "machines", "machines"),
    ("share/extensions", "extensions", "extensions"),
    ("Contrib/cbios", "contrib_cbios", "machines"),
]


@dataclass
class RomTarget:
    subdir: str          # "machines" or "extensions"
    filename: str        # canonical filename from the config
    config_name: str     # which .xml file declared it (for logging)


@dataclass
class HashDB:
    by_sha1: dict[str, list[RomTarget]] = field(default_factory=dict)

    def add(self, sha1: str, target: RomTarget) -> None:
        targets = self.by_sha1.setdefault(sha1.lower(), [])
        if not any(t.subdir == target.subdir and t.filename == target.filename for t in targets):
            targets.append(target)


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "romsort.py (openMSX ROM organizer)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def list_github_xml_files(github_path: str) -> list[tuple[str, str]]:
    """Returns [(filename, download_url), ...] for *.xml files at github_path on GitHub."""
    url = GITHUB_API_CONTENTS.format(path=github_path)
    data = json.loads(http_get(url))
    return [
        (entry["name"], entry["download_url"])
        for entry in data
        if entry.get("type") == "file" and entry["name"].lower().endswith(".xml")
    ]


def ensure_config_cache(cache_dir: Path, refresh: bool) -> None:
    have_cache = all((cache_dir / cache_name).is_dir() and any((cache_dir / cache_name).glob("*.xml"))
                      for _, cache_name, _ in CONFIG_SOURCES)
    if have_cache and not refresh:
        print(f"Using cached openMSX configs in {cache_dir} (use --refresh-cache to update)")
        return

    print("Downloading machine/extension configs from the openMSX GitHub repo...")
    for github_path, cache_name, _dest_subdir in CONFIG_SOURCES:
        target = cache_dir / cache_name
        target.mkdir(parents=True, exist_ok=True)
        try:
            entries = list_github_xml_files(github_path)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            print(f"error: could not fetch {github_path} listing from GitHub: {e}", file=sys.stderr)
            raise SystemExit(1)
        for name, download_url in entries:
            try:
                content = http_get(download_url)
            except (urllib.error.URLError, urllib.error.HTTPError) as e:
                print(f"  ! failed to download {github_path}/{name}: {e}", file=sys.stderr)
                continue
            (target / name).write_bytes(content)
        print(f"  {github_path}: {len(entries)} config files")


def build_hash_db(cache_dir: Path) -> HashDB:
    db = HashDB()
    for _github_path, cache_name, dest_subdir in CONFIG_SOURCES:
        folder = cache_dir / cache_name
        if not folder.is_dir():
            continue
        for xml_path in sorted(folder.glob("*.xml")):
            try:
                tree = ET.parse(xml_path)
            except ET.ParseError as e:
                print(f"  ! skipping unparsable config {xml_path.name}: {e}", file=sys.stderr)
                continue
            for rom_el in tree.getroot().iter("rom"):
                filename_el = rom_el.find("filename")
                if filename_el is None or not (filename_el.text or "").strip():
                    continue
                filename = filename_el.text.strip()
                target = RomTarget(subdir=dest_subdir, filename=filename, config_name=xml_path.name)
                for sha1_el in rom_el.findall("sha1"):
                    sha1 = (sha1_el.text or "").strip().lower()
                    if sha1:
                        db.add(sha1, target)
    return db


def iter_scan_files(root: Path, exclude_dirs: set[Path], self_path: Path):
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if path == self_path:
            continue
        if any(excluded in path.parents or excluded == path for excluded in exclude_dirs):
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() == ".xml":
            continue
        yield path


def unique_dest(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    n = 2
    while True:
        candidate = dest.with_name(f"{stem}_{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def place_file(src: Path, dest: Path, move: bool, dry_run: bool) -> str:
    if dest.exists():
        if sha1_of(dest) == sha1_of(src):
            return "duplicate, already sorted - left in place"
        dest = unique_dest(dest)

    if dry_run:
        return f"would {'move' if move else 'copy'} -> {dest}"

    dest.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(src), str(dest))
    else:
        shutil.copy2(str(src), str(dest))
    return f"{'moved' if move else 'copied'} -> {dest}"


def remove_empty_dirs(root: Path, exclude_dirs: set[Path]) -> None:
    """Delete now-empty subfolders left behind by moved-out files (deepest first)."""
    dirs = [p for p in root.rglob("*") if p.is_dir() and p not in exclude_dirs
            and not any(ex in p.parents for ex in exclude_dirs)]
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass  # not empty (still has files or non-empty subfolders)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=None,
                     help="Folder to scan for loose ROM files (default: the folder this script lives in).")
    ap.add_argument("--copy", action="store_true",
                     help="Copy files instead of moving them (default: move, source is relocated).")
    ap.add_argument("--dry-run", action="store_true",
                     help="Show what would happen without touching any files.")
    ap.add_argument("--refresh-cache", action="store_true",
                     help="Force re-download of the config XML files from GitHub instead of using the local cache.")
    args = ap.parse_args()

    self_path = Path(__file__).resolve()
    root: Path = (args.root or self_path.parent).resolve()
    cache_dir = self_path.parent / CACHE_DIRNAME
    systemroms_dir = root / OUTPUT_SYSTEMROMS
    nonmatch_dir = root / OUTPUT_NONMATCH

    if not root.is_dir():
        print(f"error: --root folder not found: {root}", file=sys.stderr)
        return 1

    ensure_config_cache(cache_dir, refresh=args.refresh_cache)

    print("Parsing config hashes...")
    db = build_hash_db(cache_dir)
    print(f"  loaded {len(db.by_sha1)} known ROM hashes")

    exclude_dirs = {systemroms_dir, nonmatch_dir, cache_dir, root / ".git"}
    move = not args.copy

    matched = 0
    duplicates = 0
    unmatched = 0

    print(f"\nScanning {root} ...\n")
    for src in iter_scan_files(root, exclude_dirs, self_path):
        try:
            digest = sha1_of(src)
        except OSError as e:
            print(f"  ! could not read {src}: {e}", file=sys.stderr)
            continue

        rel = src.relative_to(root)
        targets = db.by_sha1.get(digest)
        if targets:
            # A hash can map to more than one target (referenced by several
            # configs). Move (relocate) on the first target only; further
            # targets get a copy from that new location, since the original
            # is gone after a move.
            current = src
            for i, target in enumerate(targets):
                do_move = move and i == 0
                dest = systemroms_dir / target.subdir / target.filename
                status = place_file(current, dest, move=do_move, dry_run=args.dry_run)
                if "duplicate" in status:
                    tag, duplicates = "=", duplicates + 1
                else:
                    tag, matched = "+", matched + 1
                    if do_move and not args.dry_run:
                        current = dest
                print(f"  [{tag}] {rel}  (matches {target.config_name})  {status}")
        else:
            dest = nonmatch_dir / rel
            status = place_file(src, dest, move=move, dry_run=args.dry_run)
            print(f"  [?] {rel}  no hash match -> Non-Match  {status}")
            unmatched += 1

    if move and not args.dry_run:
        remove_empty_dirs(root, exclude_dirs)

    print()
    print(f"Done. matched={matched} duplicates-left-in-place={duplicates} unmatched={unmatched}"
          + ("  (dry run, nothing changed)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
