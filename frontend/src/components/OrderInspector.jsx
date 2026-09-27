import { useState, useMemo } from 'react'
import { vehicleColor } from '../utils'
import { computeRouteTimelineMap } from '../utils/routeTiming'
import { formatSimulationTime, formatTimeWindow, formatDuration } from '../utils/time'

/**
 * OrderInspector — Authoritative Order-Level Information Panel for RouterX.
 *
 * Provides progressive disclosure for delivery orders:
 * - Searchable, compact Order List (ID, Priority, Assigned Van, Status)
 * - Deep-dive Detail Inspector for currently selected order
 * - Authoritative arrival time (ETA), feasibility, route stop ordinal & sequence
 * - Automatically updates dynamically on any fleet/scenario change
 */
export default function OrderInspector({
  state,
  timelineMap: suppliedTimelineMap,
  etaChangesByDelivery = {},
  selectedDeliveryId,
  onSelectDelivery,
  onSelectVehicle,
  onOpenTimeWindowForm,
  onOpenCancelForm,
}) {
  const { deliveries = [], vehicles = [], routes = [], nodes = [], roads = [] } = state || {}
  const [searchQuery, setSearchQuery] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('ALL') // 'ALL' | 1 | 2 | 3

  const vehicleMap = useMemo(() => Object.fromEntries(vehicles.map((v, i) => [v.id, { ...v, colorIndex: i }])), [vehicles])
  const nodeMap = useMemo(() => Object.fromEntries(nodes.map(n => [n.id, n])), [nodes])

  // Authoritative timeline & timing calculations
  const computedTimelineMap = useMemo(() => {
    return computeRouteTimelineMap(routes, vehicles, deliveries, nodes, roads)
  }, [routes, vehicles, deliveries, nodes, roads])
  const timelineMap = suppliedTimelineMap || computedTimelineMap

  const selectedDelivery = useMemo(() => {
    return deliveries.find(d => d.id === selectedDeliveryId) || null
  }, [deliveries, selectedDeliveryId])

  const selectedTimeline = useMemo(() => {
    if (!selectedDeliveryId) return null
    return timelineMap[selectedDeliveryId] || null
  }, [timelineMap, selectedDeliveryId])

  // Filtered orders for compact list
  const filteredDeliveries = useMemo(() => {
    return deliveries.filter(d => {
      const matchSearch =
        d.id.toLowerCase().includes(searchQuery.toLowerCase().trim()) ||
        (nodeMap[d.location]?.label || '').toLowerCase().includes(searchQuery.toLowerCase().trim()) ||
        (d.assigned_vehicle || '').toLowerCase().includes(searchQuery.toLowerCase().trim())

      const matchPriority = priorityFilter === 'ALL' || d.priority === Number(priorityFilter)
      return matchSearch && matchPriority
    })
  }, [deliveries, searchQuery, priorityFilter, nodeMap])

  const assignedVehicle = selectedDelivery?.assigned_vehicle
    ? vehicleMap[selectedDelivery.assigned_vehicle]
    : null

  const etaChange = selectedDeliveryId ? etaChangesByDelivery[selectedDeliveryId] : null
  const selectedEtaAvailable =
    ['PENDING', 'IN_PROGRESS'].includes(selectedDelivery?.status) &&
    Number.isFinite(selectedTimeline?.arrivalTime)

  const vehicleRouteColor = assignedVehicle
    ? vehicleColor(assignedVehicle.colorIndex)
    : '#94a3b8'

  return (
    <div className="flex-1 flex flex-col h-full min-h-0 bg-[#0a0e17] text-gray-100 select-none overflow-hidden divide-y divide-gray-800/80">
      {/* 1. TOP HEADER */}
      <div className="px-3 py-2 bg-gray-950/90 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-base">📦</span>
          <div>
            <div className="text-xs font-black uppercase tracking-wider text-white">Order Inspector</div>
            <div className="text-[10px] text-gray-400">
              {deliveries.length} total · {deliveries.filter(d => d.status === 'PENDING').length} pending{deliveries.filter(d => d.status === 'IN_PROGRESS').length > 0 ? ` · ${deliveries.filter(d => d.status === 'IN_PROGRESS').length} in transit` : ''}{deliveries.filter(d => d.status === 'DELIVERED').length > 0 ? ` · ${deliveries.filter(d => d.status === 'DELIVERED').length} delivered` : ''}{deliveries.filter(d => d.status === 'CANCELLED').length > 0 ? ` · ${deliveries.filter(d => d.status === 'CANCELLED').length} cancelled` : ''}
            </div>
          </div>
        </div>

        {selectedDelivery && (
          <button
            onClick={() => onSelectDelivery?.(null)}
            className="text-[10px] text-gray-400 hover:text-white px-2 py-0.5 rounded bg-gray-900 border border-gray-800 hover:border-gray-700 transition-colors cursor-pointer"
            title="Deselect order"
          >
            Clear Selection
          </button>
        )}
      </div>

      {/* 2. SELECTED ORDER DETAIL CARD (When an order is selected) */}
      {selectedDelivery ? (
        <div className="p-2.5 bg-gray-900/40 overflow-y-auto flex-shrink min-h-0 space-y-2 max-h-[35%] border-b border-gray-800">
          {/* Order Header / Title Row */}
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono font-black text-sm text-cyan-300">
                  {selectedDelivery.id.toUpperCase()}
                </span>
                <span
                  className={`text-[9.5px] font-black px-1.5 py-0.5 rounded uppercase tracking-wider ${
                    selectedDelivery.priority === 1
                      ? 'bg-red-500/20 text-red-400 border border-red-500/50 animate-pulse'
                      : selectedDelivery.priority === 2
                      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                      : 'bg-slate-800 text-slate-300 border border-slate-700'
                  }`}
                >
                  {selectedDelivery.priority === 1
                    ? '★ Rush (P1)'
                    : selectedDelivery.priority === 2
                    ? 'High Priority (P2)'
                    : 'Standard (P3)'}
                </span>
              </div>
              <div className="text-[10px] text-gray-400 mt-0.5 flex items-center gap-2 flex-wrap">
                <span>Location: <strong className="text-gray-200">{nodeMap[selectedDelivery.location]?.label || selectedDelivery.location}</strong> ({selectedDelivery.location})</span>
                <span className="text-gray-600">·</span>
                <span className="font-mono text-cyan-400 font-semibold">🕒 Current: {formatSimulationTime(state?.simulation_start_time, state?.simulation_time || 0)}</span>
              </div>
            </div>

            {/* Lifecycle Status */}
            <span
              className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                selectedDelivery.status === 'PENDING'
                  ? 'bg-blue-950/60 text-blue-300 border-blue-500/40'
                  : selectedDelivery.status === 'IN_PROGRESS'
                  ? 'bg-yellow-950/60 text-yellow-300 border-yellow-500/40 animate-pulse'
                  : selectedDelivery.status === 'DELIVERED'
                  ? 'bg-emerald-950/60 text-emerald-300 border-emerald-500/40'
                  : 'bg-red-950/60 text-red-400 border-red-500/40'
              }`}
            >
              {selectedDelivery.status}
            </span>
          </div>

          {/* Serviceability / Feasibility Banner */}
          <div
            className={`p-2 rounded border text-xs flex items-center justify-between ${
              selectedTimeline?.isServiceable
                ? 'bg-emerald-950/30 border-emerald-500/40 text-emerald-300'
                : 'bg-red-950/30 border-red-500/50 text-red-300'
            }`}
          >
            <div className="flex items-center gap-1.5">
              <span>{selectedTimeline?.isServiceable ? '✓' : '⚠️'}</span>
              <div>
                <span className="font-bold uppercase tracking-wider text-[10px] block">
                  {selectedTimeline?.isServiceable ? 'Serviceable' : 'Unserviceable / Constraint Violated'}
                </span>
                <span className="text-[10px] opacity-80">
                  {selectedTimeline?.serviceabilityReason || 'Evaluating route conditions...'}
                </span>
              </div>
            </div>
            {selectedTimeline?.isLate && (
              <span className="font-mono font-bold text-[10px] bg-red-900/60 px-1.5 py-0.5 rounded border border-red-700 text-red-200">
                +{selectedTimeline.lateness}m late
              </span>
            )}
          </div>

          {/* Grid: Demand & Assigned Vehicle */}
          <div className="grid grid-cols-2 gap-1.5 text-xs">
            <div className="bg-gray-950/80 p-2 rounded border border-gray-800">
              <span className="text-[9px] text-gray-400 uppercase tracking-wider font-semibold block">Demand / Weight</span>
              <div className="font-mono text-white font-bold mt-0.5 text-xs">
                {selectedDelivery.demand} kg
              </div>
              <div className="text-[9px] text-gray-500 mt-0.5">Payload allocation</div>
            </div>

            <div className="bg-gray-950/80 p-2 rounded border border-gray-800">
              <span className="text-[9px] text-gray-400 uppercase tracking-wider font-semibold block">Assigned Vehicle</span>
              {assignedVehicle ? (
                <button
                  onClick={() => onSelectVehicle?.(assignedVehicle.id)}
                  className="mt-0.5 flex items-center gap-1 text-left group cursor-pointer"
                  title="Click to isolate vehicle route on graph"
                >
                  <span
                    className="w-2.5 h-2.5 rounded-full inline-block flex-shrink-0"
                    style={{ background: vehicleRouteColor }}
                  />
                  <span className="font-bold text-xs text-white group-hover:text-cyan-300 underline-offset-2 group-hover:underline truncate">
                    {assignedVehicle.name} ({assignedVehicle.id.toUpperCase()})
                  </span>
                </button>
              ) : (
                <div className="text-red-400 font-bold text-[11px] mt-0.5">
                  UNASSIGNED
                </div>
              )}
              <div className="text-[9px] text-gray-500 mt-0.5">
                {assignedVehicle ? `Status: ${assignedVehicle.status}` : 'Requires optimization'}
              </div>
            </div>
          </div>

          {/* Grid: Delivery Window & Estimated Arrival (ETA) */}
          <div className="grid grid-cols-2 gap-1.5 text-xs">
            <div className="bg-gray-950/80 p-2 rounded border border-gray-800">
              <span className="text-[9px] text-gray-400 uppercase tracking-wider font-semibold block">Delivery Window</span>
              <div className="font-mono text-white font-bold mt-0.5 text-xs">
                {formatTimeWindow(state?.simulation_start_time, selectedDelivery.time_window_start, selectedDelivery.time_window_end)}
              </div>
              <div className="text-[9px] text-gray-500 mt-0.5">
                Deadline: {formatSimulationTime(state?.simulation_start_time, selectedDelivery.time_window_end)}
              </div>
            </div>

            <div className="bg-gray-950/80 p-2 rounded border border-gray-800">
              <span className="text-[9px] text-gray-400 uppercase tracking-wider font-semibold block">Estimated Delivery (ETA)</span>
              {selectedEtaAvailable ? (
                <div>
                  <div className="font-mono text-cyan-300 font-bold mt-0.5 text-xs">
                    {formatSimulationTime(state?.simulation_start_time, selectedTimeline.arrivalTime)}
                  </div>
                  {etaChange && etaChange.currentEta === selectedTimeline.arrivalTime && etaChange.delta !== 0 && (
                    <div
                      className={`text-[11px] font-bold mt-1 ${etaChange.delta > 0 ? 'text-amber-400' : 'text-emerald-400'}`}
                      aria-label={`ETA changed from ${formatSimulationTime(state?.simulation_start_time, etaChange.previousEta)} to ${formatSimulationTime(state?.simulation_start_time, etaChange.currentEta)}`}
                    >
                      {etaChange.delta > 0 ? '↑ +' : '↓ '}{Math.abs(etaChange.delta).toFixed(1)}m
                      <span className="ml-1 text-gray-300 font-medium">from previous state ({formatSimulationTime(state?.simulation_start_time, etaChange.previousEta)})</span>
                    </div>
                  )}
                  <div className={`text-[9px] font-bold mt-0.5 ${selectedTimeline.isLate ? 'text-red-400' : 'text-emerald-400'}`}>
                    {selectedTimeline.isLate
                      ? `⚠️ Late by ${formatDuration(selectedTimeline.lateness)} (window ended ${formatSimulationTime(state?.simulation_start_time, selectedDelivery.time_window_end)})`
                      : `✓ On Time (${formatDuration(selectedTimeline.spareTime)} buffer)`}
                  </div>
                </div>
              ) : (
                <div className="text-gray-500 text-[10px] mt-0.5">
                  ETA unavailable
                </div>
              )}
            </div>
          </div>

          {/* Route Sequence & Position */}
          <div className="bg-gray-950/80 p-2 rounded border border-gray-800 text-xs space-y-1">
            <div className="flex items-center justify-between text-[10px]">
              <span className="text-gray-400 uppercase tracking-wider font-semibold">Current Route Tour</span>
              <span className="font-mono text-gray-300">
                {selectedTimeline?.stopIndex
                  ? `Stop #${selectedTimeline.stopIndex} of ${selectedTimeline.totalStops}`
                  : 'Not in tour'}
              </span>
            </div>

            {selectedTimeline?.routeSequenceLabels && selectedTimeline.routeSequenceLabels.length > 0 ? (
              <div className="font-mono text-[10px] text-gray-300 overflow-x-auto whitespace-nowrap py-1 flex items-center gap-1 scrollbar-thin">
                {selectedTimeline.routeSequenceLabels.map((lbl, idx) => {
                  const isThisStop = selectedTimeline.routeSequence[idx] === selectedDelivery.location
                  return (
                    <span key={idx} className="flex items-center gap-1">
                      {idx > 0 && <span className="text-gray-600">→</span>}
                      <span
                        className={`px-1.5 py-0.5 rounded ${
                          isThisStop
                            ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 font-bold'
                            : 'bg-gray-900 text-gray-400'
                        }`}
                      >
                        {lbl}
                      </span>
                    </span>
                  )
                })}
              </div>
            ) : (
              <div className="text-gray-500 text-[10px]">
                No active route trajectory assigned to this delivery.
              </div>
            )}
          </div>

          {/* Action Shortcuts for Selected Delivery */}
          <div className="flex gap-1.5 pt-0.5">
            <button
              onClick={() => onOpenTimeWindowForm?.(selectedDelivery)}
              className="flex-1 bg-gray-800 hover:bg-gray-700 text-cyan-300 hover:text-cyan-200 border border-gray-700 hover:border-cyan-500/40 text-[10px] font-bold py-1 px-2 rounded transition-colors flex items-center justify-center gap-1 cursor-pointer"
            >
              <span>⏱</span> Adjust Window
            </button>
            <button
              onClick={() => onOpenCancelForm?.(selectedDelivery)}
              className="flex-1 bg-gray-800 hover:bg-red-950/60 text-red-400 hover:text-red-300 border border-gray-700 hover:border-red-800/60 text-[10px] font-bold py-1 px-2 rounded transition-colors flex items-center justify-center gap-1 cursor-pointer"
            >
              <span>✕</span> Cancel Order
            </button>
          </div>
        </div>
      ) : (
        /* Empty selection prompt */
        <div className="px-3 py-1.5 bg-gray-900/20 text-center text-xs flex-shrink-0">
          <div className="text-[10px] text-gray-400 font-medium">
            💡 Select an order from the list or map to inspect details
          </div>
        </div>
      )}

      {/* 3. SEARCH & COMPACT ORDER LIST */}
      <div className="flex-1 flex flex-col min-h-0 bg-[#0a0e17] overflow-hidden">
        {/* Search & Filter Bar */}
        <div className="p-2 bg-gray-950/60 border-b border-gray-800 space-y-1.5 flex-shrink-0">
          <div className="relative">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter by Order ID (d01), Stop, Van..."
              className="w-full bg-black/60 border border-gray-800 rounded px-2.5 py-1 text-xs text-white placeholder-gray-600 focus:border-cyan-500 outline-none pr-6"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1.5 text-gray-500 hover:text-gray-300 text-xs"
              >
                ✕
              </button>
            )}
          </div>

          <div className="flex items-center justify-between text-[10px]">
            <span className="text-gray-500">Filter Priority:</span>
            <div className="flex gap-1">
              {['ALL', '1', '2', '3'].map((p) => (
                <button
                  key={p}
                  onClick={() => setPriorityFilter(p === 'ALL' ? 'ALL' : Number(p))}
                  className={`px-1.5 py-0.5 rounded font-mono text-[9px] transition-colors cursor-pointer ${
                    priorityFilter === p || priorityFilter === Number(p)
                      ? 'bg-blue-600 text-white font-bold'
                      : 'bg-gray-900 text-gray-400 hover:bg-gray-800'
                  }`}
                >
                  {p === 'ALL' ? 'All' : `P${p}`}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Scrollable Compact List */}
        <div className="flex-1 overflow-y-auto divide-y divide-gray-800/40 min-h-0">
          {filteredDeliveries.length === 0 ? (
            <div className="p-6 text-center text-gray-500 text-xs">
              {deliveries.length === 0 ? (
                <div>
                  <div className="text-base mb-1">📭</div>
                  <div className="font-semibold text-gray-400">Fresh Scenario — 0 Orders</div>
                  <div className="text-[10px] mt-1 text-gray-500">Use &quot;+ Delivery&quot; in Scenario Builder to add customer orders.</div>
                </div>
              ) : (
                'No orders match filter'
              )}
            </div>
          ) : (
            filteredDeliveries.map((deliv) => {
              const isSelected = deliv.id === selectedDeliveryId
              const veh = deliv.assigned_vehicle ? vehicleMap[deliv.assigned_vehicle] : null
              const vehColor = veh ? vehicleColor(veh.colorIndex) : '#64748b'
              const tl = timelineMap[deliv.id]

              return (
                <button
                  key={deliv.id}
                  onClick={() => onSelectDelivery?.(deliv.id)}
                  className={`w-full px-2.5 py-1.5 text-left text-xs transition-colors flex items-center justify-between cursor-pointer border-l-2 ${
                    isSelected
                      ? 'bg-blue-950/40 border-cyan-400 text-white'
                      : 'border-transparent hover:bg-gray-800/40 text-gray-300'
                  }`}
                >
                  {/* Left: ID & Node */}
                  <div className="min-w-0 flex items-center gap-1.5">
                    <span
                      className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                        deliv.priority === 1
                          ? 'bg-red-500 animate-pulse'
                          : deliv.priority === 2
                          ? 'bg-amber-400'
                          : 'bg-slate-400'
                      }`}
                    />
                    <div>
                      <div className="flex items-center gap-1">
                        <span className="font-mono font-bold text-xs">{deliv.id.toUpperCase()}</span>
                        <span className="text-[9px] text-gray-500">({deliv.demand}kg)</span>
                      </div>
                      <div className="text-[9.5px] text-gray-400 truncate">
                        {nodeMap[deliv.location]?.label || deliv.location}
                      </div>
                    </div>
                  </div>

                  {/* Right: Vehicle & Status */}
                  <div className="text-right flex-shrink-0 ml-2">
                    <div className="flex items-center justify-end gap-1">
                      {veh ? (
                        <span className="flex items-center gap-1 font-mono text-[10px] font-semibold text-gray-200">
                          <span className="w-1.5 h-1.5 rounded-full" style={{ background: vehColor }} />
                          {veh.id.toUpperCase()}
                        </span>
                      ) : (
                        <span className="text-[9.5px] font-bold text-red-400">UNASSIGNED</span>
                      )}
                    </div>
                    <div className="text-[9.5px] text-gray-500 flex items-center justify-end gap-1.5 whitespace-nowrap">
                      {['PENDING', 'IN_PROGRESS'].includes(deliv.status) && Number.isFinite(tl?.arrivalTime) ? (
                        <>
                          <span className={tl.isLate ? 'text-red-400' : 'text-emerald-400'}>ETA {formatSimulationTime(state?.simulation_start_time, tl.arrivalTime)}</span>
                          {etaChangesByDelivery[deliv.id]?.currentEta === tl.arrivalTime && etaChangesByDelivery[deliv.id]?.delta !== 0 && (
                            <span className={`font-bold ${etaChangesByDelivery[deliv.id].delta > 0 ? 'text-amber-400' : 'text-emerald-400'}`}>
                              {etaChangesByDelivery[deliv.id].delta > 0 ? '↑ +' : '↓ -'}{Math.abs(etaChangesByDelivery[deliv.id].delta).toFixed(1)}m
                            </span>
                          )}
                        </>
                      ) : (
                        'ETA unavailable'
                      )}
                    </div>
                  </div>
                </button>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
