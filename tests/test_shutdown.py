"""Tests for graceful shutdown behavior."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.messaging.whatsapp_bot import WhatsAppBot


class TestWhatsAppBridgeShutdown:
    """Tests for WhatsApp bridge process group cleanup."""

    @pytest.fixture
    def whatsapp(self):
        with patch("koda2.modules.messaging.whatsapp_bot.get_settings") as mock:
            mock.return_value = MagicMock(
                whatsapp_enabled=True,
                whatsapp_bridge_port=3001,
                api_port=8000,
            )
            return WhatsAppBot()

    @pytest.mark.asyncio
    async def test_stop_no_process(self, whatsapp) -> None:
        """stop() is safe when no bridge process exists."""
        await whatsapp.stop()

    @pytest.mark.asyncio
    async def test_stop_kills_process_group(self, whatsapp) -> None:
        """stop() sends SIGTERM to the entire process group."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # process is running
        mock_proc.pid = 12345
        mock_proc.wait.return_value = 0
        whatsapp._bridge_process = mock_proc

        with patch("os.getpgid", return_value=12345) as mock_getpgid, \
             patch("os.killpg") as mock_killpg:
            await whatsapp.stop()

            mock_getpgid.assert_called_once_with(12345)
            mock_killpg.assert_called_once_with(12345, signal.SIGTERM)

    @pytest.mark.asyncio
    async def test_stop_force_kills_on_timeout(self, whatsapp) -> None:
        """stop() escalates to SIGKILL when SIGTERM times out."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="node", timeout=5)
        mock_proc.kill.return_value = None
        whatsapp._bridge_process = mock_proc

        with patch("os.getpgid", return_value=12345), \
             patch("os.killpg") as mock_killpg:
            await whatsapp.stop()

            # Should have called SIGTERM first, then SIGKILL
            assert mock_killpg.call_count == 2
            mock_killpg.assert_any_call(12345, signal.SIGTERM)
            mock_killpg.assert_any_call(12345, signal.SIGKILL)

    @pytest.mark.asyncio
    async def test_stop_already_exited(self, whatsapp) -> None:
        """stop() is safe when process already exited."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # already exited
        whatsapp._bridge_process = mock_proc

        await whatsapp.stop()
        mock_proc.terminate.assert_not_called()

    def test_stop_sync_kills_process_group(self, whatsapp) -> None:
        """stop_sync() kills the process group synchronously."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 99999
        mock_proc.wait.return_value = 0
        whatsapp._bridge_process = mock_proc

        with patch("os.getpgid", return_value=99999) as mock_getpgid, \
             patch("os.killpg") as mock_killpg:
            whatsapp.stop_sync()

            mock_getpgid.assert_called_once_with(99999)
            mock_killpg.assert_called_once_with(99999, signal.SIGTERM)

    def test_stop_sync_no_process(self, whatsapp) -> None:
        """stop_sync() is safe when no bridge process exists."""
        whatsapp.stop_sync()

    def test_stop_sync_force_kill_on_timeout(self, whatsapp) -> None:
        """stop_sync() escalates to SIGKILL on timeout."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 99999
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="node", timeout=3)
        mock_proc.kill.return_value = None
        whatsapp._bridge_process = mock_proc

        with patch("os.getpgid", return_value=99999), \
             patch("os.killpg") as mock_killpg:
            whatsapp.stop_sync()

            assert mock_killpg.call_count == 2
            mock_killpg.assert_any_call(99999, signal.SIGTERM)
            mock_killpg.assert_any_call(99999, signal.SIGKILL)


class TestWhatsAppBridgeProcessGroup:
    """Tests for bridge starting in its own process group."""

    def test_setsid_available_for_bridge(self) -> None:
        """os.setsid is available and callable (used by start_bridge for process groups)."""
        assert hasattr(os, "setsid")
        assert callable(os.setsid)


