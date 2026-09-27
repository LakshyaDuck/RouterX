"""
Data models for the Delivery Control Tower.
Uses SQLModel ORM for PostgreSQL persistence and FastAPI validation.
"""

from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELAYED = "DELAYED"
    BREAKDOWN = "BREAKDOWN"
    NOTACTIVATED = "NOTACTIVATED"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EventType(str, Enum):
    TRAFFIC_UPDATE = "TRAFFIC_UPDATE"
    VEHICLE_BREAKDOWN = "VEHICLE_BREAKDOWN"
    NEW_DELIVERY = "NEW_DELIVERY"
    DELIVERY_CANCELLED = "DELIVERY_CANCELLED"
    ROAD_BLOCKED = "ROAD_BLOCKED"
    TIME_WINDOW_CHANGE = "TIME_WINDOW_CHANGE"


# ---------------------------------------------------------------------------
# Core entity models (SQLModel with table=True for PostgreSQL)
# ---------------------------------------------------------------------------

class Vehicle(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    capacity: float                  # max load in kg
    current_location: str            # node id
    driver_hours_remaining: float    # hours left in shift
    status: VehicleStatus = VehicleStatus.ACTIVE
    current_load: float = 0.0


class Delivery(SQLModel, table=True):
    id: str = Field(primary_key=True)
    location: str                    # node id
    demand: float = 0.0              # weight in kg
    #weight: Optional[float] = None   # alias for compatibility
    priority: int                    # 1 = highest, 3 = lowest
    time_window_start: float         # minutes from simulation start
    time_window_end: float
    status: DeliveryStatus = DeliveryStatus.PENDING
    assigned_vehicle: Optional[str] = None


class Node(SQLModel, table=True): #Location
    id: str = Field(primary_key=True)
    label: str
    lat: float
    lon: float
    is_depot: bool = False #warehouse or not


class Road(SQLModel, table=True):
    id: str = Field(primary_key=True)
    from_node: str
    to_node: str
    distance: float                  # km
    base_time: float                 # minutes
    traffic_multiplier: float = 1.0  # > 1 means slower
    blocked: bool = False


class Route(SQLModel, table=True): #Revisit
    vehicle_id: str = Field(primary_key=True)
    delivery_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    total_distance: float
    total_travel_time: float
    total_load: float
    feasible: bool = True


class Event(SQLModel, table=True):
    id: str = Field(primary_key=True)
    event_type: EventType
    timestamp: float                 # simulation time in minutes
    affected_entity_id: str
    parameters: dict = Field(default_factory=dict, sa_column=Column(JSON)) # flexible payload per event type #Revisit


class SimulationMetadata(SQLModel, table=True):
    id: str = Field(default="global", primary_key=True)
    simulation_time: float = 0.0                     # elapsed simulation minutes
    simulation_start_time: str = Field(default="")   # ISO 8601 string of simulation start datetime
    is_running: bool = False
    speed_multiplier: float = 1.0


# ---------------------------------------------------------------------------
# API response wrappers (SQLModel schemas)
# ---------------------------------------------------------------------------

class FleetState(SQLModel):
    vehicles: list[Vehicle]
    deliveries: list[Delivery]
    nodes: list[Node]
    roads: list[Road]
    routes: list[Route]
    events: list[Event]
    simulation_time: float = 0.0                     # current sim clock in minutes
    simulation_start_time: Optional[str] = None      # ISO 8601 string
    current_simulation_time: Optional[str] = None    # ISO 8601 string of current sim datetime
    is_running: Optional[bool] = False
    speed_multiplier: Optional[float] = 1.0
    metrics: Optional[dict] = Field(default_factory=dict)

