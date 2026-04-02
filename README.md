# TS-2068 Disk Imaging Tools

A comprehensive Python toolkit for analyzing and extracting files from TS-2068 computer disk images created with Greaseweazle. This collection supports multiple vintage disk formats used with the Timex Sinclair 2068 computer system.

## Supported Formats

- **Larken Format** (.img files) - 5KB blocks with directory at byte 188
- **Oliger Format V2** (.img files) - 5KB blocks with catalog at 0x600, cylinder-based allocation
- **Oliger Format V1** (.img files) - 5KB fixed file slots, no catalog, load-by-number
- **Zebra DIRSCP Format** (.dsk files) - CPC DSK format with hierarchical directory system
- **Zebra CP/M Format** (.dsk files) - CPC DSK format with flat CP/M file system
- **Sinclair QL Format** (.img files) - QDOS QL5A/QL5B floppy disk images (catalog fully supported; extraction partial — see docs)

## Features

- 🔍 **Automatic Format Detection** - Intelligently identifies disk format from file headers
- 📁 **File Extraction** - Extracts files to TAP format (Larken/Oliger) or native format (Zebra)
- 📋 **Disk Cataloging** - Lists all files and directories on disk images
- 🖥️ **Unified Interface** - Terminal-based menu system for easy operation
- 🔧 **Greaseweazle Integration** - Includes command reference for creating compatible disk images
- 📊 **File Analysis** - Shows file sizes, types, and format hints

## Quick Start

### Prerequisites

