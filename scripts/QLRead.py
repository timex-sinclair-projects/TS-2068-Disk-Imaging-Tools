#!/usr/bin/env python3
"""
QLRead.py - Extract files from Sinclair QL floppy disk images (QL5A/QL5B format)

Handles standard QDOS floppy disk images (.img) with sector de-interleaving.
"""

import argparse
import os
import sys
import string
import struct
from datetime import datetime, timedelta

# QL5A format constants
QL5A_MAGIC = b"QL5A"
QL5B_MAGIC = b"QL5B"
LOGICAL_SECTOR_SIZE = 256
SECTORS_PER_GROUP = 6          # 6 logical sectors = 3 physical 512-byte sectors
GROUP_SIZE = LOGICAL_SECTOR_SIZE * SECTORS_PER_GROUP  # 1536 bytes
SECTORS_PER_CYLINDER = 18      # 9 per side * 2 sides
CYLINDER_SIZE = SECTORS_PER_CYLINDER * LOGICAL_SECTOR_SIZE  # 4608 bytes
SIDE_SIZE = 9 * LOGICAL_SECTOR_SIZE  # 2304 bytes

# Map entry status bytes
MAP_HEADER = 0xF8
MAP_ALLOCATED = 0x00
MAP_EOF = 0xFD
MAP_FREE_BYTE = 0x30

# Directory constants
DIR_ENTRY_SIZE = 64
DIR_HEADER_SIZE = 64

# QDOS file types
TYPE_DATA = 0
TYPE_EXEC = 1
TYPE_REL = 2
TYPE_DIR = 255
FILE_TYPE_NAMES = {0: "DATA", 1: "EXEC", 2: "REL", 255: "DIR"}

# QDOS epoch: 1961-01-01 00:00:00 UTC
QDOS_EPOCH = datetime(1961, 1, 1)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Extract files from Sinclair QL floppy disk images (QL5A format)")
    parser.add_argument("-f", "--imgfile", type=str, required=True,
                        help="IMG filename for input")
    parser.add_argument("-c", "--cat", action='store_true',
                        help="Catalog of disk image contents")
    parser.add_argument("-s", "--specific", type=str,
                        help="Name of a specific file to extract")
    parser.add_argument("-v", "--verbose", action='store_true',
                        help="Verbose output")
    return parser.parse_args()


def make_safe_filename(input_filename):
    """Convert filename to contain only safe characters"""
    safechars = string.ascii_letters + string.digits + "~ -_."
    return "".join(c for c in input_filename if c in safechars)


def unique_path(filepath):
    """Return filepath with a numeric suffix if it already exists."""
    if not os.path.exists(filepath):
        return filepath
    base, ext = os.path.splitext(filepath)
    counter = 2
    while os.path.exists(f"{base}_{counter}{ext}"):
        counter += 1
    return f"{base}_{counter}{ext}"


def qdos_date_to_string(raw_date):
    """Convert QDOS date (seconds since 1961-01-01) to human-readable string"""
    if raw_date == 0:
        return "(no date)"
    try:
        dt = QDOS_EPOCH + timedelta(seconds=raw_date)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError):
        return f"(invalid: 0x{raw_date:08X})"


def get_file_type_name(type_code):
    """Get human-readable file type name"""
    return FILE_TYPE_NAMES.get(type_code, f"Unknown ({type_code})")


def read_disk_header(data):
    """Parse the QL5A/QL5B disk header"""
    if len(data) < 96:
        raise ValueError("Image too small for QL format")

    magic = data[0:4]
    if magic not in (QL5A_MAGIC, QL5B_MAGIC):
        raise ValueError(f"Not a QL disk image (magic: {magic})")

    header = {
        "format": magic.decode('ascii'),
        "label": data[4:14].decode('ascii', errors='replace').strip(),
        "random_id": struct.unpack('>H', data[14:16])[0],
        "update_count": struct.unpack('>H', data[16:18])[0],
        "free_sectors": struct.unpack('>H', data[18:20])[0],
        "good_sectors": struct.unpack('>H', data[20:22])[0],
        "total_sectors": struct.unpack('>H', data[22:24])[0],
        "sectors_per_track": struct.unpack('>H', data[26:28])[0],
        "sectors_per_cylinder": struct.unpack('>H', data[28:30])[0],
        "tracks": struct.unpack('>H', data[30:32])[0],
        "sectors_per_group": struct.unpack('>H', data[32:34])[0],
        "dir_entries": struct.unpack('>H', data[36:38])[0],
        "interleave": list(data[0x28:0x3A]),
    }

    header["num_groups"] = len(data) // GROUP_SIZE

    return header


