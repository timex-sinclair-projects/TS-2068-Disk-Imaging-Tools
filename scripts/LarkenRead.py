import argparse
import os
import sys
import string

# Directory markers
DIR_START = 0xFF  # 255
BLOCK_LIST_START = 0xFD  # 253
BLOCK_LIST_END = 0xF9  # 249
DIR_END = 0xFA  # 250
UNUSED_ENTRY = 0xFE  # 254
TRACK_MAP_USED = 0xF5  # 245 - block in use marker in track map

# File type codes
TYPE_BASIC = b'\x00'
TYPE_NUM_ARRAY = b'\x01'
TYPE_STR_ARRAY = b'\x02'
TYPE_CODE = b'\x03'

BLOCK_SIZE = 5120
TRACK_MAP_OFFSET = 24  # Track map starts at byte 24 in block 0

# Memory dump detection: TS-2068/ZX Spectrum RAM starts at 0x4000 (16384)
# and a full 48K dump would be ~49152 bytes. Files matching this pattern
# are machine state captures, not normal BASIC/CODE programs.
MEMORY_START = 16384   # 0x4000 - start of RAM
MEMORY_DUMP_MIN = 40960  # 40K threshold - anything this large from 0x4000 is a dump

def parse_arguments():
    parser = argparse.ArgumentParser(description="Extract files from Larken disk images")
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

def get_file_type(filename):
    """Determine file type from filename extension"""
    if "." not in filename:
        return TYPE_BASIC

    ext = filename.split(".")[-1]
    if not ext:
        return TYPE_BASIC

    first_char = ext[0].upper()
    if first_char == "B":
        return TYPE_BASIC
    elif first_char == "C":
        return TYPE_CODE
    elif first_char == "A":
        return TYPE_STR_ARRAY if len(ext) > 1 and ext[1] == "$" else TYPE_NUM_ARRAY
    else:
        return TYPE_BASIC

def calculate_crc(data):
    """Calculate XOR checksum for TAP data"""
    result = 0
    for byte in data:
        result ^= byte
    return result.to_bytes(1, "little")

def find_directory_start(block0):
    """Find where directory entries begin by scanning past the track map.

    The track map starts at byte 24 and is terminated by a 0xFF byte.
    The PDF warns: 'Never expect the length of the track map to always
    be 165 bytes long.' So we scan for the end marker dynamically rather
    than using a hardcoded offset.
    """
    index = TRACK_MAP_OFFSET
    while index < len(block0):
        if block0[index] == DIR_START:
            return index
        index += 1
    return None

def read_catalog(img_path):
    """Read the file catalog from disk image"""
    try:
        with open(img_path, 'rb') as f:
            # Read first block
            first_block = f.read(BLOCK_SIZE)
            if len(first_block) < BLOCK_SIZE:
                raise ValueError("Image file too small")

            # Get disk parameters
            sides = first_block[20]
            tracks = first_block[21]
            file_size = os.path.getsize(img_path)

            print(f"Sides: {sides}")
            print(f"Tracks: {tracks}")
            print(f"File size: {file_size}")

            # Determine if we need to divide blocks
            divide_blocks = file_size < 250000 and sides == 1

            if sides == 1 and file_size > 400000:
                log_bad_file(img_path, "Single sided imaged as double sided.")
                sys.exit("Extraction ended. Single sided disk with too many bytes.")

            print(f"Divide blocks: {divide_blocks}")

            # Find directory start dynamically
            dir_start = find_directory_start(first_block)
            if dir_start is None:
                raise ValueError("Could not find directory start in block 0")

            # Parse directory
            file_directory = []
            index = dir_start

            while index < len(first_block) and first_block[index] != DIR_END:
                if first_block[index] == DIR_START:
                    index += 1

                    # Check if entry is in use
                    if index < len(first_block) and first_block[index] != UNUSED_ENTRY:
                        # Read filename (up to 9 chars, terminated by BLOCK_LIST_START)
                        filename = ''
                        while index < len(first_block) and first_block[index] != BLOCK_LIST_START:
                            filename += chr(first_block[index])
                            index += 1

                        if index < len(first_block) and first_block[index] == BLOCK_LIST_START:
                            index += 1

                            # Read block list
                            blocks = []
                            while index < len(first_block) and first_block[index] != BLOCK_LIST_END:
                                block_num = first_block[index] // 2 if divide_blocks else first_block[index]
                                blocks.append(block_num)
                                index += 1

                            if blocks:  # Only add if we have blocks
                                file_entry = {
                                    "filename": filename,
                                    "blocks": blocks,
                                    "type": get_file_type(filename)
                                }
                                file_directory.append(file_entry)
                    else:
                        # Skip unused entry
                        while index < len(first_block):
                            if first_block[index] in (DIR_END, DIR_START):
                                index -= 1
                                break
                            index += 1

                index += 1

            return file_directory, divide_blocks

    except Exception as e:
        print(f"Error reading catalog: {e}")
        return [], False

