"""Contact models for unified contact management."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ContactSource(Enum):
    """Source of a contact."""
    MACOS = "macos"
    WHATSAPP = "whatsapp"
    GMAIL = "gmail"
    EXCHANGE = "exchange"
    MEMORY = "memory"


@dataclass
class ContactPhone:
    """Phone number with type."""
    number: str
    type: str = "mobile"  # mobile, home, work, other
    whatsapp_available: bool = False


@dataclass
class ContactEmail:
    """Email address with type."""
    address: str
    type: str = "personal"  # personal, work, other


@dataclass
class UnifiedContact:
    """Aggregated contact from multiple sources."""
    
    # Core identity
    name: str
    normalized_name: str = ""  # Lowercase, normalized for matching
    
    # Contact info
    phones: list[ContactPhone] = field(default_factory=list)
    emails: list[ContactEmail] = field(default_factory=list)
    
    # Organization
    company: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    
    # Address
    address: Optional[str] = None
    
    # Dates
    birthday: Optional[dt.date] = None
    
    # Source tracking
    sources: list[ContactSource] = field(default_factory=list)
    source_ids: dict[str, str] = field(default_factory=dict)  # source -> external_id
    
    # Metadata
    notes: Optional[str] = None
    photo_url: Optional[str] = None
    last_synced: Optional[dt.datetime] = None
    
    # Importance/Priority (learned from interactions)
    interaction_count: int = 0
    importance_score: float = 0.0  # 0-1, based on frequency and recency
    
    def __post_init__(self):
        if not self.normalized_name:
            self.normalized_name = self._normalize_name(self.name)
    
    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize name for matching."""
        return name.lower().replace("-", " ").replace("  ", " ").strip()
    
    def get_primary_phone(self) -> Optional[str]:
        """Get primary phone number."""
        if self.phones:
            # Prefer mobile, then work, then any
            for p in self.phones:
                if p.type == "mobile":
                    return p.number
            return self.phones[0].number
        return None
    
    def get_primary_email(self) -> Optional[str]:
        """Get primary email address."""
        if self.emails:
            # Prefer work, then personal
            for e in self.emails:
                if e.type == "work":
                    return e.address
            return self.emails[0].address
        return None
    
    def has_whatsapp(self) -> bool:
        """Check if contact has WhatsApp."""
        return any(p.whatsapp_available for p in self.phones)
    
    def merge(self, other: UnifiedContact) -> UnifiedContact:
        """Merge another contact into this one."""
        # Merge phones (dedupe by number)
        existing_numbers = {p.number for p in self.phones}
        for p in other.phones:
            if p.number not in existing_numbers:
                self.phones.append(p)
        
        # Merge emails (dedupe by address)
        existing_emails = {e.address for e in self.emails}
        for e in other.emails:
            if e.address not in existing_emails:
                self.emails.append(e)
        
        # Fill missing fields from other
        if not self.company and other.company:
            self.company = other.company
        if not self.job_title and other.job_title:
            self.job_title = other.job_title
        if not self.address and other.address:
            self.address = other.address
        if not self.birthday and other.birthday:
            self.birthday = other.birthday
        if not self.photo_url and other.photo_url:
            self.photo_url = other.photo_url
        
        # Merge sources
        for src in other.sources:
            if src not in self.sources:
                self.sources.append(src)
        
        # Merge source IDs
        self.source_ids.update(other.source_ids)
        
        # Update importance
        self.interaction_count += other.interaction_count
        self.importance_score = max(self.importance_score, other.importance_score)
        
        self.last_synced = dt.datetime.now(dt.UTC)
        return self