def logical_to_image_offset(logical_sector, interleave):
    """Convert a logical sector number to its byte offset in the image.

    The image stores physical sectors in track order. The interleave
    table maps logical sector positions within a cylinder to their
    physical (side, sector) placement.
    """
    cylinder = logical_sector // SECTORS_PER_CYLINDER
    pos_in_cyl = logical_sector % SECTORS_PER_CYLINDER
    phys = interleave[pos_in_cyl]
    side = 1 if phys >= 0x80 else 0
    sector = phys & 0x7F
    return cylinder * CYLINDER_SIZE + side * SIDE_SIZE + sector * LOGICAL_SECTOR_SIZE


def read_group_data(data, group_num, interleave):
    """Read a group's data (1536 bytes = 6 logical sectors) from the image,
    applying sector de-interleaving."""
    result = bytearray()
    base_sector = group_num * SECTORS_PER_GROUP
    for i in range(SECTORS_PER_GROUP):
        ls = base_sector + i
        offset = logical_to_image_offset(ls, interleave)
        if offset + LOGICAL_SECTOR_SIZE <= len(data):
            result.extend(data[offset:offset + LOGICAL_SECTOR_SIZE])
        else:
            result.extend(b'\x00' * LOGICAL_SECTOR_SIZE)
    return bytes(result)


def parse_allocation_map(data, header):
    """Parse the block allocation map.

    The map starts at byte 0x60 in logical sector 0 and uses 3 bytes per group.
    Returns a dict mapping file_id -> [(group_num, block_seq), ...].
    """
    map_start = 0x60
    num_entries = header["num_groups"]
    files = {}

    for g in range(num_entries):
        offset = map_start + g * 3
        if offset + 3 > len(data):
            break
        b0, b1, b2 = data[offset], data[offset + 1], data[offset + 2]

        # Skip non-allocated entries (byte 0 must be 0x00 for allocated)
        if b0 != MAP_ALLOCATED:
            continue
        # Skip empty/null entries
        if b1 == 0x00 and b2 == 0x00:
            continue

        file_id = b1 >> 4
        block_seq = ((b1 & 0x0F) << 8) | b2

        if file_id not in files:
            files[file_id] = []
        files[file_id].append((g, block_seq))

    return files


def read_directory(data, header):
    """Read directory entries from the system area of the disk.

    The directory occupies groups 3-5 (system/reserved groups) and consists
    of a 64-byte header followed by 64-byte file entries.
    """
    interleave = header["interleave"]
    max_entries = header["dir_entries"]

    # Read directory data from system groups (groups 3, 4, 5)
    dir_data = bytearray()
    for g in range(3, 6):
        dir_data.extend(read_group_data(data, g, interleave))

    entries = []
    # Skip 64-byte directory header
    for i in range(max_entries):
        offset = DIR_HEADER_SIZE + i * DIR_ENTRY_SIZE
        if offset + DIR_ENTRY_SIZE > len(dir_data):
            break

        entry = dir_data[offset:offset + DIR_ENTRY_SIZE]

        # Parse entry fields
        fl_length = struct.unpack('>I', entry[0:4])[0]
        fl_access = entry[4]
        fl_type = entry[5]
        fl_data = struct.unpack('>I', entry[6:10])[0]
        fl_extra = struct.unpack('>I', entry[10:14])[0]
        fl_nlen = struct.unpack('>H', entry[14:16])[0]

        # Validate: skip empty/invalid entries
        if fl_nlen == 0 or fl_nlen > 36 or fl_type > 2:
            continue

        fl_name = entry[16:16 + fl_nlen].decode('ascii', errors='replace')
        fl_date = struct.unpack('>I', entry[52:56])[0]
        fl_ver = struct.unpack('>H', entry[56:58])[0]
        fl_fileno = struct.unpack('>H', entry[58:60])[0]

        file_entry = {
            "index": i,
            "filename": fl_name,
            "length": fl_length,
            "access": fl_access,
            "type": fl_type,
            "data_space": fl_data,
            "extra": fl_extra,
            "date": fl_date,
            "version": fl_ver,
            "fileno": fl_fileno,
            "map_id": fl_fileno - 1,
        }
        entries.append(file_entry)

    return entries


def extract_file_data(data, header, file_map, file_entry, verbose=False):
    """Extract a file's data from the disk image using the allocation map."""
    map_id = file_entry["map_id"]
    interleave = header["interleave"]

    if map_id not in file_map:
        if verbose:
            print(f"  Warning: map_id {map_id} not found in allocation map")
        return None

    groups = sorted(file_map[map_id], key=lambda x: x[1])
    file_length = file_entry["length"]
    allocated = len(groups) * GROUP_SIZE

    if verbose:
        print(f"  {len(groups)} groups allocated ({allocated} bytes), "
              f"file declares {file_length} bytes")

    if allocated < file_length:
        if verbose:
            print(f"  Warning: allocated space ({allocated}) < file length ({file_length})")
        file_length = min(file_length, allocated)

    file_data = bytearray()
    for group_num, block_seq in groups:
        group_data = read_group_data(data, group_num, interleave)
        file_data.extend(group_data)

    return bytes(file_data[:file_length])