def read_file_data(img_path, file_entry):
    """Read file data from disk image"""
    try:
        with open(img_path, 'rb') as f:
            file_content = bytearray()
            file_data = {}

            first_block = file_entry["blocks"][0]

            for block_num in file_entry["blocks"]:
                # Seek to block
                f.seek(block_num * BLOCK_SIZE)
                block = f.read(BLOCK_SIZE)

                if not block or block[0] != 0xFF:
                    print(f"Warning: Invalid block marker at block {block_num}")
                    log_bad_file(img_path, "First byte of block is not FF.")
                    continue

                # Parse header from first block
                if block_num == first_block:
                    file_data["fileNameBytes"] = block[2:12]  # 10-byte filename field
                    stored_name = file_data["fileNameBytes"].decode().rstrip(' \x00')
                    expected_name = file_entry["filename"].rstrip(' \x00')

                    if stored_name != expected_name:
                        print(f"Warning: Filename mismatch: '{stored_name}' != '{expected_name}'")
                        log_bad_file(img_path, "File names do not match.")

                    file_data["fileStartAddr"] = int.from_bytes(block[12:14], "little")
                    file_data["fileAutoStartLine"] = int.from_bytes(block[17:19], "little")
                    file_data["varProgOffset"] = int.from_bytes(block[20:22], "little")
                    file_data["fileLength"] = int.from_bytes(block[22:24], "little")
                    file_data["type"] = file_entry["type"]

                # Get data size and extract data
                data_size = int.from_bytes(block[14:16], "little")
                file_content.extend(block[24:24 + data_size])

            file_data["fileContent"] = file_content
            return file_data

    except Exception as e:
        print(f"Error reading file data: {e}")
        return None

def is_memory_dump(file_data):
    """Detect if a file is a full memory state capture rather than a normal program.

    Memory dumps are identified by:
    - Start address at 0x4000 (16384) = beginning of RAM
    - Total length >= 40K (covers most of the 48K address space)
    - varProgOffset == 0 (no BASIC variables area, invalid for real BASIC)
    """
    return (file_data["fileStartAddr"] == MEMORY_START and
            file_data["fileLength"] >= MEMORY_DUMP_MIN and
            file_data["varProgOffset"] == 0)

def find_code_region(dump_data):
    """Find the machine code region in a memory dump.

    Scans from the top of memory downward to find the extent of code,
    then scans upward from RAMTOP to find the start. Returns (start, end)
    as absolute memory addresses.
    """
    # RAMTOP from system variables
    ramtop = int.from_bytes(dump_data[0x5CB2 - 0x4000:0x5CB4 - 0x4000], "little")
    code_start_addr = ramtop + 1

    # Find the end of code by scanning backward from 0xFFFF
    end_offset = len(dump_data) - 1
    while end_offset > 0 and dump_data[end_offset] == 0:
        end_offset -= 1
    code_end_addr = 0x4000 + end_offset

    return code_start_addr, code_end_addr

