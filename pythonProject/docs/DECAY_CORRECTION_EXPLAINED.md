# Decay Correction Explained

## What is Decay Correction?

**Decay Correction** is a flag in DICOM that indicates whether and how radioactive decay has been accounted for in nuclear medicine images.

## Why It Matters

### Radioactive Decay in Nuclear Medicine

When you inject a radiotracer (like FDG for PET scans):
- The radiotracer is **radioactive** and decays over time
- It has a **half-life** (time for half the radioactivity to decay)
- Example: F-18 FDG has a half-life of ~110 minutes

### The Problem

If you measure activity at the **scanner**:
- The measured activity is **lower** than what was injected
- Because some radioactivity has **decayed** between injection and scanning
- The longer the delay, the more decay has occurred

### Example Timeline

```
Time 0:     Injection - 100 MBq injected
            ↓
            (Radioactive decay occurs)
            ↓
Time 60 min: Scanner measures - Only 70 MBq remaining (30% decayed)
```

## What Decay Correction Does

**Decay correction** mathematically adjusts the measured activity back to a reference time:

1. **NONE** - No correction applied (raw measured values)
2. **START** - Corrected to scan/study start time
3. **ADMIN** - Corrected to administration/injection time

## DICOM Tag

- **Tag:** `(0018,1075)` - **DecayCorrection**
- **Type:** CS (Code String)
- **Format:** Text value like "NONE", "START", "ADMIN"

## Common Values

| Value | Meaning | When Used |
|-------|---------|-----------|
| **NONE** | No decay correction | Raw measurements, or when correction not needed |
| **START** | Corrected to study start | Standard for most PET/CT scans |
| **ADMIN** | Corrected to administration time | Less common, corrected to injection time |

## Why Display It?

Decay correction is important because:

1. **Image Interpretation**
   - Knowing if images are decay-corrected helps interpret SUV (Standardized Uptake Values)
   - SUV calculations depend on decay correction

2. **Activity Calculations**
   - If you're calculating remaining activity, you need to know:
     - Was the measurement already corrected?
     - To what time was it corrected?
   - If "START", the values shown might already account for decay

3. **Data Quality**
   - Indicates how the scanner/software processed the data
   - Important for research and quantitative analysis

4. **Consistency**
   - Different vendors/c scanners might use different corrections
   - Knowing this helps compare scans from different sources

## Relationship to Other Fields

- **Half Life** - The decay rate constant
- **Injection Time** - When decay correction might reference to
- **Acquisition Time** - When the actual measurement was made
- **Injected Activity** - Original activity before any decay

## Clinical Relevance

For **PET/CT scans**:
- SUV values depend on decay correction
- Standard practice: Correct to injection time or study start
- Allows comparison between scans with different injection-to-scan delays

For **quantitative analysis**:
- Need to know correction method to properly interpret measurements
- Research studies often require specific correction methods

## Summary

**Decay Correction** is displayed because it's:
- ✅ **Clinically relevant** - Affects how images should be interpreted
- ✅ **Important for calculations** - Needed for proper SUV and activity calculations
- ✅ **Quality indicator** - Shows how data was processed
- ✅ **Standard DICOM field** - Part of nuclear medicine standard tags

It's a single word/code that tells you a lot about how the nuclear medicine data was processed!

