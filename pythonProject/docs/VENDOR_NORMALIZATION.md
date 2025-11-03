# Vendor-Specific Private Tag Normalization

This project includes a dynamic vendor normalization layer that extracts and normalizes private tags from different DICOM vendors.

## Architecture

The normalization system consists of:

1. **Base `VendorExtractor` class** - Abstract interface for vendor-specific extractors
2. **Vendor-specific extractors** - Implementations for Siemens, Spectrum Dynamics, etc.
3. **`VendorNormalizer` orchestrator** - Automatically selects and runs the appropriate extractor
4. **Generic fallback** - Handles unknown vendors with pattern matching

## How It Works

1. **Automatic Detection**: The system automatically detects the vendor from the DICOM `Manufacturer` tag
2. **Vendor Selection**: The appropriate extractor is selected based on vendor name
3. **Private Tag Extraction**: All private tags are extracted generically
4. **Vendor-Specific Parsing**: The selected extractor parses vendor-specific private tags
5. **Data Normalization**: Extracted data is normalized into standard fields (e.g., `injected_activity_bq`)
6. **Fallback Merging**: Normalized data fills missing standard DICOM fields

## Current Extractors

### Siemens Extractor
- **Detection**: Manufacturer contains "SIEMENS"
- **Tags Parsed**: 
  - `(0029,1010)` and `(0029,1210)` - Common private OB tags for dose reports
  - Text-based reports with regex pattern matching
- **Extracts**: Radiopharmaceutical, injected activity, injection time/date, patient weight, delay

### Spectrum Dynamics Extractor
- **Detection**: Manufacturer contains "SPECTRUM"
- **Tags Parsed**: Vendor-specific private tags
- **Extracts**: Activity information from private tag text fields

### Generic Extractor
- **Fallback**: Used when no specific extractor matches
- **Method**: Pattern matching for common values (activity, dose) across all vendors
- **Confidence**: Lower confidence but still extracts useful data

## Adding Custom Vendor Extractors

To add support for a new vendor, create a new extractor class:

```python
from vendor_normalization import VendorExtractor, VendorMetadata
import pydicom

class MyVendorExtractor(VendorExtractor):
    def can_handle(self, ds: Dataset) -> bool:
        """Check if this extractor can handle this dataset"""
        manufacturer = getattr(ds, 'Manufacturer', '')
        return 'MY_VENDOR' in str(manufacturer).upper()
    
    def extract(self, ds: Dataset, private_tags: Dict[str, Any]) -> VendorMetadata:
        """Extract and normalize vendor-specific private tags"""
        normalized = {}
        
        # Example: Extract from specific private tag
        value = self._safe_get_private_tag(ds, 0x0029, 0x1010)
        if value:
            # Parse and normalize the value
            normalized['injected_activity_bq'] = parse_activity(value)
        
        return VendorMetadata(
            vendor_name="My Vendor",
            normalized_data=normalized,
            raw_private_tags=private_tags,
            confidence=0.8
        )

# Register the extractor
from vendor_normalization import get_normalizer
normalizer = get_normalizer()
normalizer.register_extractor(MyVendorExtractor())
```

## Normalized Fields

The vendor extractors normalize private tags into these standard fields:

- `injected_activity_bq` - Activity in Becquerels (converted from MBq, mCi, etc.)
- `injection_time` - Injection time in DICOM TM format
- `injection_date` - Injection date in DICOM DA format
- `patient_weight_kg` - Patient weight in kilograms
- `radiopharmaceutical` - Radiopharmaceutical name
- `injection_delay_minutes` - Delay between injection and scan

## Data Storage

- **Raw Private Tags**: Stored in `private_tags` JSON field (all private tags)
- **Vendor Metadata**: Stored in `vendor_metadata` JSON field (normalized vendor-specific data)
- **Merged Fields**: Normalized data automatically fills missing standard DICOM fields

## Extensibility

The system is designed to be easily extended:

1. **Add new extractors** by subclassing `VendorExtractor`
2. **Register extractors** dynamically at runtime
3. **Priority system** allows ordering extractors (specific before generic)
4. **Fallback mechanism** ensures unknown vendors still get processed

## Examples

### Siemens Files
Siemens dose reports are often stored as text in private OB tags. The Siemens extractor:
- Finds text content in common private tag locations
- Uses regex to extract structured data
- Normalizes units (MBq → Bq)
- Extracts timing information

### Spectrum Dynamics Files
Spectrum Dynamics typically uses standard DICOM tags, but may have private tags for proprietary data. The extractor:
- Identifies Spectrum-specific private tags
- Extracts activity information
- Handles various unit formats

### Unknown Vendors
For vendors without specific extractors:
- Generic extractor uses pattern matching
- Looks for common keywords (MBq, activity, dose)
- Extracts numeric values with units
- Lower confidence but still useful