def build_basic_loader(clear_addr, code_load_addr, entry_addr):
    """Build a ZX Spectrum BASIC loader program as raw bytes.

    Generates:
      10 CLEAR <clear_addr>
      20 LOAD ""CODE
      30 RANDOMIZE USR <entry_addr>
    """
    lines = bytearray()

    def add_line(line_num, tokens):
        """Append a BASIC line. tokens is a list of bytes."""
        line_body = bytearray(tokens) + b'\x0D'
        lines.extend(line_num.to_bytes(2, "big"))
        lines.extend(len(line_body).to_bytes(2, "little"))
        lines.extend(line_body)

    def num_literal(n):
        """Encode a number as displayed digits + 5-byte inline float."""
        digits = str(n).encode('ascii')
        # Inline float: 0x0E, exponent=0, sign=0, lo, hi, 0
        float_bytes = b'\x0E\x00\x00' + (n & 0xFFFF).to_bytes(2, "little") + b'\x00'
        return digits + float_bytes

    # Line 10: CLEAR <clear_addr>
    add_line(10, b'\xF9' + num_literal(clear_addr))  # 0xF9 = CLEAR

    # Line 20: LOAD ""CODE
    add_line(20, b'\xEF\x22\x22\xAF')  # 0xEF=LOAD, "", 0xAF=CODE

    # Line 30: RANDOMIZE USR <entry_addr>
    add_line(30, b'\xF5\xC0' + num_literal(entry_addr))  # 0xF5=RANDOMIZE, 0xC0=USR

    return bytes(lines)

def build_tap_block(flag, data):
    """Build a single TAP block: 2-byte length + flag + data + checksum."""
    block = bytes([flag]) + data
    crc = 0
    for b in block:
        crc ^= b
    block += bytes([crc])
    return len(block).to_bytes(2, "little") + block

