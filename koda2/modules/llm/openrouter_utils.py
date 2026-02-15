import httpx
import logging
import random
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def call_openrouter_api(
    url: str,
    headers: Dict[str, str],
    json_data: Dict[str, Any],
    max_retries: int = 3,
    base_delay: float = 1.0
) -> Optional[Dict[str, Any]]:
    """
    Make OpenRouter API calls with exponential backoff and error handling.
    
    Args:
        url: OpenRouter API endpoint URL
        headers: Request headers including auth
        json_data: Request body as dictionary
        max_retries: Maximum number of retry attempts
        base_delay: Base delay for exponential backoff in seconds
    
    Returns:
        API response as dictionary or None if all retries fail
    """
    attempt = 0
    
    while attempt <= max_retries:
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, headers=headers, json=json_data)
                response.raise_for_status()
                return response.json()
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                logger.error(
                    "OpenRouter API 400 error. Request details:\n"
                    f"URL: {url}\n"
                    f"Headers: {headers}\n"
                    f"Body: {json_data}\n"
                    f"Response: {e.response.text}"
                )
                return None
            
            attempt += 1
            if attempt > max_retries:
                logger.error(f"Max retries ({max_retries}) exceeded calling OpenRouter API")
                return None
                
            # Exponential backoff with jitter
            delay = (base_delay * 2 ** attempt) + (random.random() * 0.1)
            logger.warning(f"Retrying OpenRouter API call in {delay:.2f} seconds")
            time.sleep(delay)
            
        except Exception as e:
            logger.error(f"Unexpected error calling OpenRouter API: {str(e)}")
            return None
            
    return None