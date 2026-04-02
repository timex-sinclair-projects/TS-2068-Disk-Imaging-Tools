# QLRead.py - Sinclair QL Floppy Disk Image Extractor

## Overview

`QLRead.py` extracts files from raw disk images of floppy disks formatted by the
Sinclair QL's QDOS operating system (QL5A and QL5B formats). It reads the QDOS
directory structure, parses the block allocation map, applies sector
de-interleaving, and extracts individual files as raw binary. Extracted files
retain their original QDOS content (executables contain 68000 machine code, data
files contain their raw bytes).

## Usage

```
python3 QLRead.py -f <image_file> [-c] [-s <filename>] [-v]
```

**Arguments:**
- `-f`, `--imgfile` - Path to the QL .img disk image file (required)
- `-c`, `--cat` - Display the disk catalog without extracting files
- `-s`, `--specific` - Extract only the named file
- `-v`, `--verbose` - Show allocation details during extraction

**Examples:**
```
python3 QLRead.py -f PD1.img -c               # Show catalog
python3 QLRead.py -f PD1.img                   # Extract all files
python3 QLRead.py -f PD1.img -s "UnZip30"      # Extract one file
python3 QLRead.py -f PD1.img -v                # Verbose extraction
```

## Output

Extracted files are placed in a subdirectory named after the image file (without
extension). Files are saved as raw binary with their original QDOS filenames
(sanitized for the host filesystem). Characters outside `[A-Za-z0-9~ -_.]` are
stripped.

Unlike the ZX Spectrum extractors, QLRead does not convert files to TAP format.
QDOS executables are Motorola 68000 binaries and data files use QL-native
formats. The extracted files can be used directly with QL emulators such as
QPC2, SMSQmulator, or Q-emuLator.

When two or more files share the same name, the second and subsequent files
receive a numeric suffix: `file`, `file_2`, `file_3`, etc.

- **`manifest.md`** - A Markdown file written to the output directory after
  extraction. It records disk metadata (format, label, geometry) and a table
  mapping each original filename to its extracted filename, file type, size, and
  date.

---

## QL5A Disk Format

### Physical Layout

The Sinclair QL uses 3.5-inch double-density floppy disks with the following
geometry:

| Parameter               | Value                |
|-------------------------|----------------------|
| Tracks (cylinders)      | 80                   |
| Sides                   | 2                    |
| Sectors per track       | 9                    |
| Physical sector size    | 512 bytes            |
| Logical sector size     | 256 bytes            |
| Total logical sectors   | 1,440                |
| Disk capacity           | 360 KB (368,640 bytes) |

Each 512-byte physical sector is treated as two 256-byte logical sectors by
QDOS. The QL's filesystem addresses all 1,440 logical sectors sequentially: a
cylinder (both sides of one track) contains 18 logical sectors.

### Sector Interleaving

Logical sectors within a cylinder are not stored in sequential physical order.
The disk header contains an 18-byte interleave table (at offset 0x28) that maps
each logical sector position to its physical (side, sector) location on disk.

The interleave pattern for a standard QL5A disk is:

```
Logical:   0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17
Physical: S0 S0 S0 S1 S1 S1 S0 S0 S0 S1 S1 S1 S0 S0 S0 S1 S1 S1
Sector:    0  3  6  0  3  6  1  4  7  1  4  7  2  5  8  2  5  8
```

(S0 = side 0, S1 = side 1)

Raw disk images store sectors in physical track order (side 0 sectors 0-8,
then side 1 sectors 0-8, for each track). To read logical sector data from the
image, the interleave table must be applied to compute the correct byte offset.

For logical sector L:
```
cylinder       = L / 18
pos_in_cyl     = L % 18
phys_info      = interleave_table[pos_in_cyl]
side           = 1  if phys_info >= 0x80  else 0
physical_sector = phys_info & 0x7F
image_offset   = cylinder * 4608 + side * 2304 + physical_sector * 256
```

### Allocation Groups

Space is allocated in **groups** of 6 logical sectors (1,536 bytes), equivalent
to 3 physical 512-byte sectors. The disk contains 240 groups total.

| Group Range | Contents                                  |
|-------------|-------------------------------------------|
| 0-2         | Disk header, allocation map, status table |
| 3-5         | Directory                                 |
| 6-239       | File data (or free)                       |

### Disk Header (Logical Sector 0)

The first 96 bytes of logical sector 0 contain the disk header:

| Offset | Size | Description                                   |
|--------|------|-----------------------------------------------|
| 0x00   | 4    | Format ID (`QL5A` for DD, `QL5B` for HD)      |
| 0x04   | 10   | Disk label (ASCII, space-padded)               |
| 0x0E   | 2    | Random ID (big-endian)                         |
| 0x10   | 2    | Update count                                   |
| 0x12   | 2    | Free sectors                                   |
| 0x14   | 2    | Good sectors                                   |
| 0x16   | 2    | Total logical sectors (1,440 for DD)           |
| 0x1A   | 2    | Sectors per track (9)                          |
| 0x1C   | 2    | Sectors per cylinder (18)                      |
| 0x1E   | 2    | Number of tracks (80)                          |
| 0x20   | 2    | Logical sectors per allocation group (3)*      |
| 0x24   | 2    | Maximum directory entries (typically 64)        |
| 0x28   | 18   | Logical-to-physical sector interleave table    |
| 0x3A   | 18   | Physical-to-logical reverse interleave table   |

