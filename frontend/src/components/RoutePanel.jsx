/**
 * RoutePanel — shows route details per vehicle.
 */
export default function RoutePanel({ routes = [], vehicles = [], deliveries = [], selectedVehicle }) {
  const vehicleMap = Object.fromEntries(vehicles.map(v => [v.id, v]))
  const deliveryMap = Object.fromEntries(deliveries.map(d => [d.id, d]))

  const displayRoutes = selectedVehicle
    ? routes.filter(r => r.vehicle_id === selectedVehicle)
    : routes

  return (
    <div className="flex flex-col gap-2 h-full">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400">
        Routes {selectedVehicle ? `(${selectedVehicle})` : `(${routes.length})`}
      </h2>

      <div className="overflow-y-auto flex-1 sidebar-panel flex flex-col gap-2">
        {displayRoutes.map(route => {
          const v = vehicleMap[route.vehicle_id]
          return (
            <div key={route.vehicle_id} className="bg-gray-800 rounded-lg p-3 border border-gray-700">
              <div className="flex justify-between mb-2">
                <span className="text-sm font-semibold text-white">{v?.name || route.vehicle_id}</span>
                <span className={`text-xs px-1.5 py-0.5 rounded ${route.feasible ? 'bg-green-800 text-green-300' : 'bg-red-800 text-red-300'}`}>
                  {route.feasible ? 'Feasible' : 'Infeasible'}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-2 text-xs mb-2">
                <div className="text-center bg-gray-700 rounded p-1">
                  <div className="text-white font-semibold">{route.delivery_ids.length}</div>
                  <div className="text-gray-400">Stops</div>
                </div>
                <div className="text-center bg-gray-700 rounded p-1">
                  <div className="text-white font-semibold">{route.total_distance.toFixed(1)}</div>
                  <div className="text-gray-400">km</div>
                </div>
                <div className="text-center bg-gray-700 rounded p-1">
                  <div className="text-white font-semibold">{Math.round(route.total_travel_time)}</div>
                  <div className="text-gray-400">min</div>
                </div>
              </div>

              {/* Delivery sequence */}
              {route.delivery_ids.length > 0 && (
                <div className="text-xs">
                  <div className="text-gray-500 mb-1">Sequence:</div>
                  <div className="flex flex-wrap gap-1">
                    {route.delivery_ids.map((did, idx) => {
                      const d = deliveryMap[did]
                      const pColor = d?.priority === 1 ? 'bg-red-900 text-red-300' :
                                     d?.priority === 2 ? 'bg-yellow-900 text-yellow-300' :
                                     'bg-green-900 text-green-300'
                      return (
                        <span key={did} className={`px-1.5 py-0.5 rounded font-mono ${pColor}`}>
                          {idx + 1}. {did}
                        </span>
                      )
                    })}
                  </div>
                </div>
              )}
              {route.delivery_ids.length === 0 && (
                <div className="text-xs text-gray-500">No deliveries assigned</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
