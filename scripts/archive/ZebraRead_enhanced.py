#!/usr/bin/env python3
"""
ZebraRead_enhanced.py - Extract files from Zebra CPC DSK format disk images
Handles hierarchical directory structure
"""

import argparse
import os
import sys
import string

# Constants for CPC DSK format
CPC_DSK_HEADER = b"EXTENDED CPC DSK"
HEADER_SIZE = 0x100  # 256 bytes
TRACK_INFO_SIZE = 0x100  # 256 bytes per track

# Directory markers
MARKER_ROOT_DIR = 0xFF
MARKER_SUB_DIR = 0x80
MARKER_FILE = 0x01

# Known root directory offset
ROOT_DIR_OFFSET = 0x2880

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
    parser.add_argument("-v", "--verbose", action='store_true',
                       help="Verbose output")
    return parser.parse_args()

def make_safe_filename(input_filename):
    """Convert filename to contain only safe characters"""
    safechars = string.ascii_letters + string.digits + "~ -_."
    return "".join(c for c in input_filename if c in safechars)

def scan_entire_disk(data, verbose=False):
    """Scan entire disk for directory and file structures"""
    entries = []
    
    # Look for directory/file entries throughout the disk
    for i in range(len(data) - 32):
        marker = data[i]
        
        # Check for valid markers
        if marker in [MARKER_FILE, MARKER_SUB_DIR, MARKER_ROOT_DIR]:
            # Check if valid filename follows
            name_bytes = data[i+1:i+9]
            
            # Must start with letter
            if name_bytes[0] >= ord('A') and name_bytes[0] <= ord('Z'):
                try:
                    name = name_bytes.decode('ascii').strip()
                    if all(c.isalnum() or c.isspace() for c in name):
                        # Get file type
                        type_bytes = data[i+9:i+12]
                        file_type = type_bytes.decode('ascii', errors='ignore').strip()
                        
                        # Get metadata
                        meta_bytes = data[i+12:i+32]
                        
                        entry = {
                            'offset': i,
                            'marker': marker,
                            'name': name,
                            'type': file_type,
                            'metadata': meta_bytes,
                            'path': ''  # Will be filled in later
                        }
                        
                        # Validate entry
                        if file_type in ['DIR', 'TXT', 'COD', ''] or marker == MARKER_FILE:
                            entries.append(entry)
                            if verbose:
                                print(f"Found at 0x{i:04x}: [{marker:02x}] {name:12} {file_type}")
                
                except:
                    pass
    
    return entries

def find_directory_contents(data, dir_offset, dir_name, verbose=False):
    """Find contents of a specific directory"""
    contents = []
    
    # Start searching after the directory header
    offset = dir_offset + 32
    
    # Look for entries in this directory section
    while offset < len(data) - 32:
        marker = data[offset]
        
        # Stop if we hit another directory at the same level
        if marker == MARKER_ROOT_DIR:
            break
            
        if marker in [MARKER_FILE, MARKER_SUB_DIR]:
            name_bytes = data[offset+1:offset+9]
            if name_bytes[0] >= ord('A') and name_bytes[0] <= ord('Z'):
                try:
                    name = name_bytes.decode('ascii').strip()
                    type_bytes = data[offset+9:offset+12]
                    file_type = type_bytes.decode('ascii', errors='ignore').strip()
                    
                    entry = {
                        'offset': offset,
                        'marker': marker,
                        'name': name,
                        'type': file_type,
                        'parent': dir_name,
                        'path': f"{dir_name}/{name}"
                    }
                    contents.append(entry)
                    
                    if verbose:
                        print(f"  -> {name:12} {file_type}")
                    
                except:
                    pass
        
        offset += 32
        
        # Stop if we've gone too far (empty entries)
        if offset < len(data) - 32:
            check = data[offset:offset+32]
            if all(b == 0xE5 for b in check):  # Empty sector marker
                break
    
    return contents

