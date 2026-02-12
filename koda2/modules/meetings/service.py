"""Meeting management service with transcription and minutes generation."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Optional

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.modules.meetings.models import (
    ActionItem, ActionItemStatus, Attendee, Meeting, MeetingSegment, MeetingStatus
)
from koda2.modules.llm import LLMRouter
from koda2.modules.llm.models import ChatMessage, LLMRequest

logger = get_logger(__name__)


class MeetingService:
    """Service for managing meetings, transcription, and action items."""
    
    def __init__(self, llm_router: Optional[LLMRouter] = None) -> None:
        self._settings = get_settings()
        self._llm = llm_router
        self._meetings: dict[str, Meeting] = {}  # In-memory storage for now
        
    def set_llm_router(self, router: LLMRouter) -> None:
        """Set the LLM router for AI features."""
        self._llm = router
        
    async def create_meeting(
        self,
        title: str,
        scheduled_start: dt.datetime,
        scheduled_end: dt.datetime,
        organizer: str,
        description: str = "",
        location: str = "",
        attendees: Optional[list[dict]] = None,
    ) -> Meeting:
        """Create a new meeting."""
        meeting = Meeting(
            title=title,
            description=description,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            location=location,
            organizer=organizer,
            attendees=[Attendee(**a) for a in (attendees or [])],
        )
        self._meetings[meeting.id] = meeting
        logger.info("meeting_created", meeting_id=meeting.id, title=title)
        return meeting
        
    async def transcribe_audio(
        self,
        audio_path: str,
        language: str = "nl",  # Default to Dutch
    ) -> dict[str, Any]:
        """Transcribe audio file using OpenAI Whisper.
        
        Returns dict with:
        - transcript: Full transcript text
        - segments: List of timestamped segments with speaker info
        - language: Detected language
        """
        try:
            import openai
            
            client = openai.AsyncOpenAI(api_key=self._settings.openai_api_key)
            
            with open(audio_path, "rb") as audio_file:
                # Get transcription with timestamps
                transcript = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=language,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
                
            # Parse segments
            segments = []
            for seg in transcript.segments:
                segments.append({
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                })
                
            logger.info("audio_transcribed", 
                       path=audio_path, 
                       duration=len(segments),
                       language=transcript.language)
                       
            return {
                "transcript": transcript.text,
                "segments": segments,
                "language": transcript.language,
                "success": True,
            }
            
        except Exception as e:
            logger.error("transcription_failed", error=str(e))
            return {
                "transcript": "",
                "segments": [],
                "language": "",
                "success": False,
                "error": str(e),
            }
            
    async def process_transcript(
        self,
        meeting: Meeting,
        transcript: str,
        segments: Optional[list[dict]] = None,
    ) -> None:
        """Process transcript to generate summary and action items."""
        if not self._llm:
            logger.warning("no_llm_router_for_processing")
            meeting.transcript = transcript
            return
            
        meeting.transcript = transcript
        
        # Generate summary
        summary_prompt = f"""Generate a concise summary of this meeting transcript.
Focus on key decisions and outcomes.

Transcript:
{transcript[:4000]}  # Limit to avoid token limits

Provide:
1. A 2-3 sentence summary
2. Key decisions made
3. Any unresolved issues

Respond in the same language as the transcript."""

        try:
            summary_result = await self._llm.quick(summary_prompt, complexity="simple")
            meeting.summary = summary_result
        except Exception as e:
            logger.error("summary_generation_failed", error=str(e))
            meeting.summary = "Summary generation failed."
            
        # Extract action items
        action_prompt = f"""Extract all action items from this meeting transcript.
For each action item, identify:
- What needs to be done
- Who is responsible (assignee)
- Due date if mentioned

Transcript:
{transcript[:4000]}

Format as JSON array:
[{{"description": "...", "assignee": "...", "due_date": "YYYY-MM-DD"}}]

