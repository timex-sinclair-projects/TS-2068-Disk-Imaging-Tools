#!/usr/bin/env python3
"""
AercoRead.py - Extract files from Aerco FD / DOS-64 disk images

Handles Aerco FD disk images for the Timex/Sinclair 2068.  Supports both
DOS-64 formatted disks (with BASIC/CODE/MODULE files and TAP output) and
RP/M (CP/M clone) disks (catalog display).
"""

import argparse
import os
import sys
import string
import struct

# Disk geometry
SECTOR_SIZE = 512
SECTORS_PER_TRACK = 10
TRACK_SIZE = SECTOR_SIZE * SECTORS_PER_TRACK  # 5120 bytes

# Directory layout in track 0
DIR_START = 0x200          # Directory starts at byte 512 in track 0
DIR_ENTRY_SIZE = 32
BITMAP_SIZE = 32           # First 32 bytes at DIR_START are the allocation bitmap

# File type codes (matches ZX Spectrum convention for 0x00 and 0x03)
TYPE_BASIC = 0x00
TYPE_CODE = 0x03
TYPE_MODULE = 0x04         # Overlay/module (no per-file header on disk)
TYPE_DATA = 0x08           # Data file
TYPE_BITMAP = 0xFF         # Allocation bitmap (not a real file)

FILE_TYPE_NAMES = {
    0x00: "BASIC", 0x01: "Num array", 0x02: "Str array",
    0x03: "CODE", 0x04: "MODULE", 0x08: "DATA", 0xFF: "BITMAP",
}

# File header size on disk (type + name + metadata, before file content)
FILE_HEADER_SIZE = 17  # 1 (type) + 10 (name) + 2 (length) + 2 (param1) + 2 (param2)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Extract files from Aerco FD / DOS-64 disk images")
    parser.add_argument("-f", "--imgfile", type=str, required=True,
                        help="IMG filename for input")
    parser.add_argument("-c", "--cat", action='store_true',
                        help="Catalog of disk image contents")
    parser.add_argument("-s", "--specific", type=str,
                        help="Name of a specific file to extract")
    return parser.parse_args()


def make_safe_filename(input_filename):
    safechars = string.ascii_letters + string.digits + "~ -_."
    return "".join(c for c in input_filename if c in safechars)


def unique_path(filepath):
    if not os.path.exists(filepath):
        return filepath
    base, ext = os.path.splitext(filepath)
    counter = 2
    while os.path.exists(f"{base}_{counter}{ext}"):
        counter += 1
    return f"{base}_{counter}{ext}"


def calculate_crc(data):
    result = 0
    for byte in data:
        result ^= byte
    return result.to_bytes(1, "little")


def detect_format(data):
    """Detect whether this is a DOS-64 or RP/M disk.

    DOS-64 disks have a JR instruction at byte 0 (0x18), a disk name at
    bytes 6-15, and JP 0x3539 at bytes 16-18.  RP/M disks also start with
    0x18 but have different boot code and 'RP/M' in the name area.
    """
    if len(data) < TRACK_SIZE:
        return None

    if data[0] != 0x18:
        return None

    name = data[6:16].decode('ascii', errors='replace').rstrip('\x00 ')

    # Check for RP/M signature
    if 'RP/M' in name or 'RPM' in name:
        return "RPM"

    # DOS-64: JP 0x3539 at offset 16
    if data[16] == 0xC3 and data[17] == 0x39 and data[18] == 0x35:
        return "DOS64"

    # Fallback: check if directory area has valid entries
    if data[DIR_START] == TYPE_BITMAP:
        return "DOS64"

    return None


def read_disk_name(data):
    return data[6:16].decode('ascii', errors='replace').rstrip('\x00 ')


def block_to_offset(block_num, num_tracks):
    """Convert a block number to an image byte offset.

    Blocks 0x00-0x7F map to side 0 tracks (block N = track N).
    Blocks 0x80-0xFF map to side 1 tracks (block N = track N-0x80 on side 1).

    For interleaved images (side 0 track, side 1 track, side 0 track, ...):
      side 0 track T = offset T * 2 * TRACK_SIZE
      side 1 track T = offset (T * 2 + 1) * TRACK_SIZE

    For sequential images (all side 0, then all side 1):
      side 0 track T = offset T * TRACK_SIZE
      side 1 track T = offset (num_tracks/2 + T) * TRACK_SIZE

    We detect the layout by checking which interpretation produces valid data.
    """
    if block_num < 0x80:
        # Side 0
        return block_num * TRACK_SIZE
    else:
        # Side 1: stored as tracks 40-79 in a sequential-sides image
        half = num_tracks // 2
        return (half + (block_num - 0x80)) * TRACK_SIZE


