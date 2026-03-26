#!/usr/bin/env python3
"""
ZebraRead_universal.py - Universal scanner for CPC DSK format disk images
Handles various directory structures and file organizations
"""

import argparse
import os
import sys
import string

# Constants for CPC DSK format
CPC_DSK_HEADER = b"EXTENDED CPC DSK"
HEADER_SIZE = 0x100  # 256 bytes
ALLOCATION_UNIT_SIZE = 1024  # Default AU size
SECTOR_SIZE = 256

# Directory markers
MARKER_ROOT_DIR = 0xFF
MARKER_SUB_DIR = 0x80
MARKER_FILE = 0x01
MARKER_UNUSED = 0xE5

# Known root directory offset
ROOT_DIR_OFFSET = 0x2880

# Track skew table for proper sector interleaving (from tomato C++ implementation)
TRACK_SKEW = [0, 7, 14, 5, 12, 3, 10, 1, 8, 15, 6, 13, 4, 11, 2, 9]

def parse_arguments():
    parser = argparse.ArgumentParser(description="Universal scanner for CPC DSK images")
    parser.add_argument("-f", "--imgfile", type=str, required=True,
                       help="DSK filename for input")
    parser.add_argument("-c", "--cat", action='store_true',
                       help="Catalog of disk image contents")
    parser.add_argument("-v", "--verbose", action='store_true',
                       help="Verbose output")
    return parser.parse_args()

def make_safe_filename(input_filename):
    """Convert filename to contain only safe characters"""
    safechars = string.ascii_letters + string.digits + "~ -_."
    return "".join(c for c in input_filename if c in safechars)

def scan_directory_area(data, offset, verbose=False):
    """Scan a potential directory area for entries with enhanced metadata parsing"""
    entries = []
    
    # Check if this area starts with DIRSCP header
    if data[offset:offset+6] == b"DIRSCP":
        if verbose:
            print(f"Found DIRSCP header at 0x{offset:04x}")
        # Skip the header line and start scanning entries
        scan_start = offset + 0x28
    else:
        scan_start = offset
    
    # First try the standard format (with markers)
    found_standard = False
    for i in range(scan_start, min(scan_start + 0x200, len(data) - 32), 1):
        marker = data[i]
        
        if marker in [MARKER_ROOT_DIR, MARKER_SUB_DIR, MARKER_FILE]:
            # Check if valid filename follows
            if i + 32 <= len(data):
                name_bytes = data[i+1:i+9]
                if len(name_bytes) > 0 and name_bytes[0] >= ord('A') and name_bytes[0] <= ord('Z'):
                    try:
                        name = name_bytes.decode('ascii').strip()
                        if name and all(c.isalnum() or c.isspace() for c in name):
                            # Get file type
                            type_bytes = data[i+9:i+12]
                            file_type = type_bytes.decode('ascii', errors='ignore').strip()
                            
                            # Enhanced metadata parsing (from tomato implementation)
                            entry_data = data[i:i+32]
                            part_num = entry_data[12]  # Part number for multi-part files
                            tail_bytes = entry_data[13]  # Tail bytes in last sector
                            size_hi = entry_data[14]  # Size high byte
                            size_lo = entry_data[15]  # Size low byte
                            alloc_info = entry_data[16:32]  # Allocation blocks
                            
                            # Calculate file size in sectors
                            file_size_sectors = (size_hi << 8) | size_lo
                            
                            # Parse file attributes
                            is_hidden = (type_bytes[1] & 0x80) != 0
                            is_readonly = (type_bytes[0] & 0x80) != 0
                            
                            # Extract allocation unit numbers (filter out invalid values)
                            allocation_units = [b for b in alloc_info if b != 0 and b < 160]
                            
                            entry = {
                                'offset': i,
                                'marker': marker,
                                'name': name,
                                'type': file_type,
                                'part_number': part_num,
                                'tail_bytes': tail_bytes,
                                'size_sectors': file_size_sectors,
                                'allocation_units': allocation_units,
                                'is_hidden': is_hidden,
                                'is_readonly': is_readonly,
                                'is_directory': file_type == 'DIR',
                                'is_root': marker == MARKER_ROOT_DIR
                            }
                            entries.append(entry)
                            found_standard = True
                            
                            if verbose:
                                marker_name = {MARKER_ROOT_DIR: 'ROOT', MARKER_SUB_DIR: 'SUBDIR', MARKER_FILE: 'FILE'}
                                flags = []
                                if is_hidden: flags.append('H')
                                if is_readonly: flags.append('R')
                                flag_str = f"[{''.join(flags)}]" if flags else ""
                                print(f"  0x{i:04x}: [{marker_name.get(marker, f'{marker:02x}')}] {name:12} {file_type} {flag_str} (part:{part_num}, size:{file_size_sectors}, AUs:{len(allocation_units)})")
                    except:
                        pass
    
    # If no standard entries found, try CP/M style entries (no markers)
    if not found_standard:
        if verbose:
            print(f"  Trying CP/M style directory entries...")
            
        # Look for files that start directly with filename (no marker)
        for i in range(scan_start, min(scan_start + 0x400, len(data) - 32), 32):
            # Check if this looks like a CP/M directory entry
            if i + 32 <= len(data):
                entry_data = data[i:i+32]
                
                # First byte should be 0x00 for normal file, or 0xE5 for deleted
                if entry_data[0] in [0x00, 0xE5]:
                    # Next 8 bytes are filename
                    name_bytes = entry_data[1:9]
                    # Next 3 bytes are extension
                    ext_bytes = entry_data[9:12]
                    
                    if name_bytes[0] >= ord('A') and name_bytes[0] <= ord('Z'):
                        try:
                            name = name_bytes.decode('ascii').strip()
                            ext = ext_bytes.decode('ascii').strip()
                            
                            if name and entry_data[0] != 0xE5:  # Skip deleted files
                                # Enhanced CP/M metadata parsing
                                extent = entry_data[12]  # Extent number
                                reserved = entry_data[13:15]  # Reserved bytes
                                record_count = entry_data[15]  # Records in extent
                                
                                # Parse allocation blocks (CP/M style)
                                allocation_blocks = []
                                for block_idx in range(16, 32):
                                    if entry_data[block_idx] != 0 and entry_data[block_idx] < 160:
                                        allocation_blocks.append(entry_data[block_idx])
                                
                                entry = {
                                    'offset': i,
                                    'marker': entry_data[0],
                                    'name': name,
                                    'type': ext,
                                    'extent': extent,
                                    'record_count': record_count,
                                    'allocation_blocks': allocation_blocks,
                                    'is_directory': False,
                                    'is_root': True,  # CP/M files are considered root level
                                    'is_hidden': False,
                                    'is_readonly': False
                                }
                                entries.append(entry)
                                
                                if verbose:
                                    print(f"  0x{i:04x}: [CPM] {name:12} {ext} (ext:{extent}, recs:{record_count}, blocks:{len(allocation_blocks)})")
                        except:
                            pass
    
    return entries

