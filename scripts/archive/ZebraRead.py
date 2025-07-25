#!/usr/bin/env python3
"""
ZebraRead.py - Extract files from Zebra CPC DSK format disk images
Based on analysis of zebra.dsk file structure
"""

import argparse
import os
import sys
import string

# Constants for CPC DSK format
CPC_DSK_HEADER = b"EXTENDED CPC DSK"
HEADER_SIZE = 0x100  # 256 bytes
TRACK_INFO_SIZE = 0x100  # 256 bytes per track

# Directory location found at 0x2880
DIR_START_OFFSET = 0x2880
DIR_ENTRY_MARKER = 0xFF
DIR_ENTRY_SIZE = 20  # Approximate, based on observation

def parse_arguments():
    parser = argparse.ArgumentParser(description="Extract files from Zebra/CPC DSK images")
    parser.add_argument("-f", "--imgfile", type=str, required=True,
                       help="DSK filename for input")
    parser.add_argument("-c", "--cat", action='store_true',
                       help="Catalog of disk image contents")
    parser.add_argument("-s", "--specific", type=str,
                       help="Name of a specific program to extract")
    parser.add_argument("-o", "--outdir", action='store_true',
                       help="Output files to directory based on image name")
    return parser.parse_args()

def make_safe_filename(input_filename):
    """Convert filename to contain only safe characters"""
    safechars = string.ascii_letters + string.digits + "~ -_."
    return "".join(c for c in input_filename if c in safechars)

def read_catalog(dsk_path):
    """Read the file catalog from CPC DSK image"""
    try:
        with open(dsk_path, 'rb') as f:
            # Read and verify header
            header = f.read(HEADER_SIZE)
            if not header.startswith(CPC_DSK_HEADER):
                print("Error: Not a valid CPC DSK file")
                return []
            
            # Get disk info from header
            disk_info = header[0x22:0x30].decode('ascii', errors='ignore').strip()
            num_tracks = header[0x30]
            num_sides = header[0x31]
            
            print(f"Disk format: CPC DSK")
            print(f"Created by: {disk_info}")
            print(f"Tracks: {num_tracks}")
            print(f"Sides: {num_sides}")
            
            # Read directory at known offset
            f.seek(DIR_START_OFFSET)
            directory_data = f.read(0x200)  # Read 512 bytes of directory
            
            # Parse directory entries
            file_list = []
            
            # Skip header "DIRSCP   A       B       C       D       "
            index = 0x28  # Start after header
            
            # Find all 0xFF markers and parse entries
            # Format: 0xFF + filename(8) + type(3) + metadata(8)
            for i in range(len(directory_data) - 20):
                if directory_data[i] == DIR_ENTRY_MARKER:
                    # Found a marker, check if valid entry follows
                    entry_start = i + 1
                    if entry_start + 19 <= len(directory_data):
                        filename_bytes = directory_data[entry_start:entry_start+8]
                        filetype_bytes = directory_data[entry_start+8:entry_start+11]
                        metadata_bytes = directory_data[entry_start+11:entry_start+19]
                        
                        # Validate filename starts with letter
                        if filename_bytes[0] >= ord('A') and filename_bytes[0] <= ord('Z'):
                            filename = filename_bytes.decode('ascii', errors='ignore').strip()
                            filetype = filetype_bytes.decode('ascii', errors='ignore').strip()
                            
                            file_entry = {
                                "filename": filename,
                                "filetype": filetype if filetype else "???",
                                "offset": i + DIR_START_OFFSET,
                                "metadata": metadata_bytes.hex()
                            }
                            file_list.append(file_entry)
            
            return file_list
            
    except Exception as e:
        print(f"Error reading catalog: {e}")
        return []

def extract_file(dsk_path, file_entry):
    """Extract a file from the DSK image"""
    # For now, we'll just note that extraction would require understanding
    # the CPC file format and sector layout
    print(f"File extraction not yet implemented for CPC DSK format")
    print(f"Would extract: {file_entry['filename']}.{file_entry['filetype']}")
    return None

def main():
    args = parse_arguments()
    
    if not os.path.exists(args.imgfile):
        print(f"Error: File '{args.imgfile}' not found")
        sys.exit(1)
    
    # Get catalog
    catalog = read_catalog(args.imgfile)
    
    if not catalog:
        print("No files found in catalog.")
        return
    
    if args.cat:
        # Display catalog only
        print("\nCatalog")
        print("-" * 50)
        for entry in catalog:
            print(f"{entry['filename']:11} {entry['filetype']:3}  meta: {entry['metadata']}")
        return
    
    print(f"\nProcessing: {args.imgfile}")
    
    # Create output directory if requested
    output_path = ''
    if args.outdir:
        output_path = os.path.splitext(os.path.basename(args.imgfile))[0]
        try:
            os.makedirs(output_path, exist_ok=True)
            print(f"Output directory: {output_path}")
        except Exception as e:
            print(f"Error creating directory: {e}")
            output_path = ''
    
    # Note about extraction
    print("\nNote: File extraction from CPC DSK format is not yet implemented.")
    print("The following files were found:")
    for entry in catalog:
        print(f"  {entry['filename']:11} {entry['filetype']:3}")

if __name__ == "__main__":
    main()