def read_catalog(data):
    """Read the DOS-64 directory from track 0."""
    num_tracks = len(data) // TRACK_SIZE
    entries = []

    # Scan directory entries starting after the bitmap area
    offset = DIR_START
    while offset + DIR_ENTRY_SIZE <= TRACK_SIZE:
        entry = data[offset:offset + DIR_ENTRY_SIZE]

        # Skip empty entries
        if all(b in (0x00, 0xE5) for b in entry):
            offset += DIR_ENTRY_SIZE
            continue

        etype = entry[0]

        # Skip the bitmap entry
        if etype == TYPE_BITMAP:
            offset += DIR_ENTRY_SIZE
            continue

        # Extract filename (bytes 1-10, null-terminated)
        name_end = 1
        while name_end < 11 and entry[name_end] != 0:
            name_end += 1
        name = entry[1:name_end].decode('ascii', errors='replace')

        if not name:
            offset += DIR_ENTRY_SIZE
            continue

        # Extract metadata
        flen = struct.unpack_from('<H', entry, 11)[0]
        param1 = struct.unpack_from('<H', entry, 13)[0]
        param2 = struct.unpack_from('<H', entry, 15)[0]

        # Extract block list (bytes 17-31, non-zero values)
        blocks = [entry[b] for b in range(17, 32) if entry[b] != 0]

        file_entry = {
            "filename": name,
            "filetype": etype,
            "filesize": flen,
            "param1": param1,
            "param2": param2,
            "blocks": blocks,
        }
        entries.append(file_entry)
        offset += DIR_ENTRY_SIZE

    return entries


def read_file_data(data, file_entry):
    """Read file data from disk blocks.

    For types BASIC (0x00) and CODE (0x03), each block on disk starts with
    a 17-byte file header (type + name + metadata) followed by file content.
    Only the FIRST block has the header; subsequent blocks are pure data.

    For type MODULE (0x04), blocks contain raw data with no header.
    """
    num_tracks = len(data) // TRACK_SIZE
    blocks = file_entry["blocks"]
    etype = file_entry["filetype"]
    flen = file_entry["filesize"]

    if not blocks:
        return None

    file_content = bytearray()

    for i, block in enumerate(blocks):
        offset = block_to_offset(block, num_tracks)
        if offset + TRACK_SIZE > len(data):
            break

        track_data = data[offset:offset + TRACK_SIZE]

        if i == 0 and etype in (TYPE_BASIC, TYPE_CODE, TYPE_DATA):
            # First block: skip the 17-byte file header
            file_content.extend(track_data[FILE_HEADER_SIZE:])
        else:
            file_content.extend(track_data)

    # Trim to declared file length
    if etype in (TYPE_BASIC, TYPE_CODE, TYPE_DATA) and flen > 0:
        file_content = file_content[:flen]

    return bytes(file_content) if file_content else None


def write_tap_file(output_path, file_entry, file_data):
    """Write file in ZX Spectrum TAP format."""
    filename = file_entry["filename"]
    etype = file_entry["filetype"]
    flen = len(file_data)
    param1 = file_entry["param1"]
    param2 = file_entry["param2"]

    # Build 10-char padded name for TAP header
    tap_name = filename[:10].ljust(10).encode('ascii', errors='replace')

    # TAP type and parameters
    if etype == TYPE_BASIC:
        tap_type = b'\x00'
        tap_param1 = param1  # autostart line
        tap_param2 = param2  # program length (vars offset)
    elif etype == TYPE_CODE:
        tap_type = b'\x03'
        tap_param1 = param1  # start address
        tap_param2 = 32768
    else:
        tap_type = b'\x03'  # default to CODE
        tap_param1 = 0
        tap_param2 = 32768

    # TAP header block (19 bytes)
    header_data = (b'\x00' + tap_type + tap_name +
                   flen.to_bytes(2, 'little') +
                   tap_param1.to_bytes(2, 'little') +
                   tap_param2.to_bytes(2, 'little'))
    header_crc = calculate_crc(header_data)

    # TAP data block
    data_block = b'\xff' + file_data
    data_crc = calculate_crc(data_block)

    tap_data = (b'\x13\x00' + header_data + header_crc +
                len(data_block + data_crc).to_bytes(2, 'little') +
                data_block + data_crc)

    safe = make_safe_filename(filename)
    if not safe:
        return []

    if output_path:
        safe = os.path.join(output_path, safe)

    tap_path = unique_path(safe + ".tap")
    with open(tap_path, "wb") as f:
        f.write(tap_data)

    return [tap_path]


