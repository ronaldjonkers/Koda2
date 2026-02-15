import logging
import time
from typing import Dict, Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

class OpenRouterError(Exception):
    pass

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 300):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.last_failure_time = 0

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()

    def record_success(self):
        self.failure_count = 0

    @property
    def is_open(self) -> bool:
        if self.failure_count >= self.failure_threshold:
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.failure_count = 0
                return False
            return True
        return False

class OpenRouterClient:
    def __init__(self, api_key: str, base_url: str = 'https://openrouter.ai/api/v1'):
        self.api_key = api_key
        self.base_url = base_url
        self.circuit_breaker = CircuitBreaker()

    def _log_request_details(self, method: str, url: str, headers: Dict, data: Dict):
        logger.debug(
            'OpenRouter API Request:\n'
            f'Method: {method}\n'
            f'URL: {url}\n'
            f'Headers: {headers}\n'
            f'Data: {data}'
        )

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True
    )
    async def request(self, method: str, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if self.circuit_breaker.is_open:
            raise OpenRouterError('Circuit breaker is open')

        url = f'{self.base_url}/{endpoint.lstrip("/")}'
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        self._log_request_details(method, url, headers, data)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                    timeout=30.0
                )

                if response.status_code == 400:
                    logger.error(
                        'OpenRouter API 400 Error:\n'
                        f'Response: {response.text}\n'
                        f'Request details: {data}'
                    )
                    self.circuit_breaker.record_failure()
                    raise OpenRouterError(f'Bad request: {response.text}')

                response.raise_for_status()
                self.circuit_breaker.record_success()
                return response.json()

        except httpx.HTTPError as e:
            logger.error(f'OpenRouter API HTTP error: {str(e)}')
            self.circuit_breaker.record_failure()
            raise OpenRouterError(f'HTTP error: {str(e)}')

        except Exception as e:
            logger.error(f'OpenRouter API unexpected error: {str(e)}')
            self.circuit_breaker.record_failure()
            raise OpenRouterError(f'Unexpected error: {str(e)}')
