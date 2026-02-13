"""Models for document analysis."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FileType(Enum):
    """Supported file types for analysis."""
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    TXT = "txt"
    CSV = "csv"
    IMAGE = "image"  # jpg, png, gif, etc.
    UNKNOWN = "unknown"


@dataclass
class DocumentAnalysis:
    """Result of document analysis."""
    
    # File info
    file_path: str
    file_type: FileType
    file_size: int
    filename: str
    
    # Extracted content
    text_content: Optional[str] = None  # Full text for documents
    summary: Optional[str] = None  # AI-generated summary
    
    # For spreadsheets
    sheet_names: Optional[list[str]] = None
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    
    # For presentations
    slide_count: Optional[int] = None
    
    # For images
    image_description: Optional[str] = None
    detected_text: Optional[str] = None  # OCR result
    
    # Metadata
    title: Optional[str] = None
    author: Optional[str] = None
    created_date: Optional[dt.datetime] = None
    modified_date: Optional[dt.datetime] = None
    
    # Key topics/entities (extracted by AI)
    key_topics: list[str] = field(default_factory=list)
    mentioned_people: list[str] = field(default_factory=list)
    mentioned_dates: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    
    # Analysis metadata
    analyzed_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    analysis_error: Optional[str] = None
    
    def is_successful(self) -> bool:
        """Check if analysis was successful."""
        return self.analysis_error is None
    
    def to_context_string(self, max_length: int = 2000) -> str:
        """Convert analysis to a string suitable for LLM context."""
        parts = [
            f"Document: {self.filename}",
            f"Type: {self.file_type.value}",
        ]
        
        if self.title:
            parts.append(f"Title: {self.title}")
        if self.author:
            parts.append(f"Author: {self.author}")
        if self.summary:
            parts.append(f"Summary: {self.summary}")
        
        # Add specific content based on type
        if self.file_type == FileType.IMAGE:
            if self.image_description:
                parts.append(f"Image description: {self.image_description}")
            if self.detected_text:
                parts.append(f"Text in image: {self.detected_text}")
        elif self.text_content:
            content = self.text_content[:max_length]
            if len(self.text_content) > max_length:
                content += "... [truncated]"
            parts.append(f"Content:\n{content}")
        
        if self.key_topics:
            parts.append(f"Key topics: {', '.join(self.key_topics)}")
        if self.action_items:
            parts.append(f"Action items: {'; '.join(self.action_items)}")
        
        return "\n".join(parts)
