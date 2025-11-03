# Understanding DICOM Tags: Private vs Standard

## Quick Rule: Group Number Parity

**Simple rule to remember:**
- ✅ **Even group number** (0, 2, 4, 6, 8...) = **Standard DICOM tag**
- ⚠️ **Odd group number** (1, 3, 5, 7, 9...) = **Private tag**

## Tag Format

DICOM tags are written as `(GGGG,EEEE)` in hexadecimal:
- `GGGG` = Group number (4 hex digits)
- `EEEE` = Element number (4 hex digits)

### Examples

#### Standard Tags (Even Groups)
```
(0010,0010) - Patient Name           (Group 0x0010 = even)
(0008,0020) - Study Date              (Group 0x0008 = even)
(0018,1030) - Protocol Name           (Group 0x0018 = even)
(0020,000D) - Study Instance UID      (Group 0x0020 = even)
(0008,0060) - Modality                (Group 0x0008 = even)
```

#### Private Tags (Odd Groups)
```
(0029,1010) - Siemens private tag     (Group 0x0029 = odd)
(0019,0010) - Siemens private tag     (Group 0x0019 = odd)
(0021,1010) - Vendor-specific data   (Group 0x0021 = odd)
(7FE0,0010) - Pixel Data (special case - even but also private)
```

## Why This Matters

### Standard Tags
- ✅ **Defined by DICOM standard** - Same meaning across all vendors
- ✅ **Well-documented** - You can look up what they mean
- ✅ **Interoperable** - All DICOM software understands them
- ✅ **Examples:** Patient Name, Study Date, Modality

### Private Tags
- ⚠️ **Vendor-specific** - Meaning defined by manufacturer
- ⚠️ **Proprietary** - May contain proprietary data formats
- ⚠️ **Not standardized** - Different vendors use different tags
- ⚠️ **Examples:** 
  - Siemens dose reports
  - GE proprietary protocols
  - Philips private data

## Common Standard Tag Groups

| Group | Meaning |
|-------|---------|
| `0008` | Identification (Study info, dates) |
| `0010` | Patient information |
| `0018` | Acquisition parameters |
| `0020` | Relational information (UIDs, numbers) |
| `0028` | Image presentation |
| `7FE0` | Pixel data (special) |

## Common Private Tag Groups

Different vendors use different odd-numbered groups:

| Group | Vendor | Common Use |
|-------|--------|-----------|
| `0029` | Siemens | Dose reports, protocols |
| `0019` | Siemens | Additional data |
| `0021` | Various | Vendor-specific |
| `7FE1` | Various | Additional pixel data |

## How Your Code Identifies Private Tags

In `extract_metadata.py`, private tags are identified by:

```python
for elem in ds:
    tag = elem.tag
    # Private tags have odd group numbers
    if tag.group % 2 == 1:
        # This is a private tag!
        ...
```

This checks if the group number divided by 2 has a remainder of 1 (i.e., odd number).

## Practical Examples

### Looking at a Real DICOM File

```python
import pydicom

ds = pydicom.dcmread('file.dcm', stop_before_pixels=True)

for elem in ds:
    tag = elem.tag
    if tag.group % 2 == 1:
        print(f"PRIVATE: {tag.group:04X}{tag.element:04X} = {elem.value}")
    else:
        print(f"STANDARD: {tag.group:04X}{tag.element:04X} = {elem.value}")
```

### Example Output

```
STANDARD: 00100010 = Patient Name: "John^Doe"
STANDARD: 00080020 = Study Date: "20240101"
PRIVATE: 00291010 = <binary data: 2678 bytes>  # Siemens dose report
PRIVATE: 00291008 = "CTDOSEREPORT"             # Siemens private text
```

## Why Private Tags Are Important

1. **Vendor-Specific Information**
   - Dose reports (Siemens, GE)
   - Proprietary scan parameters
   - Advanced reconstruction settings

2. **Additional Metadata**
   - Information not in standard DICOM tags
   - Manufacturer-specific calculations
   - Internal system data

3. **Your Normalization Layer**
   - Extracts private tags for each vendor
   - Converts vendor-specific data to standard format
   - Makes proprietary data accessible

## How to Look Up Tags

### Standard Tags
Use DICOM standard documentation:
- **DICOM Part 6: Data Dictionary**
- Online tools: https://dicom.innolitics.com/
- Python: `pydicom` includes tag definitions

### Private Tags
- **Not standardized** - Must check vendor documentation
- **Siemens:** Uses groups 0029, 0019
- **GE:** Uses different odd-numbered groups
- **Spectrum Dynamics:** Uses vendor-specific groups

## Visual Guide

```
DICOM Tag Format: (GGGG,EEEE)

Examples:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tag:          (0010,0010)
Group:        0010  ← Even = STANDARD ✅
Element:           0010
Meaning:      Patient Name (standard DICOM)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tag:          (0029,1010)
Group:        0029  ← Odd = PRIVATE ⚠️
Element:           1010
Meaning:      Vendor-specific (Siemens dose report)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tag:          (0008,0020)
Group:        0008  ← Even = STANDARD ✅
Element:           0020
Meaning:      Study Date (standard DICOM)
```

## Special Cases

### Pixel Data (7FE0,0010)
- Group is **even** but contains image pixel data
- Often very large (millions of bytes)
- Sometimes treated specially by implementations

### Group 0000 (File Meta Information)
- Even group but special header information
- Contains file structure metadata
- Not patient/study data

## Tools to Identify Tags

### In Python (pydicom)
```python
import pydicom

ds = pydicom.dcmread('file.dcm', stop_before_pixels=True)

# Check if tag is private
tag = pydicom.tag.Tag(0x0029, 0x1010)
if tag.group % 2 == 1:
    print("Private tag")
else:
    print("Standard tag")
    
# Get tag name (for standard tags)
if hasattr(pydicom.datadict, 'dictionary_has_tag'):
    try:
        keyword = pydicom.datadict.keyword_for_tag(tag)
        print(f"Tag keyword: {keyword}")
    except:
        print("Private or unknown tag")
```

### Online Tools
- **DICOM Standard Browser:** https://dicom.innolitics.com/
- Enter tag like `(0010,0010)` to see definition

## Summary

**Remember:**
1. **Even group number** = Standard DICOM tag (everyone uses same meaning)
2. **Odd group number** = Private tag (vendor-specific)
3. **Your code** correctly identifies private tags using `tag.group % 2 == 1`
4. **Private tags** contain vendor-specific data that your normalization layer extracts

