import { vehicleColor } from '../utils'

/**
 * VehiclePanel — Left fleet status sidebar.
 *
 * Compact row design: each vehicle is a single tight row showing
 * status indicator, name, load bar, and key stats.
 * Clicking a row selects/deselects that vehicle on the map.
 */
export default function VehiclePanel({
  vehicles = [],
  routes = [],
  deliveries = [],
  selectedVehicle,
  onSelect,
  highlightedVehicles = [],
}) {
  const routeMap = Object.fromEntries(routes.map(r => [r.vehicle_id, r]))

  const brokenCount = vehicles.filter(v => v.status === 'BREAKDOWN').length
  const delayedCount = vehicles.filter(v => {
    const route = routeMap[v.id]
    return v.status === 'ACTIVE' && route && !route.feasible
  }).length
  const activeCount = vehicles.filter(v => {
    const route = routeMap[v.id]
    return v.status === 'ACTIVE' && (!route || route.feasible)
  }).length

  return (
    <div className="flex flex-col h-full">
      {/* Panel header */}
      <div className="px-3 py-2 border-b border-gray-800 flex-shrink-0">
        <div className="flex items-center justify-between mb-0.5">
          <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400">
            Fleet Status
          </h2>
          <div className="flex items-center gap-1.5 text-[10px]">
            <span className="flex items-center gap-1 text-emerald-400">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              {activeCount}
            </span>
            {delayedCount > 0 && (
              <span className="flex items-center gap-1 text-amber-400">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                {delayedCount}
              </span>
            )}
            {brokenCount > 0 && (
              <span className="flex items-center gap-1 text-red-400">
                <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                {brokenCount}
              </span>
            )}
          </div>
        </div>
        <div className="text-[9px] text-gray-600">{vehicles.length} vehicles · click to filter map</div>
      </div>

      {/* Vehicle list — compact rows */}
      <div className="flex-1 overflow-y-auto py-1">
        {vehicles.length === 0 ? (
          <div className="p-4 text-center text-gray-500 text-xs">
            <div className="text-xl mb-1">🚗</div>
            <div className="font-semibold text-gray-400">Empty Fleet</div>
            <div className="text-[10px] text-gray-500 mt-1">
              Fresh scenario started. Use &quot;+ Vehicle&quot; in Scenario Builder to deploy delivery vans.
            </div>
          </div>
        ) : (
          vehicles.map((v, i) => {
          const color = vehicleColor(i)
          const route = routeMap[v.id]
          const isSelected = selectedVehicle === v.id
          const isHighlighted = highlightedVehicles.includes(v.id)
          const isBroken = v.status === 'BREAKDOWN'
          const isDelayed = route && !route.feasible && !isBroken
          const loadPct = v.capacity > 0 ? Math.round((v.current_load / v.capacity) * 100) : 0
          const stopCount = route ? route.delivery_ids.length : 0
          const distKm = route ? route.total_distance.toFixed(0) : '—'

          // P1 deliveries
          const p1Count = deliveries.filter(
            d => d.assigned_vehicle === v.id && d.status === 'PENDING' && d.priority === 1
          ).length

          const rowBg = isBroken
            ? 'border-red-800/60 bg-red-950/20'
            : isDelayed
            ? 'border-amber-800/60 bg-amber-950/15'
            : isSelected
            ? 'border-blue-500/70 bg-blue-950/30'
            : isHighlighted
            ? 'border-yellow-500/50 bg-yellow-950/15'
            : 'border-transparent hover:border-gray-700 hover:bg-gray-800/40'

          return (
            <button
              key={v.id}
              onClick={() => onSelect(v.id)}
              className={`w-full text-left px-2.5 py-1.5 border-b border-gray-800/40 transition-all duration-100 cursor-pointer border-l-2 ${rowBg}`}
            >
              {/* Top row: color dot + name + status badge */}
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-1.5 min-w-0">
                  <div
                    className={`w-2 h-2 rounded-full flex-shrink-0 ${isBroken ? 'animate-pulse' : ''}`}
                    style={{ background: isBroken ? '#ef4444' : isDelayed ? '#f59e0b' : color }}
                  />
                  <span className="font-bold text-[11px] text-white truncate">{v.name}</span>
                  {isHighlighted && (
                    <span className="text-[8px] font-black text-yellow-300 flex-shrink-0">⚡</span>
                  )}
                  {p1Count > 0 && (
                    <span className="text-[8px] font-black text-red-400 flex-shrink-0">★{p1Count}</span>
                  )}
                </div>
                <span className={`text-[8px] font-bold px-1 py-0.5 rounded flex-shrink-0 ${
                  isBroken
                    ? 'bg-red-900/70 text-red-300'
                    : isDelayed
                    ? 'bg-amber-900/70 text-amber-300'
                    : 'bg-emerald-900/40 text-emerald-400'
                }`}>
                  {isBroken ? '✕ BRK' : isDelayed ? '⏱ DLY' : 'ACT'}
                </span>
              </div>

              {/* Load bar */}
              <div className="w-full bg-gray-800 rounded-full h-0.5 mb-1 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: `${Math.min(loadPct, 100)}%`,
                    background: isBroken ? '#ef4444' : isDelayed ? '#f59e0b' : loadPct > 85 ? '#f59e0b' : color,
                  }}
                />
              </div>

              {/* Stats row */}
              <div className="flex items-center gap-2 text-[9px] text-gray-500">
                <span>{loadPct}%</span>
                <span className="text-gray-700">·</span>
                <span>{stopCount} stops</span>
                <span className="text-gray-700">·</span>
                <span>{distKm} km</span>
                <span className="text-gray-700">·</span>
                <span>{v.driver_hours_remaining}h</span>
              </div>
            </button>
          )
        }))}
      </div>

      {/* Panel footer */}
      <div className="px-2.5 py-1.5 border-t border-gray-800 flex-shrink-0 bg-gray-950/40">
        <div className="flex items-center justify-between text-[9px] text-gray-600">
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" /> Active</span>
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 bg-amber-500 rounded-full" /> Delayed</span>
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 bg-red-500 rounded-full animate-pulse" /> Broken</span>
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 bg-yellow-400 rounded-full" /> Changed</span>
        </div>
      </div>
    </div>
  )
}
