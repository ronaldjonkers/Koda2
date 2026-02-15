"""Proactive assistant service - monitors context and generates alerts."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Optional, Any

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.modules.proactive.models import (
    AlertType,
    AlertPriority,
    ProactiveAlert,
    UserContext,
)

logger = get_logger(__name__)


class ProactiveService:
    """Proactive assistant that monitors user context and generates alerts.
    
    This service continuously monitors:
    - Calendar events (upcoming, conflicts, preparation time)
    - Location and traffic (time to next meeting)
    - Emails (urgent unread messages)
    - Tasks (due dates)
    - Weather (affecting outdoor plans)
    - Contacts (birthdays, important dates)
    
    And generates actionable alerts sent via WhatsApp or other channels.
    """
    
    def __init__(
        self,
        calendar_service: Optional[Any] = None,
        email_service: Optional[Any] = None,
        contact_service: Optional[Any] = None,
        memory_service: Optional[Any] = None,
        whatsapp_bot: Optional[Any] = None,
        notification_channel: str = "whatsapp",
    ) -> None:
        self._calendar = calendar_service
        self._email = email_service
        self._contacts = contact_service
        self._memory = memory_service
        self._whatsapp = whatsapp_bot
        self._notification_channel = notification_channel
        
        self._alerts: dict[str, ProactiveAlert] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._check_interval = 60  # seconds
        
        # User context cache
        self._context: Optional[UserContext] = None
        self._last_alert_times: dict[str, dt.datetime] = {}  # Track when alerts were last sent
        
        # Alert cooldowns (prevent spam)
        self._cooldowns: dict[AlertType, int] = {
            AlertType.MEETING_SOON: 300,  # 5 minutes
            AlertType.TRAFFIC_WARNING: 600,  # 10 minutes
            AlertType.WEATHER_WARNING: 3600,  # 1 hour
            AlertType.EMAIL_URGENT: 300,
        }
    
    async def start(self) -> None:
        """Start the proactive monitoring loop."""
        if self._is_running:
            return
        
        self._is_running = True
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
        logger.info("proactive_monitoring_started")
    
    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self._is_running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("proactive_monitoring_stopped")
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        while self._is_running:
            try:
                await self._check_and_alert()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("proactive_monitor_error", error=str(exc))
                await asyncio.sleep(self._check_interval)
    
    async def _check_and_alert(self) -> None:
        """Check context and generate alerts."""
        # Build current context
        context = await self._build_context()
        self._context = context
        
        # Generate alerts based on context
        new_alerts: list[ProactiveAlert] = []
        
        new_alerts.extend(await self._check_meeting_alerts(context))
        new_alerts.extend(await self._check_email_alerts(context))
        new_alerts.extend(await self._check_task_alerts(context))
        new_alerts.extend(await self._check_contact_alerts(context))
        new_alerts.extend(await self._check_suggestions(context))
        
        # Filter out cooldown alerts
        filtered_alerts = self._apply_cooldowns(new_alerts)
        
        # Store and send alerts
        for alert in filtered_alerts:
            self._alerts[alert.id] = alert
            await self._send_alert(alert)
    
    async def _build_context(self) -> UserContext:
        """Build current user context from all sources."""
        context = UserContext(
            current_time=dt.datetime.now(dt.UTC),
        )
        
        # Calendar context
        if self._calendar:
            try:
                now = dt.datetime.now(dt.UTC)
                today_end = now.replace(hour=23, minute=59, second=59)
                
                events = await self._calendar.list_events(
                    start=now,
                    end=today_end,
                )
                
                context.meetings_today = events
                
                # Find current and next meeting
                for event in events:
                    ev_start = event.start
                    ev_end = event.end
                    
                    if ev_start <= now <= ev_end:
                        context.current_meeting = event
                    elif ev_start > now and not context.next_meeting:
                        context.next_meeting = event
                        
            except Exception as exc:
                logger.warning("context_calendar_failed", error=str(exc))
        
        # Email context
        if self._email:
            try:
                unread = await self._email.fetch_all_emails(unread_only=True, limit=20)
                context.unread_emails_count = len(unread)
                
                # Find urgent emails
                for email in unread:
                    if self._is_urgent_email(email):
                        context.unread_urgent_emails.append({
                            "id": email.provider_id,
                            "subject": email.subject,
                            "sender": email.sender,
                        })
                        
            except Exception as exc:
                logger.warning("context_email_failed", error=str(exc))
        
        # Contact context (birthdays, etc.)
        if self._contacts:
            try:
                # This would fetch contact context
                pass
            except Exception as exc:
                logger.warning("context_contacts_failed", error=str(exc))
        
        return context
    
    def _is_urgent_email(self, email) -> bool:
        """Determine if an email is urgent."""
        urgent_keywords = [
            "urgent", "asap", "immediately", "deadline", "emergency",
            "action required", "please respond", "time-sensitive",
        ]
        
        subject_lower = email.subject.lower()
        if any(kw in subject_lower for kw in urgent_keywords):
            return True
        
        # Check sender importance (could be enhanced with contact importance scores)
        important_senders = ["ceo", "president", "director", "manager"]
        if any(title in email.sender.lower() for title in important_senders):
            return True
        
        return False
    
    async def _check_meeting_alerts(self, context: UserContext) -> list[ProactiveAlert]:
        """Check for meeting-related alerts."""
        alerts = []
        now = context.current_time
        
        if context.next_meeting:
            meeting = context.next_meeting
            start_time = meeting.get("start", now)
            time_until = (start_time - now).total_seconds() / 60  # minutes
            
            # Meeting soon (15 min warning)
            if 10 <= time_until <= 20:
                # Check if we already sent this alert
                alert_key = f"meeting_soon_{meeting.get('id', '')}"
                if not self._was_recently_alerted(alert_key):
                    alerts.append(ProactiveAlert(
                        id=str(uuid.uuid4()),
                        type=AlertType.MEETING_SOON,
                        priority=AlertPriority.HIGH,
                        title=f"📅 Meeting in {int(time_until)} minutes",
                        message=f"'{meeting.get('title', 'Meeting')}' starts at {start_time.strftime('%H:%M')}",
                        related_event_id=meeting.get("id"),
                        valid_until=start_time,
                        suggested_actions=self._generate_meeting_actions(meeting, context),
                        context={"minutes_until": time_until, "location": meeting.get("location")},
                    ))
                    self._last_alert_times[alert_key] = now
            
            # Preparation needed (30 min before)
            if 25 <= time_until <= 35:
                prep_key = f"prep_needed_{meeting.get('id', '')}"
                if not self._was_recently_alerted(prep_key):
                    # Check if prep materials exist
                    prep_suggestions = await self._suggest_prep_materials(meeting)
                    if prep_suggestions:
                        alerts.append(ProactiveAlert(
                            id=str(uuid.uuid4()),
                            type=AlertType.PREPARATION_NEEDED,
                            priority=AlertPriority.MEDIUM,
                            title=f"📝 Prep for: {meeting.get('title', 'Meeting')}",
                            message=prep_suggestions,
                            related_event_id=meeting.get("id"),
                            suggested_actions=[
                                {"label": "View documents", "action": "search_files", "params": {"query": meeting.get("title", "")}},
                                {"label": "Send prep message", "action": "draft_message", "params": {"context": "meeting_prep"}},
                            ],
                        ))
                        self._last_alert_times[prep_key] = now
            
            # Traffic warning (if location specified)
            if meeting.get("location") and 20 <= time_until <= 40:
                # Simple heuristic - assume 30 min buffer needed for offsite
                location = meeting.get("location", "").lower()
                if any(word in location for word in ["client", "office", "meeting room", "conference"]):
                    traffic_key = f"traffic_{meeting.get('id', '')}"
                    if not self._was_recently_alerted(traffic_key):
                        alerts.append(ProactiveAlert(
                            id=str(uuid.uuid4()),
                            type=AlertType.TRAFFIC_WARNING,
                            priority=AlertPriority.MEDIUM,
                            title="🚗 Leave soon for meeting",
                            message=f"Allow extra time to get to: {meeting.get('location')}",
                            related_event_id=meeting.get("id"),
                            suggested_actions=[
                                {"label": "Open Maps", "action": "open_maps", "params": {"destination": meeting.get("location")}},
                            ],
                        ))
                        self._last_alert_times[traffic_key] = now
        
        # Check for meeting conflicts
        if len(context.meetings_today) >= 2:
            for i, m1 in enumerate(context.meetings_today):
                for m2 in context.meetings_today[i+1:]:
                    if self._meetings_overlap(m1, m2):
                        alerts.append(ProactiveAlert(
                            id=str(uuid.uuid4()),
                            type=AlertType.MEETING_CONFLICT,
                            priority=AlertPriority.CRITICAL,
                            title="⚠️ Meeting Conflict",
                            message=f"'{m1.get('title')}' overlaps with '{m2.get('title')}'",
                            related_event_id=m1.get("id"),
                            suggested_actions=[
                                {"label": "Reschedule", "action": "suggest_reschedule", "params": {"events": [m1.get("id"), m2.get("id")]}},
                            ],
                        ))
        
        return alerts
    
    def _meetings_overlap(self, m1: dict, m2: dict) -> bool:
        """Check if two meetings overlap."""
        s1, e1 = m1.get("start"), m1.get("end")
        s2, e2 = m2.get("start"), m2.get("end")
        
        if not all([s1, e1, s2, e2]):
            return False
        
        return s1 < e2 and s2 < e1
    
    async def _suggest_prep_materials(self, meeting: dict) -> str:
        """Suggest preparation materials for a meeting."""
        title = meeting.get("title", "")
        attendees = meeting.get("attendees", [])
        
        suggestions = []
        
        # Check for previous emails about this topic
        if self._memory:
            try:
                # Search memory for related context
                results = self._memory.recall(f"meeting {title}", n=3)
                if results:
                    suggestions.append("Found previous discussions about this topic in your memory.")
            except Exception:
                pass
        
        # Suggest based on attendees
        if attendees:
            suggestions.append(f"Meeting with: {', '.join(attendees[:3])}")
        
        return " ".join(suggestions) if suggestions else "Review the meeting agenda and any attached documents."
    
    def _generate_meeting_actions(self, meeting: dict, context: UserContext) -> list[dict]:
        """Generate suggested actions for a meeting alert."""
        actions = []
        
        # Join action (for video calls)
        location = meeting.get("location", "")
        if any(word in location.lower() for word in ["zoom", "teams", "meet", "webex"]):
            actions.append({
                "label": "Join meeting",
                "action": "open_url",
                "params": {"url": location},
            })
        
        # Quick message action
        attendees = meeting.get("attendees", [])
        if attendees:
            actions.append({
                "label": "Message attendees",
                "action": "draft_message",
                "params": {"recipients": attendees, "context": "running_late"},
            })
        
        # Reschedule action if tight schedule
        if context.current_meeting:
            actions.append({
                "label": "Reschedule",
                "action": "suggest_reschedule",
                "params": {"event_id": meeting.get("id")},
            })
        
        return actions
    
    async def _check_email_alerts(self, context: UserContext) -> list[ProactiveAlert]:
        """Check for email-related alerts."""
        alerts = []
        
        # Urgent unread emails
        if context.unread_urgent_emails:
            urgent = context.unread_urgent_emails[:3]  # Top 3
            email_key = f"urgent_emails_{len(urgent)}"
            
            if not self._was_recently_alerted(email_key):
                subjects = [e.get("subject", "No subject") for e in urgent]
                alerts.append(ProactiveAlert(
                    id=str(uuid.uuid4()),
                    type=AlertType.EMAIL_URGENT,
                    priority=AlertPriority.HIGH,
                    title=f"📧 {len(urgent)} urgent email(s)",
                    message="\n".join(f"• {s}" for s in subjects),
                    suggested_actions=[
                        {"label": "Read now", "action": "open_email"},
                        {"label": "Quick reply", "action": "draft_replies", "params": {"emails": urgent}},
                    ],
                ))
                self._last_alert_times[email_key] = context.current_time
        
        return alerts
    
    async def _check_task_alerts(self, context: UserContext) -> list[ProactiveAlert]:
        """Check for task-related alerts."""
        # This would integrate with a task management system
        return []
    
    async def _check_contact_alerts(self, context: UserContext) -> list[ProactiveAlert]:
        """Check for contact-related alerts (birthdays, etc.)."""
        alerts = []
        
        if self._contacts:
            try:
                # Check for birthdays today
                today = context.current_time.date()
                # This would check the contact service for birthdays
                # Implementation depends on contact service capabilities
            except Exception:
                pass
        
        return alerts
    
    async def _check_suggestions(self, context: UserContext) -> list[ProactiveAlert]:
        """Generate helpful suggestions based on context."""
        alerts = []
        
        # Suggest follow-up after meeting
        if context.current_meeting:
            meeting_end = context.current_meeting.get("end")
            if meeting_end:
                minutes_since_end = (context.current_time - meeting_end).total_seconds() / 60
                if 5 <= minutes_since_end <= 30:
                    meeting_id = context.current_meeting.get("id", "")
                    followup_key = f"followup_{meeting_id}"
                    
                    if not self._was_recently_alerted(followup_key):
                        alerts.append(ProactiveAlert(
                            id=str(uuid.uuid4()),
                            type=AlertType.FOLLOW_UP_NEEDED,
                            priority=AlertPriority.LOW,
                            title="🤔 Follow-up from meeting?",
                            message=f"Would you like to send a follow-up message about '{context.current_meeting.get('title')}'?",
                            related_event_id=meeting_id,
                            suggested_actions=[
                                {"label": "Send thanks", "action": "draft_followup", "params": {"meeting": context.current_meeting, "type": "thanks"}},
                                {"label": "Send summary", "action": "draft_followup", "params": {"meeting": context.current_meeting, "type": "summary"}},
                            ],
                        ))
                        self._last_alert_times[followup_key] = context.current_time
        
        return alerts
    
    def _was_recently_alerted(self, key: str) -> bool:
        """Check if an alert was sent recently (cooldown)."""
        if key not in self._last_alert_times:
            return False
        
        last_time = self._last_alert_times[key]
        elapsed = (dt.datetime.now(dt.UTC) - last_time).total_seconds()
        
        # Default 5 minute cooldown
        return elapsed < 300
    
    def _apply_cooldowns(self, alerts: list[ProactiveAlert]) -> list[ProactiveAlert]:
        """Filter alerts based on type-specific cooldowns."""
        filtered = []
        now = dt.datetime.now(dt.UTC)
        
        for alert in alerts:
            cooldown = self._cooldowns.get(alert.type, 300)
            
            # Check if similar alert was sent recently
            similar_key = f"{alert.type.value}_{alert.related_event_id or ''}"
            if similar_key in self._last_alert_times:
                elapsed = (now - self._last_alert_times[similar_key]).total_seconds()
                if elapsed < cooldown:
                    continue
            
            filtered.append(alert)
            self._last_alert_times[similar_key] = now
        
        return filtered
    
    async def _send_alert(self, alert: ProactiveAlert) -> None:
        """Send alert to user via configured channel."""
        if self._notification_channel == "whatsapp" and self._whatsapp:
            try:
                # Get user's own number for self-messages
                status = await self._whatsapp.get_status()
                if status.get("info"):
                    my_number = status["info"].get("phone")
                    if my_number:
                        message = self._format_alert_message(alert)
                        await self._whatsapp.send_message(my_number, message)
                        logger.info("proactive_alert_sent", alert_id=alert.id, type=alert.type.value)
            except Exception as exc:
                logger.error("proactive_alert_send_failed", error=str(exc))
    
    def _format_alert_message(self, alert: ProactiveAlert) -> str:
        """Format alert for WhatsApp message."""
        lines = [
            f"*{alert.title}*",
            "",
            alert.message,
        ]
        
        if alert.suggested_actions:
            lines.append("")
            lines.append("*Suggested actions:*")
            for i, action in enumerate(alert.suggested_actions, 1):
                lines.append(f"{i}. {action.get('label', 'Action')}")
        
        return "\n".join(lines)
    
    # ── Public API ────────────────────────────────────────────────────
    
    async def get_active_alerts(self) -> list[ProactiveAlert]:
        """Get all active (non-dismissed) alerts."""
        return [a for a in self._alerts.values() if a.is_active()]
    
    async def dismiss_alert(self, alert_id: str) -> bool:
        """Dismiss an alert."""
        if alert_id in self._alerts:
            self._alerts[alert_id].dismiss()
            return True
        return False
    
    async def force_check(self) -> list[ProactiveAlert]:
        """Manually trigger a check and return new alerts."""
        await self._check_and_alert()
        return await self.get_active_alerts()
    
    async def get_user_context(self) -> Optional[UserContext]:
        """Get current user context."""
        return self._context
    
    def set_check_interval(self, seconds: int) -> None:
        """Change the monitoring interval."""
        self._check_interval = max(10, seconds)  # Minimum 10 seconds
