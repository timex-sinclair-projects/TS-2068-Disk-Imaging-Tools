#!/usr/bin/env python3
"""
ZebraRead.py - Analyze and extract files from Zebra CPC DSK disk images

Handles both DIRSCP (hierarchical) and CP/M (flat) directory structures.
DIRSCP disks support full file extraction; CP/M disks support catalog display.
"""

import argparse
import os
import sys
import string

# Constants for CPC DSK format
CPC_DSK_HEADER = b"EXTENDED CPC DSK"
DIRSCP_MARKER = b"DIRSCP"
HEADER_SIZE = 0x100  # 256 bytes
ROOT_DIR_OFFSET = 0x2880
TRACK_SIZE = 0x1100  # 4352 bytes per track
TRACK_HEADER_SIZE = 0x100  # 256 bytes
ALLOCATION_UNIT_SIZE = 1024  # Default AU size
SECTOR_SIZE = 256

# Track skew table for proper sector interleaving (from tomato C++ implementation)
TRACK_SKEW = [0, 7, 14, 5, 12, 3, 10, 1, 8, 15, 6, 13, 4, 11, 2, 9]

# Directory markers
MARKER_ROOT_DIR = 0xFF
MARKER_SUB_DIR = 0x80
MARKER_FILE = 0x01
MARKER_UNUSED = 0xE5


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Analyze and extract files from Zebra CPC DSK disk images")
    parser.add_argument("-f", "--imgfile", type=str, required=True,
                        help="DSK filename for input")
    parser.add_argument("-c", "--cat", action='store_true',
                        help="Catalog of disk image contents")
    parser.add_argument("-s", "--specific", type=str,
                        help="Name of a specific file to extract")
    parser.add_argument("-o", "--outdir", type=str, default=None,
                        help="Output directory (default: filename without extension)")
    parser.add_argument("-v", "--verbose", action='store_true',
                        help="Verbose output")
    return parser.parse_args()


def make_safe_filename(filename):
    """Make filename safe for filesystem"""
    safechars = string.ascii_letters + string.digits + "~ -_."
    return "".join(c for c in filename if c in safechars)


def unique_path(filepath):
    """Return filepath with a numeric suffix if it already exists."""
    if not os.path.exists(filepath):
        return filepath
    base, ext = os.path.splitext(filepath)
    counter = 2
    while os.path.exists(f"{base}_{counter}{ext}"):
        counter += 1
    return f"{base}_{counter}{ext}"


def is_dirscp_format(data):
    """Check if disk uses DIRSCP format"""
    return data[ROOT_DIR_OFFSET:ROOT_DIR_OFFSET + 6] == DIRSCP_MARKER


# ---------------------------------------------------------------------------
# DIRSCP directory parsing
# ---------------------------------------------------------------------------

def read_dirscp_entries(data, offset):
    """Read DIRSCP directory entries from given offset."""
    entries = []

    # Skip DIRSCP header if present
    if data[offset:offset + 6] == DIRSCP_MARKER:
        scan_start = offset + 0x28
    else:
        scan_start = offset

    for i in range(scan_start, min(scan_start + 0x200, len(data) - 32), 1):
        if i + 32 > len(data):
            break
        entry_data = data[i:i + 32]
        marker = entry_data[0]

        if marker not in (MARKER_ROOT_DIR, MARKER_SUB_DIR, MARKER_FILE):
            continue

        name = entry_data[1:9].decode('ascii', errors='ignore').strip()
        if not name or not name[0].isalpha():
            continue

        type_bytes = entry_data[9:12]
        file_type = type_bytes.decode('ascii', errors='ignore').strip()
        part_num = entry_data[12]
        tail_bytes = entry_data[13]
        size_hi = entry_data[14]
        size_lo = entry_data[15]
        alloc_info = entry_data[16:32]
        file_size_sectors = (size_hi << 8) | size_lo
        track_list = [b for b in alloc_info if b != 0 and b < 160]

        is_hidden = (type_bytes[1] & 0x80) != 0
        is_readonly = (type_bytes[0] & 0x80) != 0

        entry = {
            'offset': i,
            'marker': marker,
            'name': name,
            'type': file_type,
            'is_directory': file_type == 'DIR',
            'part_number': part_num,
            'tail_bytes': tail_bytes,
            'size_sectors': file_size_sectors,
            'tracks': track_list,
            'is_hidden': is_hidden,
            'is_readonly': is_readonly,
        }
        entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# CP/M directory parsing
# ---------------------------------------------------------------------------

