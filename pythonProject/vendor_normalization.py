#!/usr/bin/env python3
"""
Vendor-Specific Private Tag Normalization Layer
Dynamically extracts and normalizes private tags for different DICOM vendors
"""

import re
import json
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
from pydicom.dataset import Dataset
from dataclasses import dataclass, field, asdict


@dataclass
class VendorMetadata:
    """Normalized vendor-specific metadata extracted from private tags"""
    vendor_name: str
    normalized_data: Dict[str, Any] = field(default_factory=dict)
    raw_private_tags: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class VendorExtractor(ABC):
    """Base class for vendor-specific private tag extractors"""
    
    @abstractmethod
    def can_handle(self, ds: Dataset) -> bool:
        """Check if this extractor can handle this DICOM dataset"""
        pass
    
    @abstractmethod
    def extract(self, ds: Dataset, private_tags: Dict[str, Any]) -> VendorMetadata:
        """Extract and normalize vendor-specific private tags"""
        pass
    
    def _safe_get_private_tag(self, ds: Dataset, group: int, element: int):
        """Safely get a private tag value"""
        try:
            tag = pydicom.tag.Tag(group, element)
            if tag in ds:
                return ds[tag].value
        except Exception:
            pass
        return None
    
    def _decode_bytes(self, value) -> Optional[str]:
        """Decode bytes/bytearray to string"""
        if isinstance(value, (bytes, bytearray)):
            try:
                return value.decode('utf-8', errors='ignore')
            except:
                return None
        return None


