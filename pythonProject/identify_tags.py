#!/usr/bin/env python3
"""
Utility to identify and display DICOM tags (standard vs private)
"""

import pydicom
from pathlib import Path
import sys

def is_private_tag(tag):
    """Check if a tag is private (odd group number)"""
    return tag.group % 2 == 1

def get_tag_info(tag):
    """Get information about a DICOM tag"""
    is_private = is_private_tag(tag)
    
    # Try to get standard tag name
    tag_name = "Unknown"
    tag_keyword = None
    
    if not is_private:
        try:
            tag_keyword = pydicom.datadict.keyword_for_tag(tag)
            tag_name = pydicom.datadict.name_for_tag(tag)
        except:
            tag_name = "Standard tag (no definition found)"
    else:
        tag_name = "Private tag"
    
    return {
        'is_private': is_private,
        'tag_name': tag_name,
        'keyword': tag_keyword,
        'group': f"{tag.group:04X}",
        'element': f"{tag.element:04X}",
        'full_tag': f"({tag.group:04X},{tag.element:04X})"
    }

def analyze_dicom_file(file_path):
    """Analyze a DICOM file and show tag information"""
    try:
        ds = pydicom.dcmread(file_path, stop_before_pixels=True)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return
    
    print("=" * 80)
    print(f"File: {file_path}")
    print("=" * 80)
    
    standard_tags = []
    private_tags = []
    
    for elem in ds:
        tag_info = get_tag_info(elem.tag)
        
        # Get value (truncate if too long)
        try:
            value = elem.value
            if isinstance(value, (bytes, bytearray)):
                value_str = f"<binary data: {len(value)} bytes>"
            elif isinstance(value, pydicom.sequence.Sequence):
                value_str = f"<sequence with {len(value)} items>"
            else:
                value_str = str(value)
                if len(value_str) > 50:
                    value_str = value_str[:50] + "..."
        except:
            value_str = "<unreadable>"
        
        tag_entry = {
            'info': tag_info,
            'value': value_str,
            'VR': elem.VR if hasattr(elem, 'VR') else '??'
        }
        
        if tag_info['is_private']:
            private_tags.append(tag_entry)
        else:
            standard_tags.append(tag_entry)
    
    # Display standard tags
    print(f"\n📋 STANDARD TAGS ({len(standard_tags)}):")
    print("-" * 80)
    print(f"{'Tag':<12} {'Keyword':<25} {'VR':<6} {'Value'}")
    print("-" * 80)
    for entry in sorted(standard_tags, key=lambda x: (x['info']['group'], x['info']['element'])):
        info = entry['info']
        keyword = info['keyword'] or 'N/A'
        print(f"{info['full_tag']:<12} {keyword:<25} {entry['VR']:<6} {entry['value']}")
    
    # Display private tags
    print(f"\n⚠️  PRIVATE TAGS ({len(private_tags)}):")
    print("-" * 80)
    print(f"{'Tag':<12} {'VR':<6} {'Value'}")
    print("-" * 80)
    for entry in sorted(private_tags, key=lambda x: (x['info']['group'], x['info']['element'])):
        info = entry['info']
        print(f"{info['full_tag']:<12} {entry['VR']:<6} {entry['value']}")
    
    # Summary
    print("\n" + "=" * 80)
    print(f"Summary:")
    print(f"  Standard tags: {len(standard_tags)}")
    print(f"  Private tags: {len(private_tags)}")
    print(f"  Total tags: {len(standard_tags) + len(private_tags)}")
    
    # Show private tag groups
    if private_tags:
        private_groups = set(entry['info']['group'] for entry in private_tags)
        print(f"\n  Private tag groups found: {', '.join(sorted(private_groups))}")
        
        # Identify potential vendors
        vendors = []
        if '0029' in private_groups or '0019' in private_groups:
            vendors.append("Siemens")
        if '0021' in private_groups:
            vendors.append("Possibly vendor-specific")
        
        if vendors:
            print(f"  Potential vendor(s): {', '.join(vendors)}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 identify_tags.py <dicom_file>")
        print("\nExample:")
        print("  python3 identify_tags.py scan.dcm")
        print("  python3 identify_tags.py MIRROR_A/Anonymous^00039/.../00000001.dcm")
        sys.exit(1)
    
    file_path = Path(sys.argv[1])
    
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    
    analyze_dicom_file(file_path)

if __name__ == "__main__":
    main()

