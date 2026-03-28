# LarkenRead.py - Larken (LKDOS) Disk Image Extractor

## Overview

`LarkenRead.py` extracts files from raw disk images of floppy disks formatted
by the Larken disk system (LKDOS) for the Timex/Sinclair 2068 computer. It reads
the LKDOS directory structure, extracts individual files, and converts them to
the ZX Spectrum TAP tape format for use in emulators. Full-memory state captures
(machine snapshots) are detected automatically and saved as both raw dumps and
launchable TAP files.

## Usage

```
python3 LarkenRead.py -f <image_file> [-c] [-s <filename>]
```

**Arguments:**
- `-f`, `--imgfile` - Path to the Larken .img disk image file (required)
- `-c`, `--cat` - Display the disk catalog without extracting files
- `-s`, `--specific` - Extract only the named file

**Examples:**
```
python3 LarkenRead.py -f mydisk.img -c           # Show catalog
python3 LarkenRead.py -f mydisk.img               # Extract all files
python3 LarkenRead.py -f mydisk.img -s "prog.B1"  # Extract one file
```

## Output

Extracted files are placed in a subdirectory named after the image file (without
extension). Each file is saved as one of:

- **`.tap`** - Standard ZX Spectrum TAP format, loadable in any Spectrum/TS-2068
  emulator. Contains a proper TAP header with file type, filename, load address,
  and parameters, followed by the file data with XOR checksums.

- **`.dump`** + **`.tap`** (for memory dumps) - The `.dump` file contains the raw
  memory contents. The `.tap` file contains a BASIC loader program that will load
  the machine code into the correct memory location and execute it. The loader
  does: `CLEAR <ramtop>`, `LOAD ""CODE`, `RANDOMIZE USR <entry>`.

Filenames are sanitized for the host filesystem. Characters outside
`[A-Za-z0-9~ -_.]` are stripped. The original filename is preserved inside the
TAP header.

When two or more files on the disk share the same name, the second and subsequent
files receive a numeric suffix: `prog.B1.tap`, `prog.B1_2.tap`, etc.

- **`manifest.md`** - A Markdown file written to the output directory after
  extraction. It records the disk metadata (format, sides, tracks) and a table
  mapping each original disk filename to its extracted filename(s), file type, and
  size. This is especially useful when filenames were sanitized or de-duplicated,
  since the manifest preserves the link back to the original disk contents.

## Memory Dump Detection

Files are classified as memory dumps when all three conditions are met:
- Start address = 0x4000 (16384) - beginning of usable RAM
- Total length >= 40,960 bytes (40K)
- Variables-Program offset = 0 (invalid for a real BASIC program)

These are typically full 48K RAM snapshots saved by applications like OmniCalc,
capturing the entire machine state from 0x4000 to 0xFFFF. When a dump is
detected, the script reads RAMTOP from the system variables (address 0x5CB2) to
determine where the machine code region starts, and scans backward from 0xFFFF
to find where it ends. This information is used to build a minimal BASIC loader
and CODE block in the TAP file.

---

## LKDOS Disk Format

### Physical Layout

LKDOS uses double-density 5.25" floppy disks. Each disk is divided into 5,120-byte
(5K) blocks, with each block comprising ten 512-byte sectors. Only whole blocks
can be accessed - there is no sector-level I/O.

| Disk Type                   | Tracks | Sides | Blocks |
|-----------------------------|--------|-------|--------|
| 40-track, double-sided (DD) | 40     | 2     | 80     |
| 40-track, single-sided (SD) | 40     | 1     | 40     |
| 80-track, double-sided (QD) | 80     | 2     | 160    |

### Block Numbering

Blocks are numbered starting at track 0, side 0 and alternate between sides:

```
Side 1:  1   3   5   7   9  11  13  15  17  19  ...
Side 0:  0   2   4   6   8  10  12  14  16  18  ...
         |-- Track 0 --|-- Track 1 --|-- Track 2 --|  ...
```

Even-numbered blocks are on side 0, odd-numbered blocks are on side 1.
The track number for a given block is `block_number // 2`.

### Block 0 - Catalog Block

Block 0 is reserved for the catalog (directory), track map, and disk name.
It is never used for file data.

#### Disk Parameters (Block 0)

| Offset | Size  | Description                                    |
|--------|-------|------------------------------------------------|
| 20     | 1     | Number of sides                                |
| 21     | 1     | Number of tracks                               |
| 22     | 1     | Head step speed                                |

#### Track Map (Block 0, starting at offset 24)

The track map is a table of up to 165 bytes starting at offset 24. Each byte
represents one block (indexed from block 0). The map tells LKDOS which blocks
are available for saving files.