class SiemensExtractor(VendorExtractor):
    """Extractor for Siemens private tags"""
    
    # Common Siemens private tag locations for dose/report data
    SIEMENS_PRIVATE_TAGS = [
        (0x0029, 0x1010),  # Siemens private OB (commonly used for XML reports)
        (0x0029, 0x1210),  # Siemens private OB (alternative)
        (0x0019, 0x0010),  # Siemens private
    ]
    
    # Regex patterns for extracting information from Siemens text/XML reports
    PATTERNS = {
        'radiopharmaceutical': re.compile(r'Radiopharm[aceuticals]*[:\s>]+([^<\n\r]+)', re.IGNORECASE),
        'activity': re.compile(r'(?:Injected|Activity|Dose|Radionuclide Total Dose)[:\s>]*([\d.]+)\s*(MBq|mCi|kBq|Bq)', re.IGNORECASE),
        'injection_time': re.compile(r'(?:Injection|Inj)[\s-]*(?:Time|Timepoint|Start Time)[:\s>]+([\d:.\s]+)', re.IGNORECASE),
        'injection_date': re.compile(r'(?:Injection|Inj)[\s-]*(?:Date|Start Date)[:\s>]+([\d./-]+)', re.IGNORECASE),
        'weight': re.compile(r'(?:Patient|Body)[\s-]*(?:Weight|Mass)[:\s>]+([\d.]+)\s*(?:kg|Kg|KG)?', re.IGNORECASE),
        'delay': re.compile(r'(?:Delay|Wait)[\s-]*(?:Time)?[:\s>]+([\d.]+)\s*(?:min|minutes|minute)', re.IGNORECASE),
        'half_life': re.compile(r'(?:Half[-\s]?Life|HalfLife)[:\s>]+([\d.]+)\s*(?:s|sec)', re.IGNORECASE),
    }
    
    # XML patterns for structured Siemens data (more flexible matching)
    XML_PATTERNS = {
        'radiopharmaceutical': re.compile(r'<m_StatisticsNameVector>\s*Radiopharmaceutical\s*</m_StatisticsNameVector>.*?<m_StatisticsValueVector>\s*([^<\n\r]+?)\s*</m_StatisticsValueVector>', re.DOTALL | re.IGNORECASE),
        'radioisotope': re.compile(r'<m_StatisticsNameVector>\s*Radioisotope\s*</m_StatisticsNameVector>.*?<m_StatisticsValueVector>\s*([^<\n\r]+?)\s*</m_StatisticsValueVector>', re.DOTALL | re.IGNORECASE),
        'activity': re.compile(r'<m_StatisticsNameVector>.*?(?:Radionuclide Total Dose|Injected Activity|Total Dose).*?</m_StatisticsNameVector>.*?<m_StatisticsValueVector>\s*([\d.]+)\s*(MBq|mCi|kBq|Bq)?\s*</m_StatisticsValueVector>', re.DOTALL | re.IGNORECASE),
        'injection_date': re.compile(r'<m_StatisticsNameVector>.*?Inj[.\s-]*Start Date[^<]*</m_StatisticsNameVector>.*?<m_StatisticsValueVector>\s*([^<\n\r]+?)\s*</m_StatisticsValueVector>', re.DOTALL | re.IGNORECASE),
        'injection_time': re.compile(r'<m_StatisticsNameVector>.*?Inj[.\s-]*Start Time[^<]*</m_StatisticsNameVector>.*?<m_StatisticsValueVector>\s*([^<\n\r]+?)\s*</m_StatisticsValueVector>', re.DOTALL | re.IGNORECASE),
        'half_life': re.compile(r'<m_StatisticsNameVector>.*?Half[-\s]?Life[^<]*</m_StatisticsNameVector>.*?<m_StatisticsValueVector>\s*([\d.]+)\s*</m_StatisticsValueVector>', re.DOTALL | re.IGNORECASE),
    }
    
    def can_handle(self, ds: Dataset) -> bool:
        """Check if this is a Siemens dataset"""
        manufacturer = getattr(ds, 'Manufacturer', '')
        return 'SIEMENS' in str(manufacturer).upper()
    
    def extract(self, ds: Dataset, private_tags: Dict[str, Any]) -> VendorMetadata:
        """Extract Siemens-specific private tag information"""
        normalized = {}
        
        # Extract text/XML from common Siemens private OB tags
        text_content = ""
        for group, element in self.SIEMENS_PRIVATE_TAGS:
            try:
                tag = pydicom.tag.Tag(group, element)
                if tag in ds:
                    value = ds[tag].value
                    decoded = self._decode_bytes(value)
                    if decoded and len(decoded) > 50:  # Likely text/XML content
                        text_content = decoded
                        break
            except Exception:
                continue
        
        if text_content:
            # Try XML parsing first (for structured Siemens reports)
            is_xml = text_content.strip().startswith('<')
            
            if is_xml:
                # Siemens XML structure: all NameVector tags first, then all ValueVector tags
                # Need to parse by position/index
                try:
                    # Extract all name vectors
                    name_matches = list(re.finditer(r'<m_StatisticsNameVector>([^<]+)</m_StatisticsNameVector>', text_content, re.IGNORECASE))
                    # Value vectors may be numbered (m_StatisticsValueVector1, ValueVector2, etc.)
                    value_matches = list(re.finditer(r'<m_StatisticsValueVector\d*>([^<]+)</m_StatisticsValueVector\d*>', text_content, re.IGNORECASE))
                    
                    # Match names with values by position
                    for i, name_match in enumerate(name_matches):
                        if i < len(value_matches):
                            name = name_match.group(1).strip()
                            value = value_matches[i].group(1).strip()
                            
                            # Map to normalized fields
                            name_lower = name.lower()
                            if 'radiopharmaceutical' in name_lower:
                                normalized['radiopharmaceutical'] = value
                            elif 'radioisotope' in name_lower and 'radiopharmaceutical' not in normalized:
                                normalized['radiopharmaceutical'] = value
                            elif any(keyword in name_lower for keyword in ['radionuclide total dose', 'injected activity', 'injected dose']):
                                # Skip if it's effective dose or other non-activity doses
                                if 'effective' not in name_lower and 'equivalent' not in name_lower:
                                    # Extract numeric value and unit
                                    num_match = re.search(r'([\d.]+)\s*(MBq|mCi|kBq|Bq|MBQ|MCI|KBQ)?', value, re.IGNORECASE)
                                    if num_match:
                                        try:
                                            activity_val = float(num_match.group(1))
                                            unit = num_match.group(2).upper() if num_match.group(2) else 'MBQ'
                                            if unit == 'MBQ' or (not num_match.group(2) and 'MBq' in value.upper()):
                                                activity_val *= 1e6
                                            elif unit == 'KBQ':
                                                activity_val *= 1e3
                                            elif unit == 'MCI':
                                                activity_val *= 3.7e10
                                            elif unit == 'BQ':
                                                pass  # Already in Bq
                                            normalized['injected_activity_bq'] = activity_val
                                        except:
                                            pass
                            elif 'injection' in name_lower or 'inj' in name_lower:
                                if 'start date' in name_lower or ('date' in name_lower and 'start' in name_lower):
                                    if 'stop' not in name_lower:
                                        date_str = value.strip()
                                        # Convert DD-MM-YYYY to YYYYMMDD
                                        if '-' in date_str and date_str != 'N/A':
                                            parts = date_str.split('-')
                                            if len(parts) == 3:
                                                if len(parts[2]) == 4:  # DD-MM-YYYY
                                                    date_str = f"{parts[2]}{parts[1].zfill(2)}{parts[0].zfill(2)}"
                                                elif len(parts[0]) == 4:  # YYYY-MM-DD
                                                    date_str = f"{parts[0]}{parts[1].zfill(2)}{parts[2].zfill(2)}"
                                        normalized['injection_date'] = date_str.replace('-', '').replace('/', '')
                                elif ('start time' in name_lower or 'time' in name_lower) and 'stop' not in name_lower:
                                    if value.strip() != 'N/A':
                                        time_str = value.strip().replace(' ', '').replace('.', '')
                                        if ':' in time_str:
                                            time_str = time_str.replace(':', '')
                                        normalized['injection_time'] = time_str
                            elif 'half' in name_lower and 'life' in name_lower:
                                try:
                                    normalized['half_life_seconds'] = float(value)
                                except:
                                    pass
                            elif 'weight' in name_lower and 'height' not in name_lower:
                                try:
                                    weight_val = value.strip().upper().replace('KG', '').replace('KG', '').strip()
                                    if weight_val and weight_val != 'N/A':
                                        normalized['patient_weight_kg'] = float(weight_val)
                                except:
                                    pass
                except Exception:
                    pass
            
            # Fallback to regex patterns for text-based reports
            if not normalized:
                for key, pattern in self.PATTERNS.items():
                    match = pattern.search(text_content)
                    if match:
                        try:
                            if key == 'activity':
                                value = float(match.group(1))
                                if len(match.groups()) > 1 and match.group(2):
                                    unit = match.group(2).upper()
                                    if unit == 'MBQ':
                                        value = value * 1e6
                                    elif unit == 'KBQ':
                                        value = value * 1e3
                                    elif unit == 'MCI':
                                        value = value * 3.7e10
                                normalized['injected_activity_bq'] = value
                            elif key == 'injection_time':
                                time_str = match.group(1).strip().replace(' ', '').replace('.', '')
                                if ':' in time_str:
                                    time_str = time_str.replace(':', '')
                                normalized['injection_time'] = time_str
                            elif key == 'injection_date':
                                date_str = match.group(1).strip()
                                if '-' in date_str and len(date_str.split('-')) == 3:
                                    parts = date_str.split('-')
                                    if len(parts[2]) == 4:
                                        date_str = f"{parts[2]}{parts[1].zfill(2)}{parts[0].zfill(2)}"
                                normalized['injection_date'] = date_str.replace('-', '').replace('/', '')
                            elif key == 'radiopharmaceutical':
                                normalized['radiopharmaceutical'] = match.group(1).strip()
                            elif key == 'weight':
                                normalized['patient_weight_kg'] = float(match.group(1))
                            elif key == 'delay':
                                normalized['injection_delay_minutes'] = float(match.group(1))
                            elif key == 'half_life':
                                normalized['half_life_seconds'] = float(match.group(1))
                        except (ValueError, IndexError):
                            continue
        
        # Extract structured private tags
        siemens_private = {}
        for creator, tags in private_tags.items():
            if 'SIEMENS' in creator.upper() or any(str(tag).startswith('0019') or str(tag).startswith('0029') for tag in tags.keys()):
                siemens_private[creator] = tags
        
        # Calculate confidence based on what we found
        if normalized:
            # High confidence if we extracted meaningful data
            # Higher if we extracted from XML (structured), lower if from text patterns
            if 'injected_activity_bq' in normalized or 'radiopharmaceutical' in normalized:
                confidence = 0.85  # High confidence - we extracted key fields
            else:
                confidence = 0.7   # Medium confidence - some data but not key fields
        elif text_content and len(text_content) > 100:
            # Found text content but couldn't parse it
            confidence = 0.4  # Low-medium: has content but no structured data
        elif siemens_private:
            # Found Siemens private tags but no text content
            confidence = 0.25  # Low: Siemens file but no dose report data
        else:
            # No Siemens private tags found at all
            confidence = 0.2  # Very low: likely not a dose report file
        
        return VendorMetadata(
            vendor_name="Siemens",
            normalized_data=normalized,
            raw_private_tags=siemens_private,
            confidence=confidence
        )


