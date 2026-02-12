"""Travel data models for trips, bookings, and itineraries."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TripType(StrEnum):
    """Types of trips."""
    BUSINESS = "business"
    CONFERENCE = "conference"
    CLIENT_VISIT = "client_visit"
    TRAINING = "training"
    OTHER = "other"


class TransportMode(StrEnum):
    """Modes of transport."""
    FLIGHT = "flight"
    TRAIN = "train"
    CAR = "car"
    TAXI = "taxi"
    RENTAL_CAR = "rental_car"


class BookingStatus(StrEnum):
    """Booking status."""
    QUOTED = "quoted"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class FlightDetails(BaseModel):
    """Flight booking details."""
    airline: str
    flight_number: str
    departure_airport: str
    arrival_airport: str
    departure_time: dt.datetime
    arrival_time: dt.datetime
    seat_class: str = "economy"
    seat_number: Optional[str] = None
    booking_reference: Optional[str] = None
    price: Optional[float] = None
    currency: str = "EUR"
    checked_bags: int = 0
    carry_on: bool = True


class HotelDetails(BaseModel):
    """Hotel booking details."""
    name: str
    address: str
    check_in: dt.date
    check_out: dt.date
    room_type: str = "standard"
    booking_reference: Optional[str] = None
    price_per_night: Optional[float] = None
    total_price: Optional[float] = None
    currency: str = "EUR"
    breakfast_included: bool = False
    cancellation_policy: str = ""
    contact_phone: Optional[str] = None


class TransportDetails(BaseModel):
    """Ground transport details."""
    mode: TransportMode
    company: str
    pickup_location: str
    dropoff_location: str
    pickup_time: Optional[dt.datetime] = None
    booking_reference: Optional[str] = None
    price: Optional[float] = None
    currency: str = "EUR"


class TripSegment(BaseModel):
    """A single segment of a trip."""
    id: str = Field(default_factory=lambda: str(id(dt.datetime.now())))
    type: str  # "flight", "hotel", "transport", "activity"
    start_time: dt.datetime
    end_time: Optional[dt.datetime] = None
    details: FlightDetails | HotelDetails | TransportDetails | dict[str, Any]
    confirmed: bool = False
    notes: str = ""


class Trip(BaseModel):
    """A complete trip with all segments."""
    id: str = Field(default_factory=lambda: str(id(dt.datetime.now())))
    name: str
    trip_type: TripType = TripType.BUSINESS
    destination: str
    start_date: dt.date
    end_date: dt.date
    traveler_name: str
    purpose: str = ""
    segments: list[TripSegment] = Field(default_factory=list)
    status: BookingStatus = BookingStatus.QUOTED
    total_budget: Optional[float] = None
    total_spent: float = 0.0
    currency: str = "EUR"
    notes: str = ""
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    updated_at: Optional[dt.datetime] = None
    
    def add_segment(self, segment: TripSegment) -> None:
        """Add a segment to the trip."""
        self.segments.append(segment)
        self._recalculate_totals()
        self.updated_at = dt.datetime.now(dt.UTC)
    
    def _recalculate_totals(self) -> None:
        """Recalculate total spent."""
        total = 0.0
        for seg in self.segments:
            if isinstance(seg.details, FlightDetails) and seg.details.price:
                total += seg.details.price
            elif isinstance(seg.details, HotelDetails) and seg.details.total_price:
                total += seg.details.total_price
            elif isinstance(seg.details, TransportDetails) and seg.details.price:
                total += seg.details.price
        self.total_spent = total
    
    def get_itinerary(self) -> list[dict[str, Any]]:
        """Generate a chronological itinerary."""
        sorted_segments = sorted(self.segments, key=lambda s: s.start_time)
        return [
            {
                "time": seg.start_time.isoformat(),
                "type": seg.type,
                "description": self._describe_segment(seg),
                "confirmed": seg.confirmed,
            }
            for seg in sorted_segments
        ]
    
    def _describe_segment(self, seg: TripSegment) -> str:
        """Create a human-readable description of a segment."""
        if seg.type == "flight" and isinstance(seg.details, FlightDetails):
            d = seg.details
            return f"Flight {d.flight_number} ({d.airline}): {d.departure_airport} → {d.arrival_airport}"
        elif seg.type == "hotel" and isinstance(seg.details, HotelDetails):
            return f"Stay at {seg.details.name}"
        elif seg.type == "transport" and isinstance(seg.details, TransportDetails):
            return f"{seg.details.mode.value}: {seg.details.pickup_location} → {seg.details.dropoff_location}"
        return f"{seg.type}: {seg.notes}"


class TravelPreferences(BaseModel):
    """User preferences for travel."""
    preferred_airlines: list[str] = Field(default_factory=list)
    preferred_hotel_chains: list[str] = Field(default_factory=list)
    seat_preference: str = "window"  # window, aisle, any
    hotel_rating_min: int = 3
    max_layover_hours: int = 4
    frequent_flyer_numbers: dict[str, str] = Field(default_factory=dict)
    dietary_requirements: str = ""
    passport_number: Optional[str] = None
    passport_expiry: Optional[dt.date] = None
