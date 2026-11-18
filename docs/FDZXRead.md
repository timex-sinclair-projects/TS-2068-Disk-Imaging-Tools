# FDZXRead.py - AERCO FD-ZX (ZX81/TS1000) Disk Image Extractor

## Overview

`FDZXRead.py` extracts programs from raw disk images of floppy disks used with
the AERCO FD-ZX disk interface for the ZX81 and Timex/Sinclair 1000/1500. It
reads both directory schemes found on FD-ZX disks:

- **SADOS** - AERCO's stock disk operating system ("SADOS+ 16K / 64K", 8/83)
- **BBDOS 4.0** - Bill Bell's replacement DOS (1986)

FD-ZX disks have no file system in the usual sense. A disk holds 20 fixed
"pages", and each page is a straight memory image of a ZX81 program, so every
program is written out as a `.p` file that loads in a ZX81 emulator.

## Usage

```
python3 FDZXRead.py -f <image_file> [-o <outdir>] [--all-pages]
```

**Arguments:**
- `-f`, `--imgfile` - Path to the FD-ZX .img disk image file (required)
- `-o`, `--outdir` - Output directory (default: the image name without extension)
- `--all-pages` - Also write non-empty pages that hold no valid program

## Output

- **`NN_name.p`** - one file per program, where `NN` is the page number. The file
  is the memory image from 16393 (VERSN) up to E_LINE.
- **`01_name_page1_full.bin`** - BBDOS only: the whole 20 KB DOS page, because
  the DOS machine code continues past E_LINE. Load address 16393.
- **`NN_boot-copy.p`** - SADOS writes the 16K DOS to all four "corner" pages
  (1, 10, 11, 20); copies not named in the directory are kept with this tag.
- **`manifest.txt` / `manifest.json`** - page numbers, names, sizes, line counts,
  and program/variables lengths for every file.

## Disk Format

### Geometry

40 tracks x 2 sides x 10 sectors x 512 bytes (double density) = 409,600 bytes.
The image is track by track with the two sides alternating:

```
offset = ((track * 2) + side) * 5120 + (sector - 1) * 512
```

Sectors are in logical order in the image.

### Pages

- A **16K page** is 4 consecutive tracks on one side (20,480 bytes), holding a raw
  memory image starting at 16393.
- Pages 1-10 are side 0, tracks 0-3, 4-7 ... 36-39. Pages 11-20 are the same
  tracks on side 1.
- A **64K page** is 3 consecutive 16K pages (61,440 bytes), still one linear
  memory image from 16393. Valid 64K slots start at pages 2, 5, 8, 12, 15 and 18.

### SADOS directory

Page 1 holds the SADOS BASIC menu program. The page names are the `Q$(20,24)`
string array saved in that program's variables. A page is loaded with
`RAND USR (12290+P)` and saved with `RAND USR (12720+P)`.

### BBDOS 4.0 directory

512 bytes at side 0, track 3, sector 1 (an identical copy is in sector 2): a
32-byte header (for example `DIRECTORY  DISK NO. 002`) followed by 20 entries of
24 bytes:

| Bytes | Field |
|-------|-------|
| 0 | current-use flags |
| 1 | initial-use flags |
| 2-3 | read call address (page number = address - 0x3002) |
| 4-5 | current write call |
| 6-7 | initial write call |
| 8 | spare |
| 9-23 | name (15 characters, ZX81 character set) |

Use-flag bits: 0 = in use, 1 = program, 2 = variables, 3 = always 1,
4 = 16K, 6 = 64K, 7 = end of directory. The two follow-on pages of a 64K file
have in-use entries with blank names.

## Notes

- Tested on three disks: an AERCO SADOS master and two BBDOS 4.0 disks (the
  AERCO CP2068 and Memotech printer versions).
- Not yet tested: BBDOS variables-only ("data") files, SADOS data pages,
  single-sided or 35-track FD-ZX disks, and the 6K and "SP" BBDOS builds.
  Variables-only pages are written as raw `.bin`.
- Programs that keep their code outside BASIC (such as the BBDOS builds of
  Hot-Z II) produce a faithful memory image that loads in an emulator but lists
  no BASIC.