class SpectrumDynamicsExtractor(VendorExtractor):
    """Extractor for Spectrum Dynamics private tags"""
    
    def can_handle(self, ds: Dataset) -> bool:
        """Check if this is a Spectrum Dynamics dataset"""
        manufacturer = getattr(ds, 'Manufacturer', '')
        return 'SPECTRUM' in str(manufacturer).upper()
    
    def extract(self, ds: Dataset, private_tags: Dict[str, Any]) -> VendorMetadata:
        """Extract Spectrum Dynamics-specific private tag information"""
        normalized = {}
        
        # Spectrum Dynamics typically uses standard DICOM tags
        # but may have vendor-specific private tags for proprietary data
        spectrum_private = {}
        for creator, tags in private_tags.items():
            if 'SPECTRUM' in creator.upper() or 'SPECTRUM DYNAMICS' in creator.upper():
                spectrum_private[creator] = tags
                
                # Try to extract meaningful values from private tags
                for tag_key, value in tags.items():
                    tag_str = str(tag_key).upper()
                    value_str = str(value).upper()
                    
                    # Look for activity-related tags
                    if any(keyword in value_str for keyword in ['MBQ', 'MCI', 'ACTIVITY', 'DOSE']):
                        # Try to extract numeric value
                        nums = re.findall(r'[\d.]+', value_str)
                        if nums:
                            try:
                                num_val = float(nums[0])
                                if 'MBQ' in value_str:
                                    normalized['injected_activity_bq'] = num_val * 1e6
                                elif 'MCI' in value_str:
                                    normalized['injected_activity_bq'] = num_val * 3.7e10
                            except:
                                pass
        
        return VendorMetadata(
            vendor_name="Spectrum Dynamics",
            normalized_data=normalized,
            raw_private_tags=spectrum_private,
            confidence=0.7 if normalized else 0.5
        )


