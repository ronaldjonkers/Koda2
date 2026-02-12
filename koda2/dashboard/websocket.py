"""WebSocket handlers for real-time dashboard updates."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import socketio
from fastapi import FastAPI

from koda2.logging_config import get_logger
from koda2.modules.metrics.service import MetricsService, SystemMetrics, ServiceMetrics
from koda2.modules.task_queue.service import TaskQueueService, Task

logger = get_logger(__name__)

# Create Socket.IO server
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)


class DashboardWebSocket:
    """Manages WebSocket connections for the dashboard."""
    
    def __init__(
        self,
        task_queue: TaskQueueService,
        metrics: MetricsService,
    ):
        self.task_queue = task_queue
        self.metrics = metrics
        self._clients: set[str] = set()
        self._broadcast_task: Optional[asyncio.Task] = None
        
        # Register event handlers
        sio.on("connect", self.on_connect)
        sio.on("disconnect", self.on_disconnect)
        sio.on("subscribe", self.on_subscribe)
        
        # Register callbacks
        self.task_queue.register_callback(self.on_task_update)
        self.metrics.register_callback(self.on_metrics_update)
        
    async def start(self) -> None:
        """Start the WebSocket server."""
        logger.info("websocket_server_started")
        
    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self._broadcast_task:
            self._broadcast_task.cancel()
        logger.info("websocket_server_stopped")
        
    async def on_connect(self, sid: str, environ: dict) -> None:
        """Handle client connection."""
        self._clients.add(sid)
        logger.info("dashboard_client_connected", sid=sid, total_clients=len(self._clients))
        
        # Send initial data
        await self._send_initial_data(sid)
        
    async def on_disconnect(self, sid: str) -> None:
        """Handle client disconnection."""
        self._clients.discard(sid)
        logger.info("dashboard_client_disconnected", sid=sid, total_clients=len(self._clients))
        
    async def on_subscribe(self, sid: str, data: dict) -> None:
        """Handle subscription request."""
        channel = data.get("channel", "all")
        logger.debug("client_subscribed", sid=sid, channel=channel)
        
    async def on_task_update(self, task: Task) -> None:
        """Broadcast task updates to all clients."""
        await self.broadcast("task_update", {
            "task": task.to_dict(),
        })
        
    async def on_metrics_update(
        self,
        sys_metrics: SystemMetrics,
        svc_metrics: ServiceMetrics,
    ) -> None:
        """Broadcast metrics updates."""
        await self.broadcast("metrics_update", {
            "system": {
                "cpu_percent": sys_metrics.cpu_percent,
                "memory_percent": sys_metrics.memory_percent,
                "disk_percent": sys_metrics.disk_percent,
                "timestamp": sys_metrics.timestamp,
            },
            "service": {
                "active_tasks": svc_metrics.active_tasks,
                "pending_tasks": svc_metrics.pending_tasks,
                "messages_per_minute": svc_metrics.messages_per_minute,
                "api_requests_per_minute": svc_metrics.api_requests_per_minute,
                "memory_usage_mb": svc_metrics.memory_usage_mb,
            },
        })
        
    async def _send_initial_data(self, sid: str) -> None:
        """Send initial data to a newly connected client."""
        try:
            # Send current metrics
            sys_m, svc_m = self.metrics.get_latest()
            await sio.emit("metrics_update", {
                "system": {
                    "cpu_percent": sys_m.cpu_percent,
                    "memory_percent": sys_m.memory_percent,
                    "disk_percent": sys_m.disk_percent,
                    "platform": sys_m.platform,
                    "hostname": sys_m.hostname,
                    "python_version": sys_m.python_version,
                },
                "service": {
                    "active_tasks": svc_m.active_tasks,
                    "pending_tasks": svc_m.pending_tasks,
                    "messages_processed": svc_m.messages_processed,
                    "memory_usage_mb": svc_m.memory_usage_mb,
                },
            }, room=sid)
            
            # Send active tasks
            tasks = await self.task_queue.get_active_tasks()
            await sio.emit("tasks_list", {
                "tasks": [t.to_dict() for t in tasks],
            }, room=sid)
            
        except Exception as exc:
            logger.error("initial_data_send_failed", error=str(exc))
            
    async def broadcast(self, event: str, data: dict) -> None:
        """Broadcast an event to all connected clients."""
        if self._clients:
            try:
                await sio.emit(event, data)
            except Exception as exc:
                logger.error("broadcast_failed", event=event, error=str(exc))
                
    async def broadcast_message(self, message_type: str, data: dict) -> None:
        """Broadcast a typed message."""
        await self.broadcast("message", {
            "type": message_type,
            "data": data,
            "timestamp": asyncio.get_event_loop().time(),
        })


def create_socket_app(
    task_queue: TaskQueueService,
    metrics: MetricsService,
) -> socketio.ASGIApp:
    """Create the Socket.IO ASGI application."""
    dashboard_ws = DashboardWebSocket(task_queue, metrics)
    
    # Store reference for lifecycle management
    sio.dashboard_ws = dashboard_ws  # type: ignore
    
    return socketio.ASGIApp(sio)