def write_dump_file(output_path, file_data):
    """Write a raw memory dump and a launchable TAP file.

    The .dump file is the raw memory contents.
    The .tap file contains a BASIC loader + CODE block that can be
    loaded in a ZX Spectrum / TS-2068 emulator to run the program.
    """
    try:
        raw_name = file_data["fileNameBytes"]
        filename = raw_name.replace(b'\x00', b'\x20').decode('UTF-8').rstrip()

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
        code_start, code_end = find_code_region(dump_content)
        code_data = dump_content[code_start - 0x4000:code_end - 0x4000 + 1]
        clear_addr = code_start - 1
        entry_addr = code_start

        # BASIC loader
        loader = build_basic_loader(clear_addr, code_start, entry_addr)
        loader_name = filename[:10].ljust(10).encode('ascii')

        # TAP header for BASIC loader: type=0 (BASIC), autostart=10
        basic_header = (b'\x00' +              # type: BASIC
                       loader_name +            # 10-char filename
                       len(loader).to_bytes(2, "little") +
                       (10).to_bytes(2, "little") +   # autostart line 10
                       len(loader).to_bytes(2, "little"))  # program length
        basic_header_block = build_tap_block(0x00, basic_header)
        basic_data_block = build_tap_block(0xFF, loader)

        # TAP header for CODE block
        code_name = filename[:10].ljust(10).encode('ascii')
        code_header = (b'\x03' +               # type: CODE
                      code_name +               # 10-char filename
                      len(code_data).to_bytes(2, "little") +
                      code_start.to_bytes(2, "little") +  # load address
                      (32768).to_bytes(2, "little"))       # param2
        code_header_block = build_tap_block(0x00, code_header)
        code_data_block = build_tap_block(0xFF, code_data)

        tap_data = (basic_header_block + basic_data_block +
                   code_header_block + code_data_block)

        tap_path = unique_path(safe_filename + ".tap")
        with open(tap_path, "wb") as f:
            f.write(tap_data)

        print(f"  -> Saved memory dump: {dump_path} "
              f"({file_data['fileLength']} bytes, origin=0x{file_data['fileStartAddr']:04X})")
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
        raw_name = file_data["fileNameBytes"]
        # Ensure TAP gets a clean 10-byte space-padded filename (replace nulls with spaces)
        tap_name = raw_name.replace(b'\x00', b'\x20')
        filename = tap_name.decode('UTF-8').rstrip()
        file_type = file_data["type"]

        # TAP param1 and param2 depend on file type:
        #   BASIC:     param1 = autostart line,  param2 = vars offset (prog length)
        #   CODE:      param1 = start address,   param2 = 32768
        #   NUM_ARRAY: param1 = 0,               param2 = variable name
        #   STR_ARRAY: param1 = 0,               param2 = variable name
        if file_type == TYPE_CODE:
            tap_param1 = file_data["fileStartAddr"]
            tap_param2 = 32768
        elif file_type in (TYPE_NUM_ARRAY, TYPE_STR_ARRAY):
            tap_param1 = 0
            tap_param2 = file_data["varProgOffset"]
        else:
            # BASIC
            tap_param1 = file_data["fileAutoStartLine"]
            tap_param2 = file_data["varProgOffset"]

        # Build TAP header (19 bytes + 2 byte length prefix)
        file_header = b'\x13\x00'
        header_data = (b'\x00' +
                      file_type +
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

FILE_TYPE_NAMES = {TYPE_BASIC: "BASIC", TYPE_NUM_ARRAY: "Numeric array",
                   TYPE_STR_ARRAY: "String array", TYPE_CODE: "CODE"}

def get_file_type_name(type_code):
    """Get human-readable file type name"""
    return FILE_TYPE_NAMES.get(type_code, f"Unknown ({type_code})")

def log_bad_file(filename, message):
    """Log problematic files"""
    try:
        with open("badfiles", "a") as f:
            f.write(f"{filename},{message}\n")
    except:
        pass

def write_manifest(output_path, img_path, disk_info, extracted_files):
    """Write a markdown manifest describing the disk contents and extracted files."""
    manifest_path = os.path.join(output_path, "manifest.md") if output_path else "manifest.md"
    img_name = os.path.basename(img_path)

    with open(manifest_path, "w") as f:
        f.write(f"# {img_name}\n\n")
        f.write("## Disk Information\n\n")
        f.write(f"- **Format:** Larken (LKDOS)\n")
        f.write(f"- **Sides:** {disk_info['sides']}\n")
        f.write(f"- **Tracks:** {disk_info['tracks']}\n")
        f.write(f"- **Source image:** {img_name}\n")
        f.write("\n")

        f.write("## Extracted Files\n\n")
        f.write("| # | Disk Filename | Type | Size | Extracted As |\n")
        f.write("|---|---------------|------|------|--------------|\n")
        for i, (entry, file_data, paths) in enumerate(extracted_files, 1):
            orig = entry["filename"].rstrip()
            kind = get_file_type_name(entry["type"])
            size = file_data.get("fileLength", "?") if file_data else "?"
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

    # Get catalog
    catalog, _ = read_catalog(args.imgfile)

    if args.cat:
        # Display catalog only - read file headers to detect dumps
        print("Catalog")
        print("-" * 60)
        for entry in catalog:
            file_data = read_file_data(args.imgfile, entry)
            kind = ""
            if file_data and is_memory_dump(file_data):
                kind = " [memory dump]"
            print(f'{entry["filename"]:12}  {entry["blocks"]} {entry["type"]}{kind}')
        return

    if not catalog:
        print("Empty catalog.")
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

    # Read disk info for manifest
    with open(args.imgfile, 'rb') as imgf:
        first_block = imgf.read(BLOCK_SIZE)
    disk_info = {
        "sides": first_block[20],
        "tracks": first_block[21],
    }

    extracted_files = []

    # Process files
    if args.specific:
        # Extract specific file
        for entry in catalog:
            if entry["filename"].rstrip() == args.specific.rstrip():
                print(f"Extracting: {entry}")
                file_data = read_file_data(args.imgfile, entry)
                paths = []
                if file_data:
                    if is_memory_dump(file_data):
                        paths = write_dump_file(output_path, file_data)
                    else:
                        paths = write_tap_file(output_path, file_data)
                extracted_files.append((entry, file_data, paths))
                break
        else:
            print(f"File '{args.specific}' not found in catalog")
    else:
        # Extract all files
        for entry in catalog:
            print(f"Extracting: {entry}")
            file_data = read_file_data(args.imgfile, entry)
            paths = []
            if file_data:
                if is_memory_dump(file_data):
                    paths = write_dump_file(output_path, file_data)
                else:
                    paths = write_tap_file(output_path, file_data)
            extracted_files.append((entry, file_data, paths))

    if extracted_files:
        write_manifest(output_path, args.imgfile, disk_info, extracted_files)

if __name__ == "__main__":
    main()
