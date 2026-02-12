"""Facility management data models."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field


class VenueType(StrEnum):
    """Types of venues."""
    CONFERENCE_ROOM = "conference_room"
    MEETING_ROOM = "meeting_room"
    BOARDROOM = "boardroom"
    EVENT_SPACE = "event_space"
    HOTEL = "hotel"
    RESTAURANT = "restaurant"
    EXTERNAL = "external"


class CateringType(StrEnum):
    """Types of catering."""
    COFFEE_BREAK = "coffee_break"
    LUNCH = "lunch"
    DINNER = "dinner"
    RECEPTION = "reception"
    WORKING_LUNCH = "working_lunch"
    BREAKFAST = "breakfast"


class EquipmentType(StrEnum):
    """Meeting equipment types."""
    PROJECTOR = "projector"
    SCREEN = "screen"
    WHITEBOARD = "whiteboard"
    FLIPCHART = "flipchart"
    VIDEO_CONF = "video_conferencing"
    MICROPHONE = "microphone"
    SPEAKERS = "speakers"
    WIFI = "wifi"
    POWER = "power_outlets"


class Venue(BaseModel):
    """Meeting venue/location."""
    id: str = Field(default_factory=lambda: str(id(dt.datetime.now())))
    name: str
    venue_type: VenueType
    address: str
    
    # Capacity
    max_capacity: int
    seating_capacity: int
    standing_capacity: Optional[int] = None
    
    # Contact
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    
    # Features
    equipment: list[EquipmentType] = Field(default_factory=list)
    accessibility: bool = True  # Wheelchair accessible
    parking: bool = False
    catering_allowed: bool = True
    
    # Booking
    availability_calendar: Optional[str] = None  # Link to calendar
    booking_lead_time_hours: int = 24
    cancellation_policy: str = ""  # Hours notice required
    
    # Pricing
    hourly_rate: Optional[Decimal] = None
    half_day_rate: Optional[Decimal] = None
    full_day_rate: Optional[Decimal] = None
    currency: str = "EUR"
    
    # Metadata
    notes: str = ""
    internal_location: bool = True  # Is this our own location?
    
    def is_available(self, start: dt.datetime, end: dt.datetime) -> bool:
        """Check if venue is available for given time slot."""
        # This would check against actual calendar
        return True  # Placeholder


class CateringItem(BaseModel):
    """Individual catering item."""
    name: str
    description: str = ""
    quantity: int
    unit_price: Decimal
    dietary_info: str = ""  # vegetarian, vegan, gluten-free, etc.


class CateringOrder(BaseModel):
    """Catering order for a meeting/event."""
    id: str = Field(default_factory=lambda: str(id(dt.datetime.now())))
    catering_type: CateringType
    
    # Event details
    event_name: str
    event_date: dt.date
    delivery_time: dt.time
    venue_id: Optional[str] = None
    venue_name: str = ""
    
    # Order details
    number_of_people: int
    items: list[CateringItem] = Field(default_factory=list)
    special_requests: str = ""
    dietary_requirements: str = ""
    
    # Pricing
    subtotal: Decimal = Decimal("0")
    delivery_fee: Decimal = Decimal("0")
    vat_rate: Decimal = Decimal("9")  # 9% for food in NL
    total: Decimal = Decimal("0")
    currency: str = "EUR"
    
    # Vendor
    vendor_name: str = ""
    vendor_contact: str = ""
    
    # Status
    status: str = "pending"  # pending, confirmed, delivered, cancelled
    ordered_at: Optional[dt.datetime] = None
    confirmed_at: Optional[dt.datetime] = None
    
    def calculate_totals(self) -> None:
        """Calculate order totals."""
        self.subtotal = sum(
            item.quantity * item.unit_price for item in self.items
        )
        vat = self.subtotal * (self.vat_rate / Decimal("100"))
        self.total = self.subtotal + self.delivery_fee + vat
        
    def add_item(self, item: CateringItem) -> None:
        """Add item to order."""
        self.items.append(item)
        self.calculate_totals()


class RoomBooking(BaseModel):
    """Venue room booking."""
    id: str = Field(default_factory=lambda: str(id(dt.datetime.now())))
    venue_id: str
    meeting_title: str
    
    # Timing
    start_time: dt.datetime
    end_time: dt.datetime
    setup_time_minutes: int = 15
    cleanup_time_minutes: int = 15
    
    # Organizer
    organizer_name: str
    organizer_email: str
    department: Optional[str] = None
    
    # Attendees
    expected_attendees: int
    attendee_list: list[str] = Field(default_factory=list)
    
    # Requirements
    equipment_needed: list[EquipmentType] = Field(default_factory=list)
    catering_order_id: Optional[str] = None
    
    # Status
    status: str = "confirmed"  # confirmed, cancelled, completed
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    
    def total_duration_hours(self) -> float:
        """Calculate total booking duration in hours."""
        duration = self.end_time - self.start_time
        return duration.total_seconds() / 3600