def scan_entire_disk(data, verbose=False):
    """Scan entire disk for directory structures and files"""
    all_entries = []
    directory_locations = {}
    
    if verbose:
        print("Scanning entire disk for directory structures...")
    
    # First, scan the standard root directory location
    if verbose:
        print(f"\nScanning root directory at 0x{ROOT_DIR_OFFSET:04x}:")
    
    root_entries = scan_directory_area(data, ROOT_DIR_OFFSET, verbose)
    all_entries.extend(root_entries)
    
    # Track directories found in root
    root_directories = []
    for entry in root_entries:
        if entry['is_directory']:
            root_directories.append(entry['name'])
    
    # Now scan for subdirectory contents
    if verbose and root_directories:
        print(f"\nLooking for contents of directories: {', '.join(root_directories)}")
    
    # Scan every 256-byte boundary for directory structures
    for offset in range(0x100, len(data) - 0x200, 0x100):
        # Skip the root directory area we already scanned
        if offset == ROOT_DIR_OFFSET:
            continue
            
        # Look for directory headers
        potential_entries = scan_directory_area(data, offset, verbose=False)
        
        if potential_entries:
            # Check if this looks like a directory listing
            has_directory_header = any(entry['is_directory'] for entry in potential_entries)
            has_files = any(not entry['is_directory'] for entry in potential_entries)
            
            # If we found a directory that matches one from root, this is probably its contents
            directory_match = None
            for entry in potential_entries:
                if entry['is_directory'] and entry['name'] in root_directories:
                    directory_match = entry['name']
                    break
            
            if directory_match or (has_files and len(potential_entries) >= 2 and not any('FGFGFGFG' in e.get('name', '') for e in potential_entries)):
                if verbose:
                    if directory_match:
                        print(f"\nFound {directory_match} directory contents at 0x{offset:04x}:")
                    else:
                        print(f"\nFound file cluster at 0x{offset:04x}:")
                    
                    for entry in potential_entries:
                        if entry['is_directory']:
                            print(f"  {entry['name']}/ (subdirectory)")
                        else:
                            ext = f".{entry['type']}" if entry['type'] else ""
                            print(f"  {entry['name']}{ext}")
                
                # Store the location
                if directory_match:
                    directory_locations[directory_match] = offset
                else:
                    directory_locations[f"cluster_at_{offset:04x}"] = offset
                
                all_entries.extend(potential_entries)
    
    return all_entries, directory_locations