def read_cpm_entries(data, offset):
    """Read CP/M-style directory entries from given offset."""
    entries = []
    for i in range(offset, min(offset + 0x400, len(data) - 32), 32):
        entry_data = data[i:i + 32]

        if entry_data[0] == MARKER_UNUSED:
            continue
        if entry_data[0] not in (0x00,):
            continue

        name_bytes = entry_data[1:9]
        ext_bytes = entry_data[9:12]
        if not (ord('A') <= name_bytes[0] <= ord('Z')):
            continue

        try:
            name = name_bytes.decode('ascii').strip()
            ext = ext_bytes.decode('ascii').strip()
        except UnicodeDecodeError:
            continue
        if not name:
            continue

        extent = entry_data[12]
        record_count = entry_data[15]
        alloc_blocks = [entry_data[b] for b in range(16, 32)
                        if entry_data[b] != 0 and entry_data[b] < 160]

        entry = {
            'offset': i,
            'marker': entry_data[0],
            'name': name,
            'type': ext,
            'extent': extent,
            'record_count': record_count,
            'allocation_blocks': alloc_blocks,
            'is_directory': False,
            'is_hidden': False,
            'is_readonly': False,
        }
        entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# Disk scanning — builds a full tree for both formats
# ---------------------------------------------------------------------------

def scan_disk(data, verbose=False):
    """Scan disk for all directory structures.

    Returns (root_entries, subdirectories) where subdirectories is a dict
    mapping directory name -> list of file entries.
    """
    dirscp = is_dirscp_format(data)

    if dirscp:
        root_entries = read_dirscp_entries(data, ROOT_DIR_OFFSET)
        if verbose:
            print(f"DIRSCP format — {len(root_entries)} root entries")
    else:
        root_entries = read_cpm_entries(data, ROOT_DIR_OFFSET)
        if not root_entries:
            # Try scanning from 0x2880 area anyway
            root_entries = read_cpm_entries(data, 0x2880)
        if verbose:
            print(f"CP/M format — {len(root_entries)} root entries")

    subdirs = {}
    if dirscp:
        dir_names = [e['name'] for e in root_entries if e['is_directory']]
        for offset in range(0x3000, len(data) - 0x200, 0x100):
            check = data[offset:offset + 32]
            if check[0] not in (MARKER_ROOT_DIR, MARKER_SUB_DIR):
                continue
            dir_name = check[1:9].decode('ascii', errors='ignore').strip()
            if dir_name in dir_names and dir_name not in subdirs:
                sub_entries = read_dirscp_entries(data, offset)
                # Filter out self-reference entries
                sub_entries = [e for e in sub_entries
                               if not e['is_directory'] or e['name'] != dir_name]
                subdirs[dir_name] = sub_entries
                if verbose:
                    print(f"  Found {dir_name}/ at 0x{offset:04x} "
                          f"({len(sub_entries)} entries)")

    return root_entries, subdirs, dirscp


# ---------------------------------------------------------------------------
# Catalog display
# ---------------------------------------------------------------------------

def display_catalog(data, root_entries, subdirs, dirscp):
    """Display disk catalog."""
    # Show disk info
    if len(data) >= HEADER_SIZE:
        disk_info = data[0x22:0x30].decode('ascii', errors='ignore').strip()
        num_tracks = data[0x30] if len(data) > 0x30 else 0
        num_sides = data[0x31] if len(data) > 0x31 else 0
        fmt = "DIRSCP" if dirscp else "CP/M"
        print(f"Format: CPC DSK ({fmt})")
        print(f"Created by: {disk_info}")
        print(f"Tracks: {num_tracks}, Sides: {num_sides}")
        print()

    for entry in root_entries:
        if entry['is_directory']:
            sub = subdirs.get(entry['name'], [])
            print(f"{entry['name']}/")
            for fe in sub:
                ext = f".{fe['type']}" if fe['type'] else ""
                flags = []
                if fe.get('is_hidden'):
                    flags.append('H')
                if fe.get('is_readonly'):
                    flags.append('R')
                flag_str = f" [{''.join(flags)}]" if flags else ""
                size = f" ({fe.get('size_sectors', '?')} sectors)"
                print(f"  {fe['name']}{ext}{flag_str}{size}")
            print()
        else:
            ext = f".{entry['type']}" if entry.get('type') else ""
            if dirscp:
                size = f" ({entry.get('size_sectors', '?')} sectors)"
            else:
                size = f" (ext {entry.get('extent', '?')}, " \
                       f"{entry.get('record_count', '?')} recs)"
            print(f"{entry['name']}{ext}{size}")


# ---------------------------------------------------------------------------
# File extraction (DIRSCP only)
# ---------------------------------------------------------------------------

def extract_file_data(data, tracks, verbose=False):
    """Extract file data from specified tracks with sector interleaving."""
    file_data = bytearray()

    for track_num in tracks:
        track_start = 0x100 + track_num * TRACK_SIZE + TRACK_HEADER_SIZE
        for sector_idx in range(16):
            skewed = TRACK_SKEW[sector_idx]
            sector_offset = track_start + skewed * SECTOR_SIZE
            if sector_offset + SECTOR_SIZE <= len(data):
                file_data.extend(data[sector_offset:sector_offset + SECTOR_SIZE])
            if verbose:
                print(f"      Trk {track_num} sec {sector_idx} "
                      f"(phys {skewed}): 0x{sector_offset:04x}")

    # If data is all zeros, retry without skew
    if file_data and all(b == 0 for b in file_data[:100]):
        file_data = bytearray()
        for track_num in tracks:
            track_offset = 0x100 + track_num * TRACK_SIZE + TRACK_HEADER_SIZE
            chunk = data[track_offset:track_offset + TRACK_SIZE - TRACK_HEADER_SIZE]
            file_data.extend(chunk)

    return bytes(file_data)


