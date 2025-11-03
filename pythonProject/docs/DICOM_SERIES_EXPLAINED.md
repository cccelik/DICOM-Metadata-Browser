# DICOM Series Explained

## DICOM Hierarchy

DICOM files are organized in a **4-level hierarchy**:

```
PATIENT
  └── STUDY (one exam/session)
        └── SERIES (one scan/technique)
              └── INSTANCE (one image/file)
```

## What is a Series?

A **Series** represents **one scan or one acquisition technique** within a study.

### Key Characteristics:

1. **One Series = One Type of Scan**
   - Each series has a specific purpose
   - Has consistent parameters (modality, protocol, technique)
   - Contains multiple images (instances) of the same type

2. **Series Instance UID (Unique Identifier)**
   - Every series has a unique ID: `SeriesInstanceUID`
   - Different series = different `SeriesInstanceUID`
   - Same series = same `SeriesInstanceUID`

3. **Series Number**
   - Sequential number (1, 2, 3, ...) within a study
   - Helps organize series in order

## Real-World Example: PET/CT Scan

A single **Study** (one patient visit) might contain **multiple Series**:

### Example Study: "Chest PET/CT with Contrast"

**Series 1: Localizer**
- Purpose: Scout image to plan the scan
- Modality: CT
- Images: 1-3 images (topogram/scout)
- Series Description: "Topogram" or "Scout"

**Series 2: CT Scan**
- Purpose: Anatomical imaging
- Modality: CT
- Images: ~500 images (slices through body)
- Series Description: "CT Chest"

**Series 3: PET Scan**
- Purpose: Functional imaging (FDG uptake)
- Modality: PT (PET)
- Images: ~200 images (PET slices)
- Series Description: "PET Chest"

**Series 4: CT for Attenuation Correction**
- Purpose: Low-dose CT for PET correction
- Modality: CT
- Images: ~100 images
- Series Description: "CTAC" (CT Attenuation Correction)

**Result:** 1 Study, 4 Series, ~800 total images

## Your Data Examples

### Scan 43 (Tc99m-OneDay)

Looking at your data, scan 43 has multiple series:

```
STUDY: Tc99m-OneDay 4.23.2024 10:25:00 AM
  └── SERIES 1: STR_U_MB_SD1_SA (Stress images, anterior)
  └── SERIES 2: STR_U_MB_SD1_SA (Stress images, another view)
  └── SERIES 3: STR_U_MB_SD1_TA (Stress images, different technique)
  └── SERIES 4: RST_U_MB_SD1_TA (Rest images)
```

**Each series:**
- Different **SeriesInstanceUID** (unique ID)
- Different **SeriesNumber** (1, 2, 3, 4)
- Same **StudyInstanceUID** (all part of one study)
- May have different **SeriesDescription** (different views/techniques)

### Scan 42 (Herz - Heart PET/MR)

```
STUDY: Herz-MR-PET
  └── SERIES 1: localizer (MR localizer images)
  └── SERIES 2: localizer@center (MR localizer centered)
  └── SERIES 3: Thorax_Cor_Tra (Thorax coronal/transversal)
  └── SERIES 4: cine_tf2d14_retro_SAX (Cine MR images)
  └── SERIES 5: Native_MOLLI_T1map (T1 mapping)
  └── SERIES 6: 15min_DE_192_tfi_psir_2CH_MAG (2-chamber view)
  └── SERIES 7: gated_PRR_ACImages (Gated PET images)
  └── SERIES 8: Tho_PETMR_FDG... (PET thorax images)
```

## Why Multiple Series?

### 1. **Different Modalities**
- CT series + PET series in same study
- MR series + PET series in same study

### 2. **Different Techniques**
- Stress images vs Rest images (Nuclear Medicine)
- Different MR sequences (T1, T2, FLAIR, etc.)
- Different contrast phases (pre-contrast, post-contrast)

### 3. **Different Views/Orientations**
- Axial vs Coronal vs Sagittal
- Anterior vs Posterior
- Different angles

### 4. **Different Purposes**
- Localizer (planning)
- Diagnostic images
- Attenuation correction
- Motion correction

### 5. **Temporal Series**
- Different time points (dynamic scans)
- Before and after contrast
- Multiple acquisitions over time

## Series vs Study: Key Differences

| Aspect | Study | Series |
|--------|-------|--------|
| **Scope** | Entire exam/session | One specific scan |
| **Purpose** | Clinical question/indication | One technique/modality |
| **UID** | `StudyInstanceUID` | `SeriesInstanceUID` |
| **Number** | Usually one per visit | Multiple per study |
| **Time** | Study Date/Time (admin) | Series/Acquisition Time (actual scan) |
| **Images** | All images in exam | One type of images |

## Series-Level Metadata

Each series can have:

- **Series Description:** Name/purpose of the series
- **Series Number:** Order within study (1, 2, 3, ...)
- **Modality:** Type of imaging (CT, PT, MR, etc.)
- **Series Date/Time:** When this specific series was acquired
- **Acquisition Date/Time:** Actual scan time (more precise)
- **Number of Images:** How many instances in this series
- **Protocol Name:** Scan protocol used
- **Image Type:** Reconstruction type

## In Your Code

### Database Structure

Your code stores **one row per DICOM file (instance)**, but groups by:

1. **Study Level:** `StudyInstanceUID` - groups all series together
2. **Series Level:** `SeriesInstanceUID` - groups images within series

### Web UI Display

- **Index Page:** Shows studies (grouped by `StudyInstanceUID`)
- **Study Detail Page:** Shows all series within that study
  - Each series has its own section
  - Shows series description, modality, number of images

### Deduplication

Your code uses:
- **Series-level deduplication:** Same `SeriesInstanceUID` = skip (already in database)
- **Study-level detection:** Different `SeriesInstanceUID` = can add to existing study

This allows:
- Adding new series to an existing study
- Not duplicating series that already exist

## Common Patterns in Your Data

### Nuclear Medicine (Tc99m scans)

**Pattern:** One study with multiple series for:
- Stress images (different views/techniques)
- Rest images
- Quality control images

### PET/CT Scans

**Pattern:** One study with:
- CT series (anatomy)
- PET series (function)
- Optional: Attenuation correction, localizers

### PET/MR Scans

**Pattern:** One study with:
- MR series (various sequences: T1, T2, cine, etc.)
- PET series
- Localizer series

## Summary

**Series are NOT just "different scans"** - they're **organized scans within one study**.

**Think of it like:**
- **Study** = Photo session
- **Series** = Different types of photos (close-ups, wide shots, different angles)
- **Instance** = Individual photos

Or:
- **Study** = Meal
- **Series** = Courses (appetizer, main, dessert)
- **Instance** = Individual dishes

In medical imaging:
- **Study** = Patient visit/exam
- **Series** = Different imaging techniques/modalities used
- **Instance** = Individual DICOM image files

