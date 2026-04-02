import argparse
import os
import sys
import string

# Oliger disk format constants
BLOCK_SIZE = 5120
DIR_OFFSET = 0x600  # 1536 - Directory starts at 600h
DIR_HEADER_SIZE = 32
DIR_ENTRY_OFFSET = 0x620  # 1568 - Directory entries start at 620h
DIR_ENTRY_SIZE = 20
DIR_END_MARKER = 0x80  # 128

# File type codes
TYPE_BASIC = 0
TYPE_NUM_ARRAY = 1
TYPE_STR_ARRAY = 2
TYPE_CODE = 3

FILE_TYPE_NAMES = ["BASIC", "Numeric array", "String array", "CODE"]

# ABS state save detection: JLO SAFE saves 48.5K from 0x3E00-0xFFFF (49664 bytes)
ABS_SAVE_START = 0x3E00
ABS_SAVE_SIZE = 49664  # 0xFFFF - 0x3E00 + 1
ABS_SAVE_MIN = 45000   # threshold for detection

# V1 format constants
V1_SLOT_CYLINDERS = 5
V1_SLOT_SIZE = V1_SLOT_CYLINDERS * BLOCK_SIZE  # 25600 bytes per slot

def parse_arguments():
    parser = argparse.ArgumentParser(description="Extract files from Oliger disk images")
    parser.add_argument("-f", "--imgfile", type=str, required=True,
                       help="IMG filename for input")
    parser.add_argument("-c", "--cat", action='store_true',
                       help="Catalog of disk image contents")
    parser.add_argument("-s", "--specific", type=str,
                       help="Name of a specific program to extract")
    return parser.parse_args()

def make_safe_filename(input_filename):
    """Convert filename to contain only safe characters"""
    safechars = string.ascii_letters + string.digits + "~ -_."
    return "".join(c for c in input_filename if c in safechars)

def unique_path(filepath):
    """Return filepath with a numeric suffix if it already exists.

    Given 'dir/foo.tap', returns 'dir/foo.tap' if it doesn't exist,
    otherwise 'dir/foo_2.tap', 'dir/foo_3.tap', etc.
    """
    if not os.path.exists(filepath):
        return filepath
    base, ext = os.path.splitext(filepath)
    counter = 2
    while os.path.exists(f"{base}_{counter}{ext}"):
        counter += 1
    return f"{base}_{counter}{ext}"

def calculate_cylinder_number(cylinder_bytes):
    """Calculate cylinder number from directory entry bytes.

    byte[0] = track number, byte[1] = side (0x00=side 0, 0xFF=side 1).
    Cylinders alternate sides: cyl 0 = track 0 side 0, cyl 1 = track 0 side 1,
    cyl 2 = track 1 side 0, etc.
    """
    result = cylinder_bytes[0] * 2
    if cylinder_bytes[1] != 0:
        result += 1
    return result

def calculate_crc(data):
    """Calculate XOR checksum for TAP data"""
    result = 0
    for byte in data:
        result ^= byte
    return result.to_bytes(1, "little")

def detect_format_version(first_block):
    """Detect whether a disk image is JLO SAFE V1 or V2 format.

    V2 has a valid catalog header at offset 0x600 with sensible track/side
    values.  V1 has no catalog — the area is either 0xE5 fill or zeroed.
    """
    tracks = first_block[DIR_OFFSET]
    sides = first_block[DIR_OFFSET + 1]
    if 2 <= tracks <= 255 and sides in (1, 2):
        return "V2"
    return "V1"