def build_directory_tree(dsk_path, verbose=False):
    """Build complete directory tree from DSK image"""
    try:
        with open(dsk_path, 'rb') as f:
            data = f.read()
            
        # Verify header
        if not data.startswith(CPC_DSK_HEADER):
            print("Error: Not a valid CPC DSK file")
            return {}
            
        tree = {
            'root': [],
            'directories': {}
        }
        
        # First, find root directory entries
        if verbose:
            print("Scanning root directory...")
            
        # Use data directly, not file handle
        root_data = data[ROOT_DIR_OFFSET + 0x28:ROOT_DIR_OFFSET + 0x200]
        
        # Parse root directory
        for i in range(0, len(root_data) - 20, 1):
            if root_data[i] == MARKER_ROOT_DIR:
                entry_data = root_data[i+1:i+20]
                name = entry_data[0:8].decode('ascii', errors='ignore').strip()
                file_type = entry_data[8:11].decode('ascii', errors='ignore').strip()
                
                if name and name[0].isalpha():
                    entry = {
                        'name': name,
                        'type': file_type,
                        'offset': ROOT_DIR_OFFSET + 0x28 + i
                    }
                    tree['root'].append(entry)
                    
                    if file_type == 'DIR':
                        tree['directories'][name] = []
                        if verbose:
                            print(f"Found directory: {name}")
        
        # Now scan for subdirectory contents
        if verbose:
            print("\nScanning for subdirectory contents...")
            
        entries = scan_entire_disk(data, verbose=False)
        
        # Known subdirectory locations (found through analysis)
        known_dirs = {
            'ZEBRA': 0x4600,
        }
        
        # Also scan for directory contents throughout the disk
        # Look for clusters of file entries
        if verbose:
            print("\nScanning for file clusters throughout disk...")
            
        for offset in range(0x3000, len(data) - 512, 0x100):
            # Check if this looks like a directory listing
            marker = data[offset]
            if marker == MARKER_ROOT_DIR:
                # Check if it's a directory header
                name = data[offset+1:offset+9].decode('ascii', errors='ignore').strip()
                file_type = data[offset+9:offset+12].decode('ascii', errors='ignore').strip()
                
                if name in tree['directories'] and file_type == 'DIR':
                    if verbose:
                        print(f"\nFound {name} directory at 0x{offset:04x}")
                    contents = find_directory_contents(data, offset, name, verbose)
                    if contents:
                        tree['directories'][name] = contents
        
        # Scan known directory locations
        for dir_name, dir_offset in known_dirs.items():
            if dir_name in tree['directories']:
                if verbose:
                    print(f"\nScanning {dir_name} directory at 0x{dir_offset:04x}...")
                contents = find_directory_contents(data, dir_offset, dir_name, verbose)
                tree['directories'][dir_name] = contents
        
        return tree
        
    except Exception as e:
        print(f"Error building directory tree: {e}")
        return {}

def display_tree(tree, indent=0):
    """Display directory tree in hierarchical format"""
    prefix = "  " * indent
    
    # Show root entries
    if indent == 0:
        for entry in tree.get('root', []):
            if entry['type'] == 'DIR':
                print(f"{prefix}{entry['name']}/ (DIR)")
                # Show subdirectory contents
                if entry['name'] in tree.get('directories', {}):
                    for subentry in tree['directories'][entry['name']]:
                        if subentry['marker'] == MARKER_SUB_DIR:
                            print(f"{prefix}  {subentry['name']}/ (DIR)")
                        else:
                            print(f"{prefix}  {subentry['name']}.{subentry['type']}")
            else:
                print(f"{prefix}{entry['name']}.{entry['type']}")

def main():
    args = parse_arguments()
    
    if not os.path.exists(args.imgfile):
        print(f"Error: File '{args.imgfile}' not found")
        sys.exit(1)
    
    # Build directory tree
    tree = build_directory_tree(args.imgfile, verbose=args.verbose)
    
    if args.cat:
        # Display catalog
        print("\nDisk Catalog:")
        print("=" * 50)
        display_tree(tree)
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
    print("\nNote: File extraction from CPC DSK format is not yet fully implemented.")
    print("\nDirectory structure found:")
    display_tree(tree)

if __name__ == "__main__":
    main()