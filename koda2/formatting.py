from typing import Any, Dict, List, Union
from datetime import datetime

class ResponseFormatter:
    @staticmethod
    def format_calendar_events(events: List[Dict]) -> str:
        if not events:
            return "No events found."
        
        output = []
        for event in events:
            start = datetime.fromisoformat(event['start'].replace('Z', '+00:00'))
            title = event.get('title', 'Untitled Event')
            output.append(f"• {start.strftime('%Y-%m-%d %H:%M')} - {title}")
        
        return '\n'.join(output)
    
    @staticmethod
    def format_email_list(emails: List[Dict]) -> str:
        if not emails:
            return "No emails found."
            
        output = []
        for email in emails:
            subject = email.get('subject', 'No Subject')
            sender = email.get('from', 'Unknown')
            output.append(f"• From: {sender}\n  Subject: {subject}")
            
        return '\n'.join(output)
    
    @staticmethod
    def format_task_list(tasks: List[Dict]) -> str:
        if not tasks:
            return "No tasks found."
            
        output = []
        for task in tasks:
            status = task.get('status', 'unknown')
            description = task.get('description', 'No description')
            output.append(f"• [{status}] {description}")
            
        return '\n'.join(output)
    
    @staticmethod
    def format_error(error: Dict) -> str:
        return f"Error: {error.get('message', 'An unknown error occurred.')}"