- Python 3.6 or later
- Disk images created with [Greaseweazle](https://github.com/keirf/greaseweazle)

### Installation

#### Option 1: Download Release (Recommended)
1. **Download** the latest release zip from [GitHub Releases](https://github.com/yourusername/TS-2068-Disk-Imaging-Tools/releases)
2. **Extract** the zip file to your desired location
3. **Ready to use** - No additional setup required

#### Option 2: Clone Repository
```bash
git clone https://github.com/yourusername/TS-2068-Disk-Imaging-Tools.git
cd TS-2068-Disk-Imaging-Tools
```

### Usage

#### Option 1: Unified Interface (Recommended)

```bash
python scripts/DiskImageManager.py
```

This launches an interactive menu where you can:
- Browse available disk images
- Analyze disk contents
- Extract files automatically
- Access Greaseweazle command reference

#### Option 2: Individual Scripts

Extract from specific formats directly:

```bash
# Larken format
python scripts/LarkenRead.py -f examples/larken.img

# Oliger format (auto-detects V1 and V2)
python scripts/OligerRead.py -f examples/oliger.img

# Zebra format (auto-detects DIRSCP / CP/M)
python scripts/ZebraRead.py -f examples/zebra.dsk

# Sinclair QL format
python scripts/QLRead.py -f ql_disk.img
```

## Creating Disk Images with Greaseweazle

### Larken & Oliger Disks

Most Larken and Oliger disks use these configurations:

```bash
# Single-sided, 40 tracks (most common)
gw read --format=ibm.scan --tracks=c=0-39:h=0 disk.img

# Double-sided, 40 tracks
gw read --format=ibm.scan --tracks=c=0-39:h=0-1 disk.img

# Single-sided, 42 tracks (if 40-track seems incomplete)
gw read --format=ibm.scan --tracks=c=0-41:h=0 disk.img

# Double-sided, 42 tracks
gw read --format=ibm.scan --tracks=c=0-41:h=0-1 disk.img
```

### Zebra (CPC) Disks

```bash
# Standard CPC format
gw read --format=ibm.720 disk.dsk
```

**Tips:**
- Start with 40 tracks for most disks
- Try 42 tracks if extraction seems incomplete
- Check physical disk labels for sided information
- IMG format saves disk as a binary/ASCII file for best compatibility

## File Structure

```
TS-2068-Disk-Imaging-Tools/
├── scripts/                     # Main scripts
│   ├── DiskImageManager.py      # Main unified interface
│   ├── LarkenRead.py            # Larken format extraction
│   ├── OligerRead.py            # Oliger V1/V2 format extraction
│   ├── QLRead.py                # Sinclair QL format extraction
│   ├── ZebraRead.py             # Zebra DIRSCP/CP/M analysis & extraction
│   ├── archive/                 # Original/legacy scripts
│   │   ├── LarkenRead.py
│   │   ├── OligerRead.py
│   │   ├── ZebraExtract.py
│   │   ├── ZebraRead.py
│   │   └── ZebraRead_enhanced.py
│   └── test/                    # Test scripts
│       └── zebra_full_scan.py
├── docs/                        # Format documentation
│   ├── LarkenRead.md            # LKDOS disk format & script reference
│   ├── OligerRead.md            # JLO SAFE V1/V2 disk format & script reference
│   ├── QLRead.md                # Sinclair QL QDOS disk format & script reference
│   └── ZebraRead.md             # Zebra DIRSCP/CP/M format & script reference
├── examples/                    # Sample disk images
│   ├── larken.img
│   ├── oliger.img
│   └── zebra*.dsk
└── extracted_files/             # Output directory (created automatically)
    ├── larken/                  # Larken extractions (.tap files)
    ├── oliger/                  # Oliger extractions (.tap files)
    └── zebra/                   # Zebra extractions (native files)
```

## Output Formats

### TAP Files (Larken/Oliger)
- Compatible with ZX Spectrum emulators
- Preserves original file headers and data
- Can be loaded directly into emulation software

### Native Files (Zebra DIRSCP)
- Preserves original file structure and hierarchy
- Maintains directory organization
- Files extracted in their native format

### Raw Binary (Sinclair QL)
- Files extracted with original QDOS content
- Executables contain 68000 machine code
- Data files retain their raw bytes

## Technical Details

Detailed disk format documentation and script references are in the [docs/](docs/) folder:

- **[docs/LarkenRead.md](docs/LarkenRead.md)** - LKDOS disk format: block layout, track map,
  directory markers, data block headers, file type conventions, TAP output format,
  and memory dump detection.
- **[docs/OligerRead.md](docs/OligerRead.md)** - JLO SAFE/Oliger disk format: V2 cylinder
  interleaving, directory header and entries, file type codes, ABS state saves;
  V1 fixed-slot format, boot BASIC parsing, heuristic type detection; TAP output
  format, and comparison with LKDOS.
- **[docs/QLRead.md](docs/QLRead.md)** - Sinclair QL QDOS disk format: QL5A/QL5B layout,
  sector de-interleaving, 12-bit allocation map encoding, dynamic directory
  sizing, file types, and known limitations.
- **[docs/ZebraRead.md](docs/ZebraRead.md)** - Zebra disk format: CPC DSK container,
  sector interleaving (track skew table), DIRSCP hierarchical directories,
  CP/M flat directories, extraction details, and comparison across formats.

### Format Summary

| Feature           | Larken (LKDOS)       | Oliger (JLO SAFE)    | Zebra                 | Sinclair QL           |
|-------------------|----------------------|----------------------|-----------------------|-----------------------|
| Image format      | Raw .img             | Raw .img             | Extended CPC .dsk     | Raw .img              |
| Block size        | 5,120 bytes          | 5,120 bytes          | 4,096 bytes           | 512 bytes (sectors)   |
| Sector size       | 512 bytes            | 512 bytes            | 256 bytes             | 512 bytes             |
| Directory type    | Marker-delimited     | V2: fixed entries; V1: none (slots) | DIRSCP or CP/M | QDOS directory        |
| Subdirectories    | No                   | No                   | Yes (DIRSCP)          | No                    |
| Output format     | .tap (ZX Spectrum)   | .tap (ZX Spectrum)   | Native binary         | Raw binary            |
| State saves       | 48K memory dumps     | 48.5K ABS saves (V2)| N/A                   | N/A                   |

## Script Capabilities

### Analysis vs. Extraction Tools

The toolkit includes both **analysis** and **extraction** capabilities:

#### Extraction Tools
- **`LarkenRead.py`** - Extracts Larken format to TAP files (with CODE file fix and memory dump detection)
- **`OligerRead.py`** - Extracts Oliger format to TAP files (auto-detects V1/V2; V2 has CODE file fix and ABS save detection; V1 uses heuristic type detection)
- **`QLRead.py`** - Extracts Sinclair QL QDOS files as raw binary (with sector de-interleaving; catalog display works fully, extraction may be incomplete for files whose map entries span interleaved sectors)
- **`ZebraRead.py`** - Analyzes and extracts Zebra CPC DSK files (auto-detects DIRSCP/CP/M; DIRSCP supports full extraction with directory hierarchy; CP/M supports catalog display)

### Recommended Workflow
1. **Catalog first:** Use `-c` flag with the appropriate script to view disk contents
2. **Extract:** Run the same script without `-c` to extract files

## Command Line Options

All extraction scripts support these options:

- `-f, --file` : Specify input disk image file
- `-c, --catalog` : Show catalog only (don't extract files)
- `-v, --verbose` : Enable verbose output
- `-h, --help` : Show help message

## Examples

### View disk catalog without extracting:
```bash
python scripts/LarkenRead.py -f examples/larken.img -c
python scripts/ZebraRead.py -f examples/zebra.dsk -c
python scripts/QLRead.py -f examples/ql-pd/PD1.img -c
```

### Extract all files:
```bash
python scripts/OligerRead.py -f examples/oliger.img
python scripts/ZebraRead.py -f examples/zebra.dsk
```

### Extract a specific file:
```bash
python scripts/ZebraRead.py -f examples/zebra.dsk -s "LETTER"
```

## Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.

### Development Setup

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with various disk image formats
5. Submit a pull request

## License

This project is open source. Please see the individual script headers for specific licensing information.

## Acknowledgments

- **Greaseweazle Project** - For enabling reading of vintage disk formats
- **TS-2068 Community** - For preserving and documenting these disk formats
- **Original Format Developers** - Larken, Oliger, Zebra, and Sinclair QL disk system creators

## Support

If you encounter issues:

1. Check that your disk image was created with compatible Greaseweazle settings
2. Try the universal analyzer first: `python scripts/ZebraRead.py -f yourfile -c`
3. Verify the disk image isn't corrupted by checking file size and headers
4. Open an issue with details about your disk image and error messages

---

**Note:** These tools are designed for preserving and analyzing vintage software. Please respect copyright laws and only use with disk images you own or have permission to analyze.
