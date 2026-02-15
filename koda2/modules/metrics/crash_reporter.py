import sys
import traceback
import inspect
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class CrashReporter:
    @staticmethod
    def capture_error_context(exc_info) -> Dict:
        try:
            exc_type, exc_value, exc_traceback = exc_info
            
            # Get full traceback
            tb_list = traceback.extract_tb(exc_traceback)
            formatted_tb = ''.join(traceback.format_tb(exc_traceback))
            
            # Get source code context
            context_lines = []
            for frame in tb_list:
                try:
                    lines, start_line = inspect.getsourcelines(frame)
                    context_lines.append({
                        'filename': frame.filename,
                        'line_number': frame.lineno,
                        'function': frame.name,
                        'code_context': ''.join(lines)
                    })
                except Exception:
                    pass
            
            return {
                'error_type': exc_type.__name__,
                'error_message': str(exc_value),
                'traceback': formatted_tb,
                'source_context': context_lines
            }
        except Exception as e:
            logger.error(f"Failed to capture error context: {e}")
            return {
                'error_type': 'Unknown',
                'error_message': 'Failed to capture error context',
                'traceback': '',
                'source_context': []
            }

    @staticmethod
    def format_analysis_prompt(error_context: Dict) -> str:
        return f"""Please analyze this crash and provide specific debugging guidance.

Error Type: {error_context['error_type']}
Error Message: {error_context['error_message']}

Traceback:
{error_context['traceback']}

Relevant Source Code Context:
{chr(10).join(f'File: {ctx["filename"]}, Line {ctx["line_number"]}, Function: {ctx["function"]}\n{ctx["code_context"]}' for ctx in error_context['source_context'])}

If you cannot fully diagnose the issue, please explicitly state what additional information would be helpful for diagnosis."""