"""Supervisor Notifier — sends WhatsApp/log notifications for supervisor events.

Provides a single entry point for all supervisor notifications:
- Improvement applied/failed
- Process crash & restart
- Self-correction attempts
- Escalation when all retries exhausted
"""

from __future__ import annotations

from typing import Any, Optional

from koda2.config import get_settings
from koda2.logging_config import get_logger

logger = get_logger(__name__)


class SupervisorNotifier:
    """Sends notifications about supervisor events to the user."""

    def __init__(self, user_id: Optional[str] = None) -> None:
        self._user_id = user_id
        self._settings = get_settings()

    @property
    def is_configured(self) -> bool:
        """Check if notifications can be sent (WhatsApp + user_id)."""
        return bool(self._user_id)

    async def _send_whatsapp(self, message: str) -> bool:
        """Send a WhatsApp message to the configured user."""
        if not self._user_id:
            logger.debug("notifier_no_user_id")
            return False

        try:
            from koda2.modules.messaging.whatsapp_bot import WhatsAppBot
            bot = WhatsAppBot()
            if not bot.is_configured:
                logger.debug("notifier_whatsapp_not_configured")
                return False
            await bot.send_message(self._user_id, message)
            return True
        except Exception as exc:
            logger.warning("notifier_send_failed", error=str(exc))
            return False

    async def notify_improvement_applied(
        self, summary: str, version: Optional[str] = None
    ) -> None:
        """Notify that a self-improvement was successfully applied."""
        msg = f"🧬 *Koda2 Self-Improvement*\n\n✅ {summary}"
        if version:
            msg += f"\n\n📦 Version: v{version}"
        msg += "\n\nChanges are committed and pushed."
        logger.info("notify_improvement_applied", summary=summary[:100])
        await self._send_whatsapp(msg)

    async def notify_improvement_failed(
        self, summary: str, reason: str
    ) -> None:
        """Notify that a self-improvement attempt failed."""
        msg = (
            f"🧬 *Koda2 Self-Improvement*\n\n"
            f"❌ Improvement failed: {summary[:200]}\n\n"
            f"Reason: {reason[:300]}"
        )
        logger.info("notify_improvement_failed", summary=summary[:100])
        await self._send_whatsapp(msg)

    async def notify_crash_and_restart(
        self, exit_code: int, repaired: bool, diagnosis: str = ""
    ) -> None:
        """Notify that the process crashed and was restarted."""
        status = "✅ Auto-repaired" if repaired else "🔄 Restarted (no fix)"
        msg = (
            f"💥 *Koda2 Crash Detected*\n\n"
            f"Exit code: {exit_code}\n"
            f"Status: {status}"
        )
        if diagnosis:
            msg += f"\nDiagnosis: {diagnosis[:200]}"
        logger.info("notify_crash_restart", exit_code=exit_code, repaired=repaired)
        await self._send_whatsapp(msg)

    async def notify_escalation(
        self, issue: str, attempts: int
    ) -> None:
        """Escalate to user when all automatic retries are exhausted."""
        msg = (
            f"🚨 *Koda2 Needs Your Help*\n\n"
            f"I've tried {attempts} times to fix this but couldn't:\n\n"
            f"{issue[:400]}\n\n"
            f"Please check the code manually or run:\n"
            f"`koda2-supervisor status`"
        )
        logger.warning("notify_escalation", issue=issue[:100], attempts=attempts)
        await self._send_whatsapp(msg)

    async def notify_learning_cycle(
        self, cycle: int, queued: int, signals: int
    ) -> None:
        """Notify about a learning cycle completion (only if items were queued)."""
        if queued == 0:
            return  # Don't spam for empty cycles
        msg = (
            f"🧠 *Koda2 Learning Cycle #{cycle}*\n\n"
            f"Signals analyzed: {signals}\n"
            f"Improvements queued: {queued}"
        )
        logger.info("notify_learning_cycle", cycle=cycle, queued=queued)
        await self._send_whatsapp(msg)

    async def notify_version_bump(
        self, old_version: str, new_version: str, improvements: list[dict[str, Any]]
    ) -> None:
        """Notify about a version bump with summary of changes."""
        descriptions = "\n".join(
            f"• {i.get('description', 'Improvement')[:100]}"
            for i in improvements
        )
        msg = (
            f"📦 *Koda2 v{new_version}*\n\n"
            f"Auto-updated from v{old_version}:\n\n"
            f"{descriptions}\n\n"
            f"Restart to activate new version."
        )
        logger.info("notify_version_bump", old=old_version, new=new_version)
        await self._send_whatsapp(msg)
