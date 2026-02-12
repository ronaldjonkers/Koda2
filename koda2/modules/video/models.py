"""Video generation models."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VideoProvider(Enum):
    """Supported video generation providers."""
    RUNWAY = "runway"
    PIKA = "pika"
    STABLE_VIDEO = "stable_video"
    HEYGEN = "heygen"  # For avatar videos
    SYNTHESIA = "synthesia"


class VideoStatus(Enum):
    """Status of video generation."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class VideoGenerationRequest:
    """Request for video generation."""
    prompt: str
    provider: VideoProvider = VideoProvider.RUNWAY
    
    # Image-to-video options
    image_url: Optional[str] = None  # Starting frame image
    
    # Video parameters
    duration_seconds: int = 4  # 4-16 seconds depending on provider
    aspect_ratio: str = "16:9"  # 16:9, 9:16, 1:1, 4:3
    
    # Motion/animation
    motion_intensity: str = "medium"  # low, medium, high
    camera_motion: Optional[str] = None  # zoom_in, zoom_out, pan_left, pan_right, etc.
    
    # Style
    style: Optional[str] = None  # cinematic, anime, realistic, etc.
    
    # For avatar/text-to-speech videos
    script: Optional[str] = None  # Spoken text for avatar videos
    avatar_id: Optional[str] = None  # Specific avatar for HeyGen/Synthesia
    voice_id: Optional[str] = None  # Voice for narration
    
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))


@dataclass
class VideoGenerationResult:
    """Result of video generation."""
    request: VideoGenerationRequest
    status: VideoStatus
    
    # Output
    video_url: Optional[str] = None
    video_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    
    # Provider response
    provider_job_id: Optional[str] = None
    
    # Metadata
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    completed_at: Optional[dt.datetime] = None
    
    # Error info
    error_message: Optional[str] = None
    
    # Cost/usage
    credits_used: Optional[float] = None
    
    def is_ready(self) -> bool:
        """Check if video is ready for download."""
        return self.status == VideoStatus.COMPLETED and self.video_url is not None
