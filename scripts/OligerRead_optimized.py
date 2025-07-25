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
    """Calculate cylinder number from directory entry bytes"""
    result = cylinder_bytes[0] * 2
    if cylinder_bytes[1] != 0:
        result += 1
    return result

def calculate_crc(data):
    """Calculate checksum for data"""
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

def write_tap_file(output_path, file_data):
    """Write file data in TAP format"""
    try:
        filename = file_data["filename"].rstrip()
        
        # Build TAP header
        file_header = b'\x13\x00'
        
        # Prepare header data
        header_data = (b'\x00' + 
                      file_data["filetype"].to_bytes(1, "little") +
                      file_data["filename"].encode('utf-8') +
                      len(file_data["fileContent"]).to_bytes(2, "little") +
                      file_data["staline"].to_bytes(2, "little") +
                      file_data["param2"].to_bytes(2, "little"))
        
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
        print("-" * 50)
        for entry in catalog:
            print(f'{entry["filename"]:12} {entry["filesize"]:6} '
                  f'{entry["cylinder"]:3} {entry["filetype"]}')
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
                write_tap_file(output_path, file_data)

if __name__ == "__main__":
    main()