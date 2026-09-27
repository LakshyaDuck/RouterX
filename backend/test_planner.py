import sys
sys.path.insert(0, '.')
sys.path.insert(0, '..')
from simulation.city_data import generate_city_data
from app.planner import build_initial_routes
from app.models import Vehicle, Delivery, Node, Road

data = generate_city_data()
nodes = [Node(**n) for n in data["nodes"]]
roads = [Road(**r) for r in data["roads"]]
vehicles = [Vehicle(**v) for v in data["vehicles"]]
deliveries = [Delivery(**d) for d in data["deliveries"]]

routes = build_initial_routes(vehicles, deliveries, nodes, roads)
for r in routes:
    print(f"  {r.vehicle_id}: {len(r.delivery_ids)} deliveries, {r.total_distance:.1f} km, {r.total_travel_time:.0f} min, load={r.total_load} kg, feasible={r.feasible}")

assigned = sum(len(r.delivery_ids) for r in routes)
print(f"\nTotal assigned: {assigned}/{len(deliveries)} deliveries")
print("Planner: OK")
