# DICOM Date/Time Rollover Issue

## The Problem

When an acquisition happens **after midnight** (e.g., 01:59 AM), the **Acquisition Date** often remains the **same as the Study Date**, even though logically the acquisition occurred on the next calendar day.

## Example from Your Data

```
Study Date:      1988-01-02
Study Time:       23:11:27 (11:11 PM, Jan 2)
Acquisition Date: 1988-01-02 (same day ❌)
Acquisition Time: 01:59:56 (1:59 AM - logically Jan 3! ✅)
```

**Problem:** The acquisition time shows 01:59 AM, which is clearly the next day, but the date field still shows the previous day.

## Why This Happens

### DICOM Date/Time Fields Are Independent

DICOM stores date and time as **separate, independent fields**:

- **Acquisition Date (0008,0022):** `YYYYMMDD` format
- **Acquisition Time (0008,0032):** `HHMMSS` format

These fields don't automatically account for day boundaries.

### Scanner Behavior

When a scanner/protocol creates DICOM files:

1. **Study Date/Time** is set when the study session starts
2. **Acquisition Date** is often **copied from Study Date** at initialization
3. **Acquisition Time** is set to the **actual acquisition moment**

If the acquisition happens after midnight:
- **Acquisition Time** correctly shows the time (e.g., `015956` = 1:59 AM)
- **Acquisition Date** might not be updated (still shows previous day)

## This Is a Common DICOM Limitation

This is a **known limitation** in DICOM:
- Date and time fields are stored separately
- No automatic rollover logic
- Up to the scanner/software to correctly update the date field
- Many scanners don't update the date when time crosses midnight

## How Different Vendors Handle This

### Some Vendors Correctly Update Date

**Good behavior:**
```
Study Date:      1988-01-02
Study Time:       23:11:27
Acquisition Date: 1988-01-03 ✅ (correctly rolled over)
Acquisition Time: 01:59:56
```

### Many Vendors Keep Same Date

**Common behavior:**
```
Study Date:      1988-01-02
Study Time:       23:11:27
Acquisition Date: 1988-01-02 ❌ (same as study date)
Acquisition Time: 01:59:56
```

## How Your Code Handles This

Your code detects this situation and shows a warning:

```python
# If study is late (>= 22:00) and acquisition is early (<= 06:00), likely next day
if study_hours >= 22 and acq_hours <= 6:
    s['acquisition_likely_next_day'] = True
```

The web UI then displays: **(likely next day)**

## How to Calculate Correct Date

### Option 1: Manual Logic (What Your Code Does)

If acquisition time is after midnight and study time was late evening, add 1 day:

```python
from datetime import datetime, timedelta

study_date_str = "19880102"  # YYYYMMDD
acquisition_time_str = "015956"  # HHMMSS

# Parse study date
study_date = datetime.strptime(study_date_str, "%Y%m%d")

# If acquisition time suggests next day (after midnight when study was late)
if acquisition_hours <= 6:  # Early morning
    acquisition_date = study_date + timedelta(days=1)
else:
    acquisition_date = study_date
```

### Option 2: Trust the DICOM Date (Current Approach)

Your code currently **trusts the DICOM Acquisition Date** as-is, but adds a visual indicator when it seems wrong.

## Recommendations

### For Display

1. **Show the DICOM date as-is** (what scanner reported)
2. **Add visual indicator** when date seems wrong: "(likely next day)"
3. **Let users know** this is a scanner limitation, not a bug in your code

### For Calculations

When calculating time differences (injection delay, etc.):
- If you detect a likely next-day scenario
- Either:
  - Add 1 day to the acquisition date
  - Or use acquisition time only and assume same day if time > study time

## Example: Fixing Date for Calculations

```python
def get_correct_acquisition_datetime(study_date, study_time, acq_date, acq_time):
    """Get acquisition datetime, accounting for midnight rollover"""
    from datetime import datetime, timedelta
    
    # Parse dates and times
    study_dt = datetime.strptime(study_date + study_time[:6], "%Y%m%d%H%M%S")
    acq_time_part = acq_time[:6] if len(acq_time) >= 6 else acq_time
    
    # Start with the acquisition date from DICOM
    acq_date_obj = datetime.strptime(acq_date, "%Y%m%d")
    
    # Check if time suggests next day
    acq_hours = int(acq_time_part[:2])
    study_hours = int(str(study_time)[:2])
    
    if study_hours >= 22 and acq_hours <= 6:
        # Likely next day - add 1 day
        acq_date_obj = acq_date_obj + timedelta(days=1)
    
    # Combine date and time
    acq_dt = datetime.combine(
        acq_date_obj.date(),
        datetime.strptime(acq_time_part, "%H%M%S").time()
    )
    
    return acq_dt
```

## Summary

**The Issue:**
- DICOM stores date and time separately
- When acquisition happens after midnight, the date field often isn't updated
- This is a scanner/software limitation, not a DICOM standard flaw

**Your Code's Solution:**
- Detects when this happens (late study + early acquisition = likely next day)
- Shows visual indicator: "(likely next day)"
- Keeps original DICOM date for reference
- Could be enhanced to calculate correct date for time-difference calculations

**Best Practice:**
- Always show the original DICOM date (what scanner reported)
- Add indicators when date seems incorrect
- For calculations, use logic to infer correct date if needed