def write_raw_file(output_path, file_entry, file_data):
    """Write file as raw binary (for MODULE type)."""
    filename = file_entry["filename"]
    safe = make_safe_filename(filename)
    if not safe:
        return []

    if output_path:
        safe = os.path.join(output_path, safe)

    out_path = unique_path(safe + ".bin")
    with open(out_path, "wb") as f:
        f.write(file_data)

    return [out_path]


def get_file_type_name(type_code):
    return FILE_TYPE_NAMES.get(type_code, f"Type 0x{type_code:02x}")


def write_manifest(output_path, img_path, disk_name, extracted_files):
    manifest_path = os.path.join(output_path, "manifest.md") if output_path else "manifest.md"
    img_name = os.path.basename(img_path)

    with open(manifest_path, "w") as f:
        f.write(f"# {img_name}\n\n")
        f.write("## Disk Information\n\n")
        f.write(f"- **Format:** Aerco FD (DOS-64)\n")
        if disk_name:
            f.write(f"- **Disk name:** {disk_name}\n")
        f.write(f"- **Source image:** {img_name}\n\n")
        f.write("## Extracted Files\n\n")
        f.write("| # | Filename | Type | Size | Extracted As |\n")
        f.write("|---|----------|------|------|--------------|\n")
        for i, (entry, paths) in enumerate(extracted_files, 1):
            kind = get_file_type_name(entry["filetype"])
            size = entry["filesize"]
            if paths:
                names = ", ".join(os.path.basename(p) for p in paths)
            else:
                names = "*(failed)*"
            f.write(f"| {i} | {entry['filename']} | {kind} | {size} | {names} |\n")

    print(f"Manifest written to {manifest_path}")


# RP/M (CP/M) parameters
RPM_SYSTEM_TRACKS = 4      # Tracks 0-3 are system area
RPM_BLS = 2048             # Block size in bytes
RPM_DIR_TRACK = 4          # Directory is on first data track
RPM_RECORD_SIZE = 128      # CP/M record size


def read_rpm_catalog(data):
    """Read RP/M (CP/M 2.2) directory from track 4."""
    dir_offset = RPM_DIR_TRACK * TRACK_SIZE
    entries = []
    seen = {}  # Track multi-extent files: (name,ext) -> combined entry

    for j in range(0, TRACK_SIZE, 32):
        entry = data[dir_offset + j:dir_offset + j + 32]
        if len(entry) < 32:
            break

        user = entry[0]
        if user == 0xE5 or user > 0x0F:
            continue

        name = bytes(b & 0x7F for b in entry[1:9]).decode('ascii', errors='replace').rstrip()
        ext = bytes(b & 0x7F for b in entry[9:12]).decode('ascii', errors='replace').rstrip()
        if not name:
            continue

        extent = entry[12]
        rec_count = entry[15]
        blocks = [entry[b] for b in range(16, 32) if entry[b] != 0]

        key = (user, name, ext)
        if key in seen:
            # Merge extents — append blocks and add records
            seen[key]["blocks"].extend(blocks)
            seen[key]["records"] += rec_count
            seen[key]["extents"] += 1
        else:
            file_entry = {
                "filename": f"{name}.{ext}" if ext else name,
                "name": name,
                "ext": ext,
                "user": user,
                "records": rec_count,
                "blocks": blocks,
                "extents": 1,
            }
            seen[key] = file_entry
            entries.append(file_entry)

    return entries


def read_rpm_file_data(data, file_entry):
    """Read file data from RP/M disk using CP/M block allocation."""
    blocks = file_entry["blocks"]
    records = file_entry["records"]
    file_size = records * RPM_RECORD_SIZE

    content = bytearray()
    base_offset = RPM_SYSTEM_TRACKS * TRACK_SIZE

    for block in blocks:
        offset = base_offset + block * RPM_BLS
        if offset + RPM_BLS <= len(data):
            content.extend(data[offset:offset + RPM_BLS])

    # Trim to actual file size (records * 128)
    content = content[:file_size]

    # For text files (.DOC, .TXT), strip trailing CP/M EOF (0x1A)
    if file_entry.get("ext", "").upper() in ("DOC", "TXT", "ASM", "BAS", "SUB"):
        eof_pos = content.find(0x1A)
        if eof_pos >= 0:
            content = content[:eof_pos]

    return bytes(content) if content else None


def display_rpm_catalog(data):
    """Display RP/M (CP/M) disk catalog."""
    name = read_disk_name(data)
    num_tracks = len(data) // TRACK_SIZE
    entries = read_rpm_catalog(data)

    print(f"Disk: {name}")
    print(f"Format: RP/M (CP/M 2.2 clone)")
    print(f"Tracks: {num_tracks}")
    print()

    if not entries:
        print("No files found.")
        return

    print(f"{'Filename':<14s} {'Size':>7s}  {'Blocks':>6s}  {'Ext':>4s}")
    print("-" * 40)
    for entry in entries:
        size = entry["records"] * RPM_RECORD_SIZE
        nblocks = len(entry["blocks"])
        extents = entry["extents"]
        ext_str = f"x{extents}" if extents > 1 else ""
        print(f"{entry['filename']:<14s} {size:>7,}  {nblocks:>6d}  {ext_str:>4s}")

    print()
    print(f"{len(entries)} file(s)")


