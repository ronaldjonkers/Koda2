"""Tests for the image generation and analysis module."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.images.service import ImageService


@pytest.fixture
def image_service():
    with patch("koda2.modules.images.service.get_settings") as mock:
        mock.return_value = MagicMock(
            openai_api_key="sk-test",
            image_provider="openai",
            stability_api_key="",
        )
        return ImageService()


class TestImageService:
    """Tests for image generation and analysis."""

    @pytest.mark.asyncio
    async def test_generate_dalle(self, image_service) -> None:
        """DALL-E generation returns image URLs."""
        with patch("openai.AsyncOpenAI") as mock_client:
            mock_img = MagicMock()
            mock_img.url = "https://oaidalleapiprodscus.blob.core.windows.net/image.png"
            mock_response = MagicMock()
            mock_response.data = [mock_img]

            client = MagicMock()
            client.images.generate = AsyncMock(return_value=mock_response)
            mock_client.return_value = client

            urls = await image_service.generate("A sunset over mountains")
            assert len(urls) == 1
            assert urls[0].startswith("https://")

    @pytest.mark.asyncio
    async def test_generate_unknown_provider(self, image_service) -> None:
        """Unknown provider raises ValueError."""
        with pytest.raises(ValueError, match="Unknown image provider"):
            await image_service.generate("test", provider="unknown")

    @pytest.mark.asyncio
    async def test_generate_stability(self) -> None:
        """Stability AI generation returns base64 images."""
        with patch("koda2.modules.images.service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openai_api_key="",
                image_provider="stability",
                stability_api_key="sk-stab-test",
            )
            service = ImageService()

            with patch("httpx.AsyncClient") as mock_client:
                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "artifacts": [{"base64": base64.b64encode(b"fake_image").decode(), "finishReason": "SUCCESS"}]
                }
                mock_response.raise_for_status = MagicMock()

                mock_instance = AsyncMock()
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_instance.post = AsyncMock(return_value=mock_response)
                mock_client.return_value = mock_instance

                urls = await service.generate("test", provider="stability")
                assert len(urls) == 1
                assert urls[0].startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_generate_stability_no_key(self) -> None:
        """Stability generation without key raises ValueError."""
        with patch("koda2.modules.images.service.get_settings") as mock:
            mock.return_value = MagicMock(stability_api_key="", image_provider="stability")
            service = ImageService()
            with pytest.raises(ValueError, match="Stability API key"):
                await service.generate("test", provider="stability")

    @pytest.mark.asyncio
    async def test_save_image_url(self, image_service, tmp_path) -> None:
        """Saving an image from URL downloads it."""
        output = str(tmp_path / "test.png")
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.content = b"fake_image_data"
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_instance

            result = await image_service.save_image("https://example.com/img.png", output)
            assert Path(result).exists()

    @pytest.mark.asyncio
    async def test_save_image_base64(self, image_service, tmp_path) -> None:
        """Saving a base64 image writes it to disk."""
        output = str(tmp_path / "test.png")
        b64 = base64.b64encode(b"fake_image").decode()
        result = await image_service.save_image(f"data:image/png;base64,{b64}", output)
        assert Path(result).exists()
        assert Path(result).read_bytes() == b"fake_image"

    @pytest.mark.asyncio
    async def test_analyze_url(self, image_service) -> None:
        """Image analysis with URL source."""
        with patch("openai.AsyncOpenAI") as mock_client:
            mock_choice = MagicMock()
            mock_choice.message.content = "A beautiful mountain landscape at sunset."
            mock_response = MagicMock()
            mock_response.choices = [mock_choice]

            client = MagicMock()
            client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client.return_value = client

            result = await image_service.analyze("https://example.com/photo.jpg")
            assert "landscape" in result.lower() or "mountain" in result.lower()

    @pytest.mark.asyncio
    async def test_analyze_local_file(self, image_service, tmp_path) -> None:
        """Image analysis with local file source."""
        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"fake_jpg_data")

        with patch("openai.AsyncOpenAI") as mock_client:
            mock_choice = MagicMock()
            mock_choice.message.content = "An image."
            mock_response = MagicMock()
            mock_response.choices = [mock_choice]

            client = MagicMock()
            client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client.return_value = client

            result = await image_service.analyze(str(img_path))
            assert result == "An image."
