"""
Deterministic Explainability Layer for the Route Optimization Engine.

Generates concise, human-readable explanations based on the actual algorithm decisions
(capacity checks, time window evaluations, lowest-cost insertion, detours, reordering).
No external LLM APIs are used.
"""

from typing import Optional, Sequence


def explain_traffic_update(
    road_id: str,
    from_node: str,
    to_node: str,
    old_mult: float,
    new_mult: float,
    base_time: float,
    affected_vehicles: Sequence[str],
) -> str:
    """Generate human-readable explanation for a traffic congestion event."""
    old_time = base_time * old_mult
    new_time = base_time * new_mult
    time_diff = new_time - old_time
    v_count = len(affected_vehicles)
    v_names = ", ".join(sorted(affected_vehicles)) if affected_vehicles else "None"

    if v_count == 0:
        return (
            f"Road {road_id} ({from_node}->{to_node}) traffic updated from {old_mult:.1f}x to {new_mult:.1f}x "
            f"(segment travel time changed from {old_time:.1f}m to {new_time:.1f}m). "
            f"No active vehicle routes traversed this road, so no fleet routes were modified."
        )

    if new_mult > old_mult:
        return (
            f"Road {road_id} ({from_node}->{to_node}) became congested, increasing estimated travel time "
            f"from {old_time:.1f} minutes to {new_time:.1f} minutes (+{time_diff:.1f} min). "
            f"{v_count} route(s) ({v_names}) were re-evaluated and adjusted to minimize travel time "
            f"while preserving delivery time windows."
        )
    else:
        return (
            f"Traffic cleared on road {road_id} ({from_node}->{to_node}), reducing segment travel time "
            f"from {old_time:.1f}m to {new_time:.1f}m. "
            f"{v_count} route(s) ({v_names}) were recalculated to reflect faster travel speeds."
        )


def explain_vehicle_breakdown(
    broken_vehicle_id: str,
    orphaned_count: int,
    reassigned_deliveries: Sequence[str],
    target_vehicles: Sequence[str],
    unassigned_count: int = 0,
) -> str:
    """Generate human-readable explanation for a vehicle breakdown event."""
    unique_targets = sorted(list(set(target_vehicles)))
    if unique_targets:
        targets_str = ", ".join(unique_targets[:-1]) + (" and " if len(unique_targets) > 1 else "") + unique_targets[-1]
    else:
        targets_str = "other vehicles"

    if orphaned_count == 0:
        return f"Vehicle {broken_vehicle_id} became unavailable. The vehicle had no pending deliveries assigned, so no routes were disrupted."

    if unassigned_count == 0:
        return (
            f"Vehicle {broken_vehicle_id} became unavailable. {orphaned_count} pending deliveries were released "
            f"and reassigned to {targets_str} because they had sufficient remaining capacity and could satisfy the delivery windows."
        )
    else:
        return (
            f"Vehicle {broken_vehicle_id} became unavailable. {orphaned_count} pending deliveries were released; "
            f"{len(reassigned_deliveries)} were reassigned to {targets_str} within capacity and time constraints, "
            f"while {unassigned_count} delivery could not fit into active vehicles and was marked unassigned."
        )


def explain_new_delivery(
    delivery_id: str,
    location: str,
    demand: float,
    priority: int,
    time_window_start: float,
    time_window_end: float,
    assigned_vehicle: Optional[str],
    stop_index: Optional[int] = None,
) -> str:
    """Generate human-readable explanation for a new order insertion."""
    window_str = f"{time_window_start:.0f}-{time_window_end:.0f} min"

    if assigned_vehicle and stop_index is not None:
        p_label = "Priority 1" if priority == 1 else f"Priority {priority}"
        return (
            f"New {p_label.lower()} delivery {delivery_id} ({demand:.0f} kg at {location}) was inserted into "
            f"{assigned_vehicle} at stop #{stop_index + 1} because it was the lowest-cost feasible insertion "
            f"while satisfying the {window_str} delivery window and vehicle payload capacity."
        )
    else:
        return (
            f"New delivery {delivery_id} ({demand:.0f} kg, window {window_str}) was received but could not be feasibly "
            f"inserted into any active vehicle without violating capacity or delivery deadlines. Marked unassigned."
        )


def explain_road_blocked(
    road_id: str,
    from_node: str,
    to_node: str,
    blocked: bool,
    affected_vehicles: Sequence[str],
) -> str:
    """Generate human-readable explanation for a road block/closure."""
    v_names = ", ".join(sorted(affected_vehicles)) if affected_vehicles else "none"

    if blocked:
        if affected_vehicles:
            return (
                f"Road {road_id} ({from_node}->{to_node}) was blocked. Vehicle route(s) {v_names} "
                f"were rerouted through alternative network paths to bypass the closure while maintaining on-time deliveries."
            )
        else:
            return (
                f"Road {road_id} ({from_node}->{to_node}) was blocked. No active routes traversed this segment, "
                f"so no vehicle paths required diversion."
            )
    else:
        return (
            f"Road {road_id} ({from_node}->{to_node}) was reopened. Direct network routing was restored "
            f"for affected vehicles ({v_names})."
        )


def explain_time_window_change(
    delivery_id: str,
    old_start: float,
    old_end: float,
    new_start: float,
    new_end: float,
    vehicle_id: Optional[str],
    stop_reordered: bool = False,
    new_stop_index: Optional[int] = None,
    reassigned_to: Optional[str] = None,
) -> str:
    """Generate human-readable explanation for a time window modification."""
    old_w = f"{old_start:.0f}-{old_end:.0f}m"
    new_w = f"{new_start:.0f}-{new_end:.0f}m"

    if reassigned_to and reassigned_to != vehicle_id:
        return (
            f"Delivery {delivery_id} time window tightened from {old_w} to {new_w}. "
            f"Reassigned from {vehicle_id} to {reassigned_to} because {vehicle_id} could not meet the expedited deadline without causing downstream late deliveries."
        )

    if stop_reordered and new_stop_index is not None and vehicle_id:
        return (
            f"Delivery {delivery_id} time window was tightened from {old_w} to {new_w}. "
            f"{vehicle_id} stop sequence was reordered to stop #{new_stop_index + 1} to satisfy the expedited delivery window without delaying subsequent stops."
        )

    if vehicle_id:
        return (
            f"Delivery {delivery_id} time window updated from {old_w} to {new_w}. "
            f"The existing stop sequence for {vehicle_id} remains feasible and on schedule without requiring route changes."
        )

    return f"Delivery {delivery_id} time window updated to {new_w} (order is currently unassigned)."


def explain_delivery_cancelled(
    delivery_id: str,
    vehicle_id: Optional[str],
    demand: float = 0.0,
    time_saved: float = 0.0,
) -> str:
    """Generate human-readable explanation for a delivery cancellation."""
    if vehicle_id:
        time_text = f" and saving {time_saved:.1f} minutes of drive time" if time_saved > 0 else ""
        return (
            f"Delivery {delivery_id} was cancelled by the customer. "
            f"Vehicle {vehicle_id} route was shortened by removing the stop, freeing {demand:.0f} kg capacity{time_text}."
        )
    return f"Delivery {delivery_id} was cancelled. The order was not assigned to any active vehicle route."
