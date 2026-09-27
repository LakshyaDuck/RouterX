"""
Proxy module exposing demo scenario from simulation.demo_scenario
or directly providing the deterministic demo scenario.
"""

from simulation.demo_scenario import (
    get_demo_scenario,
    build_demo_nodes,
    build_demo_roads,
    build_demo_vehicles,
    build_demo_deliveries,
    DEMO_EVENTS_SPEC,
    DEMO_NODES_DATA,
    DEMO_ROADS_DATA,
    DEMO_VEHICLES_DATA,
    DEMO_DELIVERIES_DATA,
)