If no due date mentioned, use null."""

        try:
            action_result = await self._llm.quick(action_prompt, complexity="standard")
            # Parse JSON response
            import json
            try:
                # Try to extract JSON from response
                if "```json" in action_result:
                    json_str = action_result.split("```json")[1].split("```")[0]
                elif "```" in action_result:
                    json_str = action_result.split("```")[1].split("```")[0]
                else:
                    json_str = action_result
                    
                actions = json.loads(json_str.strip())
                for action in actions:
                    due_date = None
                    if action.get("due_date"):
                        try:
                            due_date = dt.datetime.strptime(action["due_date"], "%Y-%m-%d").date()
                        except ValueError:
                            pass
                            
                    meeting.add_action_item(
                        description=action.get("description", ""),
                        assignee=action.get("assignee", "Unknown"),
                        due_date=due_date,
                        priority="medium",
                    )
            except json.JSONDecodeError:
                logger.warning("action_item_parse_failed", response=action_result)
                
        except Exception as e:
            logger.error("action_extraction_failed", error=str(e))
            
        # Create meeting segments if we have timestamps
        if segments:
            for seg in segments:
                meeting.segments.append(MeetingSegment(
                    start_time=meeting.scheduled_start + dt.timedelta(seconds=seg["start"]),
                    end_time=meeting.scheduled_start + dt.timedelta(seconds=seg["end"]),
                    topic="Discussion",
                    transcript=seg["text"],
                ))
                
        meeting.updated_at = dt.datetime.now(dt.UTC)
        logger.info("transcript_processed", meeting_id=meeting.id, 
                   actions=len(meeting.action_items), summary_len=len(meeting.summary))
                   
    async def generate_minutes_pdf(self, meeting: Meeting) -> str:
        """Generate meeting minutes as PDF."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, ListFlowable, ListItem
        from reportlab.lib import colors
        
        output_dir = Path("data/meetings")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"minutes_{meeting.id}.pdf"
        
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18,
        )
        
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        story.append(Paragraph(f"Meeting Minutes: {meeting.title}", styles["Title"]))
        story.append(Spacer(1, 0.2 * inch))
        
        # Meeting info
        info_data = [
            ["Date:", meeting.scheduled_start.strftime("%Y-%m-%d %H:%M")],
            ["Location:", meeting.location or "Not specified"],
            ["Organizer:", meeting.organizer],
            ["Status:", meeting.status.value.title()],
        ]
        
        info_table = Table(info_data, colWidths=[1.5 * inch, 4 * inch])
        info_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 0.3 * inch))
        
        # Attendees
        if meeting.attendees:
            story.append(Paragraph("Attendees", styles["Heading2"]))
            attendee_list = []
            for att in meeting.attendees:
                status = "✓" if att.attended else "✗"
                attendee_list.append(f"{status} {att.name} ({att.role})")
            for item in attendee_list:
                story.append(Paragraph(f"• {item}", styles["Normal"]))
            story.append(Spacer(1, 0.2 * inch))
        
        # Summary
        if meeting.summary:
            story.append(Paragraph("Summary", styles["Heading2"]))
            story.append(Paragraph(meeting.summary, styles["Normal"]))
            story.append(Spacer(1, 0.2 * inch))
        
        # Decisions
        if meeting.decisions:
            story.append(Paragraph("Decisions Made", styles["Heading2"]))
            for decision in meeting.decisions:
                story.append(Paragraph(f"• {decision}", styles["Normal"]))
            story.append(Spacer(1, 0.2 * inch))
        
        # Action Items
        if meeting.action_items:
            story.append(Paragraph("Action Items", styles["Heading2"]))
            action_data = [["#", "Description", "Assignee", "Due", "Status"]]
            for i, item in enumerate(meeting.action_items, 1):
                due = item.due_date.strftime("%Y-%m-%d") if item.due_date else "-"
                action_data.append([
                    str(i),
                    item.description[:50] + "..." if len(item.description) > 50 else item.description,
                    item.assignee,
                    due,
                    item.status.value.title(),
                ])
                
            action_table = Table(action_data, colWidths=[0.3 * inch, 2.5 * inch, 1 * inch, 0.8 * inch, 0.7 * inch])
            action_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            story.append(action_table)
            
        doc.build(story)
        meeting.minutes_pdf_path = str(output_path)
        logger.info("minutes_pdf_generated", meeting_id=meeting.id, path=str(output_path))
        return str(output_path)
        
    async def send_action_reminders(self) -> list[ActionItem]:
        """Check and send reminders for upcoming/overdue action items."""
        reminders_sent = []
        
        for meeting in self._meetings.values():
            for item in meeting.action_items:
                if item.status == ActionItemStatus.COMPLETED:
                    continue
                    
                # Check if overdue
                if item.check_overdue():
                    reminders_sent.append(item)
                    logger.info("overdue_action_item", item_id=item.id, assignee=item.assignee)
                    continue
                    
                # Check if due soon (within 24 hours)
                if item.due_date:
                    days_until = (item.due_date - dt.date.today()).days
                    if days_until <= 1 and days_until >= 0:
                        reminders_sent.append(item)
                        logger.info("upcoming_action_reminder", 
                                   item_id=item.id, 
                                   assignee=item.assignee,
                                   days=days_until)
                                   
        return reminders_sent
        
    def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        """Get a meeting by ID."""
        return self._meetings.get(meeting_id)
        
    def get_all_meetings(self) -> list[Meeting]:
        """Get all meetings."""
        return list(self._meetings.values())
        
    def get_upcoming_meetings(self, days: int = 7) -> list[Meeting]:
        """Get meetings scheduled in the next N days."""
        cutoff = dt.datetime.now() + dt.timedelta(days=days)
        return [
            m for m in self._meetings.values()
            if m.scheduled_start <= cutoff and m.status != MeetingStatus.CANCELLED
        ]
        
    def get_pending_action_items(self) -> list[ActionItem]:
        """Get all pending action items across all meetings."""
        items = []
        for meeting in self._meetings.values():
            items.extend(meeting.get_pending_actions())
        return items