def build_directory_tree(entries, locations):
    """Build a hierarchical directory tree from entries"""
    tree = {
        'root_files': [],
        'directories': {}
    }
    
    # Separate root entries from subdirectory entries
    root_entries = [e for e in entries if e.get('is_root', False)]
    other_entries = [e for e in entries if not e.get('is_root', False)]
    
    # Process root entries
    for entry in root_entries:
        if entry['is_directory']:
            tree['directories'][entry['name']] = []
        else:
            tree['root_files'].append(entry)
    
    # Group other entries by their location
    entries_by_location = {}
    for entry in other_entries:
        # Find which location this entry belongs to
        entry_location = None
        for loc_name, loc_offset in locations.items():
            if abs(entry['offset'] - loc_offset) < 0x200:  # Within 512 bytes
                entry_location = loc_name
                break
        
        if entry_location:
            if entry_location not in entries_by_location:
                entries_by_location[entry_location] = []
            entries_by_location[entry_location].append(entry)
    
    # Assign entries to directories
    for loc_name, loc_entries in entries_by_location.items():
        # If location name matches a directory, assign entries there
        if loc_name in tree['directories']:
            tree['directories'][loc_name] = loc_entries
        else:
            # Create a generic container for unmatched entries
            tree['directories'][f"unknown_{loc_name}"] = loc_entries
    
    return tree

def display_catalog(tree):
    """Display the catalog in a readable format"""
    # Show root files first
    if tree['root_files']:
        print("Root files:")
        for entry in tree['root_files']:
            ext = f".{entry['type']}" if entry['type'] else ""
            print(f"  {entry['name']}{ext}")
        print()
    
    # Show directories and their contents
    for dir_name, contents in tree['directories'].items():
        if not contents:
            print(f"{dir_name}/ (empty)")
        else:
            print(f"{dir_name}/")
            for entry in contents:
                if entry['is_directory']:
                    print(f"  {entry['name']}/ (subdirectory)")
                else:
                    ext = f".{entry['type']}" if entry['type'] else ""
                    flags = []
                    if entry.get('is_hidden', False): flags.append('H')
                    if entry.get('is_readonly', False): flags.append('R')
                    flag_str = f" [{''.join(flags)}]" if flags else ""
                    
                    # Show size info if available
                    size_info = ""
                    if 'size_sectors' in entry:
                        size_info = f" ({entry['size_sectors']} sectors)"
                    elif 'record_count' in entry:
                        size_info = f" ({entry['record_count']} records)"
                    
                    print(f"  {entry['name']}{ext}{flag_str}{size_info}")
            print()

def main():
    args = parse_arguments()
    
    if not os.path.exists(args.imgfile):
        print(f"Error: File '{args.imgfile}' not found")
        sys.exit(1)
    
    # Read disk image
    try:
        with open(args.imgfile, 'rb') as f:
            data = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    
    # Verify it's a CPC DSK file
    if not data.startswith(CPC_DSK_HEADER):
        print("Warning: File doesn't appear to be a CPC DSK image")
    
    # Get disk info
    if len(data) >= HEADER_SIZE:
        disk_info = data[0x22:0x30].decode('ascii', errors='ignore').strip()
        num_tracks = data[0x30] if len(data) > 0x30 else 0
        num_sides = data[0x31] if len(data) > 0x31 else 0
        
        print(f"Disk: {os.path.basename(args.imgfile)}")
        print(f"Format: CPC DSK")
        print(f"Created by: {disk_info}")
        print(f"Tracks: {num_tracks}, Sides: {num_sides}")
        print(f"File size: {len(data)} bytes")
    
    # Scan the disk
    entries, locations = scan_entire_disk(data, verbose=args.verbose)
    
    if not entries:
        print("\nNo files or directories found.")
        return
    
    # Build directory tree
    tree = build_directory_tree(entries, locations)
    
    if args.cat:
        print(f"\nCatalog of {os.path.basename(args.imgfile)}:")
        print("=" * 50)
        display_catalog(tree)
    else:
        print(f"\nFound {len(entries)} entries in {len(locations)} locations")
        if args.verbose:
            display_catalog(tree)

if __name__ == "__main__":
    main()