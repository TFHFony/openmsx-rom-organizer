# openMSX ROM file organizer

Drop `romsort.py` into a folder containing your loose/unsorted ROM dumps
(subfolders are fine, it scans recursively) and run it. It downloads the
machine and extension configs from the [openMSX GitHub repo](https://github.com/openMSX/openMSX),
uses the SHA1 hashes declared in them to identify each ROM file, and sorts
matches into a `systemroms` folder it creates right there — renamed to the
filename openMSX expects, under `systemroms/machines` or
`systemroms/extensions`. Anything that doesn't match a known hash is moved
into a `Non-Match` folder instead (keeping its original relative subfolder
path, so nothing collides or gets lost).

This is only for **system** ROMs (BIOS, sub-ROMs, disk ROMs, cartridge
firmware, etc. needed to emulate a machine or extension) — not game ROMs.

**This script never touches an existing openMSX installation.** It only
reads from GitHub and writes inside its own folder. Once you're happy with
the result, copy the generated `systemroms` folder's contents into your
real openMSX `share/systemroms`.

## How it works

openMSX itself matches files in `systemroms` purely by SHA1 content hash —
the filename is irrelevant to openMSX. The hashes and their canonical
filenames are declared in `<rom><sha1>...</sha1><filename>...</filename></rom>`
blocks inside the machine/extension config XML files. This tool downloads
those files from `share/machines`, `share/extensions`, and `Contrib/cbios`
(the C-BIOS configs live there instead of `share/machines` in the repo,
copied into a release's `share/machines` at packaging time) on the openMSX
GitHub repo, hashes every file in your ROM folder, and on a match
copies/renames the file into the right spot.

Downloaded configs are cached in `.openmsx_config_cache` next to the
script, so re-runs work offline. Use `--refresh-cache` to pull the latest
versions again.

## Usage

```bash
python romsort.py
```

Options:

- `--root PATH` — folder to scan (default: the folder this script lives in).
- `--copy` — copy files instead of moving them (default: move).
- `--dry-run` — preview what would happen without touching any files.
- `--refresh-cache` — force re-download of the config XML files from GitHub.

Run with `--dry-run` first to review the plan before letting it touch files.

## Known limitation

A handful of openMSX's config XML files aren't strictly well-formed XML
(e.g. a mismatched closing tag in `FAC_MIDI_Interface.xml`). Files whose
only matching config is one of these get skipped with a warning and won't
be recognized until the XML is fixed upstream.