*The "sectors per group" field records the physical sector count (3), while the
effective group size is 6 logical sectors = 1,536 bytes.

### Block Allocation Map (Offset 0x60)

The allocation map begins at byte 0x60 in logical sector 0 and uses **3 bytes
per group** for 240 entries (720 bytes total). Each entry encodes which file owns
the group and the block's sequence number within that file.

**Entry format** (3 bytes, big-endian):

| Byte | Description                                         |
|------|-----------------------------------------------------|
| 0    | Status: 0x00 = allocated, 0xF8 = header, 0xFD = system/EOF |
| 1    | High nibble: file ID (1-15); Low nibble: block sequence high 4 bits |
| 2    | Block sequence low 8 bits                           |

Special entry values:
- `F8 00 00` - Disk header (group 0)
- `00 00 00` - Map/system area
- `FD FF FF` - Reserved / end-of-file (system groups)
- `30 30 30` - Free (formatted empty)

For allocated entries (byte 0 = 0x00):
```
file_id    = byte1 >> 4          (range: 1-15)
block_seq  = (byte1 & 0xF) << 8 | byte2
```

The `file_id` in the map corresponds to the directory entry's `fileno` field
minus 1 (i.e., `map_file_id = directory_fileno - 1`).

### Directory (Groups 3-5)

The directory occupies up to 3 system groups (4,608 bytes), starting at group 3
(logical sector 18). It begins with a 64-byte header (typically empty/formatted)
followed by 64-byte file entries.

**Directory entry format** (64 bytes, all multi-byte values big-endian):

| Offset | Size | Field       | Description                          |
|--------|------|-------------|--------------------------------------|
| 0x00   | 4    | fl_length   | File length in bytes                 |
| 0x04   | 1    | fl_access   | Access key (0 = open)                |
| 0x05   | 1    | fl_type     | File type                            |
| 0x06   | 4    | fl_data     | Data space (EXEC: runtime RAM needed)|
| 0x0A   | 4    | fl_extra    | Extra information                    |
| 0x0E   | 2    | fl_nlen     | Filename length                      |
| 0x10   | 36   | fl_name     | Filename (padded with 0x00)          |
| 0x34   | 4    | fl_date     | Modification date                    |
| 0x38   | 2    | fl_ver      | Version number                       |
| 0x3A   | 2    | fl_fileno   | File number (links to allocation map)|
| 0x3C   | 4    | fl_bkup     | Backup date                          |

Empty directory slots are filled with 0x30 bytes.

### File Types

QDOS uses a simple file type system:

| Code | Type | Description                                    |
|------|------|------------------------------------------------|
| 0    | DATA | Data file (text, archives, etc.)               |
| 1    | EXEC | Executable (68000 machine code)                |
| 2    | REL  | Relocatable object code                        |

For EXEC files, the `fl_data` field specifies the amount of data space (in
bytes) the program requires at runtime. This is allocated by QDOS when the
program is loaded but is not stored on disk.

### Date Format

QDOS dates are stored as a 32-bit unsigned integer representing seconds elapsed
since **1961-01-01 00:00:00 UTC**. For example, the value `0x6C2AE056`
(1,814,749,270 decimal) corresponds to 2018-07-05 01:01:10.

### File Data Storage

File data is stored across the groups assigned to it in the allocation map.
Groups are read in block sequence order (the 12-bit sequence number in each map
entry). No per-file header is prepended to the data on disk -- the directory
entry contains all metadata, and the file content begins at byte 0 of the
first allocated group.

To extract a file:
1. Look up the file's `fl_fileno` in the directory
2. Scan the allocation map for all groups with `file_id = fl_fileno - 1`
3. Sort the matched groups by their block sequence number
4. Read each group's 1,536 bytes (6 logical sectors, de-interleaved)
5. Concatenate and trim to `fl_length` bytes

---

## Known Limitations

- **C68d1_zip under-allocation**: On the PD1 disk image tested, the file
  `C68d1_zip` declares a length of 308,915 bytes but only has 2 groups allocated
  (3,072 bytes). This may indicate a multi-disk archive where only a stub entry
  exists on this disk, or a corrupted directory entry. The script extracts
  whatever data is available and prints a warning.

- **Space-named files**: Files with names consisting only of whitespace are
  skipped with a warning, since they cannot be represented as filenames on the
  host filesystem.

- **QL5B (HD) format**: The script parses QL5B headers but has only been tested
  with QL5A (double-density) images. High-density disks may use different
  geometry or group sizes.