| Value | Meaning                                          |
|-------|--------------------------------------------------|
| 0-164 | Block is free; the value is the block number     |
| 245   | Block is in use (or does not physically exist)   |
| 255   | End of track map                                 |

When a file is saved, its blocks are replaced with 245 in the track map.
When a file is deleted, the block numbers are restored. Block 0 is always
marked as 245 (reserved for the catalog).

For a single-sided 40-track disk, all odd-numbered blocks (side 1) are marked
as 245, as are blocks beyond the physical track limit.

#### Directory Name Cells (Block 0, following the track map)

The directory is a list of approximately 100 variable-length "name cells,"
each describing one file. The directory uses marker bytes to delimit its
structure:

| Marker | Value | Purpose                                        |
|--------|-------|------------------------------------------------|
| 0xFF   | 255   | Start of a directory name cell                 |
| 0xFE   | 254   | Follows 0xFF if the cell is unused/empty       |
| 0xFD   | 253   | Start of the block list within a cell          |
| 0xF9   | 249   | End of the block list within a cell            |
| 0xFA   | 250   | End of all directory cells                     |

**Active file cell layout:**
```
FF <filename: up to 9 bytes> FD <block numbers...> F9
```

**Unused/deleted cell layout:**
```
FF FE ... (remaining bytes ignored until next FF or FA)
```

When a file is deleted, the 0xF9 (end of block list) marker is moved immediately
after the 0xFD, indicating an empty block list. The blocks are returned to the
track map.

Each cell has room for up to 21 block numbers (over 100K per file), but this
can be expanded for sequential files or reduced to allow more directory entries.

The disk name is stored at offset 4500 in block 0, as a string terminated by
a zero byte. It can be up to 500+ characters long.

### Data Blocks (Blocks 1+)

Every data block contains a 24-byte header followed by up to 5,090 bytes of
file data.

#### Data Block Header

| Offset | Size | Description                                       |
|--------|------|---------------------------------------------------|
| 0      | 1    | Reserved (always 0xFF in practice)                |
| 1      | 1    | Block number                                      |
| 2-11   | 10   | Filename (space-padded to 10 characters)          |
| 12-13  | 2    | Start address of file (little-endian)             |
| 14-15  | 2    | Length of data on this block only (little-endian)  |
| 16     | 1    | CRC/checksum byte                                 |
| 17-18  | 2    | Auto-run line number for BASIC (little-endian)    |
| 20-21  | 2    | Variables-Program offset for BASIC (little-endian) |
| 22-23  | 2    | Total length of entire file (little-endian)       |
| 24+    | var  | File data (up to 5,090 bytes)                     |

The header fields at offsets 12-23 are only meaningful on the first block of a
multi-block file. The `data length` field at offset 14-15 is per-block and tells
how many valid data bytes follow the header in that specific block.

For multi-block files, the total file content is reconstructed by reading each
block's data (starting at offset 24, for `data length` bytes) in the order
specified by the directory's block list, and concatenating them.

### File Types

LKDOS does not store a file type code in the directory. Instead, file types are
determined by the filename extension convention:

| Extension    | Type           | TAP Type Code |
|-------------|----------------|---------------|
| `.B` + digit | BASIC program  | 0x00          |
| `.C` + digit | Machine code   | 0x03          |
| `.A` + char  | Numeric array  | 0x01          |
| `.A$` + char | String array   | 0x02          |

### Single-Sided Disk Images

When a single-sided disk is imaged, the image file contains only the even-numbered
blocks (side 0), stored contiguously. The block numbers in the directory still
follow the LKDOS convention (0, 2, 4, 6, ...). The script detects single-sided
images by checking `sides == 1` and `file_size < 250000`, then divides directory
block numbers by 2 to compute the correct offset in the image file.

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

## Changes from LarkenRead.py

1. **Fixed TAP header for CODE files**: param1 uses `fileStartAddr` (block header
   bytes 12-13) instead of `fileAutoStartLine`; param2 set to 32768.
2. **Dynamic directory start**: Scans for the 0xFF end-of-track-map marker instead
   of using hardcoded offset 188.
3. **Full 10-byte filename**: Reads `block[2:12]` (all 10 bytes per the spec)
   instead of `block[2:11]` plus forced space padding.
4. **Null byte handling**: Strips both spaces and null bytes when comparing names;
   replaces null padding with spaces in TAP output.
5. **Memory dump detection**: Identifies full-memory state captures and saves them
   as `.dump` (raw) + `.tap` (BASIC loader + CODE block).
6. **Duplicate filename handling**: Files that share the same disk filename are
   written with a `_2`, `_3`, etc. suffix instead of silently overwriting.
7. **Extraction manifest**: A `manifest.md` file is written to the output
   directory listing disk metadata and a table mapping every original disk
   filename to its extracted filename(s).