def parse_v1_boot_basic(first_block):
    """Parse the V1 boot BASIC program to extract file names and numbers.

    The boot program starts at byte 4 of the image (after a 4-byte header
    containing prog_length and vars_offset, both little-endian).  It uses
    PRINT statements for the menu and LOAD /n commands to load files.

    The menu maps keys to file numbers:
      keys '1'-'9'  -> LOAD /1 through LOAD /9  (via LOAD /VAL a$)
      key  '0'      -> LOAD /10
      keys 'A'-'F'  -> LOAD /11 through LOAD /16
    """
    import struct as _st

    prog_len = _st.unpack_from('<H', first_block, 0)[0]
    vars_off = _st.unpack_from('<H', first_block, 2)[0]

    offset = 4
    end = 4 + min(vars_off, prog_len, len(first_block) - 4)

    # Collect menu items (key -> display name) and explicit LOAD /n numbers
    menu_entries = {}   # key_char -> display_name
    explicit_loads = {} # file_number -> True
    has_load_val = False  # LOAD /VAL a$ detected (handles files 1-9)

    while offset + 4 <= end:
        line_num = _st.unpack_from('>H', first_block, offset)[0]
        line_len = _st.unpack_from('<H', first_block, offset + 2)[0]
        if line_num > 9999 or line_len > 500 or line_len == 0:
            break
        line_data = first_block[offset + 4:offset + 4 + line_len]

        # Extract menu items from PRINT statements: "X. Program Name"
        qstart = line_data.find(0x22)
        if qstart != -1:
            qend = line_data.find(0x22, qstart + 1)
            if qend != -1:
                text = line_data[qstart + 1:qend].decode('ascii', errors='replace').strip()
                if len(text) > 3 and text[1] == '.':
                    key = text[0].upper()
                    name = text[3:].strip()
                    paren = name.find('(')
                    if paren > 0:
                        name = name[:paren].strip()
                    if name:
                        menu_entries[key] = name

        # Scan for LOAD / patterns  (token 0xEF = LOAD, then 0x2F = '/')
        i = 0
        while i < len(line_data) - 2:
            if line_data[i] == 0xEF and line_data[i + 1] == 0x2F:
                i += 2
                # Check what follows the /
                if i < len(line_data) and line_data[i] == 0xB0:
                    # 0xB0 = VAL token -> LOAD /VAL a$ (handles digits 1-9)
                    has_load_val = True
                else:
                    # Literal digit(s) -> LOAD /10, /11, etc.
                    digits = ''
                    while i < len(line_data) and 0x30 <= line_data[i] <= 0x39:
                        digits += chr(line_data[i])
                        i += 1
                    if i < len(line_data) and line_data[i] == 0x0E:
                        i += 6  # skip inline number
                    if digits:
                        explicit_loads[int(digits)] = True
                continue
            i += 1

        offset += 4 + line_len

    # Build the file number -> name mapping.
    # Key '1'-'9' -> file 1-9 (via LOAD /VAL a$)
    # Key '0'     -> file 10 (via LOAD /10)
    # Key 'A'-'F' -> file 11-16 (via LOAD /11 - /16)
    key_to_file = {}
    for ch in '123456789':
        key_to_file[ch] = int(ch)
    key_to_file['0'] = 10
    for i, ch in enumerate('ABCDEF'):
        key_to_file[ch] = 11 + i

    file_names = {}
    file_numbers = []

    if has_load_val:
        for n in range(1, 10):
            file_numbers.append(n)

    for fnum in sorted(explicit_loads):
        if fnum > 0 and fnum not in file_numbers:
            file_numbers.append(fnum)

    file_numbers.sort()

    # Map names from menu entries
    for key, name in menu_entries.items():
        fnum = key_to_file.get(key)
        if fnum is not None:
            file_names[fnum] = name
            if fnum not in file_numbers:
                file_numbers.append(fnum)

    file_numbers.sort()

    # Fill in any missing names
    for fnum in file_numbers:
        if fnum not in file_names:
            file_names[fnum] = f"File {fnum}"

    return {
        "prog_len": prog_len,
        "vars_off": vars_off,
        "file_numbers": file_numbers,
        "names": file_names,
    }


