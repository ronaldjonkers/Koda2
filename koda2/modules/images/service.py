"""Image generation and analysis service."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from koda2.config import get_settings
from koda2.logging_config import get_logger

logger = get_logger(__name__)


class ImageService:
    """Unified image generation (DALL-E, Stability AI, Gemini Imagen) and analysis (GPT-4 Vision)."""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ── Generation ───────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), retry=retry_if_not_exception_type(ValueError))
    async def generate(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "standard",
        n: int = 1,
        provider: Optional[str] = None,
    ) -> list[str]:
        """Generate images and return URLs or base64 data."""
        provider = provider or self._settings.image_provider

        if provider == "openai":
            return await self._generate_dalle(prompt, size, quality, n)
        elif provider == "stability":
            return await self._generate_stability(prompt, size)
        elif provider == "gemini":
            return await self._generate_gemini(prompt, n)
        else:
            raise ValueError(f"Unknown image provider: {provider}")

    async def _generate_dalle(
        self, prompt: str, size: str, quality: str, n: int,
    ) -> list[str]:
        """Generate images using OpenAI DALL-E."""
        import openai

        client = openai.AsyncOpenAI(api_key=self._settings.openai_api_key)
        response = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality=quality,
            n=n,
        )
        urls = [img.url for img in response.data if img.url]
        logger.info("dalle_generated", count=len(urls), prompt=prompt[:80])
        return urls

    async def _generate_stability(self, prompt: str, size: str) -> list[str]:
        """Generate images using Stability AI."""
        if not self._settings.stability_api_key:
            raise ValueError("Stability API key not configured")

        width, height = (int(x) for x in size.split("x"))
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
                json={
                    "text_prompts": [{"text": prompt, "weight": 1}],
                    "cfg_scale": 7,
                    "width": width,
                    "height": height,
                    "samples": 1,
                    "steps": 30,
                },
                headers={
                    "Authorization": f"Bearer {self._settings.stability_api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

        images = []
        for artifact in data.get("artifacts", []):
            if artifact.get("finishReason") == "SUCCESS":
                images.append(f"data:image/png;base64,{artifact['base64']}")
        logger.info("stability_generated", count=len(images))
        return images

    async def _generate_gemini(self, prompt: str, n: int = 1) -> list[str]:
        """Generate images using Google Gemini Imagen."""
        api_key = self._settings.google_ai_api_key
        if not api_key:
            raise ValueError("Google AI API key not configured (GOOGLE_AI_API_KEY)")

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        response = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=min(n, 4),
                output_mime_type="image/png",
            ),
        )

        images: list[str] = []
        if response.generated_images:
            output_dir = Path("data/images")
            output_dir.mkdir(parents=True, exist_ok=True)
            import uuid
            for img in response.generated_images:
                filename = f"{uuid.uuid4().hex}.png"
                filepath = output_dir / filename
                img.image.save(str(filepath))
                images.append(str(filepath))

        logger.info("gemini_imagen_generated", count=len(images), prompt=prompt[:80])
        return images

    async def save_image(self, url_or_data: str, output_path: str) -> str:
        """Download and save an image to disk."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if url_or_data.startswith("data:"):
            b64 = url_or_data.split(",", 1)[1]
            path.write_bytes(base64.b64decode(b64))
        else:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url_or_data, timeout=60)
                resp.raise_for_status()
                path.write_bytes(resp.content)

        logger.info("image_saved", path=str(path))
        return str(path)

    # ── Analysis ─────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def analyze(
        self,
        image_source: str,
        prompt: str = "Describe this image in detail.",
        model: str = "gpt-4o",
    ) -> str:
        """Analyze an image using GPT-4 Vision or equivalent."""
        import openai

        client = openai.AsyncOpenAI(api_key=self._settings.openai_api_key)

        if image_source.startswith(("http://", "https://")):
            image_content = {"type": "image_url", "image_url": {"url": image_source}}
        else:
            path = Path(image_source)
            if path.exists():
                b64 = base64.b64encode(path.read_bytes()).decode()
                ext = path.suffix.lstrip(".")
                mime = f"image/{ext}" if ext != "jpg" else "image/jpeg"
                image_content = {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
            else:
                image_content = {"type": "image_url", "image_url": {"url": image_source}}

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        image_content,
                    ],
                }
            ],
            max_tokens=1024,
        )
        result = response.choices[0].message.content or ""
        logger.info("image_analyzed", source=image_source[:80])
        return result
