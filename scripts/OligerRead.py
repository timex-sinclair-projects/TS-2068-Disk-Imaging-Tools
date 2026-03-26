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
        with open(safe_filename + ".dump", "wb") as f:
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

        with open(safe_filename + ".tap", "wb") as f:
            f.write(tap_data)

        print(f"  -> Saved memory dump: {safe_filename}.dump "
              f"({file_data['filesize']} bytes, origin=0x{ABS_SAVE_START:04X})")
        print(f"  -> Saved launcher:    {safe_filename}.tap "
              f"(CLEAR {clear_addr}, LOAD CODE at 0x{code_start:04X}, "
              f"USR {entry_addr})")

    except Exception as e:
        print(f"Error writing dump file: {e}")

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

            with open(safe_filename + ".tap", "wb") as f:
                f.write(tap_data)
        else:
            print(f"Unsafe filename: {filename}")

    except Exception as e:
        print(f"Error writing TAP file: {e}")

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

def main():
    args = parse_arguments()

    if not os.path.exists(args.imgfile):
        print(f"Error: File '{args.imgfile}' not found")
        sys.exit(1)

    # Get catalog
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

    # Process files
    if args.specific:
        # Extract specific file
        found = False
        for entry in catalog:
            if entry["filename"].rstrip() == args.specific.rstrip():
                print(f"Extracting: {entry['filename']}")
                file_data = read_file_data(args.imgfile, entry)
                if file_data:
                    if is_abs_state_save(file_data):
                        write_abs_dump(output_path, file_data)
                    else:
                        write_tap_file(output_path, file_data)
                found = True
                break

        if not found:
            print(f"File '{args.specific}' not found in catalog")
    else:
        # Extract all files
        for entry in catalog:
            print(f"Extracting: {entry['filename']}")
            file_data = read_file_data(args.imgfile, entry)
            if file_data:
                if is_abs_state_save(file_data):
                    write_abs_dump(output_path, file_data)
                else:
                    write_tap_file(output_path, file_data)

if __name__ == "__main__":
    main()
