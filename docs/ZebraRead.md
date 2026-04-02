# ZebraRead.py - Zebra CPC DSK Disk Image Extractor

## Overview

`ZebraRead.py` analyzes and extracts files from Zebra-format disk images for the
Timex/Sinclair 2068. It handles both **DIRSCP** (hierarchical) and **CP/M**
(flat) directory structures, auto-detecting which is present. DIRSCP disks
support full file extraction; CP/M disks support catalog display.

Unlike the Larken and Oliger scripts, ZebraRead does **not** convert files to TAP
format. Zebra disks use a CP/M-derived filesystem rather than the ZX Spectrum
tape-style file model, so files are extracted in their native format.

## Usage

```
python3 ZebraRead.py -f <dsk_file> [-c] [-s <filename>] [-o <output_dir>] [-v]
```

**Arguments:**
- `-f`, `--imgfile` - Path to the Zebra .dsk disk image file (required)
- `-c`, `--cat` - Display the disk catalog without extracting files
- `-s`, `--specific` - Extract only the named file
- `-o`, `--outdir` - Output directory (default: filename without extension)
- `-v`, `--verbose` - Show detailed scanning and sector-level operations

**Examples:**
```
python3 ZebraRead.py -f zebra.dsk -c              # Show catalog
python3 ZebraRead.py -f zebra.dsk                  # Extract all files (DIRSCP)
python3 ZebraRead.py -f zebra.dsk -s "LETTER"      # Extract one file
python3 ZebraRead.py -f zebra3.dsk -c              # Catalog CP/M disk
python3 ZebraRead.py -f zebra.dsk -o output -v     # Extract with verbose output
```

## Output

Extracted files are saved as raw binary with their original filenames (sanitized
for the host filesystem). The disk's subdirectory structure is preserved:

```
output/
  ZEBRA/
    LETTER.TXT
    MS5Z.COD
    ...
  CH_A.SCP
  CH_B.SCP
  manifest.md
```

When two or more files share the same name, the second and subsequent files
receive a numeric suffix: `file`, `file_2`, `file_3`, etc.

- **`manifest.md`** - A Markdown file listing disk metadata and a table mapping
  each original filename to its extracted filename and size.

## Two Format Modes

**DIRSCP Format:** Detected when "DIRSCP" is found at offset 0x2880. Supports
hierarchical directories and full file extraction. Uses marker-based directory
entries (0xFF=root, 0x80=subdir, 0x01=file) with 8-character filenames +
3-character extensions.

**CP/M Format:** Fallback when no DIRSCP marker is found. Supports catalog
display only (extraction not implemented). Uses standard CP/M directory entries
(32 bytes each) with user numbers, extents, and record counts.

---

## Zebra Disk Format

### Container Format: Extended CPC DSK

Zebra disk images use the **Extended CPC DSK** format, originally designed for
Amstrad CPC disk images. This is a container format with a global header
followed by per-track data.

#### CPC DSK Global Header (256 bytes)

| Offset  | Size | Description                                       |
|---------|------|---------------------------------------------------|
| 0x00    | 16   | Magic: `"EXTENDED CPC DSK"` (or `"MV - CPCEMU"`) |
| 0x22    | 14   | Creator name (e.g., `"CPCDiskXP v2.5"`)           |
| 0x30    | 1    | Number of tracks                                  |
| 0x31    | 1    | Number of sides                                   |
| 0x34    | var  | Track size table (1 byte per track, high byte of size) |

In the Extended format, each track can have a different size. The track size
table at offset 0x34 contains the high byte of each track's size (the actual
size is this value * 256).

#### Track Layout

Each track in the image begins with a 256-byte **Track Information Block**
followed by the sector data:

| Offset | Size | Description                           |
|--------|------|---------------------------------------|
| 0x00   | 12   | Magic: `"Track-Info\r\n"`             |
| 0x10   | 1    | Track number                          |
| 0x11   | 1    | Side number                           |
| 0x14   | 1    | Sector size code (2 = 512, 1 = 256)   |
| 0x15   | 1    | Number of sectors                     |
| 0x16   | 1    | GAP3 length                           |
| 0x17   | 1    | Filler byte                           |
| 0x18+  | 8*N  | Sector information list               |

After the 256-byte header, the actual sector data follows sequentially.

### Zebra Disk Parameters

| Parameter            | Value                              |
|----------------------|------------------------------------|
| Tracks               | 40 (standard), up to 80 (QD)       |
| Sides                | 1 (typical for Zebra)              |
| Sectors per track    | 16                                 |
| Bytes per sector     | 256                                |
| Track data size      | 4,096 bytes (16 * 256)             |
| Track total size     | 4,352 bytes (256 header + 4,096)   |
| Allocation unit      | 1,024 bytes (4 sectors)            |

In the image file, each track occupies 0x1100 (4,352) bytes: a 0x100 (256) byte
track header followed by 0x1000 (4,096) bytes of sector data.

### Sector Interleaving (Track Skew)

Sectors within a track are not stored in sequential order. The Zebra system
uses a 16-sector interleave table (derived from the Tomato C++ implementation)
to map logical sector numbers to physical positions:

```
Logical:   0   1   2   3   4   5   6   7   8   9  10  11  12  13  14  15
Physical:  0   7  14   5  12   3  10   1   8  15   6  13   4  11   2   9
```

