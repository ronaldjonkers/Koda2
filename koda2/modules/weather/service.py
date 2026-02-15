import logging
import os
import httpx
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class WeatherService:
    def __init__(self):
        self.api_key = os.getenv('OPENWEATHERMAP_API_KEY', '')
        self.base_url = 'http://api.openweathermap.org/data/2.5'

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def get_forecast(self, city: str) -> Optional[Dict]:
        if not self.is_configured():
            logger.error('OpenWeatherMap API key not configured')
            return None

        try:
            async with httpx.AsyncClient() as client:
                params = {
                    'q': city,
                    'appid': self.api_key,
                    'units': 'metric'
                }
                response = await client.get(f'{self.base_url}/weather', params=params)
                response.raise_for_status()
                data = response.json()
                
                return {
                    'city': data['name'],
                    'temp': round(data['main']['temp']),
                    'feels_like': round(data['main']['feels_like']),
                    'humidity': data['main']['humidity'],
                    'description': data['weather'][0]['description'],
                    'wind_speed': round(data['wind']['speed'])
                }

        except Exception as e:
            logger.error(f'Error fetching weather for {city}: {str(e)}')
            return None