#!/usr/bin/env python3
"""
Example: How to add a custom vendor extractor

This file shows how to create and register a custom vendor extractor
for your specific vendor's private tags.
"""

from vendor_normalization import VendorExtractor, VendorMetadata, get_normalizer
from pydicom.dataset import Dataset
from typing import Dict, Any
import re


class CustomVendorExtractor(VendorExtractor):
    """Example extractor for a custom vendor"""
    
    def can_handle(self, ds: Dataset) -> bool:
        """Check if this extractor can handle this dataset"""
        manufacturer = getattr(ds, 'Manufacturer', '')
        # Replace 'CUSTOM_VENDOR' with your vendor name
        return 'CUSTOM_VENDOR' in str(manufacturer).upper()
    
    def extract(self, ds: Dataset, private_tags: Dict[str, Any]) -> VendorMetadata:
        """Extract and normalize vendor-specific private tags"""
        normalized = {}
        
        # Example 1: Extract from specific private tag location
        # Replace group/element with your vendor's private tag locations
        activity_value = self._safe_get_private_tag(ds, 0x0029, 0x1010)
        if activity_value:
            decoded = self._decode_bytes(activity_value)
            if decoded:
                # Parse the decoded text
                # Example: Extract activity from text like "Activity: 150 MBq"
                match = re.search(r'([\d.]+)\s*(MBq|mCi|kBq)', decoded, re.IGNORECASE)
                if match:
                    value = float(match.group(1))
                    unit = match.group(2).upper()
                    # Convert to Bq
                    if unit == 'MBQ':
                        normalized['injected_activity_bq'] = value * 1e6
                    elif unit == 'KBQ':
                        normalized['injected_activity_bq'] = value * 1e3
                    elif unit == 'MCI':
                        normalized['injected_activity_bq'] = value * 3.7e10
        
        # Example 2: Extract from private tags dictionary
        vendor_private = {}
        for creator, tags in private_tags.items():
            if 'CUSTOM_VENDOR' in creator.upper():
                vendor_private[creator] = tags
                # Parse tags specific to your vendor
                for tag_key, value in tags.items():
                    # Your vendor-specific parsing logic here
                    pass
        
        return VendorMetadata(
            vendor_name="Custom Vendor",
            normalized_data=normalized,
            raw_private_tags=vendor_private,
            confidence=0.8 if normalized else 0.3
        )


# To use this extractor, register it:
if __name__ == "__main__":
    # Get the normalizer instance
    normalizer = get_normalizer()
    
    # Register your custom extractor
    normalizer.register_extractor(CustomVendorExtractor())
    
    print("✓ Custom vendor extractor registered!")
    print("Now when processing DICOM files, your extractor will be used for Custom Vendor files.")