class TestGracefulShutdown:
    """Tests for the main graceful shutdown function."""

    @pytest.mark.asyncio
    async def test_graceful_shutdown_stops_all_services(self) -> None:
        """_graceful_shutdown stops all services in order."""
        import koda2.main as main_module

        # Save originals
        orig_orch = main_module._orchestrator
        orig_metrics = main_module._metrics
        orig_tq = getattr(main_module, '_task_queue', None)
        orig_shutdown = main_module._shutdown_in_progress
        orig_tasks = main_module._background_tasks[:]

        try:
            main_module._shutdown_in_progress = False

            mock_orch = MagicMock()
            mock_orch.shutdown = AsyncMock()

            mock_metrics = MagicMock()
            mock_metrics.stop = AsyncMock()

            mock_ws = MagicMock()
            mock_ws.stop = AsyncMock()

            main_module._orchestrator = mock_orch
            main_module._metrics = mock_metrics
            main_module._background_tasks = []

            from koda2.dashboard.websocket import sio
            sio.dashboard_ws = mock_ws

            with patch("koda2.main.close_db", new_callable=AsyncMock):
                await asyncio.wait_for(main_module._graceful_shutdown(), timeout=5)

            mock_orch.shutdown.assert_awaited_once()
            mock_metrics.stop.assert_awaited_once()
            mock_ws.stop.assert_awaited_once()

        finally:
            main_module._orchestrator = orig_orch
            main_module._metrics = orig_metrics
            main_module._shutdown_in_progress = orig_shutdown
            main_module._background_tasks = orig_tasks

    @pytest.mark.asyncio
    async def test_graceful_shutdown_idempotent(self) -> None:
        """_graceful_shutdown only runs once (idempotent)."""
        import koda2.main as main_module

        orig_shutdown = main_module._shutdown_in_progress
        try:
            main_module._shutdown_in_progress = True

            mock_orch = MagicMock()
            mock_orch.telegram.stop = AsyncMock()
            main_module._orchestrator = mock_orch

            await main_module._graceful_shutdown()

            # Should not have called stop because _shutdown_in_progress was True
            mock_orch.telegram.stop.assert_not_awaited()
        finally:
            main_module._shutdown_in_progress = orig_shutdown

    @pytest.mark.asyncio
    async def test_graceful_shutdown_cancels_background_tasks(self) -> None:
        """_graceful_shutdown cancels all background asyncio tasks."""
        import koda2.main as main_module

        orig_orch = main_module._orchestrator
        orig_metrics = main_module._metrics
        orig_tq = getattr(main_module, '_task_queue', None)
        orig_shutdown = main_module._shutdown_in_progress
        orig_tasks = main_module._background_tasks[:]

        try:
            main_module._shutdown_in_progress = False
            main_module._orchestrator = None
            main_module._metrics = None
            if hasattr(main_module, '_task_queue'):
                main_module._task_queue = None

            # Create a long-running background task
            async def long_task():
                await asyncio.sleep(3600)

            bg_task = asyncio.create_task(long_task())
            main_module._background_tasks = [bg_task]

            from koda2.dashboard.websocket import sio
            sio.dashboard_ws = None

            with patch("koda2.main.close_db", new_callable=AsyncMock):
                await asyncio.wait_for(main_module._graceful_shutdown(), timeout=5)

            assert bg_task.cancelled() or bg_task.done()

        finally:
            main_module._orchestrator = orig_orch
            main_module._metrics = orig_metrics
            if orig_tq is not None:
                main_module._task_queue = orig_tq
            main_module._shutdown_in_progress = orig_shutdown
            main_module._background_tasks = orig_tasks

    def test_atexit_cleanup_calls_whatsapp_stop_sync(self) -> None:
        """_atexit_cleanup calls whatsapp.stop_sync()."""
        import koda2.main as main_module

        orig_orch = main_module._orchestrator
        try:
            mock_orch = MagicMock()
            mock_orch.whatsapp.stop_sync = MagicMock()
            main_module._orchestrator = mock_orch

            main_module._atexit_cleanup()

            mock_orch.whatsapp.stop_sync.assert_called_once()
        finally:
            main_module._orchestrator = orig_orch

    def test_atexit_cleanup_no_orchestrator(self) -> None:
        """_atexit_cleanup is safe when orchestrator is None."""
        import koda2.main as main_module

        orig_orch = main_module._orchestrator
        try:
            main_module._orchestrator = None
            main_module._atexit_cleanup()  # should not raise
        finally:
            main_module._orchestrator = orig_orch
