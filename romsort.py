#!/usr/bin/env python3
"""
openMSX system ROM organizer.

Scans a folder of loose/unsorted ROM dumps, matches each file against the
SHA1 hashes declared in openMSX's machine and extension config files, then
renames and sorts matches into the systemroms/machines and
systemroms/extensions folders using the filename openMSX expects. Anything
that doesn't match a known hash is moved into systemroms/misc for manual
triage later.

This only concerns the *system* ROMs openMSX needs to emulate machines and
extensions (BIOS, sub-ROMs, disk ROMs, cartridge firmware, etc.) - it has
nothing to do with game ROMs / software list entries.

openMSX itself only cares about SHA1 content matches inside systemroms (the
"file name is irrelevant" per its own README) - the renaming this tool does
is purely for human-readable organization, mirroring how the config XML
files describe each ROM.

Usage:
    python romsort.py --systemroms "F:\\Shared Documents\\openMSX\\share\\systemroms" --scan "C:\\some\\folder\\with\\loose\\roms"

    Add --move to move files instead of copying (default is copy, source
    files are left untouched). Add --dry-run to preview without touching
    any files.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RomTarget:
    subdir: str          # "machines" or "extensions"
    filename: str        # canonical filename from the config
    config_name: str     # which .xml file declared it (for logging)


@dataclass
class HashDB:
    # sha1 (lowercase hex) -> list of possible targets (usually just one)
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


def build_hash_db(config_dir: Path) -> HashDB:
    """Parse every *.xml in config_dir/machines and config_dir/extensions
    for <rom><sha1>...</sha1><filename>...</filename></rom> blocks.
    A single <rom> block may list several <sha1> tags (alternate dumps)
    that all map to the same <filename>.
    """
    db = HashDB()
    for subdir in ("machines", "extensions"):
        folder = config_dir / subdir
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
                target = RomTarget(subdir=subdir, filename=filename, config_name=xml_path.name)
                for sha1_el in rom_el.findall("sha1"):
                    sha1 = (sha1_el.text or "").strip().lower()
                    if sha1:
                        db.add(sha1, target)
    return db


def iter_scan_files(scan_dir: Path):
    for path in sorted(scan_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() != ".xml":
            yield path


def place_file(src: Path, dest: Path, move: bool, dry_run: bool) -> str:
    """Copy/move src to dest. Returns a short status string."""
    if dest.exists():
        if sha1_of(dest) == sha1_of(src):
            return "already present"
        # Same target filename, different content - don't clobber silently.
        stem, suffix = dest.stem, dest.suffix
        n = 2
        while dest.with_name(f"{stem}_conflict{n}{suffix}").exists():
            n += 1
        dest = dest.with_name(f"{stem}_conflict{n}{suffix}")

    if dry_run:
        return f"would {'move' if move else 'copy'} -> {dest}"

    dest.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(src), str(dest))
    else:
        shutil.copy2(str(src), str(dest))
    return f"{'moved' if move else 'copied'} -> {dest}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--systemroms", required=True, type=Path,
                     help="Path to openMSX's share/systemroms folder (must contain machines/ and extensions/ subfolders with the config .xml files copied in, e.g. from openMSX's share/machines and share/extensions).")
    ap.add_argument("--scan", required=True, type=Path,
                     help="Folder to scan for loose/unsorted ROM files (searched recursively).")
    ap.add_argument("--move", action="store_true",
                     help="Move matched files instead of copying them (default: copy, leave source untouched).")
    ap.add_argument("--dry-run", action="store_true",
                     help="Show what would happen without touching any files.")
    ap.add_argument("--no-misc", action="store_true",
                     help="Don't move unmatched files into systemroms/misc; just report them.")
    args = ap.parse_args()

    systemroms: Path = args.systemroms
    scan_dir: Path = args.scan
    misc_dir = systemroms / "misc"

    if not systemroms.is_dir():
        print(f"error: --systemroms folder not found: {systemroms}", file=sys.stderr)
        return 1
    if not scan_dir.is_dir():
        print(f"error: --scan folder not found: {scan_dir}", file=sys.stderr)
        return 1

    print(f"Reading config hashes from {systemroms}\\machines and {systemroms}\\extensions ...")
    db = build_hash_db(systemroms)
    print(f"  loaded {len(db.by_sha1)} known ROM hashes")

    matched = 0
    unmatched = 0
    skipped = 0

    for src in iter_scan_files(scan_dir):
        try:
            digest = sha1_of(src)
        except OSError as e:
            print(f"  ! could not read {src}: {e}", file=sys.stderr)
            continue

        targets = db.by_sha1.get(digest)
        if targets:
            # A hash can map to more than one target (e.g. referenced by
            # several configs). Move (relocate) on the first target only;
            # any further targets get a copy from that new location, since
            # the original source is gone after a move.
            current = src
            for i, target in enumerate(targets):
                do_move = args.move and i == 0
                dest = systemroms / target.subdir / target.filename
                status = place_file(current, dest, move=do_move, dry_run=args.dry_run)
                if do_move and not args.dry_run and "already" not in status:
                    current = dest
                tag = "=" if "already" in status else "+"
                print(f"  [{tag}] {src.name}  (matches {target.config_name})  {status}")
                if "already" in status:
                    skipped += 1
                else:
                    matched += 1
        elif not args.no_misc:
            dest = misc_dir / src.name
            status = place_file(src, dest, move=args.move, dry_run=args.dry_run)
            print(f"  [?] {src.name}  no hash match -> misc  {status}")
            unmatched += 1
        else:
            print(f"  [?] {src.name}  no hash match (left in place)")
            unmatched += 1

    print()
    print(f"Done. matched={matched} already-sorted={skipped} unmatched={unmatched}"
          + ("  (dry run, nothing changed)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
