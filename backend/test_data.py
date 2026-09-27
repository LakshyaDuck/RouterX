import sys
sys.path.insert(0, '.')
sys.path.insert(0, '..')
from simulation.city_data import generate_city_data
data = generate_city_data()
print("Nodes:", len(data["nodes"]))
print("Roads:", len(data["roads"]))
print("Vehicles:", len(data["vehicles"]))
print("Deliveries:", len(data["deliveries"]))
print("City data generation: OK")
