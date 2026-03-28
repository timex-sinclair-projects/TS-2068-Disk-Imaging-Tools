# OligerRead.py - Oliger/JLO SAFE Disk Image Extractor

## Overview

`OligerRead.py` extracts files from raw disk images of floppy disks formatted
by the Oliger disk interface with JLO SAFE (Save And File Everything) software
for the Timex/Sinclair 2068 computer. It reads the JLO directory structure,
extracts individual files, and converts them to the ZX Spectrum TAP tape format
for use in emulators. Full-memory ABS state saves are detected automatically and
saved as both raw dumps and launchable TAP files.

## Usage

```
python3 OligerRead.py -f <image_file> [-c] [-s <filename>]
```

**Arguments:**
- `-f`, `--imgfile` - Path to the Oliger .img disk image file (required)
- `-c`, `--cat` - Display the disk catalog without extracting files
- `-s`, `--specific` - Extract only the named file

**Examples:**
```
python3 OligerRead.py -f mydisk.img -c              # Show catalog
python3 OligerRead.py -f mydisk.img                  # Extract all files
python3 OligerRead.py -f mydisk.img -s "multibase"   # Extract one file
```

## Output

Extracted files are placed in a subdirectory named after the image file (without
extension). Each file is saved as one of:

- **`.tap`** - Standard ZX Spectrum TAP format, loadable in any Spectrum/TS-2068
  emulator. Contains a proper TAP header with file type, filename, load address,
  and parameters, followed by the file data with XOR checksums.

- **`.dump`** + **`.tap`** (for ABS state saves) - The `.dump` file contains the
  raw memory contents (48.5K from 0x3E00-0xFFFF). The `.tap` file contains a
  BASIC loader program that will load the machine code into the correct memory
  location and execute it. The loader does: `CLEAR <ramtop>`, `LOAD ""CODE`,
  `RANDOMIZE USR <entry>`.

Filenames are sanitized for the host filesystem. Characters outside
`[A-Za-z0-9~ -_.]` are stripped (e.g., `L/Print` becomes `LPrint`, `M*5` becomes
`M5`). The original filename is preserved inside the TAP header.

When two or more files on the disk share the same name (e.g., a BASIC loader and
its CODE companion both called `mscript5.5`), the second and subsequent files
receive a numeric suffix: `mscript5.5.tap`, `mscript5.5_2.tap`, etc.

- **`manifest.md`** - A Markdown file written to the output directory after
  extraction. It records the disk metadata (format, disk name, sides, tracks) and
  a table mapping each original disk filename to its extracted filename(s), file
  type, and size. This is especially useful when filenames were sanitized or
  de-duplicated, since the manifest preserves the link back to the original disk
  contents.

## ABS State Save Detection

Files are classified as ABS (absolute) state saves when all conditions are met:
- File size >= 45,000 bytes
- File type = BASIC (type 0)
- Program length (param2) = 0 (invalid for a real BASIC program)

JLO SAFE's ABS command saves 48.5K of memory from 0x3E00 to 0xFFFF (49,664
bytes), capturing the entire machine state including system variables, BASIC
program area, and all RAM up to the top of memory. When detected, the script
reads RAMTOP from the embedded system variables to find the machine code region
and builds a launchable TAP file.

---

## Oliger/JLO SAFE Disk Format

### Physical Layout

The Oliger disk interface uses a Western Digital FD1771 (single-density) or
FD1791 (double-density) floppy disk controller connected to the TS-2068 via the
Timex command cartridge port. JLO SAFE is the DOS (Disk Operating System) that
runs on this hardware.

Disks are formatted with 10 sectors per track, 512 bytes per sector, giving
5,120 bytes (5K) per track. Storage is organized in units called **cylinders**,
where one cylinder equals one track on one side of the disk (5K).

| Disk Type              | Tracks | Sides | Total Cylinders |
|------------------------|--------|-------|-----------------|
| Double-sided (typical) | 40-42  | 2     | 80-84           |
| Single-sided           | 40     | 1     | 40              |

### Cylinder Numbering and Interleaving

Cylinders are accessed on alternating sides, starting with side 0:

```
Cylinder 0:  Track 0, Side 0  (catalog - reserved)
Cylinder 1:  Track 0, Side 1
Cylinder 2:  Track 1, Side 0
Cylinder 3:  Track 1, Side 1
Cylinder 4:  Track 2, Side 0
Cylinder 5:  Track 2, Side 1
...
```

In the raw image file, data is stored in cylinder order, so the file offset for
cylinder N is simply `N * 5120`. Files are allocated to the outermost cylinders
first, working inward toward the center of the disk.

There is no sector-to-sector skew within a track, but there is a track-to-track
sector skew of 3 sectors to allow for head stepping time. The skew is handled
at the hardware level and is transparent in the image file.

### Cylinder 0 - Catalog

Cylinder 0 (track 0, side 0) is reserved for JLO SAFE's system data and the
file directory. It is never used for file data.

#### Directory Header (offset 0x600, 32 bytes)

The directory metadata starts at offset 0x600 (1536) within cylinder 0:

| Offset | Size | Description                                        |
|--------|------|----------------------------------------------------|
| 0      | 1    | Number of tracks                                   |
| 1      | 1    | Number of sides                                    |
| 2      | 1    | Total cylinders                                    |
| 4      | 1    | Available (free) cylinders                         |
| 16-31  | 16   | Disk name (ASCII, space-padded)                    |

#### Directory Entries (offset 0x620, 20 bytes each)

File entries begin at offset 0x620 (1568) and are fixed-size, 20 bytes each.
Entries continue until a byte with value 0x80 (128) is encountered at the start
of an entry position, marking the end of the directory.

Each 20-byte directory entry has the following structure:

| Offset | Size | Description                                        |
|--------|------|----------------------------------------------------|
| 0-9    | 10   | Filename (ASCII, space-padded to 10 characters)    |
| 10     | 1    | File type code                                     |
| 11-12  | 2    | File size in bytes (little-endian)                 |
| 13-14  | 2    | Autostart line / start address (little-endian)     |
| 15-16  | 2    | Program length or parameter 2 (little-endian)      |
| 17     | 1    | Starting track number                              |
| 18     | 1    | Starting side (0x00 = side 0, 0xFF = side 1)       |
| 19     | 1    | Number of cylinders used by the file               |

The starting cylinder is calculated from bytes 17-18:
```
cylinder = track_number * 2 + (1 if side != 0 else 0)
```

### File Types

Unlike LKDOS, the Oliger format stores the file type explicitly in the
directory entry (byte 10), matching the ZX Spectrum convention:

| Code | Type           | Description                              |
|------|----------------|------------------------------------------|
| 0    | BASIC          | BASIC program with optional auto-run     |
| 1    | Numeric array  | DIM'd numeric array                      |
| 2    | String array   | DIM'd string array                       |
| 3    | CODE           | Machine code / binary data               |

#### Directory Field Usage by File Type

The meaning of the `staline` (bytes 13-14) and `param2` (bytes 15-16) fields
depends on the file type:

| Type  | staline (bytes 13-14)    | param2 (bytes 15-16)       |
|-------|--------------------------|----------------------------|
| BASIC | Auto-start line number   | Program length (vars offset)|
| CODE  | Load/start address       | Application-specific*      |
| Array | (unused)                 | Variable name descriptor   |

*Note: For CODE files, `param2` in the Oliger directory may contain
application-specific data rather than the TAP-standard value of 32768. The
script normalizes this to 32768 when generating TAP output, since emulators
expect this convention.

A `staline` value of 16384 (0x4000) is used by JLO SAFE to indicate "no
auto-start line" for BASIC programs. This value is preserved as-is in the TAP
output. Standard ZX Spectrum convention uses values >= 32768 for this purpose,
but 16384 is functionally equivalent since no BASIC line number that high can
exist (maximum valid line number is 9999).

### File Data Storage

Files are stored in consecutive cylinders starting from the cylinder indicated
in the directory entry. Each cylinder holds up to 5,120 bytes of raw file data
(no per-block headers, unlike LKDOS). The file content is simply the
concatenation of all cylinders, trimmed to the exact file size recorded in the
directory.

For example, a 12,000-byte file would occupy 3 cylinders (3 x 5,120 = 15,360
bytes of disk space), with the last 3,360 bytes of the third cylinder being
unused padding.