def read_v1_catalog(img_path):
    """Build a virtual catalog for a V1 disk by parsing the boot BASIC
    and probing each 5-cylinder file slot for data."""
    try:
        with open(img_path, 'rb') as f:
            first_block = f.read(BLOCK_SIZE)
            file_size = os.path.getsize(img_path)

        boot = parse_v1_boot_basic(first_block)

        print(f"Format: JLO SAFE V1")
        print(f"File size: {file_size}")
        print(f"Files detected: {len(boot['file_numbers'])}")

        file_directory = []

        with open(img_path, 'rb') as f:
            for fnum in boot["file_numbers"]:
                slot_offset = fnum * V1_SLOT_SIZE
                if slot_offset + V1_SLOT_SIZE > file_size:
                    print(f"Warning: File {fnum} slot extends past end of image")
                    continue

                f.seek(slot_offset)
                slot_data = f.read(V1_SLOT_SIZE)

                # Skip empty slots
                if all(b == 0xE5 for b in slot_data[:512]):
                    # First sector is all e5 — check sector 4 (offset 0x600)
                    # which may contain file data in V1 format
                    if slot_offset + 0x600 < file_size:
                        f.seek(slot_offset + 0x600)
                        probe = f.read(512)
                        if all(b == 0xE5 for b in probe):
                            continue
                    else:
                        continue

                name = boot["names"].get(fnum, f"File {fnum}")
                entry = {
                    "filename": name[:10].ljust(10),
                    "filetype": TYPE_CODE,      # default; refined below
                    "filesize": 0,              # computed during extraction
                    "staline": 0,
                    "param2": 0,
                    "cylinder": fnum * V1_SLOT_CYLINDERS,
                    "cylused": V1_SLOT_CYLINDERS,
                    "v1_file_number": fnum,
                }
                file_directory.append(entry)

        return file_directory

    except Exception as e:
        print(f"Error reading V1 catalog: {e}")
        return []


