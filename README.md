# openMSX ROM file organizer

Scans a folder of loose/unsorted ROM dumps and sorts the ones openMSX
recognizes into your `systemroms` folder, renamed to the filename openMSX's
machine/extension configs expect. Anything that doesn't match a known hash
goes into `systemroms/misc` for manual triage.

This is only for **system** ROMs (BIOS, sub-ROMs, disk ROMs, cartridge
firmware, etc. needed to emulate a machine or extension) — not game ROMs.

## How it works

openMSX itself matches files in `systemroms` purely by SHA1 content hash —
the filename is irrelevant to openMSX. The hashes and their canonical
filenames are declared in `<rom><sha1>...</sha1><filename>...</filename></rom>`
blocks inside the machine/extension config XML files. This tool reads those
XML files, hashes every file in your scan folder, and on a match copies (or
moves) the file into `systemroms/<machines|extensions>/<canonical filename>`
purely for human-readable organization.

It expects `--systemroms` to be a folder that already contains the config
XML files inside `machines/` and `extensions/` subfolders (as copied from
openMSX's own `share/machines` and `share/extensions`) alongside the actual
ROM binaries — the same layout openMSX ships and that this tool's target
folder already uses.

## Usage

```bash
python romsort.py --systemroms "F:\Shared Documents\openMSX\share\systemroms" --scan "C:\path\to\loose\roms"
```

Options:

- `--move` — move matched files instead of copying (default: copy, source
  files are left untouched).
- `--dry-run` — preview what would happen without touching any files.
- `--no-misc` — don't relocate unmatched files into `systemroms/misc`, just
  report them.

Run with `--dry-run` first to review the plan before letting it touch files.

## Known limitation

A handful of openMSX's shipped config XML files aren't strictly
well-formed XML (e.g. a mismatched closing tag in
`FAC_MIDI_Interface.xml`, or a tag name starting with a digit like
`<3bitrgboutput/>` in `Fujitsu_FM-X.xml`). Files whose only matching config
is one of these get skipped with a warning and won't be recognized until
the XML is fixed upstream.