### JLO SAFE File Operations

JLO SAFE supports several save modes:

- **Regular SAVE** - Standard file save (BASIC, CODE, or array data) with
  directory entry and type-specific metadata.

- **ABS (Absolute) state save** - Captures 48.5K of memory from address 0x3E00
  to 0xFFFF (49,664 bytes). This is a full machine state snapshot that preserves
  the entire contents of RAM including system variables, the BASIC program,
  variables, machine code, screen memory, and UDG characters. ABS saves are
  stored with file type BASIC (type 0) but have anomalous metadata (param2 = 0)
  that distinguishes them from genuine BASIC programs.

- **VER (Verify)** - Reads back a saved file and compares it against memory to
  verify the save was successful.

---

## TAP Output Format

The ZX Spectrum TAP format consists of sequential data blocks, each preceded by
a 2-byte length field. Files are stored as header+data block pairs.

### TAP Header Block (19 bytes + length prefix)

```
Bytes 0-1:   Block length = 19 (0x13, 0x00)
Byte  2:     Flag = 0x00 (header)
Byte  3:     File type (0=BASIC, 1=NumArray, 2=StrArray, 3=CODE)
Bytes 4-13:  Filename (10 bytes, space-padded)
Bytes 14-15: Data length (little-endian)
Bytes 16-17: Param 1 (little-endian) - see below
Bytes 18-19: Param 2 (little-endian) - see below
Byte  20:    XOR checksum of bytes 2-19
```

**Parameter mapping by file type:**

| Type  | Param 1                | Param 2                    |
|-------|------------------------|----------------------------|
| BASIC | Auto-start line number | Program length (vars offset) |
| CODE  | Start/load address     | 32768 (conventional)        |
| Array | 0                      | Variable name descriptor    |

### TAP Data Block

```
Bytes 0-1:   Block length = data_length + 2
Byte  2:     Flag = 0xFF (data)
Bytes 3-N:   File content
Byte  N+1:   XOR checksum of bytes 2-N
```

---

## Differences Between Oliger and LKDOS Disk Formats

| Feature              | LKDOS (Larken)                    | JLO SAFE (Oliger)                  |
|----------------------|-----------------------------------|------------------------------------|
| Block/cylinder size  | 5,120 bytes (10 x 512 sectors)    | 5,120 bytes (10 x 512 sectors)     |
| Block numbering      | Alternating sides (even=0, odd=1) | Alternating sides (0,1,2,3...)     |
| Directory location   | Block 0, after track map          | Cylinder 0, offset 0x620           |
| Directory format     | Variable-length marker-delimited  | Fixed 20-byte entries              |
| File type storage    | Inferred from filename extension  | Explicit type code in directory    |
| Block allocation     | Listed per-file in directory      | Consecutive cylinders              |
| Data block headers   | 24-byte header per block          | No per-block headers               |
| File metadata        | Stored in data block headers      | Stored in directory entry          |
| Track map            | Explicit free-block table         | Free cylinder count only           |
| Max files per disk   | ~100 (variable)                   | ~56 (fixed entry size)             |
| State save size      | 48K (0x4000-0xFFFF)               | 48.5K (0x3E00-0xFFFF)              |

## Changes from OligerRead.py

1. **Fixed TAP header for CODE files**: param2 is now set to 32768 (TAP standard)
   instead of passing through the raw directory value.
2. **File type-aware TAP parameters**: BASIC, CODE, and array types each get the
   correct param1/param2 mapping per the TAP specification.
3. **ABS state save detection**: Identifies full-memory captures and saves them as
   `.dump` (raw) + `.tap` (BASIC loader + CODE block) with auto-detected code
   region and entry point.
4. **Improved catalog display**: Shows file type names, cylinder assignments, and
   flags ABS state saves.
5. **Disk metadata display**: Shows disk name, total/available cylinders from the
   directory header.
6. **Duplicate filename handling**: Files that share the same disk filename are
   written with a `_2`, `_3`, etc. suffix instead of silently overwriting.
7. **Extraction manifest**: A `manifest.md` file is written to the output
   directory listing disk metadata and a table mapping every original disk
   filename to its extracted filename(s).
