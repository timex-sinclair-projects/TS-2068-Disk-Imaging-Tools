#!/usr/bin/env python3
"""
Full scan of zebra.dsk to map all directories and files
"""

def scan_zebra_disk(filename):
    with open(filename, 'rb') as f:
        data = f.read()
    
    print("=== ZEBRA DISK STRUCTURE ANALYSIS ===\n")
    
    # Root directory at 0x2880
    print("ROOT DIRECTORY (0x2880):")
    root_entries = [
        ("GAMES", "DIR", 0x28a9),
        ("ZEBONUS", "DIR", 0x28bb),
        ("ZEBRA", "DIR", 0x28cd),
        ("DEMO", "DIR", 0x28df),
        ("CH_A", "SCP", 0x28f1),
        ("CH_B", "SCP", 0x2903)
    ]
    
    for name, ftype, offset in root_entries:
        print(f"  {name:10} {ftype:3} at 0x{offset:04x}")
    
    print("\n\nSUBDIRECTORY CONTENTS:")
    
    # ZEBRA directory contents at 0x4600
    print("\nZEBRA/ (at 0x4600):")
    zebra_files = [
        ("MSCRIPT", "DIR", 0x4620, 0x80),
        ("MS5Z", "", 0x4640, 0x01),
        ("MS5Z", "COD", 0x4660, 0x01),
        ("ENVELOPE", "TXT", 0x4680, 0x01),
        ("LETRHEAD", "TXT", 0x46a0, 0x01),
        ("LETTER", "TXT", 0x46c0, 0x01),
        ("GOTHIC", "TXT", 0x46e0, 0x01)
    ]
    
    for name, ftype, offset, marker in zebra_files:
        prefix = "  " if marker == 0x01 else "  "
        if ftype == "DIR":
            print(f"{prefix}{name}/ (subdirectory)")
        else:
            print(f"{prefix}{name}.{ftype}" if ftype else f"{prefix}{name}")
    
    # Files that appear to be in a subdirectory
    print("\nUNKNOWN DIRECTORY (files at 0x5460+):")
    unknown_files = [
        ("CARL", "", 0x5460),
        ("BILL", "", 0x5480),
        ("ANN", "", 0x54a0),
        ("INTRO", "", 0x54c0)
    ]
    
    for name, ftype, offset in unknown_files:
        print(f"  {name}.{ftype}" if ftype else f"  {name}")
    
    print("\n\nSUMMARY:")
    print("- Root directory contains 4 directories and 2 special files")
    print("- ZEBRA directory contains 6 files and 1 subdirectory (MSCRIPT)")
    print("- Found orphaned files (CARL, BILL, ANN, INTRO) that may belong to GAMES, ZEBONUS, or DEMO")
    print("- Directory locations don't follow a simple pattern")
    
    # Try to find more directories
    print("\n\nSEARCHING FOR MORE DIRECTORY STRUCTURES...")
    
    for offset in range(0x3000, min(len(data), 0x20000), 0x100):
        # Look for directory patterns
        if offset + 64 < len(data):
            # Check for FF marker followed by known directory name
            if data[offset] == 0xFF:
                for dirname in ["GAMES", "ZEBONUS", "DEMO"]:
                    if data[offset+1:offset+1+len(dirname)] == dirname.encode():
                        if data[offset+9:offset+12] == b'DIR':
                            print(f"\nFound {dirname} directory structure at 0x{offset:04x}")
                            # Check what follows
                            has_content = False
                            for i in range(1, 8):
                                entry_offset = offset + i * 0x20
                                if entry_offset + 32 < len(data):
                                    marker = data[entry_offset]
                                    if marker in [0x01, 0x80]:
                                        name = data[entry_offset+1:entry_offset+9].decode('ascii', errors='ignore').strip()
                                        if name and name[0].isalpha():
                                            if not has_content:
                                                print("  Contains:")
                                                has_content = True
                                            print(f"    - {name}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        scan_zebra_disk(sys.argv[1])
    else:
        scan_zebra_disk("examples/zebra.dsk")