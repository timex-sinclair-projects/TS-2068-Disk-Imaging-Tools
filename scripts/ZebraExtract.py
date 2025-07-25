#!/usr/bin/env python3
"""
ZebraExtract.py - Extract files from DIRSCP format zebra disks
"""

import argparse
import os
import sys
import string

# Constants
CPC_DSK_HEADER = b"EXTENDED CPC DSK"
DIRSCP_MARKER = b"DIRSCP"
ROOT_DIR_OFFSET = 0x2880
TRACK_SIZE = 0x1100  # 4352 bytes per track
TRACK_HEADER_SIZE = 0x100  # 256 bytes

# File markers
MARKER_ROOT_DIR = 0xFF
MARKER_SUB_DIR = 0x80
MARKER_FILE = 0x01

def parse_arguments():
    parser = argparse.ArgumentParser(description="Extract files from DIRSCP zebra disks")
    parser.add_argument("-f", "--imgfile", type=str, required=True,
                       help="DSK filename for input")
    parser.add_argument("-c", "--cat", action='store_true',
                       help="Catalog only, don't extract")
    parser.add_argument("-o", "--outdir", type=str, default=None,
                       help="Output directory (default: filename without extension)")
    parser.add_argument("-v", "--verbose", action='store_true',
                       help="Verbose output")
    return parser.parse_args()

def make_safe_filename(filename):
    """Make filename safe for filesystem"""
    safechars = string.ascii_letters + string.digits + "~ -_."
    return "".join(c for c in filename if c in safechars)

def is_dirscp_format(data):
    """Check if disk uses DIRSCP format"""
    return data[ROOT_DIR_OFFSET:ROOT_DIR_OFFSET+6] == DIRSCP_MARKER

def read_directory_entries(data, offset):
    """Read directory entries from given offset"""
    entries = []
    
    # Skip DIRSCP header if present
    if data[offset:offset+6] == DIRSCP_MARKER:
        scan_start = offset + 0x28
    else:
        scan_start = offset
    
    # Scan for entries (byte by byte to find markers)  
    for i in range(scan_start, min(scan_start + 0x200, len(data) - 32), 1):
        if i + 32 <= len(data):
            entry_data = data[i:i+32]
            marker = entry_data[0]
            
            if marker in [MARKER_ROOT_DIR, MARKER_SUB_DIR, MARKER_FILE]:
                name = entry_data[1:9].decode('ascii', errors='ignore').strip()
                file_type = entry_data[9:12].decode('ascii', errors='ignore').strip()
                
                if name and name[0].isalpha():
                    # Parse allocation information
                    size_info = entry_data[12:16]
                    alloc_info = entry_data[16:24]
                    
                    # Extract track numbers from allocation bytes
                    track_list = []
                    for b in alloc_info:
                        if b != 0:
                            track_list.append(b)
                    
                    entry = {
                        'offset': i,
                        'marker': marker,
                        'name': name,
                        'type': file_type,
                        'is_directory': file_type == 'DIR',
                        'size_info': size_info.hex(),
                        'tracks': track_list,
                        'raw_data': entry_data
                    }
                    entries.append(entry)
    
    return entries

def extract_file_data(data, tracks, verbose=False):
    """Extract file data from specified tracks"""
    file_data = bytearray()
    
    if verbose:
        print(f"    Reading from tracks: {tracks}")
    
    for track_num in tracks:
        # Calculate track data offset
        # Skip main header + track_num * track_size + track header
        track_offset = 0x100 + track_num * TRACK_SIZE + TRACK_HEADER_SIZE
        
        if track_offset + TRACK_SIZE - TRACK_HEADER_SIZE <= len(data):
            track_data = data[track_offset:track_offset + TRACK_SIZE - TRACK_HEADER_SIZE]
            file_data.extend(track_data)
            
            if verbose:
                print(f"      Track {track_num}: read {len(track_data)} bytes from offset 0x{track_offset:04x}")
        else:
            if verbose:
                print(f"      Track {track_num}: offset 0x{track_offset:04x} beyond file end")
    
    return file_data

def find_file_end(data, verbose=False):
    """Find the actual end of file data by looking for padding"""
    # Common padding patterns
    padding_patterns = [b'\x00', b'\xff', b'\xe5', b'\x1a']  # 0x1a is CP/M EOF
    
    # Work backwards from end to find last meaningful data
    end_pos = len(data)
    
    # Look for consistent padding at the end
    for i in range(len(data) - 1, -1, -1):
        if data[i] not in [0x00, 0xff, 0xe5, 0x1a]:
            end_pos = i + 1
            break
        
        # If we find significant padding (>100 bytes), stop there
        if len(data) - i > 100:
            end_pos = i
            break
    
    if verbose and end_pos < len(data):
        print(f"      Trimmed {len(data) - end_pos} padding bytes")
    
    return data[:end_pos]