def write_file(output_path, file_entry, file_data):
    """Write extracted file data to disk."""
    filename = file_entry["filename"].strip()
    safe_filename = make_safe_filename(filename)
    if not safe_filename:
        print(f"  Warning: unsafe filename '{filename}', skipping")
        return []

    if output_path:
        safe_filename = os.path.join(output_path, safe_filename)

    out_path = unique_path(safe_filename)
    with open(out_path, "wb") as f:
        f.write(file_data)

    return [out_path]


def write_manifest(output_path, img_path, header, extracted_files):
    """Write a markdown manifest describing the disk contents."""
    manifest_path = os.path.join(output_path, "manifest.md") if output_path else "manifest.md"
    img_name = os.path.basename(img_path)

    with open(manifest_path, "w") as f:
        f.write(f"# {img_name}\n\n")
        f.write("## Disk Information\n\n")
        f.write(f"- **Format:** {header['format']} (Sinclair QL floppy)\n")
        if header['label']:
            f.write(f"- **Label:** {header['label']}\n")
        f.write(f"- **Tracks:** {header['tracks']}\n")
        f.write(f"- **Sectors/track:** {header['sectors_per_track']}\n")
        f.write(f"- **Total sectors:** {header['total_sectors']}\n")
        f.write(f"- **Source image:** {img_name}\n")
        f.write("\n")

        f.write("## Extracted Files\n\n")
        f.write("| # | Filename | Type | Size | Date | Extracted As |\n")
        f.write("|---|----------|------|------|------|--------------|\n")
        for i, (entry, paths) in enumerate(extracted_files, 1):
            orig = entry["filename"]
            kind = get_file_type_name(entry["type"])
            size = entry["length"]
            date = qdos_date_to_string(entry["date"])
            if paths:
                names = ", ".join(os.path.basename(p) for p in paths)
            else:
                names = "*(failed)*"
            f.write(f"| {i} | {orig} | {kind} | {size:,} | {date} | {names} |\n")

    print(f"Manifest written to {manifest_path}")


def display_catalog(header, catalog):
    """Display catalog of disk contents."""
    fmt = header["format"]
    label = header["label"] if header["label"] else "(blank)"

    print(f"Disk: {fmt}  Label: {label}")
    print(f"Tracks: {header['tracks']}  Sectors/track: {header['sectors_per_track']}  "
          f"Total sectors: {header['total_sectors']}")
    print(f"Max directory entries: {header['dir_entries']}")
    print()
    print(f"{'#':>3} {'Filename':<20} {'Type':>4} {'Length':>10} {'DataSpace':>10} "
          f"{'Date':>20} {'FileNo':>4}")
    print("-" * 80)

    for entry in catalog:
        kind = get_file_type_name(entry["type"])
        date = qdos_date_to_string(entry["date"])
        ds = f"{entry['data_space']:,}" if entry["type"] == TYPE_EXEC else "-"
        print(f"{entry['index']:>3} {entry['filename']:<20} {kind:>4} "
              f"{entry['length']:>10,} {ds:>10} {date:>20} {entry['fileno']:>4}")

    print()
    print(f"{len(catalog)} file(s)")


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

    try:
        header = read_disk_header(data)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    catalog = read_directory(data, header)

    if not catalog:
        print("No files found in directory.")
        return

    if args.cat:
        display_catalog(header, catalog)
        return

    # Parse allocation map for extraction
    file_map = parse_allocation_map(data, header)

    print(f"Processing: {args.imgfile}")
    print(f"Format: {header['format']}  "
          f"Geometry: {header['tracks']}T × 2S × {header['sectors_per_track']}SPT")

    # Create output directory
    output_path = os.path.splitext(os.path.basename(args.imgfile))[0]
    try:
        os.makedirs(output_path, exist_ok=True)
        print(f"Output directory: {output_path}")
    except Exception as e:
        print(f"Error creating directory: {e}")
        output_path = ''

    extracted_files = []

    files_to_extract = catalog
    if args.specific:
        files_to_extract = [e for e in catalog
                            if e["filename"].strip() == args.specific.strip()]
        if not files_to_extract:
            print(f"File '{args.specific}' not found in catalog")
            sys.exit(1)

    for entry in files_to_extract:
        name = entry["filename"]
        kind = get_file_type_name(entry["type"])
        print(f"Extracting: {name} ({kind}, {entry['length']:,} bytes)")

        file_data = extract_file_data(data, header, file_map, entry,
                                      verbose=args.verbose)
        paths = []
        if file_data:
            paths = write_file(output_path, entry, file_data)
            if paths:
                print(f"  -> {os.path.basename(paths[0])} ({len(file_data):,} bytes)")
        else:
            print(f"  -> Failed to extract {name}")

        extracted_files.append((entry, paths))

    if extracted_files:
        write_manifest(output_path, args.imgfile, header, extracted_files)


if __name__ == "__main__":
    main()
