"""Unified contact sync service - aggregates contacts from all sources."""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Optional, Any

from koda2.logging_config import get_logger
from koda2.modules.contacts.models import ContactSource, ContactEmail, ContactPhone, UnifiedContact

logger = get_logger(__name__)


class ContactSyncService:
    """Synchronizes and aggregates contacts from all sources.
    
    Sources:
    - macOS Contacts.app (via AppleScript)
    - WhatsApp contacts
    - Gmail/Exchange contacts (via APIs)
    - Internal memory/contacts database
    """
    
    def __init__(
        self,
        macos_service: Optional[Any] = None,
        whatsapp_bot: Optional[Any] = None,
        account_service: Optional[Any] = None,
        memory_service: Optional[Any] = None,
    ) -> None:
        self._macos = macos_service
        self._whatsapp = whatsapp_bot
        self._account_service = account_service
        self._memory = memory_service
        self._cache: dict[str, UnifiedContact] = {}  # normalized_name -> contact
        self._last_full_sync: Optional[dt.datetime] = None
        self._sync_lock = asyncio.Lock()
    
    async def search(
        self,
        query: str,
        sources: Optional[list[ContactSource]] = None,
        limit: int = 10,
    ) -> list[UnifiedContact]:
        """Search contacts across all sources.
        
        Args:
            query: Search string (name, email, or phone)
            sources: Specific sources to search (default: all)
            limit: Maximum results
        """
        results = []
        query_lower = query.lower()
        
        # Ensure cache is populated
        if not self._cache:
            await self.sync_all()
        
        # Search in cache
        for contact in self._cache.values():
            if sources and not any(s in contact.sources for s in sources):
                continue
                
            # Match name
            if query_lower in contact.normalized_name:
                results.append(contact)
                continue
            
            # Match email
            if any(query_lower in e.address.lower() for e in contact.emails):
                results.append(contact)
                continue
            
            # Match phone (strip non-digits for comparison)
            query_digits = re.sub(r'\D', '', query)
            if query_digits and any(query_digits in re.sub(r'\D', '', p.number) for p in contact.phones):
                results.append(contact)
                continue
        
        # Sort by importance
        results.sort(key=lambda c: c.importance_score, reverse=True)
        return results[:limit]
    
    async def find_by_name(self, name: str) -> Optional[UnifiedContact]:
        """Find a contact by exact or partial name match."""
        normalized = UnifiedContact._normalize_name(name)
        
        # Try exact match first
        if normalized in self._cache:
            return self._cache[normalized]
        
        # Try partial match
        for norm_name, contact in self._cache.items():
            if normalized in norm_name or norm_name in normalized:
                return contact
        
        return None
    
    async def find_by_email(self, email: str) -> Optional[UnifiedContact]:
        """Find a contact by email address."""
        email_lower = email.lower()
        
        for contact in self._cache.values():
            if any(e.address.lower() == email_lower for e in contact.emails):
                return contact
        
        return None
    
    async def find_by_phone(self, phone: str) -> Optional[UnifiedContact]:
        """Find a contact by phone number."""
        phone_digits = re.sub(r'\D', '', phone)
        
        for contact in self._cache.values():
            if any(phone_digits in re.sub(r'\D', '', p.number) for p in contact.phones):
                return contact
        
        return None
    
    async def sync_all(self, force: bool = False, persist_to_db: bool = True) -> dict[str, int]:
        """Sync contacts from all available sources.
        
        Args:
            force: Force a new sync even if recent sync exists
            persist_to_db: Save synced contacts to database for persistence
            
        Returns:
            Dict with counts per source
        """
        async with self._sync_lock:
            # Check if recent sync exists
            if not force and self._last_full_sync:
                elapsed = dt.datetime.now(dt.UTC) - self._last_full_sync
                if elapsed < dt.timedelta(minutes=5):
                    logger.debug("contact_sync_skipped_recent")
                    return {}
            
            counts = {source.value: 0 for source in ContactSource}
            all_contacts: list[UnifiedContact] = []
            
            # Sync from each source
            tasks = []
            
            if self._macos:
                tasks.append(self._sync_macos())
            if self._whatsapp:
                tasks.append(self._sync_whatsapp())
            if self._account_service:
                tasks.append(self._sync_email_accounts())
            if self._memory:
                tasks.append(self._sync_memory())
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    logger.error("contact_sync_source_failed", error=str(result))
                    continue
                for contact in result:
                    counts[contact.sources[0].value] += 1
                    all_contacts.append(contact)
            
            # Merge duplicates
            self._cache = self._merge_contacts(all_contacts)
            self._last_full_sync = dt.datetime.now(dt.UTC)
            
            # Persist to database if requested
            if persist_to_db and self._memory:
                await self._persist_contacts_to_db()
            
            logger.info("contact_sync_complete", total=len(self._cache), counts=counts)
            return counts
    
    async def _persist_contacts_to_db(self) -> None:
        """Save all cached contacts to the database for persistence."""
        if not self._memory:
            return
        
        persisted = 0
        updated = 0
        
        for contact in self._cache.values():
            try:
                # Check if contact already exists in DB
                existing = await self._memory.find_contact("default", contact.name)
                
                if existing:
                    # Update existing contact with new info
                    # Note: We're not updating here to avoid conflicts,
                    # but we could implement merge logic
                    updated += 1
                else:
                    # Add new contact
                    await self._memory.add_contact(
                        user_id="default",
                        name=contact.name,
                        email=contact.get_primary_email(),
                        phone=contact.get_primary_phone(),
                        company=contact.company,
                        notes=f"Synced from: {', '.join(s.value for s in contact.sources)}",
                    )
                    persisted += 1
                    
            except Exception as exc:
                logger.error("contact_persist_failed", name=contact.name, error=str(exc))
        
        logger.info("contacts_persisted_to_db", new=persisted, updated=updated)
    
    async def _sync_macos(self) -> list[UnifiedContact]:
        """Sync from macOS Contacts.app."""
        try:
            macos_contacts = await self._macos.get_contacts()
            contacts = []
            
            for mc in macos_contacts:
                phones = [
                    ContactPhone(number=p, type="mobile")
                    for p in mc.get("phones", [])
                ]
                emails = [
                    ContactEmail(address=e, type="personal")
                    for e in mc.get("emails", [])
                ]
                
                # Parse birthday string to date if possible
                birthday = None
                if mc.get("birthday"):
                    try:
                        # AppleScript returns dates in various formats
                        bday_str = mc["birthday"]
                        # Try common formats
                        for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%B %d, %Y"]:
                            try:
                                birthday = dt.datetime.strptime(bday_str, fmt).date()
                                break
                            except ValueError:
                                continue
                    except Exception:
                        pass
                
                contact = UnifiedContact(
                    name=mc.get("name", "Unknown"),
                    phones=phones,
                    emails=emails,
                    company=mc.get("company"),
                    job_title=mc.get("job_title"),
                    address=mc.get("address"),
                    birthday=birthday,
                    sources=[ContactSource.MACOS],
                    source_ids={"macos": mc.get("name", "")},  # Use name as ID since AppleScript doesn't expose stable IDs
                    last_synced=dt.datetime.now(dt.UTC),
                )
                contacts.append(contact)
            
            logger.info("macos_contacts_synced", count=len(contacts))
            return contacts
            
        except Exception as exc:
            logger.error("macos_contact_sync_failed", error=str(exc))
            return []
    
    async def _sync_whatsapp(self) -> list[UnifiedContact]:
        """Sync from WhatsApp contacts."""
        try:
            wa_contacts = await self._whatsapp.get_contacts()
            contacts = []
            
            for wc in wa_contacts:
                # Extract name - use pushname as fallback
                name = wc.get("name") or wc.get("pushname") or "Unknown"
                number = wc.get("number", "")
                
                contact = UnifiedContact(
                    name=name,
                    phones=[ContactPhone(
                        number=number,
                        type="mobile",
                        whatsapp_available=True,
                    )],
                    sources=[ContactSource.WHATSAPP],
                    source_ids={"whatsapp": wc.get("id", "")},
                    last_synced=dt.datetime.now(dt.UTC),
                )
                contacts.append(contact)
            
            logger.info("whatsapp_contacts_synced", count=len(contacts))
            return contacts
            
        except Exception as exc:
            logger.error("whatsapp_contact_sync_failed", error=str(exc))
            return []
    
    async def _sync_email_accounts(self) -> list[UnifiedContact]:
        """Sync from Gmail and Exchange contacts."""
        contacts = []
        
        if not self._account_service:
            return contacts
        
        try:
            from koda2.modules.account.models import AccountType, ProviderType
            
            email_accounts = await self._account_service.get_accounts(
                account_type=AccountType.EMAIL,
                active_only=True,
            )
            
            for account in email_accounts:
                try:
                    if account.provider == ProviderType.GOOGLE.value:
                        gmail_contacts = await self._sync_gmail_contacts(account)
                        contacts.extend(gmail_contacts)
                    elif account.provider == ProviderType.MSGRAPH.value:
                        exchange_contacts = await self._sync_exchange_contacts(account)
                        contacts.extend(exchange_contacts)
                except Exception as exc:
                    logger.error("email_contact_sync_failed", account=account.name, error=str(exc))
            
        except Exception as exc:
            logger.error("email_accounts_sync_failed", error=str(exc))
        
        return contacts
    
    async def _sync_gmail_contacts(self, account) -> list[UnifiedContact]:
        """Sync contacts from Gmail API."""
        try:
            credentials = self._account_service.decrypt_credentials(account)
            
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            
            def _fetch():
                creds = Credentials.from_authorized_user_file(credentials["credentials_file"])
                service = build("people", "v1", credentials=creds, cache_discovery=False)
                
                results = service.people().connections().list(
                    resourceName="people/me",
                    pageSize=1000,
                    personFields="names,emailAddresses,phoneNumbers,organizations,birthdays",
                ).execute()
                
                connections = results.get("connections", [])
                contacts = []
                
                for person in connections:
                    names = person.get("names", [])
                    name = names[0].get("displayName", "Unknown") if names else "Unknown"
                    
                    emails = [
                        ContactEmail(address=e.get("value", ""), type=e.get("type", "other"))
                        for e in person.get("emailAddresses", [])
                    ]
                    
                    phones = [
                        ContactPhone(number=p.get("value", ""), type=p.get("type", "other"))
                        for p in person.get("phoneNumbers", [])
                    ]
                    
                    orgs = person.get("organizations", [])
                    company = orgs[0].get("name") if orgs else None
                    job_title = orgs[0].get("title") if orgs else None
                    
                    birthdays = person.get("birthdays", [])
                    birthday = None
                    if birthdays:
                        bday = birthdays[0].get("date", {})
                        if bday:
                            try:
                                birthday = dt.date(bday["year"], bday["month"], bday["day"])
                            except (KeyError, ValueError):
                                pass
                    
                    contact = UnifiedContact(
                        name=name,
                        emails=emails,
                        phones=phones,
                        company=company,
                        job_title=job_title,
                        birthday=birthday,
                        sources=[ContactSource.GMAIL],
                        source_ids={"gmail": person.get("resourceName", "")},
                        last_synced=dt.datetime.now(dt.UTC),
                    )
                    contacts.append(contact)
                
                return contacts
            
            contacts = await asyncio.to_thread(_fetch)
            logger.info("gmail_contacts_synced", account=account.name, count=len(contacts))
            return contacts
            
        except Exception as exc:
            logger.error("gmail_contact_sync_failed", error=str(exc))
            return []
    
    async def _sync_exchange_contacts(self, account) -> list[UnifiedContact]:
        """Sync contacts from Exchange via MS Graph."""
        try:
            credentials = self._account_service.decrypt_credentials(account)
            
            import httpx
            
            # Get token
            token_url = f"https://login.microsoftonline.com/{credentials['tenant_id']}/oauth2/v2.0/token"
            async with httpx.AsyncClient() as client:
                token_resp = await client.post(token_url, data={
                    "client_id": credentials["client_id"],
                    "client_secret": credentials["client_secret"],
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                })
                token_resp.raise_for_status()
                token = token_resp.json()["access_token"]
                
                # Fetch contacts
                resp = await client.get(
                    "https://graph.microsoft.com/v1.0/me/contacts",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$top": 500},
                )
                resp.raise_for_status()
                data = resp.json()
                
                contacts = []
                for person in data.get("value", []):
                    emails = [
                        ContactEmail(address=e.get("address", ""), type="work")
                        for e in person.get("emailAddresses", [])
                    ]
                    
                    phones = []
                    for p in person.get("businessPhones", []):
                        phones.append(ContactPhone(number=p, type="work"))
                    if person.get("mobilePhone"):
                        phones.append(ContactPhone(number=person["mobilePhone"], type="mobile"))
                    
                    contact = UnifiedContact(
                        name=person.get("displayName", "Unknown"),
                        emails=emails,
                        phones=phones,
                        company=person.get("companyName"),
                        job_title=person.get("jobTitle"),
                        sources=[ContactSource.EXCHANGE],
                        source_ids={"exchange": person.get("id", "")},
                        last_synced=dt.datetime.now(dt.UTC),
                    )
                    contacts.append(contact)
                
                logger.info("exchange_contacts_synced", account=account.name, count=len(contacts))
                return contacts
                
        except Exception as exc:
            logger.error("exchange_contact_sync_failed", error=str(exc))
            return []
    
    async def _sync_memory(self) -> list[UnifiedContact]:
        """Sync from internal memory/contacts."""
        # This would fetch from memory service contacts
        # For now, return empty list
        return []
    
    def _merge_contacts(self, contacts: list[UnifiedContact]) -> dict[str, UnifiedContact]:
        """Merge duplicate contacts based on name/email/phone."""
        merged: dict[str, UnifiedContact] = {}
        
        for contact in contacts:
            key = contact.normalized_name
            
            # Try to find existing match
            existing = None
            
            # First try exact name match
            if key in merged:
                existing = merged[key]
            else:
                # Try email match
                for e in contact.emails:
                    for m in merged.values():
                        if any(me.address.lower() == e.address.lower() for me in m.emails):
                            existing = m
                            break
                    if existing:
                        break
                
                # Try phone match if no email match
                if not existing:
                    for p in contact.phones:
                        p_digits = re.sub(r'\D', '', p.number)
                        for m in merged.values():
                            if any(p_digits in re.sub(r'\D', '', mp.number) for mp in m.phones):
                                existing = m
                                break
                        if existing:
                            break
            
            if existing:
                existing.merge(contact)
            else:
                merged[key] = contact
        
        return merged
    
    async def get_contact_summary(self) -> dict[str, Any]:
        """Get summary of synced contacts."""
        if not self._cache:
            await self.sync_all()
        
        source_counts = {source.value: 0 for source in ContactSource}
        for contact in self._cache.values():
            for source in contact.sources:
                source_counts[source.value] += 1
        
        whatsapp_count = sum(1 for c in self._cache.values() if c.has_whatsapp())
        
        return {
            "total_unique": len(self._cache),
            "by_source": source_counts,
            "with_whatsapp": whatsapp_count,
            "last_sync": self._last_full_sync.isoformat() if self._last_full_sync else None,
        }
    
    async def add_contact(
        self,
        name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        source: ContactSource = ContactSource.MEMORY,
    ) -> UnifiedContact:
        """Add a new contact."""
        contact = UnifiedContact(
            name=name,
            phones=[ContactPhone(number=phone, type="mobile")] if phone else [],
            emails=[ContactEmail(address=email, type="personal")] if email else [],
            sources=[source],
            last_synced=dt.datetime.now(dt.UTC),
        )
        
        # Add to cache
        if contact.normalized_name in self._cache:
            self._cache[contact.normalized_name].merge(contact)
        else:
            self._cache[contact.normalized_name] = contact
        
        # Persist to memory if available
        if self._memory:
            try:
                await self._memory.add_contact(
                    user_id="default",
                    name=name,
                    email=email,
                    phone=phone,
                )
            except Exception as exc:
                logger.error("memory_contact_save_failed", error=str(exc))
        
        return contact
