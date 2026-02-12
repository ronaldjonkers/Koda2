"""Facility management service for venues and catering."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Optional

from koda2.logging_config import get_logger
from koda2.modules.facilities.models import (
    CateringItem, CateringOrder, CateringType, EquipmentType, 
    RoomBooking, Venue, VenueType
)

logger = get_logger(__name__)


class FacilityService:
    """Service for managing venues, catering, and meeting logistics."""
    
    def __init__(self) -> None:
        self._venues: dict[str, Venue] = {}
        self._bookings: dict[str, RoomBooking] = {}
        self._catering_orders: dict[str, CateringOrder] = {}
        self._init_default_venues()
        
    def _init_default_venues(self) -> None:
        """Initialize with some default internal venues."""
        default_venues = [
            Venue(
                name="Boardroom A",
                venue_type=VenueType.BOARDROOM,
                address="Main Building, Floor 2",
                max_capacity=20,
                seating_capacity=16,
                equipment=[
                    EquipmentType.PROJECTOR,
                    EquipmentType.SCREEN,
                    EquipmentType.VIDEO_CONF,
                    EquipmentType.WHITEBOARD,
                ],
                hourly_rate=Decimal("0"),  # Internal = free
                internal_location=True,
            ),
            Venue(
                name="Meeting Room B",
                venue_type=VenueType.MEETING_ROOM,
                address="Main Building, Floor 1",
                max_capacity=10,
                seating_capacity=8,
                equipment=[
                    EquipmentType.SCREEN,
                    EquipmentType.WHITEBOARD,
                    EquipmentType.VIDEO_CONF,
                ],
                hourly_rate=Decimal("0"),
                internal_location=True,
            ),
            Venue(
                name="Conference Center",
                venue_type=VenueType.EVENT_SPACE,
                address="Annex Building",
                max_capacity=100,
                seating_capacity=80,
                standing_capacity=120,
                equipment=[
                    EquipmentType.PROJECTOR,
                    EquipmentType.SCREEN,
                    EquipmentType.MICROPHONE,
                    EquipmentType.SPEAKERS,
                    EquipmentType.VIDEO_CONF,
                ],
                full_day_rate=Decimal("500"),
                internal_location=True,
            ),
        ]
        for venue in default_venues:
            self._venues[venue.id] = venue
            
    # ── Venue Management ────────────────────────────────────────────
    
    def add_venue(self, venue: Venue) -> str:
        """Add a new venue."""
        self._venues[venue.id] = venue
        logger.info("venue_added", venue_id=venue.id, name=venue.name)
        return venue.id
        
    def get_venue(self, venue_id: str) -> Optional[Venue]:
        """Get venue by ID."""
        return self._venues.get(venue_id)
        
    def list_venues(
        self,
        venue_type: Optional[VenueType] = None,
        min_capacity: int = 0,
        internal_only: bool = False,
    ) -> list[Venue]:
        """List venues with optional filters."""
        venues = list(self._venues.values())
        
        if venue_type:
            venues = [v for v in venues if v.venue_type == venue_type]
        if min_capacity > 0:
            venues = [v for v in venues if v.max_capacity >= min_capacity]
        if internal_only:
            venues = [v for v in venues if v.internal_location]
            
        return sorted(venues, key=lambda v: v.max_capacity)
        
    def find_suitable_venue(
        self,
        num_people: int,
        requirements: list[EquipmentType],
        start_time: dt.datetime,
        end_time: dt.datetime,
    ) -> list[Venue]:
        """Find venues that match requirements."""
        suitable = []
        for venue in self._venues.values():
            if venue.max_capacity >= num_people:
                # Check equipment requirements
                has_equipment = all(eq in venue.equipment for eq in requirements)
                if has_equipment and venue.is_available(start_time, end_time):
                    suitable.append(venue)
        return suitable
        
    # ── Room Booking ───────────────────────────────────────────────
    
    async def book_room(
        self,
        venue_id: str,
        meeting_title: str,
        organizer_name: str,
        organizer_email: str,
        start_time: dt.datetime,
        end_time: dt.datetime,
        expected_attendees: int,
        equipment_needed: Optional[list[EquipmentType]] = None,
    ) -> RoomBooking:
        """Book a room for a meeting."""
        venue = self._venues.get(venue_id)
        if not venue:
            raise ValueError(f"Venue not found: {venue_id}")
            
        if not venue.is_available(start_time, end_time):
            raise ValueError(f"Venue {venue.name} is not available at requested time")
            
        if expected_attendees > venue.max_capacity:
            raise ValueError(
                f"Venue capacity ({venue.max_capacity}) exceeded by "
                f"attendee count ({expected_attendees})"
            )
            
        booking = RoomBooking(
            venue_id=venue_id,
            meeting_title=meeting_title,
            organizer_name=organizer_name,
            organizer_email=organizer_email,
            start_time=start_time,
            end_time=end_time,
            expected_attendees=expected_attendees,
            equipment_needed=equipment_needed or [],
        )
        
        self._bookings[booking.id] = booking
        
        # Calculate cost
        hours = booking.total_duration_hours()
        if venue.hourly_rate:
            cost = venue.hourly_rate * Decimal(str(hours))
        elif venue.half_day_rate and hours <= 4:
            cost = venue.half_day_rate
        elif venue.full_day_rate:
            cost = venue.full_day_rate
        else:
            cost = Decimal("0")
            
        logger.info(
            "room_booked",
            booking_id=booking.id,
            venue=venue.name,
            organizer=organizer_name,
            cost=str(cost),
        )
        
        return booking
        
    def cancel_booking(self, booking_id: str) -> bool:
        """Cancel a room booking."""
        booking = self._bookings.get(booking_id)
        if booking:
            booking.status = "cancelled"
            logger.info("booking_cancelled", booking_id=booking_id)
            return True
        return False
        
    def get_bookings_for_venue(
        self,
        venue_id: str,
        date: Optional[dt.date] = None,
    ) -> list[RoomBooking]:
        """Get bookings for a venue."""
        bookings = [
            b for b in self._bookings.values()
            if b.venue_id == venue_id and b.status != "cancelled"
        ]
        if date:
            bookings = [
                b for b in bookings
                if b.start_time.date() == date
            ]
        return sorted(bookings, key=lambda b: b.start_time)
        
    # ── Catering ───────────────────────────────────────────────────
    
    async def create_catering_order(
        self,
        catering_type: CateringType,
        event_name: str,
        event_date: dt.date,
        delivery_time: dt.time,
        number_of_people: int,
        venue_name: str = "",
        vendor_name: str = "",
    ) -> CateringOrder:
        """Create a new catering order."""
        order = CateringOrder(
            catering_type=catering_type,
            event_name=event_name,
            event_date=event_date,
            delivery_time=delivery_time,
            number_of_people=number_of_people,
            venue_name=venue_name,
            vendor_name=vendor_name,
        )
        
        self._catering_orders[order.id] = order
        logger.info("catering_order_created", order_id=order.id, event=event_name)
        return order
        
    async def suggest_catering_menu(
        self,
        catering_type: CateringType,
        number_of_people: int,
        dietary_requirements: str = "",
        budget_per_person: Optional[Decimal] = None,
    ) -> list[CateringItem]:
        """Suggest a catering menu based on event type."""
        suggestions = []
        
        if catering_type == CateringType.COFFEE_BREAK:
            suggestions = [
                CateringItem(
                    name="Coffee & Tea",
                    description="Freshly brewed coffee and selection of teas",
                    quantity=number_of_people * 2,  # 2 cups per person
                    unit_price=Decimal("2.50"),
                ),
                CateringItem(
                    name="Pastries",
                    description="Assorted pastries and cookies",
                    quantity=number_of_people,
                    unit_price=Decimal("4.50"),
                ),
                CateringItem(
                    name="Fresh Fruit",
                    description="Seasonal fruit platter",
                    quantity=max(1, number_of_people // 10),
                    unit_price=Decimal("25.00"),
                ),
            ]
        elif catering_type == CateringType.LUNCH:
            suggestions = [
                CateringItem(
                    name="Sandwich Platter",
                    description="Assorted sandwiches (meat, fish, vegetarian)",
                    quantity=number_of_people,
                    unit_price=Decimal("12.50"),
                ),
                CateringItem(
                    name="Salad",
                    description="Mixed green salad with dressings",
                    quantity=max(1, number_of_people // 8),
                    unit_price=Decimal("35.00"),
                ),
                CateringItem(
                    name="Soft Drinks",
                    description="Selection of soft drinks and water",
                    quantity=number_of_people,
                    unit_price=Decimal("3.50"),
                ),
            ]
        elif catering_type == CateringType.WORKING_LUNCH:
            suggestions = [
                CateringItem(
                    name="Lunch Box",
                    description="Individual lunch boxes with sandwich, snack, and fruit",
                    quantity=number_of_people,
                    unit_price=Decimal("15.00"),
                ),
                CateringItem(
                    name="Beverages",
                    description="Water, juices, and sodas",
                    quantity=number_of_people,
                    unit_price=Decimal("4.00"),
                ),
            ]
            
        # Mark dietary info
        for item in suggestions:
            if "vegetarian" in item.description.lower():
                item.dietary_info = "vegetarian option available"
                
        return suggestions
        
    def confirm_catering_order(self, order_id: str) -> bool:
        """Confirm a catering order with vendor."""
        order = self._catering_orders.get(order_id)
        if order:
            order.status = "confirmed"
            order.confirmed_at = dt.datetime.now(dt.UTC)
            logger.info("catering_order_confirmed", order_id=order_id)
            return True
        return False
        
    # ── Meeting Logistics ──────────────────────────────────────────
    
    async def setup_meeting(
        self,
        meeting_title: str,
        organizer_name: str,
        organizer_email: str,
        start_time: dt.datetime,
        end_time: dt.datetime,
        num_attendees: int,
        venue_requirements: list[EquipmentType],
        catering_type: Optional[CateringType] = None,
    ) -> dict[str, Any]:
        """Complete meeting setup with venue and catering."""
        # Find and book venue
        venues = self.find_suitable_venue(num_attendees, venue_requirements, start_time, end_time)
        
        if not venues:
            raise ValueError("No suitable venue found for the meeting")
            
        venue = venues[0]  # Take first suitable venue
        
        booking = await self.book_room(
            venue_id=venue.id,
            meeting_title=meeting_title,
            organizer_name=organizer_name,
            organizer_email=organizer_email,
            start_time=start_time,
            end_time=end_time,
            expected_attendees=num_attendees,
            equipment_needed=venue_requirements,
        )
        
        result = {
            "booking": booking,
            "venue": venue,
            "catering": None,
        }
        
        # Setup catering if requested
        if catering_type:
            catering = await self.create_catering_order(
                catering_type=catering_type,
                event_name=meeting_title,
                event_date=start_time.date(),
                delivery_time=(start_time - dt.timedelta(minutes=15)).time(),
                number_of_people=num_attendees,
                venue_name=venue.name,
            )
            
            # Add suggested menu
            menu_items = await self.suggest_catering_menu(
                catering_type=catering_type,
                number_of_people=num_attendees,
            )
            for item in menu_items:
                catering.add_item(item)
                
            result["catering"] = catering
            booking.catering_order_id = catering.id
            
        logger.info(
            "meeting_setup_complete",
            booking_id=booking.id,
            venue=venue.name,
            has_catering=catering_type is not None,
        )
        
        return result
