# DICOM Time Fields Explained

## Study Time vs Acquisition Time

### Study Time (0008,0020 / 0008,0030)
**Tag:** `(0008,0030)` - Study Time
**Date Tag:** `(0008,0020)` - Study Date

**What it represents:**
- The **date and time when the study was created/ordered**
- When the scan was **scheduled** or **initiated**
- Administrative/booking time
- Often set when the technologist starts the study session

**Use case:**
- Administrative tracking
- Study identification
- Reporting and documentation
- Usually same for all series in a study

### Acquisition Time (0008,0022 / 0008,0032)
**Tag:** `(0008,0032)` - Acquisition Time  
**Date Tag:** `(0008,0022)` - Acquisition Date

**What it represents:**
- The **actual time when data was acquired**
- When the scanner **collected the image data**
- Physical scan time - when radiation was emitted/collected
- Can be different for each series (if multiple scans in one study)

**Use case:**
- Precise timing for decay correction calculations
- Physical measurement timing
- May vary between series if multiple scans were done

## Visual Timeline

```
Study Created (Study Time)
    |
    |  [Preparation, patient positioning, etc.]
    |
    v
Acquisition Starts (Acquisition Time)
    |
    |  [Scanner collecting data]
    |
    v
Acquisition Ends
```

## Real-World Example

**PET/CT Scan Session:**

1. **Study Time: 09:00:00**
   - Technologist starts study session
   - Patient positioned
   - Protocol selected

2. **CT Acquisition Time: 09:15:23**
   - CT scan actually performed
   - First data collected

3. **PET Acquisition Time: 09:30:45**
   - PET scan actually performed
   - Different from CT (different series)

**Result:**
- Study Date/Time: 2024-01-15 09:00:00 (same for all)
- CT Series Acquisition: 2024-01-15 09:15:23
- PET Series Acquisition: 2024-01-15 09:30:45

## Series Time vs Acquisition Time

### Series Time (0008,0021 / 0008,0031)
**Tag:** `(0008,0031)` - Series Time
**Date Tag:** `(0008,0021)` - Series Date

**What it represents:**
- Time when the **series was created**
- Similar to study time but at series level
- Often same as acquisition time (but not always)

### When They Differ

**Study Time < Series Time ≤ Acquisition Time**

- **Study Time**: Administrative start
- **Series Time**: Series-specific start
- **Acquisition Time**: Actual data collection

In practice, Series Time and Acquisition Time are often the same or very close.

## In Nuclear Medicine / PET Scans

### Why Acquisition Time Matters

For **decay correction calculations**, you need **Acquisition Time**:
- Radionuclide activity decays over time
- Need precise time between injection and acquisition
- Study time is too early (before preparation)

**Formula:**
```
Activity_at_acquisition = Injected_activity × e^(-λ × (acquisition_time - injection_time))
```

Where:
- `λ = ln(2) / half_life`
- Need **acquisition_time**, not study_time

## What Your Code Extracts

Currently extracting:

1. **Study Date/Time** `(0008,0020 / 0008,0030)`
   - Administrative study start
   - Same for all series in study

2. **Series Date/Time** `(0008,0021 / 0008,0031)`
   - Series-specific time
   - Can differ between series

3. **Acquisition Date/Time** `(0008,0022 / 0008,0032)`
   - Actual data collection time
   - Most accurate for timing calculations

4. **Content Date/Time** `(0008,0023 / 0008,0033)`
   - When DICOM object was created
   - Often same as acquisition

## Best Practice

### For Nuclear Medicine Calculations:
✅ **Use Acquisition Time** - Most accurate for decay calculations
⚠️ **Use Series Time** - If acquisition time not available
❌ **Don't use Study Time** - Too early, includes preparation time

### For Display/Reporting:
✅ **Study Time** - Good for "when was scan performed?" (general)
✅ **Acquisition Time** - Good for precise timing information

## Summary

| Field | Represents | When Used |
|-------|-----------|-----------|
| **Study Time** | When study session started | Administrative, general timing |
| **Series Time** | When series started | Series-specific timing |
| **Acquisition Time** | When data actually collected | **Decay calculations, precise timing** |

**Key Takeaway:** 
- **Study Time** = Administrative/booking time
- **Acquisition Time** = Actual scan time (most important for calculations)

