"""WhatsApp Web integration via QR code bridge (whatsapp-web.js).

Connects to any personal WhatsApp account by scanning a QR code.
The bot reads all messages but only responds to messages the user sends to themselves.
It can send messages to anyone on the user's behalf.
"""

from __future__ import annotations

import asyncio
import datetime as dt
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
        self._monitor_task: Optional[asyncio.Task] = None

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
        """Start the Node.js WhatsApp bridge process.

        Kills any stale bridge processes first, starts the bridge,
        waits for the HTTP API to become available, and starts a
        background health monitor that restarts the bridge on crash.
        """
        if not self.is_configured:
            logger.info("whatsapp_disabled_skipping")
            return

        # Kill any stale bridge process from a previous run
        await self._kill_stale_bridge()

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

        self._spawn_bridge()
        logger.info("whatsapp_bridge_started", port=self._settings.whatsapp_bridge_port)

        # Wait for bridge HTTP API to come up
        for _ in range(60):
            await asyncio.sleep(1)
            # Check if process died
            if self._bridge_process and self._bridge_process.poll() is not None:
                rc = self._bridge_process.returncode
                logger.error("whatsapp_bridge_crashed_on_start", returncode=rc)
                # Retry once after crash
                logger.info("whatsapp_bridge_retrying_after_crash")
                await self._kill_stale_bridge()
                await asyncio.sleep(2)
                self._spawn_bridge()
                continue
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{self._bridge_url}/status", timeout=2)
                    if resp.status_code == 200:
                        logger.info("whatsapp_bridge_ready")
                        # Start background health monitor
                        self._monitor_task = asyncio.create_task(self._health_monitor())
                        return
            except (httpx.ConnectError, httpx.ReadTimeout):
                continue

        logger.warning("whatsapp_bridge_slow_start")
        # Start monitor anyway — bridge might still come up
        self._monitor_task = asyncio.create_task(self._health_monitor())

    def _spawn_bridge(self) -> None:
        """Spawn the Node.js bridge subprocess."""
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
        if sys.platform != "win32":
            popen_kwargs["preexec_fn"] = os.setsid

        self._bridge_process = subprocess.Popen(
            ["node", "bridge.js"],
            **popen_kwargs,
        )

    async def _kill_stale_bridge(self) -> None:
        """Kill any existing bridge process and stale Chrome instances."""
        # Kill our tracked process
        if self._bridge_process and self._bridge_process.poll() is None:
            await self.stop()

        # Kill any orphaned node bridge.js processes on this port
        if sys.platform != "win32":
            try:
                proc = await asyncio.create_subprocess_exec(
                    "sh", "-c",
                    f"lsof -ti :{self._settings.whatsapp_bridge_port} | xargs kill -9 2>/dev/null || true",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, OSError):
                pass

    async def _health_monitor(self) -> None:
        """Background task: monitor bridge health and restart on crash.

        Checks every 15 seconds if the bridge process is still alive.
        If it crashed, waits a bit and restarts it.
        Also logs connection status changes (connected → disconnected).
        """
        was_ready = False
        while True:
            try:
                await asyncio.sleep(15)

                # Check if process is still running
                if self._bridge_process and self._bridge_process.poll() is not None:
                    rc = self._bridge_process.returncode
                    logger.error("whatsapp_bridge_crashed", returncode=rc)
                    await asyncio.sleep(3)
                    await self._kill_stale_bridge()
                    self._spawn_bridge()
                    logger.info("whatsapp_bridge_restarted")
                    was_ready = False
                    continue

                # Check bridge HTTP status
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(f"{self._bridge_url}/status", timeout=5)
                        if resp.status_code == 200:
                            data = resp.json()
                            is_ready = data.get("ready", False)
                            error = data.get("error")
                            disconnected = data.get("disconnected")

                            if was_ready and not is_ready:
                                logger.warning(
                                    "whatsapp_connection_lost",
                                    error=error,
                                    disconnected=disconnected,
                                )
                            elif not was_ready and is_ready:
                                logger.info("whatsapp_connection_restored")

                            was_ready = is_ready
                except (httpx.ConnectError, httpx.ReadTimeout):
                    if was_ready:
                        logger.warning("whatsapp_bridge_unreachable")
                        was_ready = False

            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("whatsapp_health_monitor_error", error=str(exc))

    async def stop(self) -> None:
        """Stop the health monitor and bridge process."""
        # Cancel health monitor first
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

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

    async def send_typing(self, to: str) -> None:
        """Send typing indicator to a WhatsApp chat."""
        if not self.is_configured:
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self._bridge_url}/typing",
                    json={"to": to},
                    timeout=5,
                )
        except Exception:
            pass  # typing indicator is best-effort

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
        """Send a media message from URL (image, document, etc.).
        
        For local files, use send_file() instead.
        """
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
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10),
           retry=retry_if_not_exception_type(ValueError))
    async def send_file(
        self, 
        to: str, 
        file_path: str, 
        caption: str = "",
        mimetype: Optional[str] = None,
    ) -> dict[str, Any]:
        """Send a local file via WhatsApp.
        
        Args:
            to: Phone number (e.g., "+31612345678")
            file_path: Path to local file
            caption: Optional caption
            mimetype: Optional MIME type (auto-detected if not provided)
        """
        if not self.is_configured:
            return {"status": "not_configured"}
        
        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "error": f"File not found: {file_path}"}
        
        # Auto-detect mimetype if not provided
        if not mimetype:
            mimetype = self._guess_mime_type(path.name)
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._bridge_url}/send-media",
                json={
                    "to": to, 
                    "file_path": str(path.resolve()),
                    "mimetype": mimetype,
                    "filename": path.name,
                    "caption": caption,
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()
    
    def _guess_mime_type(self, filename: str) -> str:
        """Guess MIME type from filename."""
        ext = Path(filename).suffix.lower()
        mime_types = {
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".mp4": "video/mp4",
            ".mp3": "audio/mpeg",
            ".txt": "text/plain",
            ".csv": "text/csv",
            ".zip": "application/zip",
        }
        return mime_types.get(ext, "application/octet-stream")

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
                # This is the most reliable check — the "Message yourself" chat
                # has your own number as the chat ID.
                if my_wid and chat_id and chat_id == my_wid:
                    is_self = True
                # NOTE: Do NOT use to_addr == from_addr as fallback.
                # For outgoing messages, from is always your own WID,
                # and to can also match in some edge cases.

            if not from_me or not is_self:
                logger.debug(
                    "whatsapp_webhook_ignored",
                    reason="not_self_message",
                    from_me=from_me,
                    is_self=is_self,
                )
                print(f"[WhatsApp] Ignored (not self-message): fromMe={from_me} isToSelf={is_self}")
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

    # ── Auto Document Analysis ───────────────────────────────────────

    async def process_message_with_document_analysis(
        self,
        payload: dict[str, Any],
        document_analyzer: Any,
        message_handler: Any,
    ) -> Optional[dict[str, Any]]:
        """Process WhatsApp message with automatic document analysis.
        
        This method:
        1. Checks if the message has media/attachments
        2. Downloads the file
        3. Analyzes the document content
        4. Combines document analysis with user message
        5. Generates an intelligent response
        
        Args:
            payload: WhatsApp webhook payload
            document_analyzer: DocumentAnalyzerService instance
            message_handler: Async callable to handle the enriched message
            
        Returns:
            Result dict with analysis and response, or None if not a self-message
        """
        # First process as normal message
        base_result = await self.process_webhook(payload)
        if not base_result:
            return None
        
        user_message = base_result.get("text", "")
        has_media = base_result.get("has_media", False)
        
        # If no media, just handle as text message
        if not has_media:
            if message_handler:
                response = await message_handler(
                    user_id=base_result["from"],
                    text=user_message,
                    platform="whatsapp",
                )
                base_result["response"] = response
            return base_result
        
        # Has media - download and analyze
        logger.info("whatsapp_media_detected", message_preview=user_message[:100])
        
        try:
            # Get media details from payload
            # The bridge sends hasMedia=true with the message id
            # We need to use the message_id to download the media
            message_id = payload.get("id")  # This is the serialized message ID
            mimetype = payload.get("mimetype", "application/octet-stream")
            original_filename = payload.get("filename")
            
            logger.info("whatsapp_media_details", 
                       message_id=message_id, 
                       original_filename=original_filename,
                       mimetype=mimetype)
            
            # Strategy:
            # 1. If WhatsApp gives us a filename with extension, use that
            # 2. If not, let the bridge try to determine from msg.filename
            # 3. Only as last resort, use mimetype to generate extension
            
            filename = None  # Let bridge use original filename by default
            
            if original_filename and original_filename != "unknown":
                # Check if filename has an extension
                if "." in original_filename:
                    timestamp = payload.get("timestamp", str(int(dt.datetime.now().timestamp())))
                    filename = f"{timestamp}_{original_filename}"
                else:
                    # No extension in original filename, try to add from mimetype
                    ext = self._mime_to_extension(mimetype)
                    timestamp = payload.get("timestamp", str(int(dt.datetime.now().timestamp())))
                    filename = f"{timestamp}_{original_filename}{ext}"
            
            logger.info("downloading_media", message_id=message_id, filename=filename or "using_original")
            
            # Download the file using message_id
            download_path = await self.download_media(
                message_id=message_id,
                output_dir="data/whatsapp_received",
                filename=filename,  # Can be None, then bridge uses original
            )
            
            if not download_path:
                logger.error("whatsapp_media_download_failed")
                base_result["media_error"] = "Failed to download media"
                return base_result
            
            base_result["downloaded_path"] = download_path
            base_result["mime_type"] = mimetype
            
            # Analyze the document
            logger.info("analyzing_document", path=download_path)
            analysis = await document_analyzer.analyze_with_context(
                file_path=download_path,
                user_message=user_message,
            )
            
            base_result["document_analysis"] = {
                "file_type": analysis.file_type.value,
                "summary": analysis.summary,
                "text_content": analysis.text_content[:500] if analysis.text_content else None,
                "image_description": analysis.image_description,
                "detected_text": analysis.detected_text,
                "key_topics": analysis.key_topics,
                "action_items": analysis.action_items,
                "title": analysis.title,
                "author": analysis.author,
            }
            
            # Create enriched prompt for the message handler
            enriched_message = self._create_enriched_prompt(user_message, analysis)
            
            # Handle with enriched context
            if message_handler:
                response = await message_handler(
                    user_id=base_result["from"],
                    text=enriched_message,
                    platform="whatsapp",
                    original_message=user_message,
                    document_analysis=analysis,
                )
                base_result["response"] = response
            
            return base_result
            
        except Exception as exc:
            logger.error("document_analysis_failed", error=str(exc))
            base_result["analysis_error"] = str(exc)
            
            # Still try to handle the original message
            if message_handler:
                response = await message_handler(
                    user_id=base_result["from"],
                    text=user_message,
                    platform="whatsapp",
                )
                base_result["response"] = response
            
            return base_result
    
    def _create_enriched_prompt(self, user_message: str, analysis) -> str:
        """Create an enriched prompt combining user message and document analysis."""
        parts = []
        
        # Include original message
        if user_message.strip():
            parts.append(f"User message: {user_message}")
        else:
            parts.append("User sent a file without a message.")
        
        parts.append("")
        parts.append(f"File: {analysis.filename}")
        parts.append(f"Type: {analysis.file_type.value}")
        
        # Add relevant content based on file type
        if analysis.file_type.value == "image":
            if analysis.image_description:
                parts.append(f"\nImage description: {analysis.image_description}")
            if analysis.detected_text:
                parts.append(f"\nText detected in image: {analysis.detected_text}")
        else:
            if analysis.summary:
                parts.append(f"\nDocument summary: {analysis.summary}")
            if analysis.title:
                parts.append(f"Title: {analysis.title}")
            if analysis.author:
                parts.append(f"Author: {analysis.author}")
        
        if analysis.key_topics:
            parts.append(f"\nKey topics: {', '.join(analysis.key_topics)}")
        
        if analysis.action_items:
            parts.append(f"\nAction items mentioned: {'; '.join(analysis.action_items)}")
        
        # Add content preview for text documents
        if analysis.text_content and analysis.file_type.value != "image":
            preview = analysis.text_content[:800]
            if len(analysis.text_content) > 800:
                preview += "... [truncated]"
            parts.append(f"\nContent preview:\n{preview}")
        
        parts.append("\nPlease respond to the user's message considering the document content above.")
        
        return "\n".join(parts)

    # ── Media Download ───────────────────────────────────────────────

    async def download_media(
        self,
        media_url: Optional[str] = None,
        message_id: Optional[str] = None,
        output_dir: str = "data/whatsapp_media",
        filename: Optional[str] = None,
    ) -> Optional[str]:
        """Download WhatsApp media (image, video, document, audio).
        
        Args:
            media_url: URL to download from (optional, for external URLs)
            message_id: WhatsApp message ID to download media from (preferred)
            output_dir: Directory to save the file
            filename: Optional filename (auto-generated if not provided)
            
        Returns:
            Path to downloaded file, or None if failed
        """
        if not self.is_configured:
            logger.warning("whatsapp_not_configured_for_media_download")
            return None
        
        if not message_id and not media_url:
            logger.error("download_media_requires_message_id_or_url")
            return None

        try:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            async with httpx.AsyncClient() as client:
                # Build request payload
                request_payload = {}
                if message_id:
                    request_payload["message_id"] = message_id
                elif media_url:
                    request_payload["media_url"] = media_url
                # Only include filename if explicitly provided
                # If not provided, bridge will use original filename from WhatsApp
                if filename:
                    request_payload["filename"] = filename
                
                logger.debug("calling_bridge_download", payload=request_payload)
                
                # Call bridge download endpoint
                resp = await client.post(
                    f"{self._bridge_url}/download",
                    json=request_payload,
                    timeout=60,
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success"):
                        # Bridge saved the file directly and returns the path
                        if "path" in data:
                            logger.info("whatsapp_media_downloaded", path=data["path"])
                            return data["path"]
                        # Or bridge returns filename for us to save
                        elif "filename" in data:
                            file_path = output_path / data["filename"]
                            logger.info("whatsapp_media_downloaded", path=str(file_path))
                            return str(file_path)
                else:
                    error_data = resp.json() if resp.status_code < 500 else {}
                    logger.warning("whatsapp_media_download_failed", 
                                 status=resp.status_code, 
                                 error=error_data.get("error", "Unknown error"))
                    return None

        except Exception as exc:
            logger.error("whatsapp_media_download_error", error=str(exc))
            return None

    async def process_webhook_with_media(
        self,
        payload: dict[str, Any],
        auto_download_media: bool = True,
    ) -> Optional[dict[str, Any]]:
        """Process webhook and optionally auto-download media.
        
        This extends process_webhook with automatic media download support.
        """
        result = await self.process_webhook(payload)
        if result and result.get("has_media") and auto_download_media:
            message_id = payload.get("id")
            mimetype = payload.get("mimetype", "application/octet-stream")
            original_filename = payload.get("filename")
            
            # Generate filename
            ext = self._mime_to_extension(mimetype)
            if original_filename:
                filename = f"{payload.get('timestamp', '0')}_{original_filename}"
            else:
                filename = f"whatsapp_{payload.get('timestamp', '0')}{ext}"
            
            download_path = await self.download_media(
                message_id=message_id,
                filename=filename,
            )
            if download_path:
                result["downloaded_media_path"] = download_path
                result["media_mimetype"] = mimetype
        
        return result

    def _mime_to_extension(self, mimetype: str) -> str:
        """Convert MIME type to file extension."""
        mapping = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "video/mp4": ".mp4",
            "video/ogg": ".ogv",
            "audio/ogg": ".ogg",
            "audio/mpeg": ".mp3",
            "audio/mp4": ".m4a",
            "application/pdf": ".pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        }
        return mapping.get(mimetype, ".bin")
