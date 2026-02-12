"""WhatsApp Web integration via QR code bridge (whatsapp-web.js).

Connects to any personal WhatsApp account by scanning a QR code.
The bot reads all messages but only responds to messages the user sends to themselves.
It can send messages to anyone on the user's behalf.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.modules.messaging.command_parser import CommandParser, ParsedCommand

logger = get_logger(__name__)

BRIDGE_DIR = Path(__file__).parent / "whatsapp_bridge"


class WhatsAppBot:
    """WhatsApp Web client using QR code pairing via Node.js bridge.

    Architecture:
        Python (this class) <--HTTP--> Node.js bridge (whatsapp-web.js)

    The bridge handles the WhatsApp Web protocol and exposes a local HTTP API.
    Messages from the user to themselves are forwarded to Koda2 for processing.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._bridge_process: Optional[subprocess.Popen] = None
        self._bridge_url = f"http://localhost:{self._settings.whatsapp_bridge_port}"
        self._command_parser: Optional[CommandParser] = None
        self._message_handler: Optional[Any] = None

    def set_command_parser(self, parser: CommandParser) -> None:
        """Set the command parser for handling commands."""
        self._command_parser = parser

    def set_message_handler(self, handler: Any) -> None:
        """Set the handler for non-command messages."""
        self._message_handler = handler

    async def handle_message(self, user_id: str, text: str) -> str:
        """Process an incoming message with command support."""
        if not self._command_parser:
            # Fallback to natural language only
            if self._message_handler:
                return await self._message_handler(user_id=user_id, text=text, platform="whatsapp")
            return "Command parser not configured"

        # Try to parse as command
        parsed = self._command_parser.parse(text, platform="whatsapp")
        
        if parsed.is_command:
            is_cmd, response = await self._command_parser.execute(
                parsed, user_id=user_id, platform="whatsapp"
            )
            if is_cmd:
                return response
        
        # Not a command or command not found - treat as natural language
        if self._message_handler:
            return await self._message_handler(user_id=user_id, text=text, platform="whatsapp")
        
        return "I understand: " + text[:100]

    @property
    def is_configured(self) -> bool:
        """WhatsApp is configured if the bridge is enabled."""
        return self._settings.whatsapp_enabled

    @property
    def bridge_url(self) -> str:
        return self._bridge_url

    async def start_bridge(self) -> None:
        """Start the Node.js WhatsApp bridge process."""
        if not self.is_configured:
            logger.info("whatsapp_disabled_skipping")
            return

        if not (BRIDGE_DIR / "node_modules").exists():
            logger.info("whatsapp_bridge_installing_deps")
            proc = await asyncio.create_subprocess_exec(
                "npm", "install", "--production",
                cwd=str(BRIDGE_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode != 0:
                stderr = (await proc.stderr.read()).decode() if proc.stderr else ""
                logger.error("whatsapp_bridge_npm_install_failed", error=stderr)
                return

        env = {
            "WHATSAPP_BRIDGE_PORT": str(self._settings.whatsapp_bridge_port),
            "KODA2_CALLBACK_URL": f"http://localhost:{self._settings.api_port}/api/whatsapp/webhook",
            "WHATSAPP_AUTH_DIR": str(Path("data") / "whatsapp_session"),
            "PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin",
        }

        popen_kwargs: dict[str, Any] = {
            "cwd": str(BRIDGE_DIR),
            "env": env,
            "stdout": sys.stdout,
            "stderr": sys.stderr,
        }
        # Use a new process group on Unix so we can kill all children
        if sys.platform != "win32":
            popen_kwargs["preexec_fn"] = os.setsid

        self._bridge_process = subprocess.Popen(
            ["node", "bridge.js"],
            **popen_kwargs,
        )
        logger.info("whatsapp_bridge_started", port=self._settings.whatsapp_bridge_port)

        for _ in range(30):
            await asyncio.sleep(1)
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{self._bridge_url}/status", timeout=2)
                    if resp.status_code == 200:
                        logger.info("whatsapp_bridge_ready")
                        return
            except httpx.ConnectError:
                continue

        logger.warning("whatsapp_bridge_slow_start")

    async def stop(self) -> None:
        """Stop the bridge process and all its children."""
        if self._bridge_process and self._bridge_process.poll() is None:
            pgid = None
            try:
                pgid = os.getpgid(self._bridge_process.pid)
            except OSError:
                pass

            # Try graceful SIGTERM on the whole process group
            if pgid:
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except OSError:
                    pass
            else:
                self._bridge_process.terminate()

            try:
                self._bridge_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill the entire process group
                if pgid:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except OSError:
                        pass
                self._bridge_process.kill()
                try:
                    self._bridge_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass

            logger.info("whatsapp_bridge_stopped")

    def stop_sync(self) -> None:
        """Synchronous stop — used by atexit handler."""
        if self._bridge_process and self._bridge_process.poll() is None:
            pgid = None
            try:
                pgid = os.getpgid(self._bridge_process.pid)
            except OSError:
                pass
            if pgid:
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except OSError:
                    pass
            else:
                self._bridge_process.terminate()
            try:
                self._bridge_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if pgid:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except OSError:
                        pass
                self._bridge_process.kill()

    async def get_status(self) -> dict[str, Any]:
        """Get bridge connection status."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._bridge_url}/status", timeout=5)
                return resp.json()
        except Exception as exc:
            return {"ready": False, "error": str(exc)}

    async def get_qr(self) -> dict[str, Any]:
        """Get QR code for WhatsApp pairing."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._bridge_url}/qr", timeout=5)
                return resp.json()
        except Exception as exc:
            return {"status": "bridge_unavailable", "error": str(exc)}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10),
           retry=retry_if_not_exception_type(ValueError))
    async def send_message(self, to: str, text: str) -> dict[str, Any]:
        """Send a text message to any WhatsApp number.

        Args:
            to: Phone number (e.g., "+31612345678" or "31612345678")
            text: Message body
        """
        if not self.is_configured:
            logger.warning("whatsapp_not_configured")
            return {"status": "not_configured"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._bridge_url}/send",
                json={"to": to, "message": text},
                timeout=30,
            )
            if resp.status_code == 503:
                return {"status": "not_connected", "message": "Scan QR code first"}
            resp.raise_for_status()
            data = resp.json()
            logger.info("whatsapp_message_sent", to=to)
            return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10),
           retry=retry_if_not_exception_type(ValueError))
    async def send_media(
        self, to: str, media_url: str, caption: str = "",
    ) -> dict[str, Any]:
        """Send a media message (image, document, etc.)."""
        if not self.is_configured:
            return {"status": "not_configured"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._bridge_url}/send",
                json={"to": to, "media_url": media_url, "media_caption": caption},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_messages(self, since: int = 0, self_only: bool = True) -> list[dict[str, Any]]:
        """Get recent messages from the bridge queue.

        Args:
            since: Unix timestamp to filter messages after
            self_only: If True, only return messages the user sent to themselves
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._bridge_url}/messages",
                    params={"since": since, "self_only": str(self_only).lower()},
                    timeout=10,
                )
                data = resp.json()
                return data.get("messages", [])
        except Exception:
            return []

    async def get_contacts(self) -> list[dict[str, Any]]:
        """Get the user's WhatsApp contacts."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._bridge_url}/contacts", timeout=15)
                data = resp.json()
                return data.get("contacts", [])
        except Exception:
            return []

    async def process_webhook(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Process incoming message from the bridge callback.

        Only processes messages the user sends to themselves (self-chat).
        The bridge already filters for self-messages, but we double-check here.
        Self-message detection uses multiple strategies:
          1. Bridge-side isToSelf flag (compares chat ID against own WID)
          2. fromMe + msg.to === msg.from (classic check)
          3. fromMe + chatId === myWid (reliable for "Message yourself" chat)
        """
        try:
            from_me = payload.get("fromMe", False)
            is_to_self = payload.get("isToSelf", False)
            my_wid = payload.get("myWid")
            chat_id = payload.get("chatId")
            from_addr = payload.get("from", "unknown")
            to_addr = payload.get("to", "unknown")

            logger.info(
                "whatsapp_webhook_received",
                from_me=from_me,
                is_to_self=is_to_self,
                from_addr=from_addr,
                to_addr=to_addr,
                my_wid=my_wid,
                chat_id=chat_id,
                body_preview=payload.get("body", "")[:50],
            )

            # Robust self-message detection (multiple strategies)
            is_self = is_to_self  # trust bridge-side detection first
            if not is_self and from_me:
                # Fallback: check if chat ID matches our own WID
                if my_wid and chat_id and chat_id == my_wid:
                    is_self = True
                # Fallback: classic to === from check
                elif to_addr == from_addr:
                    is_self = True

            if not from_me or not is_self:
                logger.debug(
                    "whatsapp_webhook_ignored",
                    reason="not_self_message",
                    from_me=from_me,
                    is_self=is_self,
                )
                return None

            result = {
                "from": from_addr,
                "type": payload.get("type", "text"),
                "timestamp": payload.get("timestamp", ""),
                "text": payload.get("body", ""),
                "chat_name": payload.get("chatName", ""),
                "has_media": payload.get("hasMedia", False),
                "is_self_message": True,
            }

            logger.info(
                "whatsapp_self_message_received",
                text_length=len(result["text"]),
                preview=result["text"][:100],
            )
            return result

        except (KeyError, IndexError) as exc:
            logger.error("whatsapp_webhook_parse_error", error=str(exc))
            return None

    async def logout(self) -> dict[str, Any]:
        """Disconnect WhatsApp session (requires re-scan of QR)."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{self._bridge_url}/logout", timeout=10)
                return resp.json()
        except Exception as exc:
            return {"error": str(exc)}
