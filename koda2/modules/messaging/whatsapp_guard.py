"""WhatsApp webhook guard utilities.

Provides deduplication, self-message filtering, status-update filtering,
and per-conversation rate limiting to prevent message loops and duplicate
processing.
"""

import logging
import time
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class MessageDeduplicator:
    """Thread-safe message deduplication cache with TTL."""

    def __init__(self, ttl_seconds: int = 60):
        self._ttl = ttl_seconds
        self._seen: dict[str, float] = {}  # message_id -> timestamp
        self._lock = threading.Lock()

    def is_duplicate(self, message_id: str) -> bool:
        """Return True if message_id was already seen within the TTL window."""
        if not message_id:
            return False

        now = time.time()

        with self._lock:
            self._evict_expired(now)

            if message_id in self._seen:
                logger.info(
                    "Duplicate message filtered: message_id=%s", message_id
                )
                return True

            self._seen[message_id] = now
            return False

    def _evict_expired(self, now: float) -> None:
        """Remove entries older than TTL."""
        expired = [
            mid for mid, ts in self._seen.items()
            if now - ts > self._ttl
        ]
        for mid in expired:
            del self._seen[mid]


class ConversationRateLimiter:
    """Per-conversation rate limiter.

    Limits the number of bot responses within a sliding time window
    as a safety net against message loops.
    """

    def __init__(self, max_responses: int = 3, window_seconds: int = 10):
        self._max = max_responses
        self._window = window_seconds
        self._timestamps: dict[str, list[float]] = {}  # conversation_id -> [timestamps]
        self._lock = threading.Lock()

    def is_rate_limited(self, conversation_id: str) -> bool:
        """Return True if the conversation has exceeded the response limit."""
        if not conversation_id:
            return False

        now = time.time()

        with self._lock:
            timestamps = self._timestamps.get(conversation_id, [])
            # Keep only timestamps within the window
            timestamps = [t for t in timestamps if now - t < self._window]

            if len(timestamps) >= self._max:
                logger.warning(
                    "Rate limit hit for conversation %s: %d responses in %ds",
                    conversation_id,
                    len(timestamps),
                    self._window,
                )
                return True

            timestamps.append(now)
            self._timestamps[conversation_id] = timestamps
            return False

    def record_response(self, conversation_id: str) -> None:
        """Explicitly record a response timestamp (if not using is_rate_limited to record)."""
        # is_rate_limited already records when not limited, but this allows
        # external callers to record without checking.
        now = time.time()
        with self._lock:
            timestamps = self._timestamps.get(conversation_id, [])
            timestamps = [t for t in timestamps if now - t < self._window]
            timestamps.append(now)
            self._timestamps[conversation_id] = timestamps


def is_self_message(
    sender: Optional[str],
    bot_number: Optional[str],
) -> bool:
    """Check if the message was sent by the bot itself.

    Handles both raw numbers and whatsapp:-prefixed formats.
    Returns True if sender matches the bot's own number.
    """
    if not sender or not bot_number:
        return False

    def normalize(number: str) -> str:
        """Strip whatsapp: prefix and non-digit chars for comparison."""
        n = number.lower().strip()
        for prefix in ("whatsapp:", "whatsapp://"):
            if n.startswith(prefix):
                n = n[len(prefix):]
        # Keep only digits and leading +
        return n.lstrip("+").strip()

    normalised_sender = normalize(sender)
    normalised_bot = normalize(bot_number)

    if normalised_sender == normalised_bot:
        logger.info(
            "Self-message filtered: sender=%s matches bot_number=%s",
            sender,
            bot_number,
        )
        return True

    return False


def is_status_update(payload: dict) -> bool:
    """Check if a WhatsApp Business API webhook payload is a status update.

    Status updates (sent, delivered, read) should not be processed as
    incoming messages.
    """
    try:
        # WhatsApp Business API (Cloud API) structure
        entry = payload.get("entry", [])
        for e in entry:
            changes = e.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                # If 'statuses' key is present and 'messages' is not,
                # this is purely a status update.
                if "statuses" in value and "messages" not in value:
                    logger.debug(
                        "Status update webhook filtered (statuses: %d)",
                        len(value["statuses"]),
                    )
                    return True
    except (AttributeError, TypeError):
        pass

    return False


# Module-level singleton instances for use across the application
_deduplicator = MessageDeduplicator(ttl_seconds=60)
_rate_limiter = ConversationRateLimiter(max_responses=3, window_seconds=10)


def get_deduplicator() -> MessageDeduplicator:
    """Return the module-level deduplicator instance."""
    return _deduplicator


def get_rate_limiter() -> ConversationRateLimiter:
    """Return the module-level rate limiter instance."""
    return _rate_limiter
