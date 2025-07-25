#!/usr/bin/env python3
"""
DiskImageManager.py - Terminal-based front-end for TS-2068 Disk Imaging Tools

Provides a unified interface for:
- Larken format disks (.img files)
- Oliger format disks (.img files) 
- Zebra DIRSCP format disks (.dsk files)
- Zebra CP/M format disks (.dsk files)
"""

import os
import sys
import subprocess
import glob
from pathlib import Path

class DiskImageManager:
    def __init__(self):
        self.current_directory = os.getcwd()
        self.script_directory = os.path.dirname(os.path.abspath(__file__))
        self.available_files = []
        self.refresh_file_list()
    
    def refresh_file_list(self):
        """Scan for disk image files in current directory"""
        patterns = ['*.img', '*.dsk', '*.IMG', '*.DSK']
        self.available_files = []
        
        for pattern in patterns:
            self.available_files.extend(glob.glob(os.path.join(self.current_directory, pattern)))
        
        # Also check examples directory if it exists
        examples_dir = os.path.join(self.current_directory, 'examples')
        if os.path.exists(examples_dir):
            for pattern in patterns:
                self.available_files.extend(glob.glob(os.path.join(examples_dir, pattern)))
        
        self.available_files.sort()
    
    def clear_screen(self):
        """Clear terminal screen"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def print_header(self):
        """Print application header"""
        print("=" * 70)
        print("             TS-2068 DISK IMAGING TOOLS MANAGER")
        print("=" * 70)
        print(f"Current directory: {self.current_directory}")
        print(f"Found {len(self.available_files)} disk image files")
        print()
    
    def print_main_menu(self):
        """Print main menu options"""
        print("MAIN MENU:")
        print("1. List available disk images")
        print("2. Analyze disk image (show format and catalog)")
        print("3. Extract files from disk image")
        print("4. Change directory")
        print("5. Refresh file list")
        print("6. Greaseweazle quick reference")
        print("7. Help")
        print("0. Exit")
        print()
    
    def list_disk_images(self):
        """Display list of available disk images"""
        self.clear_screen()
        self.print_header()
        
        if not self.available_files:
            print("No disk image files found in current directory.")
            print("Supported formats: .img (Larken/Oliger), .dsk (Zebra)")
            print()
            input("Press Enter to continue...")
            return
        
        print("AVAILABLE DISK IMAGES:")
        print("-" * 50)
        
        for i, filepath in enumerate(self.available_files, 1):
            filename = os.path.basename(filepath)
            size = os.path.getsize(filepath)
            size_str = self.format_file_size(size)
            
            # Try to determine format
            format_hint = self.detect_format_hint(filepath)
            
            print(f"{i:2d}. {filename:<20} ({size_str:>8}) {format_hint}")
        
        print()
        input("Press Enter to continue...")
    
    def format_file_size(self, size_bytes):
        """Format file size in human readable format"""
        if size_bytes < 1024:
            return f"{size_bytes}B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes/1024:.1f}KB"
        else:
            return f"{size_bytes/(1024*1024):.1f}MB"
    
    def detect_format_hint(self, filepath):
        """Try to detect disk format"""
        try:
            with open(filepath, 'rb') as f:
                header = f.read(32)
                
            if header.startswith(b"EXTENDED CPC DSK"):
                # Check if it's DIRSCP or CP/M
                with open(filepath, 'rb') as f:
                    f.seek(0x2880)
                    dir_marker = f.read(6)
                    if dir_marker == b"DIRSCP":
                        return "[Zebra DIRSCP]"
                    else:
                        return "[Zebra CP/M]"
            elif filepath.lower().endswith('.img'):
                # Check file size to guess Larken vs Oliger
                size = os.path.getsize(filepath)
                if size > 300000:
                    return "[Likely Larken]"
                else:
                    return "[Likely Oliger]"
            else:
                return "[Unknown]"
        except:
            return "[Unknown]"
    
    def select_disk_image(self, prompt="Select disk image"):
        """Let user select a disk image file"""
        if not self.available_files:
            print("No disk image files available.")
            input("Press Enter to continue...")
            return None
        
        while True:
            self.clear_screen()
            self.print_header()
            
            print(f"{prompt}:")
            print("-" * 50)
            
            for i, filepath in enumerate(self.available_files, 1):
                filename = os.path.basename(filepath)
                format_hint = self.detect_format_hint(filepath)
                print(f"{i:2d}. {filename} {format_hint}")
            
            print(f" 0. Cancel")
            print()
            
            try:
                choice = input("Enter selection (0 to cancel): ").strip()
                if choice == '0':
                    return None
                
                index = int(choice) - 1
                if 0 <= index < len(self.available_files):
                    return self.available_files[index]
                else:
                    print("Invalid selection. Please try again.")
                    input("Press Enter to continue...")
            except ValueError:
                print("Please enter a valid number.")
                input("Press Enter to continue...")
    
    def analyze_disk_image(self):
        """Analyze and show catalog of selected disk image"""
        filepath = self.select_disk_image("Select disk image to analyze")
        if not filepath:
            return
        
        self.clear_screen()
        self.print_header()
        
        filename = os.path.basename(filepath)
        print(f"ANALYZING: {filename}")
        print("=" * 50)
        
        # Detect format and run appropriate tool
        format_hint = self.detect_format_hint(filepath)
        
        try:
            if "Zebra DIRSCP" in format_hint:
                print("Format: Zebra DIRSCP")
                print()
                self.run_script("ZebraExtract.py", ["-f", filepath, "-c"])
            
            elif "Zebra CP/M" in format_hint:
                print("Format: Zebra CP/M")
                print()
                self.run_script("ZebraRead_universal.py", ["-f", filepath, "-c"])
            
            elif filepath.lower().endswith('.img'):
                # Try both Larken and Oliger
                print("Trying Larken format...")
                result = self.run_script("LarkenRead_optimized.py", ["-f", filepath, "-c"], capture_output=True)
                
                if "Empty catalog" in result or not result.strip():
                    print("Not Larken format. Trying Oliger format...")
                    self.run_script("OligerRead_optimized.py", ["-f", filepath, "-c"])
                else:
                    print("Format: Larken")
                    print()
                    print(result)
            
            else:
                print("Unknown format - trying universal scanner...")
                self.run_script("ZebraRead_universal.py", ["-f", filepath, "-c"])
        
        except Exception as e:
            print(f"Error analyzing disk image: {e}")
        
        print()
        input("Press Enter to continue...")
    
    def extract_files(self):
        """Extract files from selected disk image"""
        filepath = self.select_disk_image("Select disk image to extract files from")
        if not filepath:
            return
        
        self.clear_screen()
        self.print_header()
        
        filename = os.path.basename(filepath)
        print(f"EXTRACTING FILES FROM: {filename}")
        print("=" * 50)
        
        # Detect format and run appropriate extraction tool
        format_hint = self.detect_format_hint(filepath)
        
        try:
            if "Zebra DIRSCP" in format_hint:
                print("Format: Zebra DIRSCP")
                print()
                self.run_script("ZebraExtract.py", ["-f", filepath])
            
            elif "Zebra CP/M" in format_hint:
                print("Format: Zebra CP/M - extraction not implemented")
                print("Use analyze option to view file catalog.")
            
            elif filepath.lower().endswith('.img'):
                # Try Larken first, then Oliger
                print("Attempting Larken extraction...")
                result = self.run_script("LarkenRead_optimized.py", ["-f", filepath, "-c"], capture_output=True)
                
                if "Empty catalog" in result or not result.strip():
                    print("Not Larken format. Attempting Oliger extraction...")
                    self.run_script("OligerRead_optimized.py", ["-f", filepath])
                else:
                    print("Format detected: Larken")
                    print()
                    self.run_script("LarkenRead_optimized.py", ["-f", filepath])
            
            else:
                print("Unknown format - cannot extract files")
        
        except Exception as e:
            print(f"Error extracting files: {e}")
        
        print()
        input("Press Enter to continue...")
    
    def run_script(self, script_name, args, capture_output=False):
        """Run one of the extraction scripts"""
        script_path = os.path.join(self.script_directory, script_name)
        
        if not os.path.exists(script_path):
            print(f"Error: Script {script_name} not found")
            return ""
        
        cmd = [sys.executable, script_path] + args
        
        try:
            if capture_output:
                result = subprocess.run(cmd, capture_output=True, text=True)
                return result.stdout + result.stderr
            else:
                subprocess.run(cmd)
                return ""
        except Exception as e:
            print(f"Error running {script_name}: {e}")
            return ""
    
    def change_directory(self):
        """Change current working directory"""
        self.clear_screen()
        self.print_header()
        
        print("CHANGE DIRECTORY")
        print("-" * 30)
        print(f"Current directory: {self.current_directory}")
        print()
        
        new_dir = input("Enter new directory path (or . for current): ").strip()
        
        if new_dir and new_dir != '.':
            if os.path.exists(new_dir) and os.path.isdir(new_dir):
                self.current_directory = os.path.abspath(new_dir)
                self.refresh_file_list()
                print(f"Changed to: {self.current_directory}")
            else:
                print("Directory not found!")
        
        print()
        input("Press Enter to continue...")
    
    def show_help(self):
        """Display help information"""
        self.clear_screen()
        self.print_header()
        
        print("HELP - TS-2068 Disk Imaging Tools")
        print("=" * 50)
        print()
        print("SUPPORTED FORMATS:")
        print("• Larken format (.img files) - Greaseweazle scans")
        print("• Oliger format (.img files) - Greaseweazle scans") 
        print("• Zebra DIRSCP (.dsk files) - CPC DSK with hierarchical directories")
        print("• Zebra CP/M (.dsk files) - CPC DSK with flat file system")
        print()
        print("FEATURES:")
        print("• Automatic format detection")
        print("• File catalog viewing") 
        print("• File extraction to TAP format (Larken/Oliger)")
        print("• File extraction to native format (Zebra DIRSCP)")
        print("• Creates output directories named after disk image")
        print()
        print("USAGE:")
        print("1. Place disk image files in current directory or examples/ subdirectory")
        print("2. Use 'List available disk images' to see what's available")
        print("3. Use 'Analyze disk image' to view file catalogs")
        print("4. Use 'Extract files' to extract all files from a disk")
        print()
        print("EXTRACTED FILES:")
        print("• Larken/Oliger: Creates .tap files compatible with ZX Spectrum emulators")
        print("• Zebra DIRSCP: Creates native files preserving directory structure")
        print()
        print("GREASEWEAZLE IMAGING COMMANDS:")
        print("=" * 50)
        print("For creating disk images that these tools can process:")
        print()
        print("LARKEN/OLIGER DISKS (.img format):")
        print("• Single-sided, 40 tracks:")
        print("  gw read --format=img --tracks=c=0-39:h=0 output.img")
        print()
        print("• Double-sided, 40 tracks:")
        print("  gw read --format=img --tracks=c=0-39:h=0-1 output.img")
        print()
        print("• Single-sided, 42 tracks:")
        print("  gw read --format=img --tracks=c=0-41:h=0 output.img")
        print()
        print("• Double-sided, 42 tracks:")
        print("  gw read --format=img --tracks=c=0-41:h=0-1 output.img")
        print()
        print("ZEBRA DISKS (.dsk format):")
        print("• Use standard CPC disk parameters for .dsk creation")
        print("  gw read --format=ibm.720 output.dsk")
        print()
        print("Notes:")
        print("• Start with 40 tracks for most Larken/Oliger disks")
        print("• Try 42 tracks if 40-track read seems incomplete")
        print("• Check disk label or documentation for sided information")
        print("• IMG format preserves raw flux data for best compatibility")
        print()
        print("For more information, see the individual script documentation.")
        print()
        input("Press Enter to continue...")
    
    def show_greaseweazle_reference(self):
        """Display Greaseweazle command reference"""
        self.clear_screen()
        self.print_header()
        
        print("GREASEWEAZLE QUICK REFERENCE")
        print("=" * 50)
        print("Commands for creating disk images compatible with these tools:")
        print()
        print("LARKEN & OLIGER DISK FORMATS:")
        print("┌─────────────────────────────────────────────────────────────┐")
        print("│ SINGLE-SIDED DISKS                                         │")
        print("├─────────────────────────────────────────────────────────────┤")
        print("│ 40 tracks: gw read --format=img --tracks=c=0-39:h=0 disk.img │")
        print("│ 42 tracks: gw read --format=img --tracks=c=0-41:h=0 disk.img │")
        print("└─────────────────────────────────────────────────────────────┘")
        print()
        print("┌─────────────────────────────────────────────────────────────┐")
        print("│ DOUBLE-SIDED DISKS                                         │")
        print("├─────────────────────────────────────────────────────────────┤")
        print("│ 40 tracks: gw read --format=img --tracks=c=0-39:h=0-1 disk.img │")
        print("│ 42 tracks: gw read --format=img --tracks=c=0-41:h=0-1 disk.img │")
        print("└─────────────────────────────────────────────────────────────┘")
        print()
        print("ZEBRA (CPC) DISK FORMATS:")
        print("┌─────────────────────────────────────────────────────────────┐")
        print("│ Standard CPC format:                                       │")
        print("│ gw read --format=ibm.720 disk.dsk                         │")
        print("└─────────────────────────────────────────────────────────────┘")
        print()
        print("TIPS:")
        print("• Most Larken/Oliger disks are 40 tracks - start there")
        print("• If extraction seems incomplete, try 42 tracks")
        print("• Check physical disk label for sided information")
        print("• IMG format preserves raw magnetic flux data")
        print("• DSK format is structured for CPC compatibility")
        print()
        print("EXAMPLE WORKFLOW:")
        print("1. Insert disk into Greaseweazle-compatible drive")
        print("2. Run: gw read --format=img --tracks=c=0-39:h=0 mydisk.img")
        print("3. Copy mydisk.img to this tool's directory")
        print("4. Use this interface to analyze and extract files")
        print()
        input("Press Enter to continue...")
    
    def run(self):
        """Main application loop"""
        while True:
            self.clear_screen()
            self.print_header()
            self.print_main_menu()
            
            try:
                choice = input("Enter your choice (0-7): ").strip()
                
                if choice == '0':
                    print("Goodbye!")
                    break
                elif choice == '1':
                    self.list_disk_images()
                elif choice == '2':
                    self.analyze_disk_image()
                elif choice == '3':
                    self.extract_files()
                elif choice == '4':
                    self.change_directory()
                elif choice == '5':
                    self.refresh_file_list()
                    print("File list refreshed.")
                    input("Press Enter to continue...")
                elif choice == '6':
                    self.show_greaseweazle_reference()
                elif choice == '7':
                    self.show_help()
                else:
                    print("Invalid choice. Please enter a number from 0-7.")
                    input("Press Enter to continue...")
            
            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                break
            except EOFError:
                print("\n\nGoodbye!")
                break

def main():
    """Entry point"""
    manager = DiskImageManager()
    manager.run()

if __name__ == "__main__":
    main()