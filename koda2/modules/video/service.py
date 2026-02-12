"""Video generation service supporting multiple providers."""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path
from typing import Optional, Any

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.modules.video.models import (
    VideoProvider,
    VideoStatus,
    VideoGenerationRequest,
    VideoGenerationResult,
)

logger = get_logger(__name__)


class VideoService:
    """Unified video generation service.
    
    Supports:
    - Runway ML (text-to-video, image-to-video)
    - Pika Labs (text-to-video, image-to-video)
    - Stable Video Diffusion
    - HeyGen (AI avatars)
    """
    
    def __init__(self) -> None:
        self._settings = get_settings()
        self._pending_jobs: dict[str, VideoGenerationResult] = {}
    
    async def generate(
        self,
        prompt: str,
        image_path: Optional[str] = None,
        provider: Optional[str] = None,
        duration: int = 4,
        aspect_ratio: str = "16:9",
        motion: str = "medium",
    ) -> VideoGenerationResult:
        """Generate a video from text or image.
        
        Args:
            prompt: Text description of desired video
            image_path: Optional starting image (for image-to-video)
            provider: Provider to use (runway, pika, stable_video)
            duration: Video length in seconds (4-16)
            aspect_ratio: Output aspect ratio (16:9, 9:16, 1:1)
            motion: Motion intensity (low, medium, high)
            
        Returns:
            VideoGenerationResult with status and URL
        """
        provider_enum = VideoProvider(provider or self._settings.video_provider or "runway")
        
        request = VideoGenerationRequest(
            prompt=prompt,
            provider=provider_enum,
            image_url=f"file://{image_path}" if image_path else None,
            duration_seconds=min(max(duration, 4), 16),
            aspect_ratio=aspect_ratio,
            motion_intensity=motion,
        )
        
        if provider_enum == VideoProvider.RUNWAY:
            return await self._generate_runway(request)
        elif provider_enum == VideoProvider.PIKA:
            return await self._generate_pika(request)
        elif provider_enum == VideoProvider.STABLE_VIDEO:
            return await self._generate_stable_video(request)
        elif provider_enum == VideoProvider.HEYGEN:
            return await self._generate_heygen(request)
        else:
            raise ValueError(f"Unsupported video provider: {provider}")
    
    async def _generate_runway(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        """Generate video using Runway ML API."""
        api_key = self._settings.runway_api_key
        if not api_key:
            return VideoGenerationResult(
                request=request,
                status=VideoStatus.FAILED,
                error_message="Runway API key not configured",
            )
        
        try:
            async with httpx.AsyncClient() as client:
                # Create generation task
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                
                # Prepare payload
                payload: dict[str, Any] = {
                    "prompt": request.prompt,
                    "duration": request.duration_seconds,
                    "ratio": request.aspect_ratio.replace(":", ":"),
                    "motion": request.motion_intensity,
                }
                
                # Add image if provided
                if request.image_url and request.image_url.startswith("file://"):
                    image_path = request.image_url[7:]
                    image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
                    payload["image"] = f"data:image/png;base64,{image_b64}"
                elif request.image_url:
                    payload["image_url"] = request.image_url
                
                resp = await client.post(
                    "https://api.runwayml.com/v1/generations",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                
                job_id = data.get("id")
                result = VideoGenerationResult(
                    request=request,
                    status=VideoStatus.PROCESSING,
                    provider_job_id=job_id,
                )
                self._pending_jobs[job_id] = result
                
                logger.info("runway_generation_started", job_id=job_id)
                
                # Poll for completion
                video_url = await self._poll_runway_job(client, headers, job_id)
                
                if video_url:
                    result.status = VideoStatus.COMPLETED
                    result.video_url = video_url
                    result.completed_at = dt.datetime.now(dt.UTC)
                    
                    # Download video
                    download_path = await self._download_video(video_url, f"runway_{job_id}.mp4")
                    result.video_path = download_path
                else:
                    result.status = VideoStatus.FAILED
                    result.error_message = "Generation timed out or failed"
                
                return result
                
        except httpx.HTTPError as exc:
            logger.error("runway_api_error", error=str(exc))
            return VideoGenerationResult(
                request=request,
                status=VideoStatus.FAILED,
                error_message=f"API error: {exc}",
            )
        except Exception as exc:
            logger.error("runway_generation_failed", error=str(exc))
            return VideoGenerationResult(
                request=request,
                status=VideoStatus.FAILED,
                error_message=str(exc),
            )
    
    async def _poll_runway_job(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        job_id: str,
        max_attempts: int = 60,
        delay_seconds: int = 5,
    ) -> Optional[str]:
        """Poll Runway job until completion."""
        for attempt in range(max_attempts):
            try:
                resp = await client.get(
                    f"https://api.runwayml.com/v1/generations/{job_id}",
                    headers=headers,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                
                status = data.get("status")
                if status == "completed":
                    return data.get("output", [{}])[0].get("url")
                elif status == "failed":
                    logger.error("runway_job_failed", job_id=job_id)
                    return None
                
                # Still processing
                logger.debug("runway_job_processing", job_id=job_id, attempt=attempt)
                await asyncio.sleep(delay_seconds)
                
            except Exception as exc:
                logger.warning("runway_poll_error", error=str(exc))
                await asyncio.sleep(delay_seconds)
        
        logger.warning("runway_poll_timeout", job_id=job_id)
        return None
    
    async def _generate_pika(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        """Generate video using Pika Labs API."""
        api_key = self._settings.pika_api_key
        if not api_key:
            return VideoGenerationResult(
                request=request,
                status=VideoStatus.FAILED,
                error_message="Pika API key not configured",
            )
        
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                
                payload: dict[str, Any] = {
                    "prompt": request.prompt,
                    "duration": request.duration_seconds,
                    "aspect_ratio": request.aspect_ratio,
                    "motion": request.motion_intensity,
                }
                
                # Add image if provided
                if request.image_url and request.image_url.startswith("file://"):
                    image_path = request.image_url[7:]
                    image_b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
                    payload["image"] = f"data:image/png;base64,{image_b64}"
                elif request.image_url:
                    payload["image_url"] = request.image_url
                
                resp = await client.post(
                    "https://api.pika.art/generations",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                
                job_id = data.get("id")
                result = VideoGenerationResult(
                    request=request,
                    status=VideoStatus.PROCESSING,
                    provider_job_id=job_id,
                )
                
                # Poll for completion
                video_url = await self._poll_pika_job(client, headers, job_id)
                
                if video_url:
                    result.status = VideoStatus.COMPLETED
                    result.video_url = video_url
                    result.completed_at = dt.datetime.now(dt.UTC)
                    download_path = await self._download_video(video_url, f"pika_{job_id}.mp4")
                    result.video_path = download_path
                else:
                    result.status = VideoStatus.FAILED
                    result.error_message = "Generation timed out"
                
                return result
                
        except Exception as exc:
            logger.error("pika_generation_failed", error=str(exc))
            return VideoGenerationResult(
                request=request,
                status=VideoStatus.FAILED,
                error_message=str(exc),
            )
    
    async def _poll_pika_job(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        job_id: str,
        max_attempts: int = 60,
        delay_seconds: int = 5,
    ) -> Optional[str]:
        """Poll Pika job until completion."""
        for _ in range(max_attempts):
            try:
                resp = await client.get(
                    f"https://api.pika.art/generations/{job_id}",
                    headers=headers,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                
                status = data.get("status")
                if status == "completed":
                    return data.get("video_url")
                elif status == "failed":
                    return None
                
                await asyncio.sleep(delay_seconds)
            except Exception:
                await asyncio.sleep(delay_seconds)
        
        return None
    
    async def _generate_stable_video(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        """Generate video using Stable Video Diffusion."""
        api_key = self._settings.stability_api_key
        if not api_key:
            return VideoGenerationResult(
                request=request,
                status=VideoStatus.FAILED,
                error_message="Stability API key not configured",
            )
        
        # Stable Video requires an image
        if not request.image_url:
            # First generate an image
            from koda2.modules.images import ImageService
            image_service = ImageService()
            image_urls = await image_service.generate(request.prompt, size="1024x576")
            if not image_urls:
                return VideoGenerationResult(
                    request=request,
                    status=VideoStatus.FAILED,
                    error_message="Failed to generate starting image",
                )
            request.image_url = image_urls[0]
        
        try:
            async with httpx.AsyncClient() as client:
                # Get image data
                if request.image_url.startswith("file://"):
                    image_data = Path(request.image_url[7:]).read_bytes()
                elif request.image_url.startswith("http"):
                    img_resp = await client.get(request.image_url, timeout=30)
                    image_data = img_resp.content
                else:
                    image_data = base64.b64decode(request.image_url.split(",")[1])
                
                # Upload to Stability
                headers = {"Authorization": f"Bearer {api_key}"}
                files = {"image": ("input.png", image_data, "image/png")}
                
                resp = await client.post(
                    "https://api.stability.ai/v2beta/image-to-video",
                    headers=headers,
                    files=files,
                    data={"seed": 0, "cfg_scale": 2.5, "motion_bucket_id": 40},
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                
                generation_id = data.get("id")
                result = VideoGenerationResult(
                    request=request,
                    status=VideoStatus.PROCESSING,
                    provider_job_id=generation_id,
                )
                
                # Poll for completion
                video_url = await self._poll_stable_video(client, headers, generation_id)
                
                if video_url:
                    result.status = VideoStatus.COMPLETED
                    result.video_url = video_url
                    result.completed_at = dt.datetime.now(dt.UTC)
                    download_path = await self._download_video(video_url, f"svd_{generation_id}.mp4")
                    result.video_path = download_path
                else:
                    result.status = VideoStatus.FAILED
                    result.error_message = "Generation timed out"
                
                return result
                
        except Exception as exc:
            logger.error("stable_video_generation_failed", error=str(exc))
            return VideoGenerationResult(
                request=request,
                status=VideoStatus.FAILED,
                error_message=str(exc),
            )
    
    async def _poll_stable_video(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        generation_id: str,
        max_attempts: int = 60,
    ) -> Optional[str]:
        """Poll Stable Video job."""
        for _ in range(max_attempts):
            try:
                resp = await client.get(
                    f"https://api.stability.ai/v2beta/image-to-video/result/{generation_id}",
                    headers=headers,
                    timeout=30,
                )
                
                if resp.status_code == 202:
                    # Still processing
                    await asyncio.sleep(5)
                    continue
                
                resp.raise_for_status()
                
                # Save video
                video_path = f"data/generated/svd_{generation_id}.mp4"
                Path(video_path).parent.mkdir(parents=True, exist_ok=True)
                Path(video_path).write_bytes(resp.content)
                
                return video_path
                
            except Exception:
                await asyncio.sleep(5)
        
        return None
    
    async def _generate_heygen(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        """Generate avatar video using HeyGen."""
        api_key = self._settings.heygen_api_key
        if not api_key:
            return VideoGenerationResult(
                request=request,
                status=VideoStatus.FAILED,
                error_message="HeyGen API key not configured",
            )
        
        if not request.script:
            return VideoGenerationResult(
                request=request,
                status=VideoStatus.FAILED,
                error_message="Script required for avatar video",
            )
        
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                
                payload = {
                    "video_inputs": [{
                        "character": {
                            "type": "avatar",
                            "avatar_id": request.avatar_id or "default",
                            "avatar_style": "normal",
                        },
                        "voice": {
                            "type": "text",
                            "input_text": request.script,
                            "voice_id": request.voice_id or "default",
                        },
                    }],
                    "dimension": {"width": 1280, "height": 720},
                }
                
                resp = await client.post(
                    "https://api.heygen.com/v2/video/generate",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                
                video_id = data.get("data", {}).get("video_id")
                result = VideoGenerationResult(
                    request=request,
                    status=VideoStatus.PROCESSING,
                    provider_job_id=video_id,
                )
                
                # Poll for completion
                video_url = await self._poll_heygen_job(client, headers, video_id)
                
                if video_url:
                    result.status = VideoStatus.COMPLETED
                    result.video_url = video_url
                    result.completed_at = dt.datetime.now(dt.UTC)
                    download_path = await self._download_video(video_url, f"heygen_{video_id}.mp4")
                    result.video_path = download_path
                else:
                    result.status = VideoStatus.FAILED
                    result.error_message = "Generation timed out"
                
                return result
                
        except Exception as exc:
            logger.error("heygen_generation_failed", error=str(exc))
            return VideoGenerationResult(
                request=request,
                status=VideoStatus.FAILED,
                error_message=str(exc),
            )
    
    async def _poll_heygen_job(
        self,
        client: httpx.AsyncClient,
        headers: dict,
        video_id: str,
        max_attempts: int = 60,
    ) -> Optional[str]:
        """Poll HeyGen job."""
        for _ in range(max_attempts):
            try:
                resp = await client.get(
                    f"https://api.heygen.com/v1/video_status.get?video_id={video_id}",
                    headers=headers,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                
                status = data.get("data", {}).get("status")
                if status == "completed":
                    return data.get("data", {}).get("video_url")
                elif status == "failed":
                    return None
                
                await asyncio.sleep(5)
            except Exception:
                await asyncio.sleep(5)
        
        return None
    
    async def _download_video(self, url: str, filename: str) -> str:
        """Download video to local storage."""
        output_dir = Path("data/generated/videos")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=120)
            resp.raise_for_status()
            
            file_path = output_dir / filename
            file_path.write_bytes(resp.content)
            
            logger.info("video_downloaded", path=str(file_path))
            return str(file_path)
    
    async def list_pending_jobs(self) -> list[VideoGenerationResult]:
        """List all pending video generation jobs."""
        return [r for r in self._pending_jobs.values() if r.status == VideoStatus.PROCESSING]
    
    async def get_job_status(self, job_id: str) -> Optional[VideoGenerationResult]:
        """Get status of a specific job."""
        return self._pending_jobs.get(job_id)
