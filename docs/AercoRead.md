# AercoRead.py - Aerco FD / DOS-64 Disk Image Extractor

## Overview

`AercoRead.py` extracts files from raw disk images of floppy disks formatted by
the Aerco FD-68 disk interface with DOS-64 software for the Timex/Sinclair 2068
computer. It reads the DOS-64 directory structure, extracts individual files, and
converts BASIC and CODE files to the ZX Spectrum TAP tape format for use in
emulators. MODULE (overlay) files are saved as raw binary.

The script also identifies RP/M (CP/M clone) disks and displays basic disk
information, though RP/M directory extraction is not yet implemented.

## Usage

```
python3 AercoRead.py -f <image_file> [-c] [-s <filename>]
```

**Arguments:**
- `-f`, `--imgfile` - Path to the Aerco .img disk image file (required)
- `-c`, `--cat` - Display the disk catalog without extracting files
- `-s`, `--specific` - Extract only the named file

**Examples:**
```
python3 AercoRead.py -f aerco-update-oct.img -c       # Show catalog
python3 AercoRead.py -f aerco-update-oct.img           # Extract all files
python3 AercoRead.py -f aerco-update-oct.img -s "boot" # Extract one file
python3 AercoRead.py -f aerco-rpm.img -c               # Show RP/M disk info
```

## Output

Extracted files are placed in a subdirectory named after the image file (without
extension). Each file is saved as one of:

- **`.tap`** - Standard ZX Spectrum TAP format for BASIC, CODE, and DATA files.
  Contains a proper TAP header with file type, filename, load address, and
  parameters, followed by the file data with XOR checksums.

- **`.bin`** - Raw binary for MODULE (overlay) files, which have no file metadata
  on disk.

Filenames are sanitized for the host filesystem. When two or more files share the
same name, the second and subsequent files receive a numeric suffix.

- **`manifest.md`** - A Markdown file listing disk metadata and a table mapping
  each original filename to its extracted filename, type, and size.

---

## Aerco FD-68 Hardware

The Aerco FD-68 is a floppy disk interface for the TS-2068, built around the
Western Digital WD1797 floppy disk controller. It provides 64 KiB of DOCK RAM
(expandable to 256 KiB) and supports up to 4 drives (5.25" or 3.5"). The
companion DOS-64 software combines a disk operating system with OS-64, a
64-column display mode for the TS-2068.

## DOS-64 Disk Format

### Physical Layout

| Parameter              | Value                            |
|------------------------|----------------------------------|
| Sector size            | 512 bytes                        |
| Sectors per track      | 10                               |
| Track size             | 5,120 bytes                      |
| Tracks (single-sided)  | 40 (204,800 bytes)               |
| Tracks (double-sided)  | 80 (409,600 bytes)               |

For double-sided disks, blocks 0x00-0x27 (0-39) address side 0 tracks and blocks
0x80-0xA7 (128-167) address side 1 tracks. In the image file, side 0 occupies
the first half and side 1 the second half (sequential side storage).

### Boot Sector (Track 0, Bytes 0-18)

The first sector of the disk contains the boot code:

| Offset | Size | Description                                         |
|--------|------|-----------------------------------------------------|
| 0-1    | 2    | Z80 JR instruction (`18 0E`) — jump past header     |
| 2-5    | 4    | System bytes (vary per disk)                         |
| 6-15   | 10   | Disk name (ASCII, null-terminated)                   |
| 16-18  | 3    | Z80 JP instruction (`C3 39 35`) — jump to boot code |

### Allocation Bitmap (Track 0, Offset 0x200)

The first 32 bytes at offset 0x200 form an allocation bitmap where each bit
represents one track. A set bit indicates the track is in use. For an 80-track
(double-sided) disk, the bitmap uses approximately 80 bits (10 bytes).

### Directory (Track 0, Offset 0x220+)

Directory entries follow the bitmap, each 32 bytes:

