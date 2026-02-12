"""Account service — unified management for multiple accounts per provider."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from koda2.database import get_session
from koda2.logging_config import get_logger
from koda2.modules.account.models import (
    Account,
    AccountType,
    ProviderType,
    validate_credentials,
)
from koda2.modules.account.validators import (
    validate_caldav_credentials,
    validate_ews_credentials,
    validate_google_credentials,
    validate_imap_credentials,
    validate_msgraph_credentials,
    validate_smtp_credentials,
    validate_telegram_credentials,
)
from koda2.security.encryption import decrypt, encrypt

logger = get_logger(__name__)


class AccountService:
    """Service for managing multiple accounts across different providers."""

    def __init__(self, session: Optional[AsyncSession] = None) -> None:
        """Initialize the account service.
        
        Args:
            session: Optional database session. If not provided, a new session
                will be created for each operation.
        """
        self._session = session

    def _get_session(self):
        """Get the database session context manager to use.
        
        Returns:
            An async context manager that yields a session.
        """
        if self._session is not None:
            # Return a simple context manager that yields the existing session
            class _SessionContext:
                def __init__(self, session):
                    self._session = session
                async def __aenter__(self):
                    return self._session
                async def __aexit__(self, *args):
                    pass
            return _SessionContext(self._session)
        # Return the async context manager from get_session()
        return get_session()

    def _encrypt_credentials(self, credentials: dict) -> str:
        """Encrypt credentials dictionary to a string.
        
        Args:
            credentials: The credentials dictionary to encrypt.
            
        Returns:
            Encrypted, base64-encoded string.
        """
        json_str = json.dumps(credentials)
        return encrypt(json_str)

    def _decrypt_credentials(self, encrypted_credentials: str) -> dict:
        """Decrypt credentials string back to a dictionary.
        
        Args:
            encrypted_credentials: The encrypted credentials string.
            
        Returns:
            Decrypted credentials dictionary.
        """
        json_str = decrypt(encrypted_credentials)
        return json.loads(json_str)

    async def create_account(
        self,
        name: str,
        account_type: AccountType,
        provider: ProviderType,
        credentials: dict,
        is_default: bool = False,
    ) -> Account:
        """Create a new account.
        
        Args:
            name: User-friendly name for the account.
            account_type: Type of account (calendar, email, messaging).
            provider: Provider backend (ews, google, msgraph, etc.).
            credentials: Provider-specific credentials dictionary.
            is_default: Whether this should be the default account for this type/provider.
            
        Returns:
            The created Account instance.
            
        Raises:
            ValueError: If credentials are invalid.
        """
        # Validate credentials against provider schema
        validate_credentials(provider, credentials)
        
        # Encrypt credentials
        encrypted_creds = self._encrypt_credentials(credentials)
        
        async with self._get_session() as session:
            return await self._create_account_internal(
                session, name, account_type, provider, encrypted_creds, is_default
            )

    async def _create_account_internal(
        self,
        session: AsyncSession,
        name: str,
        account_type: AccountType,
        provider: ProviderType,
        encrypted_creds: str,
        is_default: bool,
    ) -> Account:
        """Internal method to create account within a session context."""
        # If setting as default, clear existing default first
        if is_default:
            await self._clear_default_for_type_provider(
                session, account_type, provider
            )
        
        account = Account(
            name=name,
            account_type=account_type.value,
            provider=provider.value,
            is_active=True,
            is_default=is_default,
            credentials=encrypted_creds,
        )
        
        session.add(account)
        await session.flush()  # Flush to get the ID assigned
        
        logger.info(
            "account_created",
            account_id=account.id,
            name=name,
            account_type=account_type.value,
            provider=provider.value,
            is_default=is_default,
        )
        
        return account

    async def _clear_default_for_type_provider(
        self,
        session: AsyncSession,
        account_type: AccountType,
        provider: ProviderType,
    ) -> None:
        """Clear the default flag for all accounts of the given type and provider."""
        stmt = (
            update(Account)
            .where(
                and_(
                    Account.account_type == account_type.value,
                    Account.provider == provider.value,
                    Account.is_default == True,
                )
            )
            .values(is_default=False)
        )
        await session.execute(stmt)

    async def get_account(self, account_id: str) -> Optional[Account]:
        """Get an account by ID.
        
        Args:
            account_id: The UUID of the account.
            
        Returns:
            The Account if found, None otherwise.
        """
        async with self._get_session() as session:
            result = await session.execute(
                select(Account).where(Account.id == account_id)
            )
            return result.scalar_one_or_none()

    async def get_accounts(
        self,
        account_type: Optional[AccountType] = None,
        provider: Optional[ProviderType] = None,
        active_only: bool = True,
    ) -> list[Account]:
        """Get accounts with optional filtering.
        
        Args:
            account_type: Filter by account type.
            provider: Filter by provider.
            active_only: If True, only return active accounts.
            
        Returns:
            List of matching Account instances.
        """
        stmt = select(Account)
        
        if account_type:
            stmt = stmt.where(Account.account_type == account_type.value)
        if provider:
            stmt = stmt.where(Account.provider == provider.value)
        if active_only:
            stmt = stmt.where(Account.is_active == True)
        
        stmt = stmt.order_by(Account.name)
        
        async with self._get_session() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_default_account(
        self,
        account_type: AccountType,
        provider: Optional[ProviderType] = None,
    ) -> Optional[Account]:
        """Get the default account for a given type and optional provider.
        
        Args:
            account_type: The type of account.
            provider: Optional provider filter. If not specified, returns the
                first default account of that type across all providers.
                
        Returns:
            The default Account if found, None otherwise.
        """
        stmt = select(Account).where(
            and_(
                Account.account_type == account_type.value,
                Account.is_default == True,
                Account.is_active == True,
            )
        )
        
        if provider:
            stmt = stmt.where(Account.provider == provider.value)
        
        async with self._get_session() as session:
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def update_account(self, account_id: str, **fields) -> Optional[Account]:
        """Update an account's fields.
        
        Args:
            account_id: The UUID of the account to update.
            **fields: Fields to update (name, is_active, is_default, credentials).
            
        Returns:
            The updated Account if found, None otherwise.
            
        Raises:
            ValueError: If credentials are invalid.
        """
        # Handle credentials separately if provided
        if "credentials" in fields:
            account = await self.get_account(account_id)
            if account is None:
                return None
            
            provider = ProviderType(account.provider)
            validate_credentials(provider, fields["credentials"])
            fields["credentials"] = self._encrypt_credentials(fields["credentials"])
        
        # Handle is_default specially
        set_default = fields.pop("is_default", None)
        
        async with self._get_session() as session:
            return await self._update_account_internal(
                session, account_id, fields, set_default
            )

    async def _update_account_internal(
        self,
        session: AsyncSession,
        account_id: str,
        fields: dict,
        set_default: Optional[bool],
    ) -> Optional[Account]:
        """Internal method to update account within a session context."""
        # Get the account first to check provider for default handling
        result = await session.execute(
            select(Account).where(Account.id == account_id)
        )
        account = result.scalar_one_or_none()
        
        if account is None:
            return None
        
        # If setting as default, clear existing default first
        if set_default:
            await self._clear_default_for_type_provider(
                session,
                AccountType(account.account_type),
                ProviderType(account.provider),
            )
            fields["is_default"] = True
        elif set_default is False:
            fields["is_default"] = False
        
        # Update fields
        for key, value in fields.items():
            if hasattr(account, key):
                setattr(account, key, value)
        
        logger.info(
            "account_updated",
            account_id=account_id,
            updated_fields=list(fields.keys()),
        )
        
        return account

    async def delete_account(self, account_id: str) -> bool:
        """Delete an account.
        
        Args:
            account_id: The UUID of the account to delete.
            
        Returns:
            True if deleted, False if not found.
        """
        async with self._get_session() as session:
            return await self._delete_account_internal(session, account_id)

    async def _delete_account_internal(
        self, session: AsyncSession, account_id: str
    ) -> bool:
        """Internal method to delete account within a session context."""
        result = await session.execute(
            select(Account).where(Account.id == account_id)
        )
        account = result.scalar_one_or_none()
        
        if account is None:
            return False
        
        await session.delete(account)
        
        logger.info(
            "account_deleted",
            account_id=account_id,
            name=account.name,
            account_type=account.account_type,
            provider=account.provider,
        )
        
        return True

    async def set_default(self, account_id: str) -> Optional[Account]:
        """Set an account as the default for its type and provider.
        
        Args:
            account_id: The UUID of the account to set as default.
            
        Returns:
            The updated Account if found, None otherwise.
        """
        return await self.update_account(account_id, is_default=True)

    async def validate_account_credentials(
        self,
        account_type: AccountType,
        provider: ProviderType,
        credentials: dict,
    ) -> tuple[bool, str]:
        """Validate that account credentials actually work.
        
        This performs a connection test to verify the credentials are valid.
        
        Args:
            account_type: The type of account.
            provider: The provider type.
            credentials: The credentials dictionary to validate.
            
        Returns:
            Tuple of (success: bool, message: str).
        """
        # First validate the schema
        try:
            validate_credentials(provider, credentials)
        except ValueError as exc:
            return False, f"Invalid credential format: {exc}"
        
        # Perform provider-specific connection tests using existing validators
        try:
            if provider == ProviderType.EWS:
                return await validate_ews_credentials(
                    server=credentials["server"],
                    username=credentials["username"],
                    password=credentials["password"],
                    email=credentials["email"],
                )
            elif provider == ProviderType.GOOGLE:
                return await validate_google_credentials(
                    credentials_file=credentials["credentials_file"],
                    token_file=credentials["token_file"],
                )
            elif provider == ProviderType.MSGRAPH:
                return await validate_msgraph_credentials(
                    client_id=credentials["client_id"],
                    client_secret=credentials["client_secret"],
                    tenant_id=credentials["tenant_id"],
                )
            elif provider == ProviderType.CALDAV:
                return await validate_caldav_credentials(
                    url=credentials["url"],
                    username=credentials["username"],
                    password=credentials["password"],
                )
            elif provider == ProviderType.IMAP:
                return await validate_imap_credentials(
                    server=credentials["server"],
                    port=credentials.get("port", 993),
                    username=credentials["username"],
                    password=credentials["password"],
                    use_ssl=credentials.get("use_ssl", True),
                )
            elif provider == ProviderType.SMTP:
                return await validate_smtp_credentials(
                    server=credentials["server"],
                    port=credentials.get("port", 587),
                    username=credentials["username"],
                    password=credentials["password"],
                    use_tls=credentials.get("use_tls", True),
                )
            elif provider == ProviderType.TELEGRAM:
                return await validate_telegram_credentials(
                    bot_token=credentials["bot_token"],
                )
            else:
                return False, f"Unsupported provider: {provider}"
        except Exception as exc:
            logger.error(
                "credential_validation_failed",
                provider=provider.value,
                error=str(exc),
            )
            return False, f"Validation error: {exc}"

    def decrypt_credentials(self, account: Account) -> dict:
        """Decrypt an account's credentials.
        
        Args:
            account: The Account instance whose credentials to decrypt.
            
        Returns:
            Decrypted credentials dictionary.
        """
        return self._decrypt_credentials(account.credentials)

    def encrypt_credentials(self, credentials: dict) -> str:
        """Encrypt credentials dictionary.
        
        Args:
            credentials: The credentials dictionary to encrypt.
            
        Returns:
            Encrypted, base64-encoded string.
        """
        return self._encrypt_credentials(credentials)
