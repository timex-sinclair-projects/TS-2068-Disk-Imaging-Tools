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

# File type codes
TYPE_BASIC = b'\x00'
TYPE_NUM_ARRAY = b'\x01'
TYPE_STR_ARRAY = b'\x02'
TYPE_CODE = b'\x03'

BLOCK_SIZE = 5120
DIR_START_OFFSET = 188

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
    """Calculate checksum for data"""
    result = 0
    for byte in data:
        result ^= byte
    return result.to_bytes(1, "little")

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
            
            # Parse directory
            file_directory = []
            index = DIR_START_OFFSET
            
            while index < len(first_block) and first_block[index] != DIR_END:
                if first_block[index] == DIR_START:
                    index += 1
                    
                    # Check if entry is in use
                    if index < len(first_block) and first_block[index] != UNUSED_ENTRY:
                        # Read filename
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
                    file_data["fileNameBytes"] = block[2:11] + b'\x20'  # Add space padding
                    stored_name = file_data["fileNameBytes"].decode().rstrip()
                    expected_name = file_entry["filename"].rstrip()
                    
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

def write_tap_file(output_path, file_data):
    """Write file data in TAP format"""
    try:
        filename = file_data["fileNameBytes"].decode('UTF-8').rstrip()
        
        # Build TAP header
        file_header = b'\x13\x00'
        header_data = (b'\x00' + 
                      file_data["type"] + 
                      file_data["fileNameBytes"] + 
                      len(file_data["fileContent"]).to_bytes(2, "little") +
                      file_data["fileAutoStartLine"].to_bytes(2, "little") +
                      file_data["varProgOffset"].to_bytes(2, "little"))
        
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

def main():
    args = parse_arguments()
    
    if not os.path.exists(args.imgfile):
        print(f"Error: File '{args.imgfile}' not found")
        sys.exit(1)
    
    # Get catalog
    catalog, _ = read_catalog(args.imgfile)
    
    if args.cat:
        # Display catalog only
        print("Catalog")
        print("-" * 50)
        for entry in catalog:
            print(f'{entry["filename"]:12}  {entry["blocks"]} {entry["type"]}')
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
    
    # Process files
    if args.specific:
        # Extract specific file
        for entry in catalog:
            if entry["filename"].rstrip() == args.specific.rstrip():
                print(f"Extracting: {entry}")
                file_data = read_file_data(args.imgfile, entry)
                if file_data:
                    write_tap_file(output_path, file_data)
                return
        print(f"File '{args.specific}' not found in catalog")
    else:
        # Extract all files
        for entry in catalog:
            print(f"Extracting: {entry}")
            file_data = read_file_data(args.imgfile, entry)
            if file_data:
                write_tap_file(output_path, file_data)

if __name__ == "__main__":
    main()