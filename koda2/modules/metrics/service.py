"""System metrics collection and monitoring service."""

from __future__ import annotations

import asyncio
import datetime as dt
import platform
import socket
from dataclasses import dataclass, field
from typing import Any, Optional

import psutil

from koda2.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class SystemMetrics:
    """Current system metrics snapshot."""
    
    # Timestamp
    timestamp: str = field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())
    
    # CPU
    cpu_percent: float = 0.0
    cpu_count: int = 0
    cpu_freq_mhz: float = 0.0
    load_average: tuple[float, ...] = field(default_factory=tuple)
    
    # Memory
    memory_percent: float = 0.0
    memory_used_gb: float = 0.0
    memory_total_gb: float = 0.0
    swap_percent: float = 0.0
    
    # Disk
    disk_percent: float = 0.0
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    
    # Network
    net_io_sent_mb: float = 0.0
    net_io_recv_mb: float = 0.0
    
    # Process
    process_count: int = 0
    thread_count: int = 0
    
    # System info
    hostname: str = ""
    platform: str = ""
    python_version: str = ""
    boot_time: str = ""


@dataclass
class ServiceMetrics:
    """Koda2 service-specific metrics."""
    
    timestamp: str = field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())
    
    # Tasks
    active_tasks: int = 0
    pending_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    
    # Messages
    messages_processed: int = 0
    messages_per_minute: float = 0.0
    
    # Memory usage
    memory_usage_mb: float = 0.0
    
    # API requests
    api_requests_total: int = 0
    api_requests_per_minute: float = 0.0
    
    # Connected services
    llm_providers_active: int = 0
    calendar_providers_active: int = 0
    email_connected: bool = False
    telegram_connected: bool = False
    whatsapp_connected: bool = False


class MetricsService:
    """Collects and provides system and service metrics."""
    
    def __init__(self, collection_interval: int = 5):
        self.collection_interval = collection_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._callbacks: list[Callable[[SystemMetrics, ServiceMetrics], Coroutine[Any, Any, None]]] = []
        
        # Historical data (keep last hour)
        self._history: list[tuple[SystemMetrics, ServiceMetrics]] = []
        self._max_history = 720  # 1 hour at 5-second intervals
        
        # Counters
        self._message_times: list[dt.datetime] = []
        self._api_request_times: list[dt.datetime] = []
        self._messages_processed = 0
        self._api_requests_total = 0
        
    def register_callback(
        self,
        callback: Callable[[SystemMetrics, ServiceMetrics], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a callback for metrics updates."""
        self._callbacks.append(callback)
        
    async def start(self) -> None:
        """Start metrics collection."""
        self._running = True
        self._task = asyncio.create_task(self._collection_loop())
        logger.info("metrics_service_started", interval=self.collection_interval)
        
    async def stop(self) -> None:
        """Stop metrics collection."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("metrics_service_stopped")
        
    async def _collection_loop(self) -> None:
        """Main collection loop."""
        while self._running:
            try:
                sys_metrics = self.collect_system_metrics()
                svc_metrics = self.collect_service_metrics()
                
                # Store history
                self._history.append((sys_metrics, svc_metrics))
                if len(self._history) > self._max_history:
                    self._history.pop(0)
                
                # Notify callbacks
                for callback in self._callbacks:
                    try:
                        await callback(sys_metrics, svc_metrics)
                    except Exception as exc:
                        logger.error("metrics_callback_failed", error=str(exc))
                        
                await asyncio.sleep(self.collection_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("metrics_collection_error", error=str(exc))
                await asyncio.sleep(self.collection_interval)
                
    @staticmethod
    def _safe_thread_count() -> int:
        """Safely count total threads across all processes."""
        total = 0
        for p in psutil.process_iter(['num_threads']):
            try:
                nt = p.info.get('num_threads')
                if nt:
                    total += nt
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return total

    def collect_system_metrics(self) -> SystemMetrics:
        """Collect current system metrics."""
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()
            cpu_freq = psutil.cpu_freq()
            
            # Load average (Unix only)
            try:
                load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else (0.0, 0.0, 0.0)
            except:
                load_avg = (0.0, 0.0, 0.0)
            
            # Memory
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # Disk
            disk = psutil.disk_usage('/')
            
            # Network
            net_io = psutil.net_io_counters()
            
            # Boot time
            boot_time = dt.datetime.fromtimestamp(psutil.boot_time(), dt.UTC)
            
            return SystemMetrics(
                timestamp=dt.datetime.now(dt.UTC).isoformat(),
                cpu_percent=cpu_percent,
                cpu_count=cpu_count or 0,
                cpu_freq_mhz=cpu_freq.current if cpu_freq else 0,
                load_average=load_avg,
                memory_percent=mem.percent,
                memory_used_gb=mem.used / (1024**3),
                memory_total_gb=mem.total / (1024**3),
                swap_percent=swap.percent,
                disk_percent=disk.percent,
                disk_used_gb=disk.used / (1024**3),
                disk_total_gb=disk.total / (1024**3),
                net_io_sent_mb=net_io.bytes_sent / (1024**2),
                net_io_recv_mb=net_io.bytes_recv / (1024**2),
                process_count=len(psutil.pids()),
                thread_count=self._safe_thread_count(),
                hostname=socket.gethostname(),
                platform=f"{platform.system()} {platform.release()}",
                python_version=platform.python_version(),
                boot_time=boot_time.isoformat(),
            )
        except Exception as exc:
            logger.error("system_metrics_collection_failed", error=str(exc))
            return SystemMetrics()
            
    def collect_service_metrics(self) -> ServiceMetrics:
        """Collect Koda2 service metrics."""
        now = dt.datetime.now(dt.UTC)
        
        # Clean old message times (older than 1 minute)
        cutoff = now - dt.timedelta(minutes=1)
        self._message_times = [t for t in self._message_times if t > cutoff]
        self._api_request_times = [t for t in self._api_request_times if t > cutoff]
        
        # Get process memory
        try:
            proc = psutil.Process()
            mem_mb = proc.memory_info().rss / (1024**2)
        except:
            mem_mb = 0.0
        
        return ServiceMetrics(
            timestamp=now.isoformat(),
            messages_processed=self._messages_processed,
            messages_per_minute=len(self._message_times),
            memory_usage_mb=mem_mb,
            api_requests_total=self._api_requests_total,
            api_requests_per_minute=len(self._api_request_times),
        )
        
    def record_message_processed(self) -> None:
        """Record a processed message."""
        self._messages_processed += 1
        self._message_times.append(dt.datetime.now(dt.UTC))
        
    def record_api_request(self) -> None:
        """Record an API request."""
        self._api_requests_total += 1
        self._api_request_times.append(dt.datetime.now(dt.UTC))
        
    def get_history(
        self,
        seconds: int = 300,
    ) -> list[tuple[SystemMetrics, ServiceMetrics]]:
        """Get metrics history for the last N seconds."""
        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=seconds)
        return [(s, m) for s, m in self._history 
                if dt.datetime.fromisoformat(s.timestamp) > cutoff]
                
    def get_latest(self) -> tuple[SystemMetrics, ServiceMetrics]:
        """Get the most recent metrics."""
        if self._history:
            return self._history[-1]
        return SystemMetrics(), ServiceMetrics()


# For type hints
import os
from typing import Coroutine, Callable
