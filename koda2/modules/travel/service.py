"""Travel Management Service — Flight, hotel, and transport booking."""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional
from dataclasses import dataclass

import httpx
from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.modules.travel.models import (
    FlightDetails, HotelDetails, TransportDetails, TransportMode,
    Trip, TripSegment, TripType, TravelPreferences
)

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """Generic search result container."""
    success: bool
    data: list[Any]
    error: Optional[str] = None
    source: str = ""


class AmadeusClient:
    """Client for Amadeus Flight API."""
    
    BASE_URL = "https://api.amadeus.com/v2"
    TEST_URL = "https://test.api.amadeus.com/v2"
    
    def __init__(self, api_key: str, api_secret: str, test_mode: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.test_mode = test_mode
        self.base_url = self.TEST_URL if test_mode else self.BASE_URL
        self._token: Optional[str] = None
        self._token_expires: Optional[dt.datetime] = None
        
    async def _get_token(self) -> str:
        """Get or refresh OAuth token."""
        if self._token and self._token_expires and dt.datetime.now() < self._token_expires:
            return self._token
            
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/security/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.api_key,
                    "client_secret": self.api_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()
            self._token = data["access_token"]
            expires_in = data.get("expires_in", 1800)
            self._token_expires = dt.datetime.now() + dt.timedelta(seconds=expires_in - 60)
            return self._token
            
    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: dt.date,
        return_date: Optional[dt.date] = None,
        adults: int = 1,
        travel_class: str = "ECONOMY",
        max_results: int = 10,
    ) -> SearchResult:
        """Search for flights using Amadeus API."""
        try:
            token = await self._get_token()
            
            params = {
                "originLocationCode": origin.upper(),
                "destinationLocationCode": destination.upper(),
                "departureDate": departure_date.isoformat(),
                "adults": adults,
                "travelClass": travel_class,
                "max": max_results,
            }
            
            if return_date:
                params["returnDate"] = return_date.isoformat()
                
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/shopping/flight-offers",
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30.0,
                )
                
                if response.status_code == 429:
                    return SearchResult(False, [], "Rate limit exceeded", "amadeus")
                    
                response.raise_for_status()
                data = response.json()
                
                flights = []
                for offer in data.get("data", [])[:max_results]:
                    flight = self._parse_flight_offer(offer)
                    if flight:
                        flights.append(flight)
                        
                return SearchResult(True, flights, source="amadeus")
                
        except httpx.HTTPError as e:
            logger.error("amadeus_flight_search_failed", error=str(e))
            return SearchResult(False, [], str(e), "amadeus")
        except Exception as e:
            logger.error("amadeus_flight_search_error", error=str(e))
            return SearchResult(False, [], str(e), "amadeus")
            
    def _parse_flight_offer(self, offer: dict) -> Optional[FlightDetails]:
        """Parse Amadeus flight offer into FlightDetails."""
        try:
            itineraries = offer.get("itineraries", [])
            if not itineraries:
                return None
                
            # Get first segment
            segments = itineraries[0].get("segments", [])
            if not segments:
                return None
                
            first_segment = segments[0]
            last_segment = segments[-1]
            
            # Parse times
            dep_time = dt.datetime.fromisoformat(first_segment["departure"]["at"].replace("Z", "+00:00"))
            arr_time = dt.datetime.fromisoformat(last_segment["arrival"]["at"].replace("Z", "+00:00"))
            
            # Get price
            price_data = offer.get("price", {})
            price = float(price_data.get("total", 0))
            currency = price_data.get("currency", "EUR")
            
            # Build flight number from carrier + number
            carrier = first_segment.get("carrierCode", "XX")
            flight_num = first_segment.get("number", "000")
            
            return FlightDetails(
                airline=carrier,
                flight_number=f"{carrier}{flight_num}",
                departure_airport=first_segment["departure"]["iataCode"],
                arrival_airport=last_segment["arrival"]["iataCode"],
                departure_time=dep_time,
                arrival_time=arr_time,
                seat_class=offer.get("travelerPricings", [{}])[0].get("fareOption", "ECONOMY"),
                booking_reference=offer.get("id", ""),
                price=price,
                currency=currency,
            )
        except Exception as e:
            logger.error("parse_flight_offer_failed", error=str(e))
            return None