def main():
    args = parse_arguments()

    if not os.path.exists(args.imgfile):
        print(f"Error: File '{args.imgfile}' not found")
        sys.exit(1)

    with open(args.imgfile, 'rb') as f:
        data = f.read()

    fmt = detect_format(data)
    if fmt is None:
        print("Error: Not a recognized Aerco disk image")
        sys.exit(1)

    disk_name = read_disk_name(data)

    if fmt == "RPM":
        if args.cat:
            display_rpm_catalog(data)
            return

        # RP/M extraction
        catalog = read_rpm_catalog(data)
        if not catalog:
            print("Empty catalog.")
            return

        print(f"Processing: {args.imgfile}")
        print(f"Disk: {disk_name} (RP/M)")

        output_path = os.path.splitext(os.path.basename(args.imgfile))[0]
        try:
            os.makedirs(output_path, exist_ok=True)
            print(f"Output directory: {output_path}")
        except Exception as e:
            print(f"Error creating directory: {e}")
            output_path = ''

        extracted_files = []
        for entry in catalog:
            if args.specific and entry["filename"].strip() != args.specific.strip():
                continue

            print(f"Extracting: {entry['filename']}")
            file_data = read_rpm_file_data(data, entry)
            paths = []
            if file_data:
                safe = make_safe_filename(entry["filename"])
                if safe and output_path:
                    out_path = unique_path(os.path.join(output_path, safe))
                    with open(out_path, "wb") as f:
                        f.write(file_data)
                    paths = [out_path]
                    print(f"  -> {os.path.basename(out_path)} ({len(file_data):,} bytes)")
            else:
                print(f"  -> Failed to extract")

            extracted_files.append(({"filename": entry["filename"],
                                     "filetype": 0x03,
                                     "filesize": len(file_data) if file_data else 0},
                                    paths))

        if extracted_files:
            write_manifest(output_path, args.imgfile, disk_name, extracted_files)
        return

    # DOS-64 format
    catalog = read_catalog(data)

    if not catalog:
        print("Empty catalog.")
        return

    if args.cat:
        print(f"Disk: {disk_name}")
        print(f"Format: Aerco FD (DOS-64)")
        num_tracks = len(data) // TRACK_SIZE
        sides = 2 if num_tracks > 40 else 1
        print(f"Tracks: {num_tracks // sides}, Sides: {sides}")
        print()
        print(f"{'Filename':<14s} {'Type':<8s} {'Size':>6s} {'Param1':>7s} {'Param2':>7s}  Blocks")
        print("-" * 70)
        for entry in catalog:
            kind = get_file_type_name(entry["filetype"])
            if entry["filetype"] in (TYPE_BASIC, TYPE_CODE, TYPE_DATA):
                print(f"{entry['filename']:<14s} {kind:<8s} {entry['filesize']:>6d} "
                      f"{entry['param1']:>7d} {entry['param2']:>7d}  {entry['blocks']}")
            else:
                print(f"{entry['filename']:<14s} {kind:<8s} {'':>6s} "
                      f"{'':>7s} {'':>7s}  {entry['blocks']}")
        return

    # Extraction
    print(f"Processing: {args.imgfile}")
    print(f"Disk: {disk_name}")

    output_path = os.path.splitext(os.path.basename(args.imgfile))[0]
    try:
        os.makedirs(output_path, exist_ok=True)
        print(f"Output directory: {output_path}")
    except Exception as e:
        print(f"Error creating directory: {e}")
        output_path = ''

    extracted_files = []

    for entry in catalog:
        if args.specific and entry["filename"].strip() != args.specific.strip():
            continue

        print(f"Extracting: {entry['filename']}")

        file_data = read_file_data(data, entry)
        paths = []

        if file_data:
            if entry["filetype"] in (TYPE_BASIC, TYPE_CODE, TYPE_DATA):
                paths = write_tap_file(output_path, entry, file_data)
            else:
                paths = write_raw_file(output_path, entry, file_data)

            if paths:
                print(f"  -> {os.path.basename(paths[0])} ({len(file_data):,} bytes)")
        else:
            print(f"  -> Failed to extract")

        extracted_files.append((entry, paths))

    if extracted_files:
        write_manifest(output_path, args.imgfile, disk_name, extracted_files)


if __name__ == "__main__":
    main()
