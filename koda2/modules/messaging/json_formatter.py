import json
import logging
from typing import Any, Dict, List, Union

logger = logging.getLogger(__name__)

class JsonFormatter:
    @staticmethod
    def is_json(text: str) -> bool:
        try:
            json.loads(text)
            return True
        except (json.JSONDecodeError, TypeError):
            return False

    @staticmethod
    def format_value(value: Any, indent: int = 0) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, indent=2)
        return str(value)

    @staticmethod
    def format_json(json_str: str) -> str:
        try:
            data = json.loads(json_str)
            if isinstance(data, dict):
                return '\n'.join(f'{k}: {JsonFormatter.format_value(v)}'
                                for k, v in data.items())
            elif isinstance(data, list):
                return '\n'.join(f'- {JsonFormatter.format_value(item)}'
                                for item in data)
            return str(data)
        except Exception as e:
            logger.error(f'Error formatting JSON: {e}')
            return json_str

    @staticmethod
    def process(text: str) -> str:
        if JsonFormatter.is_json(text):
            return JsonFormatter.format_json(text)
        return text