| Offset | Size | Description                                         |
|--------|------|-----------------------------------------------------|
| 0      | 1    | File type code                                      |
| 1-10   | 10   | Filename (ASCII, null-padded)                        |
| 11-12  | 2    | File length in bytes (little-endian)                 |
| 13-14  | 2    | Parameter 1 (little-endian) — see below              |
| 15-16  | 2    | Parameter 2 (little-endian) — see below              |
| 17-31  | 15   | Block list (track numbers; 0 = unused)               |

### File Types

| Code | Type   | Param 1              | Param 2                     |
|------|--------|----------------------|-----------------------------|
| 0x00 | BASIC  | Auto-start line      | Program length (vars offset) |
| 0x03 | CODE   | Start address        | (application-specific)       |
| 0x04 | MODULE | (unused)             | (unused)                     |
| 0x08 | DATA   | (application-specific)| (application-specific)      |
| 0xFF | BITMAP | —                    | — (allocation bitmap entry)  |

Types 0x00 (BASIC) and 0x03 (CODE) match the standard ZX Spectrum file type
convention. Type 0x04 (MODULE) is used for DOS-64 overlay/screen files that have
no per-file metadata.

### File Data Storage

Each file's data is stored across the tracks listed in its block list. The first
track of a BASIC, CODE, or DATA file begins with a **17-byte file header**
(identical in layout to the first 17 bytes of the directory entry), followed by
the file content. Subsequent tracks for the same file contain pure data with no
header.

MODULE files (type 0x04) have no on-disk header — the track data is entirely
raw content.

To extract a file:
1. Read the block list from the directory entry
2. For the first block: skip 17 bytes (file header), read the rest of the track
3. For subsequent blocks: read the full track
4. Concatenate and trim to the declared file length

### Block Numbering

| Block Range | Mapping                                   |
|-------------|-------------------------------------------|
| 0x00-0x27   | Side 0, tracks 0-39                       |
| 0x80-0xA7   | Side 1, tracks 0-39 (image offset + 40 tracks) |

Block 0 is always the system track (directory and boot code). File data starts
at block 1.

---

## RP/M (CP/M) Disk Format

RP/M is a CP/M 2.2 clone by Micromethods that runs on the TS-2068 with Aerco
FD-68 hardware. RP/M disks are identified by the string "RP/M" in the disk name
area.

### RP/M Physical Layout

| Parameter              | Value                            |
|------------------------|----------------------------------|
| System tracks          | 4 (tracks 0-3)                   |
| Block size (BLS)       | 2,048 bytes                      |
| Directory location     | Track 4 (first data track)       |
| Record size            | 128 bytes (standard CP/M)        |

### RP/M Directory

The directory occupies the first data track (track 4) and uses standard CP/M 2.2
32-byte entries:

| Offset | Size | Description                              |
|--------|------|------------------------------------------|
| 0      | 1    | User number (0x00-0x0F active, 0xE5 deleted) |
| 1-8    | 8    | Filename (high bit 7 = attributes)       |
| 9-11   | 3    | Extension (high bit 7 = attributes)      |
| 12     | 1    | Extent number                            |
| 13-14  | 2    | Reserved                                 |
| 15     | 1    | Record count (128-byte records)          |
| 16-31  | 16   | Allocation block numbers                 |

Files larger than 16 blocks span multiple extents, each with its own directory
entry. The script merges extents automatically.

### RP/M Block Mapping

Block N maps to image offset `(4 × 5120) + (N × 2048)`, where 4 is the number
of system tracks. Text files (.DOC, .TXT, etc.) are automatically trimmed at the
CP/M EOF marker (0x1A).

---

## Known Limitations

- **MODULE file sizes**: MODULE files have no declared length, so they are
  extracted as full track data (multiples of 5,120 bytes). The actual content
  may be shorter.

- **DATA type metadata**: The param1/param2 fields for DATA files appear to
  contain application-specific values whose meaning varies by program.

## Acknowledgments

The DOS-64 disk format was reverse-engineered from disk images, as no public
byte-level documentation exists. The Internet Archive hosts scanned copies of the
FD-68 manual and related documentation at https://archive.org/details/aerco.