class GenericVendorExtractor(VendorExtractor):
    """Generic extractor for vendors without specific parsers"""
    
    def can_handle(self, ds: Dataset) -> bool:
        """Always returns True - fallback extractor"""
        return True
    
    def extract(self, ds: Dataset, private_tags: Dict[str, Any]) -> VendorMetadata:
        """Extract generic private tag information"""
        manufacturer = getattr(ds, 'Manufacturer', 'Unknown')
        
        # Try to extract any meaningful numeric/text patterns from private tags
        normalized = {}
        
        # Look for common patterns across all vendors
        for creator, tags in private_tags.items():
            for tag_key, value in tags.items():
                value_str = str(value).upper()
                
                # Look for activity/dose patterns
                if any(keyword in value_str for keyword in ['MBQ', 'MCI', 'ACTIVITY', 'DOSE', 'BQ']):
                    nums = re.findall(r'[\d.]+', value_str)
                    if nums and 'injected_activity_bq' not in normalized:
                        try:
                            num_val = float(nums[0])
                            if 'MBQ' in value_str:
                                normalized['injected_activity_bq'] = num_val * 1e6
                            elif 'KBQ' in value_str:
                                normalized['injected_activity_bq'] = num_val * 1e3
                            elif 'MCI' in value_str:
                                normalized['injected_activity_bq'] = num_val * 3.7e10
                            elif 'BQ' in value_str or 'BECQUEREL' in value_str:
                                normalized['injected_activity_bq'] = num_val
                        except:
                            pass
        
        return VendorMetadata(
            vendor_name=str(manufacturer) if manufacturer else "Unknown",
            normalized_data=normalized,
            raw_private_tags=private_tags,
            confidence=0.2 if normalized else 0.1
        )


class VendorNormalizer:
    """Orchestrator for vendor-specific normalization"""
    
    def __init__(self):
        """Initialize with registered extractors"""
        # Order matters - specific extractors first, generic last
        self.extractors: List[VendorExtractor] = [
            SiemensExtractor(),
            SpectrumDynamicsExtractor(),
            GenericVendorExtractor(),  # Always last as fallback
        ]
    
    def normalize(self, ds: Dataset, private_tags: Dict[str, Any]) -> Optional[VendorMetadata]:
        """Normalize private tags using appropriate vendor extractor"""
        for extractor in self.extractors:
            if extractor.can_handle(ds):
                try:
                    return extractor.extract(ds, private_tags)
                except Exception as e:
                    # Log error but continue to next extractor
                    print(f"Warning: Error in {extractor.__class__.__name__}: {e}")
                    continue
        return None
    
    def register_extractor(self, extractor: VendorExtractor, priority: int = None):
        """Register a custom vendor extractor"""
        if priority is None:
            # Insert before GenericVendorExtractor
            self.extractors.insert(-1, extractor)
        else:
            self.extractors.insert(priority, extractor)


# Global normalizer instance
_normalizer = None

def get_normalizer() -> VendorNormalizer:
    """Get the global vendor normalizer instance"""
    global _normalizer
    if _normalizer is None:
        _normalizer = VendorNormalizer()
    return _normalizer


# Import pydicom here to avoid circular imports
import pydicom

