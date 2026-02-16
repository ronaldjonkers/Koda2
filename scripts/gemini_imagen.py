#!/usr/bin/env python3
"""Generate images using Gemini Imagen 4 (or Imagen 3) via google-genai SDK."""

import argparse
import base64
import os
import sys
from pathlib import Path

from google import genai
from google.genai import types


def generate_image(prompt: str, output_path: str, model: str = "imagen-4.0-generate-preview-06-06") -> str:
    """Generate an image with Gemini Imagen and save to output_path."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        # Try loading from .env
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

    if not api_key:
        print("ERROR: No GEMINI_API_KEY found", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Try Imagen 4 first, fall back to Imagen 3
    models_to_try = [model, "imagen-3.0-generate-002", "imagen-3.0-generate-001"]
    
    last_error = None
    for m in models_to_try:
        try:
            print(f"Trying model: {m}")
            response = client.models.generate_images(
                model=m,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="9:16",  # Portrait
                    person_generation="ALLOW_ADULT",
                ),
            )
            
            if response.generated_images and len(response.generated_images) > 0:
                img_data = response.generated_images[0].image.image_bytes
                Path(output_path).write_bytes(img_data)
                print(f"SUCCESS: Image saved to {output_path} (model: {m})")
                return output_path
            else:
                print(f"No images returned by {m}")
                last_error = "No images returned"
        except Exception as e:
            print(f"Model {m} failed: {e}")
            last_error = str(e)
            continue

    # Fallback: try gemini-2.0-flash with image generation
    try:
        print("Trying Gemini 2.0 Flash image generation...")
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )
        
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                img_data = part.inline_data.data
                Path(output_path).write_bytes(img_data)
                print(f"SUCCESS: Image saved to {output_path} (model: gemini-2.0-flash-exp)")
                return output_path
    except Exception as e:
        print(f"Gemini Flash fallback failed: {e}")

    print(f"ERROR: All models failed. Last error: {last_error}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate image with Gemini Imagen")
    parser.add_argument("--prompt", "-p", required=True, help="Image prompt")
    parser.add_argument("--output", "-o", default="/Users/ronaldjonkers/Desktop/joyce_generated.png", help="Output path")
    parser.add_argument("--model", "-m", default="imagen-4.0-generate-preview-06-06", help="Model name")
    args = parser.parse_args()
    
    generate_image(args.prompt, args.output, args.model)
