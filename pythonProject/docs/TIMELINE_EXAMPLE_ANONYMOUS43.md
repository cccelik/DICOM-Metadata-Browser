# Timeline Issue: Anonymous 43 Example

## The Question

**How can injection time be 10:06 AM but acquisition be 00:38 (12:38 AM) on the same day?**

**Answer: They're NOT on the same day!** This is a DICOM date field rollover issue.

## Anonymous 43 - Series #3 (Rest Scan)

### What DICOM Fields Show

```
Study Date:          June 25, 1990
Injection Time:      10:06:48 (10:06 AM)
Acquisition Date:    June 25, 1990  ← Shows same day (INCORRECT!)
Acquisition Time:    00:38:51 (12:38:51 AM)
```

### The Problem

The **Acquisition Time** of `00:38:51` means:
- **00:38:51 = 12:38:51 AM**
- This is **AFTER MIDNIGHT** (the next calendar day!)
- So acquisition is actually **June 26, 1990 at 12:38 AM**

But the **Acquisition Date** field still shows **June 25** because:
- The scanner didn't update the date field when time crossed midnight
- This is the DICOM date rollover limitation

## Correct Timeline

### June 25, 1990
```
10:06:48 AM  → Injection given (rest protocol)
              (wait period - patient rests)
...
11:59:59 PM  → Still June 25
```

### June 26, 1990 (Next Day)
```
12:00:00 AM  → MIDNIGHT - new day begins
12:38:51 AM  → Acquisition happens ← NEXT DAY!
```

## Time Difference

**Actual delay:**
- Injection: June 25, 10:06:48 AM
- Acquisition: June 26, 00:38:51 AM
- **Total delay: ~14 hours 32 minutes**

If we incorrectly assumed same day:
- Injection: June 25, 10:06:48 AM
- Acquisition: June 25, 00:38:51 AM
- This would be **NEGATIVE time** (impossible!)

## Why This Happens

### DICOM Date/Time Fields Are Separate

- **Acquisition Date (0008,0022):** `YYYYMMDD` - Set at study start
- **Acquisition Time (0008,0032):** `HHMMSS` - Set when acquisition happens

When acquisition happens after midnight:
- ✅ **Time field** correctly shows early morning (00:38 = 12:38 AM)
- ❌ **Date field** often NOT updated (still shows previous day)

### Scanner Behavior

Many scanners:
1. Set Acquisition Date to Study Date at initialization
2. Update Acquisition Time correctly when scan happens
3. **Don't update** Acquisition Date when time crosses midnight

## Clinical Context

This makes sense for a **rest scan protocol**:
- **Morning:** Injection (10:06 AM)
- **Wait period:** Patient rests, radiotracer distributes
- **Next morning:** Rest scan acquisition (12:38 AM next day)

A 14+ hour delay between injection and rest imaging is **normal** for stress/rest protocols.

## Solution

The UI should detect this and show:
- **Acquisition Date:** June 25, 1990 (what DICOM says)
- **Acquisition Time:** 00:38:51
- **Note:** "(likely next day)" - indicating the date might be wrong

Or ideally, calculate the correct date:
- If acquisition time is early morning (00:00-06:00)
- And study time was late evening (22:00-23:59)
- Then acquisition date should be **next day**

## Summary

**Injection Time: 10:06 AM** and **Acquisition Time: 00:38** are:
- ✅ **NOT on the same day** (acquisition is next morning)
- ❌ But DICOM **Acquisition Date** incorrectly shows same day
- ✅ **Acquisition Time** is correct (shows after midnight)
- ⚠️ This is a **scanner limitation**, not a bug in your code

The actual timeline is:
- **June 25, 10:06 AM** - Injection
- **June 26, 12:38 AM** - Acquisition (next day!)

