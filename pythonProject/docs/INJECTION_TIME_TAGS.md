# Injection Time DICOM Tags

## Primary Tag (Standard DICOM)

**Tag:** `(0018,1072)` - **RadiopharmaceuticalStartTime**

- **Location:** Inside `RadiopharmaceuticalInformationSequence` (SQ - Sequence)
- **Format:** TM (Time) - `HHMMSS[.frac]` (24-hour format)
- **Example:** `112754.000` = 11:27:54 AM
- **Standard:** Part of DICOM Standard for Nuclear Medicine

**Access in code:**
```python
if 'RadiopharmaceuticalInformationSequence' in ds:
    item = ds.RadiopharmaceuticalInformationSequence[0]
    injection_time = item.RadiopharmaceuticalStartTime  # Tag (0018,1072)
```

## Fallback Tag (Non-Standard)

**Tag:** `InjectionTime` (not a standard tag, vendor-specific)

- **Location:** Direct dataset attribute
- **Format:** TM (Time) - `HHMMSS[.frac]`
- **Note:** Not always present, depends on vendor implementation

**Access in code:**
```python
injection_time = ds.InjectionTime  # If RadiopharmaceuticalInformationSequence not available
```

## Injection Date Tag

**Tag:** `InjectionDate` or `(0018,1074)` - **InjectionDate**

- **Location:** Direct dataset attribute or in RadiopharmaceuticalInformationSequence
- **Format:** DA (Date) - `YYYYMMDD`
- **Example:** `19880102` = January 2, 1988

## Related Tags in Sequence

Inside `RadiopharmaceuticalInformationSequence`, you can also find:

- `(0018,1071)` - **RadiopharmaceuticalVolume** (volume injected)
- `(0018,1072)` - **RadiopharmaceuticalStartTime** (injection start time)
- `(0018,1073)` - **RadiopharmaceuticalStopTime** (injection end time) - *not currently extracted*
- `(0018,1074)` - **RadionuclideTotalDose** (total activity injected)
- `(0018,1075)` - **RadionuclideHalfLife** (half-life of radionuclide)

## How Your Code Extracts It

**Priority order:**

1. **First:** `RadiopharmaceuticalInformationSequence[0].RadiopharmaceuticalStartTime` (standard)
2. **Second:** `ds.InjectionTime` (fallback if sequence not available)
3. **Third:** Vendor-specific normalization from private tags (Siemens, Spectrum Dynamics, etc.)

**Code location:** `extract_metadata.py` lines 193-210

```python
# Primary source - from sequence
if 'RadiopharmaceuticalInformationSequence' in ds:
    item = rad_seq[0]
    meta.injection_time = safe_getattr(item, 'RadiopharmaceuticalStartTime')

# Fallback - direct tag
meta.injection_time = meta.injection_time or safe_getattr(ds, 'InjectionTime')
```

## Verification

To see what tag was actually used in your data:

```python
import pydicom
ds = pydicom.dcmread("path/to/file.dcm")

# Check if sequence exists
if 'RadiopharmaceuticalInformationSequence' in ds:
    item = ds.RadiopharmaceuticalInformationSequence[0]
    print(f"Injection Time from sequence: {item.get('RadiopharmaceuticalStartTime', 'N/A')}")

# Check direct tag
if 'InjectionTime' in ds:
    print(f"Injection Time direct: {ds.InjectionTime}")
```

## Time Format

All injection times are stored in **DICOM TM (Time) format:**
- Format: `HHMMSS[.frac]` (no colons, 24-hour)
- `112754` = 11:27:54 AM
- `231127` = 23:11:27 PM
- `112754.000` = 11:27:54.000 AM (with fractional seconds)

Your code converts this to human-readable format: `11:27:54`