When reading file data, sectors must be read in the skewed order to reconstruct
the correct byte sequence. If the skewed read produces all-zero data (suggesting
the skew table doesn't apply to this particular disk), the script falls back to
sequential sector reading.

### DIRSCP Directory Format

The DIRSCP (Directory SCP) format provides a hierarchical directory system
on top of the CPC DSK container. It is identified by the string `"DIRSCP"`
at offset 0x2880 in the disk image.

#### Root Directory

The root directory begins at offset 0x2880 with a DIRSCP header, followed by
directory entries starting at offset 0x28A8 (0x2880 + 0x28). Entries are
scanned byte-by-byte looking for marker bytes.

#### Directory Entry Format (32 bytes)

| Offset | Size | Description                                        |
|--------|------|----------------------------------------------------|
| 0      | 1    | Entry marker (see below)                           |
| 1-8    | 8    | Filename (ASCII, space-padded)                     |
| 9-11   | 3    | File extension / type (ASCII, e.g., `"DIR"`, `"TXT"`, `"COD"`) |
| 12     | 1    | Part number (for multi-part files)                 |
| 13     | 1    | Tail bytes (remaining bytes in last sector)        |
| 14     | 1    | Size high byte                                     |
| 15     | 1    | Size low byte                                      |
| 16-31  | 16   | Allocation unit list (track numbers)               |

**Entry markers:**

| Marker | Value | Meaning                                          |
|--------|-------|--------------------------------------------------|
| 0xFF   | 255   | Root-level directory entry                       |
| 0x80   | 128   | Subdirectory entry                               |
| 0x01   | 1     | Regular file entry                               |
| 0xE5   | 229   | Unused/deleted entry                             |

**File attributes** are encoded in the high bits of the extension bytes:
- Bit 7 of extension byte 0: Read-only flag
- Bit 7 of extension byte 1: Hidden flag

**Size calculation:**
The file size in sectors is `(size_hi << 8) | size_lo`. The allocation unit list
(bytes 16-31) contains the track numbers where the file's data is stored. Values
of 0 or >= 160 are filtered out as invalid.

#### Subdirectory Structure

Directories listed in the root (with type `"DIR"`) have their contents stored
elsewhere on the disk. The script scans from offset 0x3000 onward, looking for
32-byte entries that match the directory name. Subdirectory content areas contain
their own set of file entries using the same 32-byte format.

### CP/M Directory Format

Some Zebra disks use a standard CP/M flat directory instead of DIRSCP. These
are identified by the absence of the "DIRSCP" marker at 0x2880. CP/M directory
entries are 32 bytes each, stored at fixed 32-byte intervals:

| Offset | Size | Description                              |
|--------|------|------------------------------------------|
| 0      | 1    | User number (0x00 = active, 0xE5 = deleted) |
| 1-8    | 8    | Filename (ASCII, space-padded)           |
| 9-11   | 3    | Extension (ASCII, space-padded)          |
| 12     | 1    | Extent number                            |
| 13-14  | 2    | Reserved                                 |
| 15     | 1    | Record count (128-byte records in this extent) |
| 16-31  | 16   | Allocation block numbers                 |

CP/M files can span multiple extents (extent 0, 1, 2, ...), with each extent
having its own directory entry and allocation block list. The total file size
is the sum of all extents' record counts times 128 bytes.

---

## Differences: DIRSCP vs CP/M Zebra Disks

| Feature              | DIRSCP                          | CP/M                              |
|----------------------|---------------------------------|-----------------------------------|
| Directory marker     | "DIRSCP" at 0x2880              | No marker (standard CP/M)         |
| Directory structure  | Hierarchical (subdirectories)   | Flat (all files at root)           |
| Entry markers        | 0xFF/0x80/0x01 per entry        | User number (0x00/0xE5)            |
| Entry size           | 32 bytes (variable position)    | 32 bytes (fixed 32-byte intervals) |
| File attributes      | Hidden, read-only in extension  | Standard CP/M attributes           |
| Typical contents     | TS-2068 programs, documents     | CP/M programs (WordStar, MBASIC)   |
| Extraction support   | Full                            | Catalog only                       |

---

## Differences from Larken and Oliger Formats

| Feature              | Larken (LKDOS)       | Oliger (JLO SAFE)     | Zebra                    |
|----------------------|----------------------|-----------------------|--------------------------|
| Image format         | Raw IMG              | Raw IMG               | Extended CPC DSK         |
| Sector size          | 512 bytes            | 512 bytes             | 256 bytes                |
| Block/track size     | 5,120 bytes          | 5,120 bytes           | 4,096 bytes (data only)  |
| Filesystem           | Custom (LKDOS)       | Custom (JLO SAFE)     | CP/M-derived             |
| Directory type       | Marker-delimited     | Fixed entries         | DIRSCP or CP/M           |
| Subdirectories       | No                   | No                    | Yes (DIRSCP only)        |
| File type storage    | Filename extension   | Directory field       | Directory field           |
| Output format        | TAP (tape emulation) | TAP (tape emulation)  | Native (raw binary)      |
| Sector interleaving  | None in image        | None in image         | 16-sector skew table     |

## Changes from ZebraExtract.py / ZebraRead.py

1. **Combined into single script**: The separate `ZebraExtract.py` (extraction
   only) and `ZebraRead.py` (analysis only) have been merged into a unified
   `ZebraRead.py` that handles both catalog display and file extraction, matching
   the interface pattern of the other tools (LarkenRead, OligerRead, QLRead).
2. **Auto-format detection**: Automatically detects DIRSCP vs CP/M and handles
   each appropriately.
3. **Specific file extraction**: Added `-s` flag to extract a single file by
   name.
4. **Extraction manifest**: Writes a `manifest.md` to the output directory.
5. **Duplicate filename handling**: Uses `_2`, `_3` suffixes for collisions.
