# DICOM Time Format Explanation

## Format

**DICOM Time (TM - Time) format:** `HHMMSS[.frac]`

- **HH** = Hours (00-23, 24-hour format)
- **MM** = Minutes (00-59)
- **SS** = Seconds (00-59)
- **[.frac]** = Optional fractional seconds

**Examples:**
- `231127` = 23:11:27 (11:11:27 PM)
- `015956` = 01:59:56 (1:59:56 AM)
- `112754` = 11:27:54 (11:27:54 AM)
- `000000` = 00:00:00 (midnight)
- `235959` = 23:59:59 (one second before midnight)

## Understanding Your Timeline

### Your Example:
- **Study Time:** `231127` = **23:11:27** (11:11 PM)
- **Acquisition Time:** `015956` = **01:59:56** (1:59 AM)
- **Injection Time:** `112754` = **11:27:54** (11:27 AM)

### What This Means:

**If all on the same date (1988-01-02):**

The timeline could be:
1. **11:27 AM** - Injection (morning)
2. **23:11 PM** - Study session starts (evening, same day)
3. **01:59 AM** - Acquisition happens (**next day**, after midnight)

**OR** the times might be in different timezones, or there could be data entry errors.

## Common Scenarios

### Scenario 1: All Same Day
```
Date: 1988-01-02
11:27 AM - Injection
23:11 PM - Study starts
01:59 AM (next day) - Acquisition
```
This means acquisition happened the **next morning** after study start.

### Scenario 2: Acquisition Next Day
If acquisition time (01:59) is after midnight, it's likely the **next day**:
```
Date: 1988-01-02
23:11 PM - Study starts
01:59 AM (1988-01-03) - Acquisition (next day)
```

### Scenario 3: Timezone Issues
Times might be stored in different timezones or UTC vs local time.

## How Your Code Parses It

```python
# DICOM format: "231127" or "231127.000"
hours = "23"   # First 2 digits
minutes = "11"  # Next 2 digits  
seconds = "27"  # Next 2 digits
# Result: "23:11:27"
```

## Why Times Might Not Make Sense

1. **Date Field Missing:** If dates are the same but times span midnight
2. **Timezone Issues:** Times stored in UTC vs local time
3. **System Clock Issues:** Scanner system time might be wrong
4. **Data Entry Errors:** Human error when entering times
5. **Cross-Day Scans:** Long scans that span midnight

## Checking Your Data

To verify:
1. Check if **acquisition_date** differs from **study_date**
2. Check if injection date differs
3. Look at series-level acquisition times (each series can have different times)

## Example Timeline That Makes Sense

**Normal PET/CT scan:**
```
Date: 2024-01-15
08:00 AM - Study session starts
08:15 AM - Patient positioned
08:30 AM - CT Acquisition (08:30:00)
09:00 AM - PET Acquisition (09:00:00)
09:45 AM - Study complete
```

**With injection:**
```
Date: 2024-01-15
07:30 AM - Injection (injection_time: 073000)
08:00 AM - Study session starts (study_time: 080000)
09:00 AM - Acquisition (acquisition_time: 090000)
```

## Your Specific Case

For scan 43:
- **Injection:** 11:27 AM (morning)
- **Study:** 23:11 PM (evening) - This is **after** injection (same day)
- **Acquisition:** 01:59 AM - This is **after midnight**, so likely **next day**

**Most likely:** The acquisition happened the **morning after** the study was initiated.

## How to Fix Display

The times are being parsed correctly. If the timeline seems wrong, it might be:
1. The data itself (check if dates are correct)
2. Need to check if acquisition_date is actually the next day
3. Timezone conversion needed