def extract_files(dsk_path, output_dir, verbose=False):
    """Extract all files from DIRSCP disk"""
    try:
        with open(dsk_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        print(f"Error reading disk image: {e}")
        return False
    
    if not data.startswith(CPC_DSK_HEADER):
        print("Error: Not a valid CPC DSK file")
        return False
    
    if not is_dirscp_format(data):
        print("Error: Not a DIRSCP format disk")
        return False
    
    print(f"Extracting files from {os.path.basename(dsk_path)}...")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Read root directory
    root_entries = read_directory_entries(data, ROOT_DIR_OFFSET)
    
    if verbose:
        print(f"Found {len(root_entries)} root entries")
    
    extracted_count = 0
    
    # Process root directories
    for entry in root_entries:
        if entry['is_directory']:
            print(f"\nProcessing directory: {entry['name']}/")
            
            # Look for this directory's contents
            dir_found = False
            for offset in range(0x3000, len(data) - 0x200, 0x100):
                check_data = data[offset:offset+32]
                if (check_data[0] == MARKER_ROOT_DIR and 
                    check_data[1:9].decode('ascii', errors='ignore').strip() == entry['name'] and
                    check_data[9:12] == b'DIR'):
                    
                    if verbose:
                        print(f"  Found directory contents at offset 0x{offset:04x}")
                    
                    # Read directory contents
                    dir_entries = read_directory_entries(data, offset)
                    dir_found = True
                    
                    # Create subdirectory
                    subdir_path = os.path.join(output_dir, make_safe_filename(entry['name']))
                    os.makedirs(subdir_path, exist_ok=True)
                    
                    # Extract files from this directory
                    for file_entry in dir_entries:
                        if not file_entry['is_directory'] and file_entry['tracks']:
                            filename = file_entry['name']
                            if file_entry['type']:
                                filename += '.' + file_entry['type']
                            
                            print(f"  Extracting: {filename}")
                            
                            # Extract file data
                            file_data = extract_file_data(data, file_entry['tracks'], verbose)
                            
                            if file_data:
                                # Trim padding
                                file_data = find_file_end(file_data, verbose)
                                
                                # Write file
                                safe_filename = make_safe_filename(filename)
                                output_path = os.path.join(subdir_path, safe_filename)
                                
                                with open(output_path, 'wb') as f:
                                    f.write(file_data)
                                
                                print(f"    -> {safe_filename} ({len(file_data)} bytes)")
                                extracted_count += 1
                            else:
                                print(f"    -> Failed to extract {filename}")
                    
                    break
            
            if not dir_found and verbose:
                print(f"  Directory contents not found for {entry['name']}")
        
        elif entry['tracks']:  # Root level file
            filename = entry['name']
            if entry['type']:
                filename += '.' + entry['type']
            
            print(f"Extracting root file: {filename}")
            
            file_data = extract_file_data(data, entry['tracks'], verbose)
            if file_data:
                file_data = find_file_end(file_data, verbose)
                safe_filename = make_safe_filename(filename)
                output_path = os.path.join(output_dir, safe_filename)
                
                with open(output_path, 'wb') as f:
                    f.write(file_data)
                
                print(f"  -> {safe_filename} ({len(file_data)} bytes)")
                extracted_count += 1
    
    print(f"\nExtracted {extracted_count} files to {output_dir}/")
    return extracted_count > 0

def catalog_disk(dsk_path):
    """Display catalog of disk contents"""
    try:
        with open(dsk_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        print(f"Error reading disk image: {e}")
        return
    
    if not is_dirscp_format(data):
        print("Not a DIRSCP format disk")
        return
    
    print(f"Catalog of {os.path.basename(dsk_path)}:")
    print("=" * 50)
    
    root_entries = read_directory_entries(data, ROOT_DIR_OFFSET)
    
    for entry in root_entries:
        if entry['is_directory']:
            print(f"{entry['name']}/")
            
            # Look for directory contents
            for offset in range(0x3000, len(data) - 0x200, 0x100):
                check_data = data[offset:offset+32]
                if (check_data[0] == MARKER_ROOT_DIR and 
                    check_data[1:9].decode('ascii', errors='ignore').strip() == entry['name']):
                    
                    dir_entries = read_directory_entries(data, offset)
                    for file_entry in dir_entries:
                        if not file_entry['is_directory']:
                            filename = file_entry['name']
                            if file_entry['type']:
                                filename += '.' + file_entry['type']
                            print(f"  {filename}")
                    break
        else:
            filename = entry['name']
            if entry['type']:
                filename += '.' + entry['type']
            print(filename)

def main():
    args = parse_arguments()
    
    if not os.path.exists(args.imgfile):
        print(f"Error: File '{args.imgfile}' not found")
        sys.exit(1)
    
    if args.cat:
        catalog_disk(args.imgfile)
    else:
        # Use filename without extension as default output directory
        if args.outdir is None:
            args.outdir = os.path.splitext(os.path.basename(args.imgfile))[0]
        
        success = extract_files(args.imgfile, args.outdir, args.verbose)
        if not success:
            sys.exit(1)

if __name__ == "__main__":
    main()