class BookingComClient:
    """Client for Booking.com/Rapid API (hotels)."""
    
    BASE_URL = "https://booking-com.p.rapidapi.com/v1"
    
    def __init__(self, rapidapi_key: str):
        self.api_key = rapidapi_key
        self.headers = {
            "X-RapidAPI-Key": rapidapi_key,
            "X-RapidAPI-Host": "booking-com.p.rapidapi.com",
        }
        
    async def search_hotels(
        self,
        destination: str,
        check_in: dt.date,
        check_out: dt.date,
        adults: int = 1,
        rooms: int = 1,
        max_results: int = 10,
        min_rating: int = 3,
    ) -> SearchResult:
        """Search for hotels."""
        try:
            # First, search for destination ID
            dest_id = await self._get_destination_id(destination)
            if not dest_id:
                return SearchResult(False, [], f"Destination not found: {destination}", "booking.com")
                
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/hotels/search",
                    headers=self.headers,
                    params={
                        "dest_id": dest_id,
                        "dest_type": "city",
                        "checkin_date": check_in.isoformat(),
                        "checkout_date": check_out.isoformat(),
                        "adults_number": adults,
                        "room_number": rooms,
                        "order_by": "popularity",
                        "filter_by_currency": "EUR",
                        "locale": "en-gb",
                    },
                    timeout=30.0,
                )
                
                response.raise_for_status()
                data = response.json()
                
                hotels = []
                for result in data.get("result", [])[:max_results]:
                    hotel = self._parse_hotel_result(result, check_in, check_out)
                    if hotel and hotel.get("review_score", 0) / 10 >= min_rating:
                        hotels.append(HotelDetails(**hotel))
                        
                return SearchResult(True, hotels, source="booking.com")
                
        except Exception as e:
            logger.error("booking_hotel_search_failed", error=str(e))
            return SearchResult(False, [], str(e), "booking.com")
            
    async def _get_destination_id(self, destination: str) -> Optional[str]:
        """Get destination ID from location name."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/hotels/locations",
                    headers=self.headers,
                    params={"name": destination, "locale": "en-gb"},
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()
                
                for item in data:
                    if item.get("dest_type") == "city":
                        return item.get("dest_id")
                return None
        except Exception as e:
            logger.error("get_destination_id_failed", error=str(e))
            return None
            
    def _parse_hotel_result(self, result: dict, check_in: dt.date, check_out: dt.date) -> dict:
        """Parse hotel result into dict for HotelDetails."""
        return {
            "name": result.get("hotel_name", "Unknown Hotel"),
            "address": result.get("address", "Address not available"),
            "check_in": check_in,
            "check_out": check_out,
            "room_type": result.get("accommodation_type_name", "Standard"),
            "price_per_night": float(result.get("min_rate", 0)) or None,
            "total_price": float(result.get("min_rate", 0)) * (check_out - check_in).days if result.get("min_rate") else None,
            "currency": result.get("currency_code", "EUR"),
            "breakfast_included": "breakfast" in result.get("included_breakfast", "").lower(),
        }


class TravelService:
    """Unified travel management service."""
    
    def __init__(self) -> None:
        self._settings = get_settings()
        self._amadeus: Optional[AmadeusClient] = None
        self._booking: Optional[BookingComClient] = None
        self._init_clients()
        
    def _init_clients(self) -> None:
        """Initialize API clients if credentials are available."""
        # Amadeus
        if self._settings.amadeus_api_key and self._settings.amadeus_api_secret:
            self._amadeus = AmadeusClient(
                self._settings.amadeus_api_key,
                self._settings.amadeus_api_secret,
                test_mode=self._settings.amadeus_test_mode,
            )
            logger.info("amadeus_client_initialized")
            
        # Booking.com
        if self._settings.rapidapi_key:
            self._booking = BookingComClient(self._settings.rapidapi_key)
            logger.info("booking_client_initialized")
            
    @property
    def has_flight_provider(self) -> bool:
        return self._amadeus is not None
        
    @property
    def has_hotel_provider(self) -> bool:
        return self._booking is not None
        
    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: dt.date,
        return_date: Optional[dt.date] = None,
        preferences: Optional[TravelPreferences] = None,
    ) -> SearchResult:
        """Search for flights across all providers."""
        if not self.has_flight_provider:
            return SearchResult(
                False, [],
                "No flight provider configured. Set AMADEUS_API_KEY and AMADEUS_API_SECRET in .env",
                ""
            )
            
        prefs = preferences or TravelPreferences()
        
        return await self._amadeus.search_flights(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            adults=1,
            travel_class=prefs.seat_preference.upper() if prefs.seat_preference else "ECONOMY",
        )
        
    async def search_hotels(
        self,
        destination: str,
        check_in: dt.date,
        check_out: dt.date,
        preferences: Optional[TravelPreferences] = None,
    ) -> SearchResult:
        """Search for hotels across all providers."""
        if not self.has_hotel_provider:
            return SearchResult(
                False, [],
                "No hotel provider configured. Set RAPIDAPI_KEY in .env",
                ""
            )
            
        prefs = preferences or TravelPreferences()
        
        return await self._booking.search_hotels(
            destination=destination,
            check_in=check_in,
            check_out=check_out,
            min_rating=prefs.hotel_rating_min,
        )
        
    async def create_trip(
        self,
        name: str,
        destination: str,
        start_date: dt.date,
        end_date: dt.date,
        traveler_name: str,
        trip_type: TripType = TripType.BUSINESS,
        purpose: str = "",
    ) -> Trip:
        """Create a new trip."""
        trip = Trip(
            name=name,
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            traveler_name=traveler_name,
            trip_type=trip_type,
            purpose=purpose,
        )
        logger.info("trip_created", trip_id=trip.id, name=name)
        return trip
        
    async def add_flight_to_trip(
        self,
        trip: Trip,
        flight: FlightDetails,
    ) -> None:
        """Add a flight segment to a trip."""
        segment = TripSegment(
            type="flight",
            start_time=flight.departure_time,
            end_time=flight.arrival_time,
            details=flight,
            confirmed=flight.booking_reference is not None,
        )
        trip.add_segment(segment)
        logger.info("flight_added_to_trip", trip_id=trip.id, flight=flight.flight_number)
        
    async def add_hotel_to_trip(
        self,
        trip: Trip,
        hotel: HotelDetails,
    ) -> None:
        """Add a hotel segment to a trip."""
        segment = TripSegment(
            type="hotel",
            start_time=dt.datetime.combine(hotel.check_in, dt.time(15, 0)),
            end_time=dt.datetime.combine(hotel.check_out, dt.time(11, 0)),
            details=hotel,
            confirmed=hotel.booking_reference is not None,
        )
        trip.add_segment(segment)
        logger.info("hotel_added_to_trip", trip_id=trip.id, hotel=hotel.name)
        
    async def add_transport_to_trip(
        self,
        trip: Trip,
        mode: TransportMode,
        company: str,
        pickup: str,
        dropoff: str,
        pickup_time: dt.datetime,
        price: Optional[float] = None,
    ) -> None:
        """Add ground transport to a trip."""
        transport = TransportDetails(
            mode=mode,
            company=company,
            pickup_location=pickup,
            dropoff_location=dropoff,
            pickup_time=pickup_time,
            price=price,
        )
        segment = TripSegment(
            type="transport",
            start_time=pickup_time,
            details=transport,
        )
        trip.add_segment(segment)
        
    def generate_itinerary_pdf(self, trip: Trip) -> str:
        """Generate a PDF itinerary for the trip."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from pathlib import Path
        
        output_path = Path(f"data/travel/itinerary_{trip.id}.pdf")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        doc = SimpleDocTemplate(str(output_path), pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        story.append(Paragraph(f"Travel Itinerary: {trip.name}", styles["Title"]))
        story.append(Spacer(1, 12))
        
        # Trip details
        story.append(Paragraph(f"<b>Destination:</b> {trip.destination}", styles["Normal"]))
        story.append(Paragraph(f"<b>Dates:</b> {trip.start_date} to {trip.end_date}", styles["Normal"]))
        story.append(Paragraph(f"<b>Traveler:</b> {trip.traveler_name}", styles["Normal"]))
        if trip.purpose:
            story.append(Paragraph(f"<b>Purpose:</b> {trip.purpose}", styles["Normal"]))
        story.append(Spacer(1, 20))
        
        # Itinerary table
        itinerary = trip.get_itinerary()
        if itinerary:
            data = [["Time", "Type", "Description"]]
            for item in itinerary:
                data.append([
                    item["time"][:16].replace("T", " "),
                    item["type"].title(),
                    item["description"],
                ])
                
            table = Table(data, colWidths=[120, 80, 300])
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 12),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]))
            story.append(table)
            
        doc.build(story)
        logger.info("itinerary_pdf_generated", path=str(output_path))
        return str(output_path)