def read_v1_file_data(img_path, file_entry):
    """Read and classify a V1 file from its 5-cylinder slot.

    V1 files have no catalog metadata, so we detect the file type
    heuristically from the data content.
    """
    import struct as _st

    try:
        with open(img_path, 'rb') as f:
            cyl = file_entry["cylinder"]
            ncyl = file_entry["cylused"]
            f.seek(cyl * BLOCK_SIZE)
            raw = f.read(ncyl * BLOCK_SIZE)

        # Strip trailing e5 fill to find the effective data length
        end = len(raw)
        while end > 0 and raw[end - 1] == 0xE5:
            end -= 1
        # Also strip trailing zeros — many saves zero-pad
        data_end = end
        while data_end > 0 and raw[data_end - 1] == 0x00:
            data_end -= 1
        if data_end == 0:
            data_end = end  # all zeros is valid data (e.g. cleared screen)

        # Determine where the real data starts.
        # Even-numbered slots may have e5-filled sectors 1-3 in the first
        # cylinder(s).  Find the first non-e5 byte.
        data_start = 0
        while data_start < len(raw) and raw[data_start] == 0xE5:
            data_start += 1
        # Align to sector boundary
        data_start = (data_start // 512) * 512

        effective = raw[data_start:end]
        if not effective:
            return None

        # --- Heuristic type detection ---

        # Check for BASIC program header (4 bytes: prog_len + vars_offset)
        if len(effective) >= 8:
            prog_len = _st.unpack_from('<H', effective, 0)[0]
            vars_off = _st.unpack_from('<H', effective, 2)[0]
            diff = prog_len - vars_off
            if (0 < prog_len < len(effective)
                    and 0 < vars_off <= prog_len
                    and 0 <= diff < 1000):
                # Verify first BASIC line structure at offset 4
                if len(effective) > 8:
                    test_line = _st.unpack_from('>H', effective, 4)[0]
                    test_len = _st.unpack_from('<H', effective, 6)[0]
                    if 0 < test_line < 10000 and 0 < test_len < 500:
                        # Looks like a BASIC program
                        basic_data = effective[4:4 + prog_len]
                        file_entry["filetype"] = TYPE_BASIC
                        file_entry["filesize"] = prog_len
                        file_entry["staline"] = test_line  # autostart = first line
                        file_entry["param2"] = vars_off
                        file_entry["fileContent"] = bytearray(basic_data)
                        return file_entry

        # Not BASIC — treat as CODE.
        # Use the full effective data range.
        file_entry["filetype"] = TYPE_CODE
        file_entry["filesize"] = len(effective)
        file_entry["staline"] = 0  # unknown start address; default 0
        file_entry["param2"] = 32768
        file_entry["fileContent"] = bytearray(effective)
        return file_entry

    except Exception as e:
        print(f"Error reading V1 file data: {e}")
        return None


def read_catalog(img_path):
    """Read the file catalog from Oliger disk image"""
    try:
        with open(img_path, 'rb') as f:
            # Read first block containing directory
            f.seek(0)
            first_block = f.read(BLOCK_SIZE)

            if len(first_block) < DIR_ENTRY_OFFSET + DIR_ENTRY_SIZE:
                raise ValueError("Image file too small for Oliger format")

            # Parse directory header at offset 0x600
            dir_header = first_block[DIR_OFFSET:DIR_OFFSET + DIR_HEADER_SIZE]
            tracks = dir_header[0]
            sides = dir_header[1]
            total_cylinders = dir_header[2]
            available_cylinders = dir_header[4]
            disk_name = dir_header[16:32].decode('ascii', errors='ignore').rstrip()

            file_size = os.path.getsize(img_path)

            print(f"Disk: {disk_name}")
            print(f"Sides: {sides}")
            print(f"Tracks: {tracks}")
            print(f"Total cylinders: {total_cylinders}")
            print(f"Available cylinders: {available_cylinders}")
            print(f"File size: {file_size}")

            # Validate disk parameters
            if sides == 1 and file_size > 400000:
                log_bad_file(img_path, "Single sided imaged as double sided.")
                sys.exit("Extraction ended. Single sided disk with too many bytes.")

            # Parse directory entries starting at 0x620
            file_directory = []
            entry_offset = DIR_ENTRY_OFFSET

            while entry_offset + DIR_ENTRY_SIZE <= len(first_block):
                entry = first_block[entry_offset:entry_offset + DIR_ENTRY_SIZE]

                # Check for end of directory marker
                if entry[0] == DIR_END_MARKER:
                    break

                # Parse directory entry
                file_entry = {
                    "filename": entry[0:10].decode('ascii', errors='ignore'),
                    "filetype": entry[10],
                    "filesize": int.from_bytes(entry[11:13], "little"),
                    "staline": int.from_bytes(entry[13:15], "little"),
                    "param2": int.from_bytes(entry[15:17], "little"),
                    "cylinder": calculate_cylinder_number(entry[17:19]),
                    "cylused": entry[19]
                }

                file_directory.append(file_entry)
                entry_offset += DIR_ENTRY_SIZE

            return file_directory

    except Exception as e:
        print(f"Error reading catalog: {e}")
        return []

def read_file_data(img_path, file_entry):
    """Read file data from disk image"""
    try:
        with open(img_path, 'rb') as f:
            file_content = bytearray()

            start_cylinder = file_entry["cylinder"]
            cylinders_used = file_entry["cylused"]

            # Read all cylinders for this file
            for cyl_offset in range(cylinders_used):
                seek_position = (start_cylinder + cyl_offset) * BLOCK_SIZE
                f.seek(seek_position)

                cylinder_data = f.read(BLOCK_SIZE)
                if not cylinder_data:
                    print(f"Warning: Unable to read cylinder {start_cylinder + cyl_offset}")
                    break

                file_content.extend(cylinder_data)

            # Trim to actual file size
            file_entry["fileContent"] = file_content[:file_entry["filesize"]]
            return file_entry

    except Exception as e:
        print(f"Error reading file data: {e}")
        return None

def is_abs_state_save(file_data):
    """Detect if a file is a JLO SAFE ABS state save (full memory capture).

    ABS saves capture 48.5K from 0x3E00-0xFFFF. They are identified by:
    - Large file size (>= 45K)
    - BASIC file type with no meaningful autostart/vars offset
    """
    return (file_data["filesize"] >= ABS_SAVE_MIN and
            file_data["filetype"] == TYPE_BASIC and
            file_data["param2"] == 0)

def find_code_region(dump_data, origin):
    """Find the machine code region in a memory dump.

    Scans from the top of memory downward to find the extent of code,
    then uses RAMTOP from system variables to find the start.
    Returns (start, end) as absolute memory addresses.
    """
    # RAMTOP at 0x5CB2 (system variable)
    ramtop_offset = 0x5CB2 - origin
    if ramtop_offset + 2 <= len(dump_data) and ramtop_offset >= 0:
        ramtop = int.from_bytes(dump_data[ramtop_offset:ramtop_offset + 2], "little")
        code_start_addr = ramtop + 1
    else:
        # Fallback: assume code starts after standard BASIC area
        code_start_addr = 0xDA00

    # Find the end of code by scanning backward from top
    end_offset = len(dump_data) - 1
    while end_offset > 0 and dump_data[end_offset] == 0:
        end_offset -= 1
    code_end_addr = origin + end_offset

    return code_start_addr, code_end_addr

def build_basic_loader(clear_addr, entry_addr):
    """Build a ZX Spectrum BASIC loader program as raw bytes.

    Generates:
      10 CLEAR <clear_addr>
      20 LOAD ""CODE
      30 RANDOMIZE USR <entry_addr>
    """
    lines = bytearray()

    def add_line(line_num, tokens):
        line_body = bytearray(tokens) + b'\x0D'
        lines.extend(line_num.to_bytes(2, "big"))
        lines.extend(len(line_body).to_bytes(2, "little"))
        lines.extend(line_body)

    def num_literal(n):
        digits = str(n).encode('ascii')
        float_bytes = b'\x0E\x00\x00' + (n & 0xFFFF).to_bytes(2, "little") + b'\x00'
        return digits + float_bytes

    # Line 10: CLEAR <clear_addr>
    add_line(10, b'\xF9' + num_literal(clear_addr))
    # Line 20: LOAD ""CODE
    add_line(20, b'\xEF\x22\x22\xAF')
    # Line 30: RANDOMIZE USR <entry_addr>
    add_line(30, b'\xF5\xC0' + num_literal(entry_addr))

    return bytes(lines)

def build_tap_block(flag, data):
    """Build a single TAP block: 2-byte length + flag + data + checksum."""
    block = bytes([flag]) + data
    crc = 0
    for b in block:
        crc ^= b
    block += bytes([crc])
    return len(block).to_bytes(2, "little") + block

def write_abs_dump(output_path, file_data):
    """Write an ABS state save as a raw dump and a launchable TAP file."""
    try:
        filename = file_data["filename"].rstrip()
        safe_filename = make_safe_filename(filename)
        if not safe_filename:
            print(f"Unsafe filename: {filename}")
            return

        if output_path:
            safe_filename = os.path.join(output_path, safe_filename)

        dump_content = file_data["fileContent"]

        # Write raw dump
        dump_path = unique_path(safe_filename + ".dump")
        with open(dump_path, "wb") as f:
            f.write(dump_content)

        # Build a launchable TAP file
        code_start, code_end = find_code_region(dump_content, ABS_SAVE_START)
        code_data = dump_content[code_start - ABS_SAVE_START:code_end - ABS_SAVE_START + 1]
        clear_addr = code_start - 1
        entry_addr = code_start

        # BASIC loader
        loader = build_basic_loader(clear_addr, entry_addr)
        tap_name = filename[:10].ljust(10).encode('ascii')

        # TAP header for BASIC loader
        basic_header = (b'\x00' + tap_name +
                       len(loader).to_bytes(2, "little") +
                       (10).to_bytes(2, "little") +
                       len(loader).to_bytes(2, "little"))
        basic_header_block = build_tap_block(0x00, basic_header)
        basic_data_block = build_tap_block(0xFF, loader)

        # TAP header for CODE block
        code_header = (b'\x03' + tap_name +
                      len(code_data).to_bytes(2, "little") +
                      code_start.to_bytes(2, "little") +
                      (32768).to_bytes(2, "little"))
        code_header_block = build_tap_block(0x00, code_header)
        code_data_block = build_tap_block(0xFF, code_data)

        tap_data = (basic_header_block + basic_data_block +
                   code_header_block + code_data_block)

        tap_path = unique_path(safe_filename + ".tap")
        with open(tap_path, "wb") as f:
            f.write(tap_data)

        print(f"  -> Saved memory dump: {dump_path} "
              f"({file_data['filesize']} bytes, origin=0x{ABS_SAVE_START:04X})")
        print(f"  -> Saved launcher:    {tap_path} "
              f"(CLEAR {clear_addr}, LOAD CODE at 0x{code_start:04X}, "
              f"USR {entry_addr})")

        return [dump_path, tap_path]

    except Exception as e:
        print(f"Error writing dump file: {e}")
        return []

def write_tap_file(output_path, file_data):
    """Write file data in TAP format"""
    try:
        filename = file_data["filename"].rstrip()
        filetype = file_data["filetype"]

        # TAP param1 and param2 depend on file type:
        #   BASIC:     param1 = autostart line,  param2 = vars offset (prog length)
        #   CODE:      param1 = start address,   param2 = 32768
        #   NUM_ARRAY: param1 = 0,               param2 = variable name
        #   STR_ARRAY: param1 = 0,               param2 = variable name
        if filetype == TYPE_CODE:
            tap_param1 = file_data["staline"]   # start address
            tap_param2 = 32768
        elif filetype in (TYPE_NUM_ARRAY, TYPE_STR_ARRAY):
            tap_param1 = 0
            tap_param2 = file_data["param2"]
        else:
            # BASIC
            tap_param1 = file_data["staline"]   # autostart line
            tap_param2 = file_data["param2"]    # program length (vars offset)

        # Build TAP header (19 bytes + 2 byte length prefix)
        file_header = b'\x13\x00'

        # 10-byte filename for TAP header
        tap_name = file_data["filename"].encode('ascii', errors='replace')

        header_data = (b'\x00' +
                      filetype.to_bytes(1, "little") +
                      tap_name +
                      len(file_data["fileContent"]).to_bytes(2, "little") +
                      tap_param1.to_bytes(2, "little") +
                      tap_param2.to_bytes(2, "little"))

        header_crc = calculate_crc(header_data)
        header_data += header_crc

        # Build data block
        data_block = b'\xff' + file_data["fileContent"]
        data_crc = calculate_crc(data_block)
        data_block += data_crc

        data_block_len = len(data_block).to_bytes(2, "little")

        # Combine all parts
        tap_data = file_header + header_data + data_block_len + data_block

        # Write to file
        safe_filename = make_safe_filename(filename)
        if safe_filename:
            if output_path:
                safe_filename = os.path.join(output_path, safe_filename)

            tap_path = unique_path(safe_filename + ".tap")
            with open(tap_path, "wb") as f:
                f.write(tap_data)
            return [tap_path]
        else:
            print(f"Unsafe filename: {filename}")
            return []

    except Exception as e:
        print(f"Error writing TAP file: {e}")
        return []

def log_bad_file(filename, message):
    """Log problematic files"""
    try:
        with open("badfiles", "a") as f:
            f.write(f"{filename},{message}\n")
    except:
        pass

def get_file_type_name(type_code):
    """Get human-readable file type name"""
    if 0 <= type_code < len(FILE_TYPE_NAMES):
        return FILE_TYPE_NAMES[type_code]
    return f"Unknown ({type_code})"

def write_manifest(output_path, img_path, disk_info, extracted_files):
    """Write a markdown manifest describing the disk contents and extracted files."""
    manifest_path = os.path.join(output_path, "manifest.md") if output_path else "manifest.md"
    img_name = os.path.basename(img_path)

    with open(manifest_path, "w") as f:
        f.write(f"# {img_name}\n\n")
        f.write("## Disk Information\n\n")
        fmt_ver = disk_info.get("format_version", "V2")
        f.write(f"- **Format:** Oliger (JLO SAFE {fmt_ver})\n")
        if disk_info.get("disk_name"):
            f.write(f"- **Disk name:** {disk_info['disk_name']}\n")
        if fmt_ver == "V2":
            f.write(f"- **Sides:** {disk_info['sides']}\n")
            f.write(f"- **Tracks:** {disk_info['tracks']}\n")
        f.write(f"- **Total cylinders:** {disk_info['total_cylinders']}\n")
        f.write(f"- **Source image:** {img_name}\n")
        f.write("\n")

        f.write("## Extracted Files\n\n")
        f.write("| # | Disk Filename | Type | Size | Extracted As |\n")
        f.write("|---|---------------|------|------|--------------|\n")
        for i, (entry, paths) in enumerate(extracted_files, 1):
            orig = entry["filename"].rstrip()
            kind = get_file_type_name(entry["filetype"])
            size = entry["filesize"]
            if paths:
                names = ", ".join(os.path.basename(p) for p in paths)
            else:
                names = "*(failed)*"
            f.write(f"| {i} | {orig} | {kind} | {size} | {names} |\n")

    print(f"Manifest written to {manifest_path}")

def main():
    args = parse_arguments()

    if not os.path.exists(args.imgfile):
        print(f"Error: File '{args.imgfile}' not found")
        sys.exit(1)

    # Detect format version
    with open(args.imgfile, 'rb') as f:
        first_block = f.read(BLOCK_SIZE)

    version = detect_format_version(first_block)
    is_v1 = version == "V1"

    # Get catalog
    if is_v1:
        catalog = read_v1_catalog(args.imgfile)
    else:
        catalog = read_catalog(args.imgfile)

    if not catalog:
        print("Empty catalog.")
        return

    if args.cat:
        # Display catalog only
        print("Catalog")
        print("-" * 65)
        for entry in catalog:
            kind = get_file_type_name(entry["filetype"])
            extra = ""
            if is_v1:
                fnum = entry.get("v1_file_number", "?")
                # Read data to determine actual type and size
                file_data = read_v1_file_data(args.imgfile, entry.copy())
                if file_data:
                    kind = get_file_type_name(file_data["filetype"])
                    size = file_data["filesize"]
                else:
                    size = 0
                print(f'{entry["filename"]:12s} #{fnum:<3}  {kind:14s} {size:6d}  '
                      f'cyl {entry["cylinder"]:3d}  ({entry["cylused"]} cyl)')
            else:
                # Peek at file data to detect ABS saves
                file_data = read_file_data(args.imgfile, entry)
                if file_data and is_abs_state_save(file_data):
                    extra = " [ABS state save]"
                print(f'{entry["filename"]:12s} {kind:14s} {entry["filesize"]:6d}  '
                      f'cyl {entry["cylinder"]:3d}  ({entry["cylused"]} cyl){extra}')
        return

    print(f"Processing: {args.imgfile}")

    # Always create output directory using filename without extension
    output_path = os.path.splitext(os.path.basename(args.imgfile))[0]
    try:
        os.makedirs(output_path, exist_ok=True)
        print(f"Output directory: {output_path}")
    except Exception as e:
        print(f"Error creating directory: {e}")
        output_path = ''

    # Build disk info for manifest
    if is_v1:
        boot = parse_v1_boot_basic(first_block)
        disk_info = {
            "format_version": "V1",
            "tracks": 0,
            "sides": 0,
            "total_cylinders": os.path.getsize(args.imgfile) // BLOCK_SIZE,
            "disk_name": "",
        }
    else:
        dir_header = first_block[DIR_OFFSET:DIR_OFFSET + DIR_HEADER_SIZE]
        disk_info = {
            "format_version": "V2",
            "tracks": dir_header[0],
            "sides": dir_header[1],
            "total_cylinders": dir_header[2],
            "disk_name": dir_header[16:32].decode('ascii', errors='ignore').rstrip(),
        }

    extracted_files = []

    def extract_entry(entry):
        if is_v1:
            file_data = read_v1_file_data(args.imgfile, entry)
        else:
            file_data = read_file_data(args.imgfile, entry)
        paths = []
        if file_data:
            if not is_v1 and is_abs_state_save(file_data):
                paths = write_abs_dump(output_path, file_data)
            else:
                paths = write_tap_file(output_path, file_data)
        return file_data, paths

    # Process files
    if args.specific:
        found = False
        for entry in catalog:
            if entry["filename"].rstrip() == args.specific.rstrip():
                print(f"Extracting: {entry['filename']}")
                file_data, paths = extract_entry(entry)
                extracted_files.append((entry, paths))
                found = True
                break
        if not found:
            print(f"File '{args.specific}' not found in catalog")
    else:
        for entry in catalog:
            print(f"Extracting: {entry['filename']}")
            file_data, paths = extract_entry(entry)
            extracted_files.append((entry, paths))

    if extracted_files:
        write_manifest(output_path, args.imgfile, disk_info, extracted_files)

if __name__ == "__main__":
    main()
