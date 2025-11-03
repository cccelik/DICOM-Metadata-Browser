# Multiple Injections in Same Study

## Yes, It's Possible!

**Different series in the same study CAN have different injection times** - and your data shows this is common!

## Examples from Your Data

### Example 1: Stress/Rest Protocol
```
Study: Anonymous 43
  Series #1: STR_U_MB_SD1_TA (Stress)
    Injection Time: 09:26:36
    
  Series #2: RST_U_MB_SD1_TA (Rest)
    Injection Time: 10:06:48  ← Different injection!
```

### Example 2: Multiple Stress Series
```
Study: Anonymous 44
  Series #1: STR_U_MB_SD1_TA
    Injection Time: 13:14:34
    
  Series #2: STR_U_MB_SD1_TA (different view)
    Injection Time: 13:42:53  ← Different injection (28 minutes later!)
    
  Series #3: RST_U_MB_SD1_TA (Rest)
    Injection Time: 13:48:32  ← Third injection!
```

### Example 3: PET Study with Dose Report
```
Study: PET FDG
  Series #9: PET Dose Report
    Injection Time: 09:48:00
    
  Series #11: PET FDG stat
    Injection Time: 09:48:00.000000  (same, but different precision)
```

## Why Multiple Injections Happen

### 1. **Stress/Rest Protocols** (Common in Nuclear Medicine)
- **Stress Phase:** Injection #1, then stress test, then imaging
- **Rest Phase:** Injection #2 (often later, sometimes different dose), then rest imaging
- Each series corresponds to one phase with its own injection

### 2. **Multi-Phase Studies**
- **Early Phase:** Injection #1 → immediate imaging
- **Delayed Phase:** Wait period → delayed imaging (same or different injection)
- Different series capture different time points

### 3. **Dosimetry Studies**
- Multiple injections at different times
- Each injection tracked separately
- Different series for each time point

### 4. **Re-injection for Repeat Imaging**
- Initial injection didn't work well
- Additional injection given
- New series created with new injection time

## Current Issue in Your Code

### Database Storage ✅
Your database **correctly stores injection time per series**:
- Each DICOM file/instance has its own `injection_time` field
- Stored at the series level (one row per DICOM file)
- Can have different values for different series in same study

### Web UI Display ❌
Your web UI **only shows ONE injection time** at the study level:
- Takes the first injection time found
- Doesn't show that different series might have different injections
- Loses important information about multi-injection protocols

## How DICOM Handles This

### Injection Information Location

DICOM stores injection information in `RadiopharmaceuticalInformationSequence`:
- This sequence is **stored in EACH DICOM file**
- Each file/series can have its own sequence
- Each sequence can have different injection times

### Why This Makes Sense

In nuclear medicine workflows:
- **Study** = One patient visit/session
- **Series** = One imaging sequence (stress, rest, early, late, etc.)
- **Each series** might represent imaging after a different injection
- **Each injection** should be tracked separately

## What Should Change

### Current Behavior
```
Study Level:
  Injection Time: 09:26:36  ← Only shows first one found
  
Series Table:
  Series #1: STR_U_MB_SD1_TA
    (no injection time shown)
  Series #2: RST_U_MB_SD1_TA
    (no injection time shown)
```

### Recommended Behavior
```
Study Level:
  Note: Injection times vary by series - see Series table below

Series Table:
  Series #1: STR_U_MB_SD1_TA
    Injection Time: 09:26:36
  Series #2: RST_U_MB_SD1_TA
    Injection Time: 10:06:48  ← Different injection shown!
```

## Clinical Importance

### For Calculations

**Decay correction** requires knowing which injection corresponds to which acquisition:
- Series 1: Injection at 09:26:36, Acquisition at 10:15:00 → 48 min delay
- Series 2: Injection at 10:06:48, Acquisition at 10:45:00 → 38 min delay

Using the wrong injection time = wrong decay correction!

### For Protocol Documentation

Medical records need to track:
- How many injections were given
- When each injection occurred
- Which series corresponds to which injection
- Doses for each injection (if different)

## Summary

**Yes, different series can have different injections!**

This is **common and expected** in nuclear medicine:
- Stress/Rest protocols
- Multi-phase studies
- Dosimetry protocols
- Re-injections

**Your database already stores this correctly** (per series), but **your web UI should be updated** to:
1. Show injection times per series (like acquisition times)
2. Not assume all series have the same injection time
3. Display multiple injections when they exist

This would make the display much more accurate and clinically useful!