def trim_padding(data):
    """Trim trailing padding bytes from file data."""
    end = len(data)
    for i in range(len(data) - 1, -1, -1):
        if data[i] not in (0x00, 0xFF, 0xE5, 0x1A):
            end = i + 1
            break
        if len(data) - i > 100:
            end = i
            break
    return data[:end]


def write_manifest(output_path, img_path, dirscp, extracted_files):
    """Write extraction manifest."""
    manifest_path = os.path.join(output_path, "manifest.md") if output_path else "manifest.md"
    img_name = os.path.basename(img_path)

    with open(manifest_path, "w") as f:
        fmt = "DIRSCP" if dirscp else "CP/M"
        f.write(f"# {img_name}\n\n")
        f.write("## Disk Information\n\n")
        f.write(f"- **Format:** CPC DSK ({fmt})\n")
        f.write(f"- **Source image:** {img_name}\n\n")
        f.write("## Extracted Files\n\n")
        f.write("| # | Filename | Size | Extracted As |\n")
        f.write("|---|----------|------|--------------|\n")
        for i, (name, path) in enumerate(extracted_files, 1):
            ext_name = os.path.basename(path) if path else "*(failed)*"
            size = os.path.getsize(path) if path and os.path.exists(path) else "?"
            f.write(f"| {i} | {name} | {size} | {ext_name} |\n")

    print(f"Manifest written to {manifest_path}")


def extract_dirscp(data, root_entries, subdirs, output_dir, specific, verbose):
    """Extract files from a DIRSCP disk."""
    os.makedirs(output_dir, exist_ok=True)
    extracted = []

    def do_extract(entry, dest_dir):
        """Extract a single file entry. Returns (display_name, output_path)."""
        filename = entry['name']
        if entry['type']:
            filename += '.' + entry['type']

        if specific and entry['name'].strip() != specific.strip():
            return None

        if not entry.get('tracks'):
            return None

        print(f"  Extracting: {filename}")
        file_data = extract_file_data(data, entry['tracks'], verbose)
        if not file_data:
            print(f"    -> Failed")
            return (filename, None)

        file_data = trim_padding(file_data)
        safe = make_safe_filename(filename)
        if not safe:
            print(f"    -> Unsafe filename, skipping")
            return (filename, None)

        out_path = unique_path(os.path.join(dest_dir, safe))
        with open(out_path, 'wb') as f:
            f.write(file_data)
        print(f"    -> {os.path.basename(out_path)} ({len(file_data)} bytes)")
        return (filename, out_path)

    # Root-level files
    for entry in root_entries:
        if entry['is_directory']:
            dir_name = entry['name']
            sub = subdirs.get(dir_name, [])
            if not sub:
                continue
            print(f"\n{dir_name}/")
            subdir_path = os.path.join(output_dir, make_safe_filename(dir_name))
            os.makedirs(subdir_path, exist_ok=True)
            for fe in sub:
                if fe['is_directory']:
                    continue
                result = do_extract(fe, subdir_path)
                if result:
                    extracted.append(result)
        else:
            result = do_extract(entry, output_dir)
            if result:
                extracted.append(result)

    return extracted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_arguments()

    if not os.path.exists(args.imgfile):
        print(f"Error: File '{args.imgfile}' not found")
        sys.exit(1)

    try:
        with open(args.imgfile, 'rb') as f:
            data = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)

    if not data.startswith(CPC_DSK_HEADER):
        print("Error: Not a valid Extended CPC DSK file")
        sys.exit(1)

    print(f"Disk: {os.path.basename(args.imgfile)}")

    root_entries, subdirs, dirscp = scan_disk(data, verbose=args.verbose)

    if not root_entries:
        print("No files or directories found.")
        return

    if args.cat:
        display_catalog(data, root_entries, subdirs, dirscp)
        return

    # Extraction
    if not dirscp:
        print("CP/M format detected. Extraction is not supported for CP/M disks.")
        print("Use -c to display the catalog.")
        return

    output_dir = args.outdir or os.path.splitext(os.path.basename(args.imgfile))[0]
    print(f"Output directory: {output_dir}")

    extracted = extract_dirscp(data, root_entries, subdirs, output_dir,
                               args.specific, args.verbose)

    ok = sum(1 for _, p in extracted if p)
    print(f"\nExtracted {ok} file(s) to {output_dir}/")

    if extracted:
        write_manifest(output_dir, args.imgfile, dirscp, extracted)


if __name__ == "__main__":
    main()
