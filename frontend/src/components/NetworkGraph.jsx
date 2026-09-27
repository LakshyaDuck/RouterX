import { useMemo, useState, useRef, useEffect, useCallback } from 'react'
import { vehicleColor } from '../utils'
import { computeShortestPath, computeRouteTimelineMap } from '../utils/routeTiming'
import { formatSimulationTime, formatTimeWindow, formatDuration } from '../utils/time'


/**
 * LogisticsNetworkGraph — Interactive Logistics Control Center Graph.
 *
 * Visualizes the authoritative graph:
 * - Nodes: city locations & central depot anchor
 * - Edges: actual road segments with traffic/blocked states
 * - Routes: exact edge-traversal paths along the road graph
 * - Vehicles: status-colored position markers on routes
 * - Deliveries: clear order count & priority badges (Blue = Standard, Red = P1 Rush)
 * - Inspector: full order-level inspection on node click with windows, ETA, vehicle & demand
 * - Legend: compact on-graph visual key for rapid understanding
 */
export default function NetworkGraph({
  state,
  timelineMap: suppliedTimelineMap,
  etaChangesByDelivery = {},
  selectedVehicle,
  selectedDeliveryId = null,
  onSelectDelivery,
  affectedVehicles = [],
  affectedDeliveries = [],
  onVehicleClick,

  // Scenario interaction mode props
  mapMode = null,
  onMapModeCancel,
  newStopDraft = null,
  onNewStopDraftChange,
  onConfirmNewStop,
  selectedRoadId = null,
  onSelectRoad,
  onApplyTraffic,
  onApplyRoadBlock,
}) {
  const { nodes = [], roads = [], vehicles = [], deliveries = [], routes = [] } = state || {}

  const svgRef = useRef(null)
  const [trafficMultiplier, setTrafficMultiplier] = useState(3.5)
  const [hoveredRoadId, setHoveredRoadId] = useState(null)
  const [hoveredNodeId, setHoveredNodeId] = useState(null)

  // Node & Order inspection state
  const [selectedNodeId, setSelectedNodeId] = useState(null)
  const [localSelectedDeliveryId, setLocalSelectedDeliveryId] = useState(null)
  const [legendVisible, setLegendVisible] = useState(true)

  const effectiveDeliveryId = selectedDeliveryId !== undefined && selectedDeliveryId !== null
    ? selectedDeliveryId
    : localSelectedDeliveryId

  // Synchronize node selection when selected delivery changes externally
  useEffect(() => {
    if (selectedDeliveryId) {
      const deliv = deliveries.find(d => d.id === selectedDeliveryId)
      if (deliv && deliv.location) {
        setSelectedNodeId(deliv.location)
      }
    }
  }, [selectedDeliveryId, deliveries])

  // Pan & Zoom state
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 })
  const [isPanning, setIsPanning] = useState(false)
  const panStartRef = useRef({ x: 0, y: 0, tx: 0, ty: 0 })

  // Dimensions of virtual coordinate space
  const V_WIDTH = 1000
  const V_HEIGHT = 680
  const PADDING = 70

  // 1. Calculate deterministic, planar node positions from lat/lon
  const { nodePosMap, depot, latRange, lonRange } = useMemo(() => {
    if (nodes.length === 0) {
      return { nodePosMap: {}, depot: null, latRange: { min: 0, max: 1 }, lonRange: { min: 0, max: 1 } }
    }

    let minLat = Infinity, maxLat = -Infinity
    let minLon = Infinity, maxLon = -Infinity
    let dNode = null

    for (const n of nodes) {
      if (n.lat < minLat) minLat = n.lat
      if (n.lat > maxLat) maxLat = n.lat
      if (n.lon < minLon) minLon = n.lon
      if (n.lon > maxLon) maxLon = n.lon
      if (n.is_depot) dNode = n
    }

    // Safety margins
    const latSpan = Math.max(0.001, maxLat - minLat)
    const lonSpan = Math.max(0.001, maxLon - minLon)

    const posMap = {}
    for (const n of nodes) {
      // lon -> x (left to right)
      const xNorm = (n.lon - minLon) / lonSpan
      const x = PADDING + xNorm * (V_WIDTH - 2 * PADDING)

      // lat -> y (inverted: higher lat is North / up)
      const yNorm = (n.lat - minLat) / latSpan
      const y = (V_HEIGHT - PADDING) - yNorm * (V_HEIGHT - 2 * PADDING)

      posMap[n.id] = { x: Math.round(x), y: Math.round(y), node: n }
    }

    return {
      nodePosMap: posMap,
      depot: dNode,
      latRange: { min: minLat, max: maxLat, span: latSpan },
      lonRange: { min: minLon, max: maxLon, span: lonSpan },
    }
  }, [nodes])

  // Convert SVG canvas coordinates back to lat/lon for "Add Stop" mode
  const canvasToLatLon = useCallback((cx, cy) => {
    const xNorm = Math.max(0, Math.min(1, (cx - PADDING) / (V_WIDTH - 2 * PADDING)))
    const yNorm = Math.max(0, Math.min(1, (V_HEIGHT - PADDING - cy) / (V_HEIGHT - 2 * PADDING)))
    const lon = Number((lonRange.min + xNorm * lonRange.span).toFixed(5))
    const lat = Number((latRange.min + yNorm * latRange.span).toFixed(5))
    return { lat, lon }
  }, [lonRange, latRange])

  // Fast lookups
  const nodeMap = useMemo(() => Object.fromEntries(nodes.map(n => [n.id, n])), [nodes])
  const deliveryMap = useMemo(() => Object.fromEntries(deliveries.map(d => [d.id, d])), [deliveries])
  const vehicleMap = useMemo(() => Object.fromEntries(vehicles.map((v, i) => [v.id, { ...v, colorIndex: i }])), [vehicles])
  const selectedRoad = useMemo(() => roads.find(r => r.id === selectedRoadId) || null, [roads, selectedRoadId])

  // Deliveries grouped by node
  const deliveriesByNode = useMemo(() => {
    const map = {}
    for (const d of deliveries) {
      if (d.status === 'PENDING') {
        if (!map[d.location]) map[d.location] = []
        map[d.location].push(d)
      }
    }
    return map
  }, [deliveries])

  // Pre-calculate authoritative route timeline, arrival times and sequence indices
  const computedDeliveryArrivalMap = useMemo(() => {
    return computeRouteTimelineMap(routes, vehicles, deliveries, nodes, roads)
  }, [routes, vehicles, deliveries, nodes, roads])
  const deliveryArrivalMap = suppliedTimelineMap || computedDeliveryArrivalMap

  // Sync traffic slider when road changes
  useEffect(() => {
    if (selectedRoad) {
      setTrafficMultiplier(selectedRoad.traffic_multiplier > 1.0 ? selectedRoad.traffic_multiplier : 3.5)
    }
  }, [selectedRoad])

  // 2. Build full graph-edge traversal paths for each vehicle route
  const visualRoutes = useMemo(() => {
    return routes.map((r, i) => {
      const v = vehicleMap[r.vehicle_id]
      const color = v ? vehicleColor(v.colorIndex) : vehicleColor(i)
      const isSelected = selectedVehicle === r.vehicle_id
      const isAffected = affectedVehicles.includes(r.vehicle_id)

      // Waypoint nodes: depot -> delivery stops -> depot
      const stops = []
      if (depot) stops.push(depot.id)
      for (const did of r.delivery_ids) {
        const d = deliveryMap[did]
        if (d && nodeMap[d.location]) {
          stops.push(d.location)
        }
      }
      if (depot && r.delivery_ids.length > 0) {
        stops.push(depot.id)
      }

      // Expand consecutive stops into actual road network paths via Dijkstra
      const fullNodeSequence = []
      for (let s = 0; s < stops.length - 1; s++) {
        const leg = computeShortestPath(stops[s], stops[s + 1], nodes, roads)
        if (s === 0) {
          fullNodeSequence.push(...leg)
        } else {
          fullNodeSequence.push(...leg.slice(1))
        }
      }

      // Build points string for SVG polyline
      const points = fullNodeSequence
        .map(nid => nodePosMap[nid])
        .filter(Boolean)
        .map(p => `${p.x},${p.y}`)
        .join(' ')

      const stopsAtSelectedNode = Boolean(
        selectedNodeId && r.delivery_ids.some(did => deliveryMap[did]?.location === selectedNodeId)
      )

      return {
        route: r,
        vehicleId: r.vehicle_id,
        color,
        isSelected,
        isAffected,
        stopsAtSelectedNode,
        points,
        nodeSequence: fullNodeSequence,
      }
    })
  }, [routes, vehicleMap, selectedVehicle, affectedVehicles, selectedNodeId, depot, deliveryMap, nodeMap, nodes, roads, nodePosMap])

  // Handle pan & zoom
  const handleWheel = (e) => {
    e.preventDefault()
    const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89
    setTransform(prev => {
      const newK = Math.max(0.6, Math.min(3.5, prev.k * zoomFactor))
      return { ...prev, k: newK }
    })
  }

  const handleMouseDown = (e) => {
    if (e.target.tagName === 'svg' || e.target.id === 'network-canvas-bg') {
      setIsPanning(true)
      panStartRef.current = {
        x: e.clientX,
        y: e.clientY,
        tx: transform.x,
        ty: transform.y,
      }
    }
  }

  const handleMouseMove = (e) => {
    if (!isPanning) return
    const dx = e.clientX - panStartRef.current.x
    const dy = e.clientY - panStartRef.current.y
    setTransform(prev => ({
      ...prev,
      x: panStartRef.current.tx + dx,
      y: panStartRef.current.ty + dy,
    }))
  }

  const handleMouseUp = () => {
    setIsPanning(false)
  }

  const resetView = () => {
    setTransform({ x: 0, y: 0, k: 1 })
  }

  // Handle canvas click for "Add Stop"
  const handleSvgClick = (e) => {
    if (mapMode === 'add_stop' && !newStopDraft?.lat) {
      const rect = svgRef.current?.getBoundingClientRect()
      if (!rect) return
      const screenX = e.clientX - rect.left
      const screenY = e.clientY - rect.top
      const canvasX = (screenX - transform.x) / transform.k * (V_WIDTH / rect.width)
      const canvasY = (screenY - transform.y) / transform.k * (V_HEIGHT / rect.height)
      const { lat, lon } = canvasToLatLon(canvasX, canvasY)

      onNewStopDraftChange?.({
        lat,
        lon,
        label: `Stop n${nodes.length + 1}`,
        connectToNodeId: null,
      })
    } else if (!isPanning && (e.target.tagName === 'svg' || e.target.id === 'network-canvas-bg')) {
      // Clicking empty canvas deselects active node
      setSelectedNodeId(null)
      setLocalSelectedDeliveryId(null)
      onSelectDelivery?.(null)
    }
  }

  const handleNodeClick = (nodeId) => {
    const nextNodeId = selectedNodeId === nodeId ? null : nodeId
    setSelectedNodeId(nextNodeId)
    if (nextNodeId) {
      const delivs = deliveriesByNode[nextNodeId] || []
      const firstId = delivs[0]?.id || null
      setLocalSelectedDeliveryId(firstId)
      onSelectDelivery?.(firstId)
    } else {
      setLocalSelectedDeliveryId(null)
      onSelectDelivery?.(null)
    }
  }

  const isRoadSelectionMode = mapMode === 'select_road_traffic' || mapMode === 'select_road_block'

  // Selected node & active delivery details for Inspector Card
  const selectedNode = selectedNodeId ? nodeMap[selectedNodeId] : null
  const nodeDeliveries = selectedNodeId ? deliveriesByNode[selectedNodeId] || [] : []
  const activeDelivery = effectiveDeliveryId
    ? deliveryMap[effectiveDeliveryId]
    : nodeDeliveries[0] || null
  const assignedVeh = activeDelivery?.assigned_vehicle ? vehicleMap[activeDelivery.assigned_vehicle] : null
  const deliveryArrival = activeDelivery ? deliveryArrivalMap[activeDelivery.id] : null
  const activeEtaChange = activeDelivery ? etaChangesByDelivery[activeDelivery.id] : null

  return (
    <div
      className={`relative w-full h-full bg-[#080c14] select-none overflow-hidden ${
        mapMode === 'add_stop' && !newStopDraft?.lat ? 'cursor-crosshair' : isPanning ? 'cursor-grabbing' : 'cursor-default'
      }`}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onWheel={handleWheel}
    >
      {/* ------------------------------------------------------------- */}
      {/* 1. MAIN SVG NETWORK GRAPH                                      */}
      {/* ------------------------------------------------------------- */}
      <svg
        ref={svgRef}
        viewBox={`0 0 ${V_WIDTH} ${V_HEIGHT}`}
        className="w-full h-full block"
        preserveAspectRatio="xMidYMid meet"
        onClick={handleSvgClick}
      >
        <defs>
          {/* Subtle grid pattern */}
          <pattern id="grid-pattern" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#131b2e" strokeWidth="0.8" opacity="0.6" />
            <circle cx="0" cy="0" r="1.2" fill="#1e293b" />
          </pattern>

          {/* Radial dark gradient background */}
          <radialGradient id="network-glow" cx="50%" cy="50%" r="65%">
            <stop offset="0%" stopColor="#0f172a" stopOpacity="0.85" />
            <stop offset="60%" stopColor="#080c14" stopOpacity="0.95" />
            <stop offset="100%" stopColor="#04060a" stopOpacity="1" />
          </radialGradient>

          {/* Glowing filters */}
          <filter id="cyan-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>

          <filter id="gold-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="4.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Background Layers */}
        <rect id="network-canvas-bg" width={V_WIDTH} height={V_HEIGHT} fill="url(#network-glow)" />
        <rect width={V_WIDTH} height={V_HEIGHT} fill="url(#grid-pattern)" pointerEvents="none" />

        {/* TRANSFORM CONTAINER (Pan & Zoom) */}
        <g transform={`translate(${transform.x}, ${transform.y}) scale(${transform.k})`}>

          {/* =========================================================== */}
          {/* LAYER 1: BASE NETWORK ROAD EDGES                            */}
          {/* =========================================================== */}
          <g id="network-edges" pointerEvents="none">
            {roads.map(road => {
              const from = nodePosMap[road.from_node]
              const to = nodePosMap[road.to_node]
              if (!from || !to) return null

              const isSelected = selectedRoadId === road.id
              const isHovered = hoveredRoadId === road.id
              const isBlocked = road.blocked
              const isHeavyTraffic = road.traffic_multiplier > 2.5
              const isModerateTraffic = road.traffic_multiplier > 1.5 && !isHeavyTraffic

              let strokeColor = '#1e293b'
              let strokeWidth = 2.0
              let strokeDash = undefined

              if (isSelected) {
                strokeColor = '#06b6d4'
                strokeWidth = 4.5
              } else if (isBlocked) {
                strokeColor = '#ef4444'
                strokeWidth = 3.0
                strokeDash = '6 4'
              } else if (isHeavyTraffic) {
                strokeColor = '#f97316'
                strokeWidth = 3.5
              } else if (isModerateTraffic) {
                strokeColor = '#f59e0b'
                strokeWidth = 3.0
              } else if (isHovered && isRoadSelectionMode) {
                strokeColor = '#38bdf8'
                strokeWidth = 3.5
              }

              return (
                <g key={road.id}>
                  {isSelected && (
                    <line
                      x1={from.x}
                      y1={from.y}
                      x2={to.x}
                      y2={to.y}
                      stroke="#06b6d4"
                      strokeWidth={10}
                      strokeOpacity={0.35}
                      filter="url(#cyan-glow)"
                    />
                  )}

                  <line
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke={strokeColor}
                    strokeWidth={strokeWidth}
                    strokeDasharray={strokeDash}
                    strokeLinecap="round"
                    opacity={isBlocked ? 0.95 : 0.85}
                  />

                  {(isBlocked || isHeavyTraffic || isModerateTraffic) && (
                    <g transform={`translate(${(from.x + to.x) / 2}, ${(from.y + to.y) / 2})`}>
                      {isBlocked ? (
                        <g>
                          <circle r="7.5" fill="#ef4444" stroke="#7f1d1d" strokeWidth="1.5" />
                          <text textAnchor="middle" dy="3" fill="#ffffff" fontSize="9" fontWeight="900" fontFamily="sans-serif">✕</text>
                        </g>
                      ) : (
                        <g>
                          <rect
                            x="-14"
                            y="-6.5"
                            width="28"
                            height="13"
                            rx="3"
                            fill="#1e180d"
                            stroke={isHeavyTraffic ? '#f97316' : '#f59e0b'}
                            strokeWidth="1.2"
                          />
                          <text
                            textAnchor="middle"
                            dy="3.5"
                            fill={isHeavyTraffic ? '#fb923c' : '#fcd34d'}
                            fontSize="8"
                            fontWeight="800"
                            fontFamily="monospace"
                          >
                            {road.traffic_multiplier.toFixed(1)}×
                          </text>
                        </g>
                      )}
                    </g>
                  )}
                </g>
              )
            })}
          </g>

          {/* =========================================================== */}
          {/* LAYER 2: ACTUAL ROUTE TOPOLOGY (Along Graph Edges)          */}
          {/* =========================================================== */}
          <g id="network-routes" pointerEvents="none">
            {visualRoutes.map(vr => {
              if (!vr.points) return null

              const isVehicleFiltered = selectedVehicle !== null
              const isThisVehicle = selectedVehicle === vr.vehicleId
              const isAffected = vr.isAffected
              const stopsAtFocusedNode = vr.stopsAtSelectedNode

              // Opacity and weight: highlight focused vehicle OR routes serving selected node
              let strokeOpacity = 0.65
              let strokeWidth = 2.8

              if (isVehicleFiltered) {
                if (isThisVehicle) {
                  strokeOpacity = 0.95
                  strokeWidth = 4.5
                } else {
                  strokeOpacity = 0.12
                  strokeWidth = 1.6
                }
              } else if (selectedNodeId) {
                if (stopsAtFocusedNode) {
                  strokeOpacity = 0.95
                  strokeWidth = 4.2
                } else {
                  strokeOpacity = 0.15
                  strokeWidth = 1.8
                }
              } else if (isAffected) {
                strokeOpacity = 0.95
                strokeWidth = 4.0
              }

              return (
                <g key={`route-${vr.vehicleId}`}>
                  {(isThisVehicle || isAffected || (selectedNodeId && stopsAtFocusedNode)) && (
                    <polyline
                      points={vr.points}
                      fill="none"
                      stroke={isAffected ? '#fbbf24' : vr.color}
                      strokeWidth={strokeWidth + 5}
                      strokeOpacity={0.4}
                      strokeLinejoin="round"
                      strokeLinecap="round"
                      filter={isAffected ? 'url(#gold-glow)' : 'url(#cyan-glow)'}
                    />
                  )}

                  <polyline
                    points={vr.points}
                    fill="none"
                    stroke={vr.color}
                    strokeWidth={strokeWidth}
                    strokeOpacity={strokeOpacity}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                </g>
              )
            })}
          </g>

          {/* =========================================================== */}
          {/* LAYER 3: FORGIVING ROAD HITBOXES                            */}
          {/* =========================================================== */}
          <g id="road-hitboxes">
            {roads.map(road => {
              const from = nodePosMap[road.from_node]
              const to = nodePosMap[road.to_node]
              if (!from || !to) return null

              return (
                <line
                  key={`hitbox-${road.id}`}
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  stroke="transparent"
                  strokeWidth={26}
                  strokeLinecap="round"
                  className={isRoadSelectionMode ? 'cursor-pointer' : 'cursor-default'}
                  onMouseEnter={() => setHoveredRoadId(road.id)}
                  onMouseLeave={() => setHoveredRoadId(null)}
                  onClick={(e) => {
                    e.stopPropagation()
                    onSelectRoad?.(road.id)
                  }}
                >
                  <title>{`${road.id}: ${nodeMap[road.from_node]?.label || road.from_node} ↔ ${nodeMap[road.to_node]?.label || road.to_node} (${road.distance} km${road.blocked ? ' - BLOCKED' : `, ${road.traffic_multiplier}×`})`}</title>
                </line>
              )
            })}
          </g>

          {/* =========================================================== */}
          {/* LAYER 4: NODES, DEPOT ANCHOR & UNDERSTANDABLE BADGES        */}
          {/* =========================================================== */}
          <g id="network-nodes">
            {nodes.map(node => {
              const pos = nodePosMap[node.id]
              if (!pos) return null

              const isDepot = Boolean(node.is_depot)
              const isHovered = hoveredNodeId === node.id
              const isSelected = selectedNodeId === node.id
              const pendingDelivs = deliveriesByNode[node.id] || []
              const hasP1 = pendingDelivs.some(d => d.priority === 1)
              const isCandidateLink = mapMode === 'add_stop' && newStopDraft?.lat && !newStopDraft?.connectToNodeId
              const isSelectedLink = newStopDraft?.connectToNodeId === node.id

              const vehiclesAtNode = vehicles.filter(v => v.current_location === node.id)

              // Badge dimensions and label
              const badgeWidth = pendingDelivs.length > 0
                ? (hasP1 ? 26 : 22)
                : 0

              return (
                <g
                  key={node.id}
                  transform={`translate(${pos.x}, ${pos.y})`}
                  className="cursor-pointer"
                  onMouseEnter={() => setHoveredNodeId(node.id)}
                  onMouseLeave={() => setHoveredNodeId(null)}
                  onClick={(e) => {
                    e.stopPropagation()
                    if (isCandidateLink) {
                      onNewStopDraftChange?.({ ...newStopDraft, connectToNodeId: node.id })
                    } else {
                      handleNodeClick(node.id)
                    }
                  }}
                >
                  {/* Tooltip on entire node */}
                  <title>{`${node.label || node.id} (${node.id}): ${pendingDelivs.length} delivery order(s)${hasP1 ? ' [P1 RUSH]' : ''} — Click to inspect`}</title>

                  {/* Forgiving click target hitbox */}
                  <circle r="18" fill="transparent" />

                  {/* Pulsing selection halo when node is selected */}
                  {isSelected && (
                    <g>
                      <circle r="18" fill="#06b6d4" fillOpacity="0.25" stroke="#22d3ee" strokeWidth="2.5" />
                      <circle r="22" fill="none" stroke="#38bdf8" strokeWidth="1.2" strokeDasharray="4 3" opacity={0.8} />
                    </g>
                  )}

                  {/* Candidate link pulsing ring in Add Stop mode */}
                  {isCandidateLink && (
                    <circle r="18" fill="#06b6d4" fillOpacity="0.2" stroke="#22d3ee" strokeWidth="1.5" className="animate-ping" />
                  )}

                  {/* 4A. DEPOT ANCHOR */}
                  {isDepot ? (
                    <g>
                      <circle r="19" fill="#0284c7" fillOpacity="0.2" filter="url(#cyan-glow)" />
                      <circle r="13" fill="#0f172a" stroke="#0ea5e9" strokeWidth="2.5" />
                      <circle r="5" fill="#38bdf8" />
                      <text
                        y="23"
                        textAnchor="middle"
                        fill="#38bdf8"
                        fontSize="9.5"
                        fontWeight="900"
                        letterSpacing="0.8"
                        className="pointer-events-none select-none drop-shadow"
                      >
                        DEPOT
                      </text>
                    </g>
                  ) : (
                    /* 4B. NORMAL CITY NETWORK NODE */
                    <g>
                      <circle
                        r={isSelected ? 9 : isSelectedLink ? 9 : isHovered ? 8 : 6.5}
                        fill={isSelected ? '#06b6d4' : isSelectedLink ? '#06b6d4' : '#0f172a'}
                        stroke={isSelected ? '#ffffff' : isSelectedLink ? '#22d3ee' : isHovered ? '#94a3b8' : '#475569'}
                        strokeWidth={isSelected ? 2.5 : isSelectedLink ? 2.5 : isHovered ? 2 : 1.5}
                        className="transition-all duration-150"
                      />
                      <text
                        y="-10"
                        textAnchor="middle"
                        fill={isSelected ? '#38bdf8' : isHovered ? '#f1f5f9' : '#94a3b8'}
                        fontSize="8.5"
                        fontWeight="700"
                        fontFamily="monospace"
                        className="pointer-events-none select-none"
                      >
                        {node.id}
                      </text>
                    </g>
                  )}

                  {/* 4C. UNDERSTANDABLE ORDER COUNT & PRIORITY BADGE */}
                  {pendingDelivs.length > 0 && (
                    <g transform={`translate(7, -8)`} className="pointer-events-none select-none">
                      <rect
                        x="-2"
                        y="-7.5"
                        width={badgeWidth}
                        height="14"
                        rx="4"
                        fill={hasP1 ? '#1c0d0d' : '#0b1329'}
                        stroke={hasP1 ? '#ef4444' : '#3b82f6'}
                        strokeWidth="1.4"
                      />
                      <text
                        x={badgeWidth / 2 - 2}
                        dy="3"
                        textAnchor="middle"
                        fill={hasP1 ? '#fca5a5' : '#93c5fd'}
                        fontSize="8"
                        fontWeight="900"
                        fontFamily="monospace"
                      >
                        {hasP1 ? `★${pendingDelivs.length}` : `📦${pendingDelivs.length}`}
                      </text>
                    </g>
                  )}

                  {/* 4D. VEHICLE CHIP */}
                  {vehiclesAtNode.map((veh, idx) => {
                    const isVehSelected = selectedVehicle === veh.id
                    const isBroken = veh.status === 'BREAKDOWN'
                    const isDelayed = veh.status === 'DELAYED'

                    const badgeColor = isBroken ? '#ef4444' : isDelayed ? '#f59e0b' : isVehSelected ? '#06b6d4' : '#10b981'

                    return (
                      <g
                        key={veh.id}
                        transform={`translate(${-18 - idx * 28}, 14)`}
                        className="cursor-pointer"
                        onClick={(e) => {
                          e.stopPropagation()
                          onVehicleClick?.(veh.id)
                        }}
                      >
                        <rect
                          x="-13"
                          y="-7"
                          width="26"
                          height="14"
                          rx="4"
                          fill="#0b111e"
                          stroke={badgeColor}
                          strokeWidth={isVehSelected ? 2 : 1.2}
                          className="transition-colors"
                        />
                        <text
                          textAnchor="middle"
                          dy="3.5"
                          fill={badgeColor}
                          fontSize="8"
                          fontWeight="800"
                          fontFamily="monospace"
                        >
                          {veh.id.toUpperCase()}
                        </text>
                      </g>
                    )
                  })}
                </g>
              )
            })}

            {/* In-progress new stop draft marker (Add Stop mode) */}
            {mapMode === 'add_stop' && newStopDraft?.lat && (
              <g
                transform={`translate(${
                  PADDING + ((newStopDraft.lon - lonRange.min) / lonRange.span) * (V_WIDTH - 2 * PADDING)
                }, ${
                  (V_HEIGHT - PADDING) - ((newStopDraft.lat - latRange.min) / latRange.span) * (V_HEIGHT - 2 * PADDING)
                })`}
              >
                <circle r="12" fill="#06b6d4" fillOpacity="0.3" className="animate-ping" />
                <circle r="7.5" fill="#06b6d4" stroke="#ffffff" strokeWidth="2" />
                <text y="-11" textAnchor="middle" fill="#22d3ee" fontSize="9" fontWeight="900" className="select-none">
                  NEW STOP
                </text>
              </g>
            )}
          </g>

        </g>
      </svg>

      {/* ------------------------------------------------------------- */}
      {/* 2. FLOATING CANVAS CONTROLS (Top-Right Zoom & Fit)             */}
      {/* ------------------------------------------------------------- */}
      <div className="absolute top-3 right-3 z-30 flex items-center gap-1 bg-gray-950/80 border border-gray-800 rounded-lg p-1 shadow-lg backdrop-blur-md">
        <button
          onClick={() => setTransform(prev => ({ ...prev, k: Math.min(3.5, prev.k * 1.2) }))}
          className="w-6 h-6 flex items-center justify-center text-gray-400 hover:text-white hover:bg-gray-800 rounded text-xs font-bold transition-colors cursor-pointer"
          title="Zoom In"
        >
          +
        </button>
        <button
          onClick={() => setTransform(prev => ({ ...prev, k: Math.max(0.6, prev.k / 1.2) }))}
          className="w-6 h-6 flex items-center justify-center text-gray-400 hover:text-white hover:bg-gray-800 rounded text-xs font-bold transition-colors cursor-pointer"
          title="Zoom Out"
        >
          -
        </button>
        <button
          onClick={resetView}
          className="px-1.5 h-6 flex items-center justify-center text-[10px] text-gray-400 hover:text-white hover:bg-gray-800 rounded font-semibold transition-colors cursor-pointer"
          title="Reset Network View"
        >
          Fit View
        </button>
      </div>

      {/* ------------------------------------------------------------- */}
      {/* 3. ACTIVE INTERACTION MODE HINT BANNER                         */}
      {/* ------------------------------------------------------------- */}
      {mapMode && !(mapMode === 'add_stop' && newStopDraft?.connectToNodeId) && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-30 flex items-center gap-3 bg-gray-950/95 border border-cyan-500/50 shadow-2xl px-3.5 py-1.5 rounded-full backdrop-blur-md animate-fadeIn text-xs">
          {mapMode === 'add_stop' && (
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse flex-shrink-0" />
              <span className="text-cyan-300 font-medium">
                {!newStopDraft?.lat
                  ? 'Click anywhere on graph canvas to place new stop'
                  : 'Click an existing node to connect edge'}
              </span>
              {newStopDraft?.lat && (
                <button
                  onClick={() => onNewStopDraftChange?.(null)}
                  className="text-gray-400 hover:text-white underline text-[11px] ml-1 cursor-pointer"
                >
                  Reposition
                </button>
              )}
            </div>
          )}

          {mapMode === 'select_road_traffic' && (
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse flex-shrink-0" />
              <span className="text-amber-300 font-medium">
                {selectedRoad
                  ? `Edge Selected: ${selectedRoad.id} (${nodeMap[selectedRoad.from_node]?.label || selectedRoad.from_node} ↔ ${nodeMap[selectedRoad.to_node]?.label || selectedRoad.to_node})`
                  : 'Click any road edge on the network graph'}
              </span>
            </div>
          )}

          {mapMode === 'select_road_block' && (
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-orange-400 animate-pulse flex-shrink-0" />
              <span className="text-orange-300 font-medium">
                {selectedRoad
                  ? `Edge Selected: ${selectedRoad.id} (${selectedRoad.blocked ? 'BLOCKED' : 'OPEN'})`
                  : 'Click any road edge on the network graph'}
              </span>
            </div>
          )}

          <button
            onClick={onMapModeCancel}
            className="bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white px-2 py-0.5 rounded-full border border-gray-700 transition-colors text-[11px] font-medium ml-1 flex-shrink-0 cursor-pointer"
          >
            ✕ Cancel
          </button>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* 4. ACTIVE VEHICLE FILTER PILL                                  */}
      {/* ------------------------------------------------------------- */}
      {selectedVehicle && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-30 bg-blue-600/90 border border-blue-400 text-white text-xs font-bold px-4 py-1.5 rounded-full shadow-lg flex items-center gap-2 backdrop-blur-md">
          <span className="w-2 h-2 bg-white rounded-full animate-pulse" />
          <span>Focusing Route: {state?.vehicles?.find(v => v.id === selectedVehicle)?.name || selectedVehicle}</span>
          <button
            onClick={() => onVehicleClick?.(null)}
            className="ml-1 opacity-70 hover:opacity-100 text-sm leading-none cursor-pointer"
          >
            ✕
          </button>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* 5. LOCATION & ORDERS INSPECTOR CARD (Node clicked)             */}
      {/* ------------------------------------------------------------- */}
      {selectedNode && (
        <div className="absolute bottom-4 left-4 z-40 w-96 max-w-[calc(100vw-32px)] max-h-[460px] bg-[#0c121e]/98 border border-cyan-500/70 rounded-xl shadow-2xl p-3.5 text-xs backdrop-blur-md animate-fadeIn flex flex-col gap-2.5">
          {/* Card Header */}
          <div className="flex items-center justify-between border-b border-gray-800 pb-2 flex-shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-base flex-shrink-0">📍</span>
              <div className="min-w-0">
                <div className="font-bold text-white text-xs flex items-center gap-1.5 truncate">
                  <span className="truncate">{selectedNode.label || selectedNode.id}</span>
                  <span className="font-mono text-[10px] text-cyan-400 bg-cyan-950/70 px-1.5 py-0.5 rounded border border-cyan-800/60 flex-shrink-0">
                    {selectedNode.id}
                  </span>
                  {selectedNode.is_depot && (
                    <span className="text-[9px] font-black text-amber-300 bg-amber-950/80 px-1 py-0.5 rounded border border-amber-700/60 flex-shrink-0">
                      DEPOT
                    </span>
                  )}
                </div>
                <div className="text-[10px] text-gray-400 font-mono mt-0.5">
                  Location: {selectedNode.lat.toFixed(4)}, {selectedNode.lon.toFixed(4)} · <strong className="text-gray-200">{nodeDeliveries.length}</strong> active order{nodeDeliveries.length !== 1 ? 's' : ''}
                </div>
              </div>
            </div>
            <button
              onClick={() => {
                setSelectedNodeId(null)
                setLocalSelectedDeliveryId(null)
                onSelectDelivery?.(null)
              }}
              className="text-gray-400 hover:text-white p-1 rounded hover:bg-gray-800 transition-colors cursor-pointer flex-shrink-0 text-sm"
              title="Close Location Inspector"
            >
              ✕
            </button>
          </div>

          {/* Delivery list & active order details */}
          {nodeDeliveries.length === 0 ? (
            <div className="py-4 text-center text-gray-500 text-xs">
              <div className="text-gray-400 font-medium">Transit Station</div>
              <div className="text-[10px] text-gray-500 mt-1">
                Zero active packages stationed at this node. Road intersection or intermediate network waypoint.
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-2 min-h-0 flex-1 overflow-hidden">
              {/* Order selector tabs if multiple deliveries */}
              {nodeDeliveries.length > 1 && (
                <div className="flex items-center gap-1.5 overflow-x-auto pb-1 flex-shrink-0" style={{ scrollbarWidth: 'thin' }}>
                  {nodeDeliveries.map(d => {
                    const isP1 = d.priority === 1
                    const isSelected = (activeDelivery?.id || nodeDeliveries[0]?.id) === d.id
                    return (
                      <button
                        key={d.id}
                        onClick={() => {
                          setLocalSelectedDeliveryId(d.id)
                          onSelectDelivery?.(d.id)
                        }}
                        className={`px-2 py-1 rounded text-[10px] font-mono font-bold flex items-center gap-1 transition-all cursor-pointer flex-shrink-0 ${
                          isSelected
                            ? 'bg-cyan-600 text-white shadow-md shadow-cyan-600/30 ring-1 ring-cyan-400'
                            : isP1
                            ? 'bg-red-950/70 border border-red-800/80 text-red-300 hover:bg-red-900/60'
                            : 'bg-gray-900 border border-gray-800 text-gray-300 hover:bg-gray-800'
                        }`}
                      >
                        {isP1 && <span>★</span>}
                        <span>{d.id.toUpperCase()}</span>
                        <span className="text-[8px] opacity-70">({d.demand}kg)</span>
                      </button>
                    )
                  })}
                </div>
              )}

              {/* Active Delivery Detail Card */}
              {activeDelivery && (
                <div className="bg-black/50 border border-gray-800/90 rounded-lg p-2.5 space-y-2 overflow-y-auto flex-1 min-h-0" style={{ scrollbarWidth: 'thin' }}>
                  {/* Order ID & Priority Badge */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono font-bold text-white text-xs tracking-wider">{activeDelivery.id.toUpperCase()}</span>
                      <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded uppercase ${
                        activeDelivery.priority === 1
                          ? 'bg-red-950/90 border border-red-700 text-red-300'
                          : activeDelivery.priority === 2
                          ? 'bg-amber-950/90 border border-amber-700 text-amber-300'
                          : 'bg-blue-950/90 border border-blue-800 text-blue-300'
                      }`}>
                        {activeDelivery.priority === 1 ? '★ P1 Rush' : activeDelivery.priority === 2 ? 'P2 High' : 'P3 Standard'}
                      </span>
                    </div>
                    <span className="text-[10px] font-mono text-gray-400">
                      Demand: <strong className="text-white">{activeDelivery.demand} kg</strong>
                    </span>
                  </div>

                  {/* Assigned Vehicle */}
                  <div className="flex items-center justify-between bg-gray-900/80 px-2 py-1.5 rounded border border-gray-800/80 text-[11px]">
                    <span className="text-gray-400">Assigned Vehicle:</span>
                    {assignedVeh ? (
                      <button
                        onClick={() => onVehicleClick?.(assignedVeh.id)}
                        className="font-bold flex items-center gap-1.5 text-cyan-300 hover:text-cyan-200 hover:underline cursor-pointer"
                        title="Click to isolate this vehicle route"
                      >
                        <span className={`w-2 h-2 rounded-full ${
                          assignedVeh.status === 'BREAKDOWN' ? 'bg-red-500 animate-pulse' :
                          assignedVeh.status === 'DELAYED' ? 'bg-amber-500' : 'bg-emerald-500'
                        }`} />
                        <span>{assignedVeh.name} ({assignedVeh.id.toUpperCase()})</span>
                      </button>
                    ) : (
                      <span className="text-red-400 font-bold">Unassigned (Needs Optimization)</span>
                    )}
                  </div>

                  {/* Delivery Window & Estimated Arrival (ETA) */}
                  <div className="grid grid-cols-2 gap-1.5 text-[11px]">
                    <div className="bg-gray-900/80 p-2 rounded border border-gray-800/80">
                      <div className="text-[8.5px] text-gray-500 uppercase tracking-wider font-semibold">Delivery Window</div>
                      <div className="font-mono text-white font-bold mt-0.5 text-xs">
                        {formatTimeWindow(state?.simulation_start_time, activeDelivery.time_window_start, activeDelivery.time_window_end)}
                      </div>
                      <div className="text-[9px] text-gray-400 mt-0.5">
                        Deadline: {formatSimulationTime(state?.simulation_start_time, activeDelivery.time_window_end)}
                      </div>
                    </div>

                    <div className="bg-gray-900/80 p-2 rounded border border-gray-800/80">
                      <div className="text-[8.5px] text-gray-500 uppercase tracking-wider font-semibold">Estimated Arrival (ETA)</div>
                      {Number.isFinite(deliveryArrival?.arrivalTime) ? (
                        <div>
                          <div className="font-mono text-cyan-300 font-bold mt-0.5 text-xs">
                            {formatSimulationTime(state?.simulation_start_time, deliveryArrival.arrivalTime)}
                          </div>
                          {activeEtaChange?.currentEta === deliveryArrival.arrivalTime && activeEtaChange.delta !== 0 && (
                            <div className={`text-[11px] font-bold mt-1 ${activeEtaChange.delta > 0 ? 'text-amber-400' : 'text-emerald-400'}`}>
                              {activeEtaChange.delta > 0 ? '↑ +' : '↓ -'}{Math.abs(activeEtaChange.delta).toFixed(1)}m
                              <span className="ml-1 text-gray-300 font-medium">from previous state ({formatSimulationTime(state?.simulation_start_time, activeEtaChange.previousEta)})</span>
                            </div>
                          )}
                          <div className={`text-[9px] font-bold mt-0.5 ${deliveryArrival.isLate ? 'text-red-400' : 'text-emerald-400'}`}>
                            {deliveryArrival.isLate ? `⚠️ Late by ${formatDuration(deliveryArrival.lateness)} (window ended ${formatSimulationTime(state?.simulation_start_time, activeDelivery.time_window_end)})` : `✓ On Time (${formatDuration(deliveryArrival.spareTime)} buffer)`}
                          </div>
                        </div>
                      ) : (
                        <div className="text-gray-500 text-[10px] mt-0.5">
                          ETA unavailable
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Route Sequence & Status */}
                  <div className="flex items-center justify-between text-[10px] text-gray-400 px-1 pt-0.5">
                    <span>
                      {Number.isFinite(deliveryArrival?.arrivalTime) ? (
                        <span>Sequence: <strong className="text-gray-200">Stop #{deliveryArrival.stopIndex} of {deliveryArrival.totalStops}</strong></span>
                      ) : (
                        <span>Status: <strong className="text-gray-200">{activeDelivery.status}</strong></span>
                      )}
                    </span>
                    <span className="text-gray-500">
                      {assignedVeh?.status === 'BREAKDOWN' ? (
                        <span className="text-red-400 font-bold">⚠️ Van Breakdown</span>
                      ) : (
                        <span>Ready for dispatch</span>
                      )}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* 6. FLOATING CONFIRMATION CARD: ADD STOP                        */}
      {/* ------------------------------------------------------------- */}
      {mapMode === 'add_stop' && newStopDraft?.lat && newStopDraft?.connectToNodeId && (
        <div className="absolute bottom-6 left-6 z-40 w-80 bg-gray-950/95 border border-cyan-500/70 rounded-xl shadow-2xl p-4 text-xs backdrop-blur-md animate-fadeIn">
          <div className="flex items-center justify-between mb-2">
            <span className="font-bold text-cyan-300 text-sm flex items-center gap-1.5">
              <span>📍</span> Add Network Stop
            </span>
            <button
              onClick={() => onNewStopDraftChange?.({ ...newStopDraft, connectToNodeId: null })}
              className="text-[11px] text-cyan-400 hover:underline cursor-pointer"
            >
              Change Link
            </button>
          </div>
          <div className="space-y-2 mb-3">
            <div>
              <label className="text-[10px] text-gray-400 block mb-0.5">Stop Label / Station Name</label>
              <input
                type="text"
                value={newStopDraft.label || ''}
                onChange={(e) => onNewStopDraftChange?.({ ...newStopDraft, label: e.target.value })}
                placeholder="e.g. North Point Annex"
                className="w-full bg-black/60 border border-gray-700 rounded px-2.5 py-1.5 text-white text-xs focus:border-cyan-500 outline-none"
              />
            </div>
            <div className="bg-gray-900/90 p-2.5 rounded border border-gray-800 space-y-1 text-[11px]">
              <div className="text-gray-300 flex justify-between">
                <span className="text-gray-400">Network Position:</span>
                <span className="font-mono text-cyan-300">{newStopDraft.lat}, {newStopDraft.lon}</span>
              </div>
              <div className="text-gray-300 flex justify-between">
                <span className="text-gray-400">Linked to Node:</span>
                <span className="font-semibold text-white">
                  {nodeMap[newStopDraft.connectToNodeId]?.label || newStopDraft.connectToNodeId} ({newStopDraft.connectToNodeId})
                </span>
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => onConfirmNewStop?.(newStopDraft)}
              className="flex-1 bg-cyan-600 hover:bg-cyan-500 text-white font-bold py-1.5 rounded transition-colors text-xs flex items-center justify-center gap-1 shadow-lg cursor-pointer"
            >
              <span>✓</span> Add Stop to Graph
            </button>
            <button
              onClick={onMapModeCancel}
              className="bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded text-xs transition-colors cursor-pointer"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* 7. FLOATING CONTROL CARD: TRAFFIC MULTIPLIER                   */}
      {/* ------------------------------------------------------------- */}
      {mapMode === 'select_road_traffic' && selectedRoad && (
        <div className="absolute bottom-6 left-6 z-40 w-80 bg-gray-950/95 border border-amber-500/70 rounded-xl shadow-2xl p-4 text-xs backdrop-blur-md animate-fadeIn">
          <div className="flex items-center justify-between mb-2">
            <span className="font-bold text-amber-300 text-sm flex items-center gap-1.5">
              <span>🚦</span> Modify Edge Traffic
            </span>
            <button onClick={() => onSelectRoad?.(null)} className="text-gray-400 hover:text-white cursor-pointer">✕</button>
          </div>
          <div className="bg-gray-900/90 p-2.5 rounded border border-gray-800 mb-3 space-y-1 text-[11px]">
            <div className="flex justify-between">
              <span className="text-gray-400">Edge ID:</span>
              <span className="font-mono font-bold text-white">{selectedRoad.id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Endpoints:</span>
              <span className="text-gray-200">
                {nodeMap[selectedRoad.from_node]?.label || selectedRoad.from_node} ↔ {nodeMap[selectedRoad.to_node]?.label || selectedRoad.to_node}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Current Congestion:</span>
              <span className="font-mono text-amber-300 font-bold">{selectedRoad.traffic_multiplier}×</span>
            </div>
          </div>
          <div className="mb-3">
            <div className="flex justify-between text-[10px] text-gray-400 mb-1">
              <span>Multiplier: <strong className="text-amber-400 text-xs">{trafficMultiplier}×</strong></span>
              <span>1.0× (Flow) — 5.0× (Jam)</span>
            </div>
            <input
              type="range"
              min="1.0"
              max="5.0"
              step="0.5"
              value={trafficMultiplier}
              onChange={(e) => setTrafficMultiplier(Number(e.target.value))}
              className="w-full accent-amber-500"
            />
            <div className="flex justify-between gap-1.5 mt-2">
              {[1.0, 2.0, 3.5, 5.0].map((val) => (
                <button
                  key={val}
                  onClick={() => setTrafficMultiplier(val)}
                  className={`flex-1 py-1 rounded text-[10px] font-bold border transition-colors cursor-pointer ${
                    trafficMultiplier === val
                      ? 'bg-amber-500 text-black border-amber-400'
                      : 'bg-gray-900 text-gray-300 border-gray-800 hover:border-gray-700'
                  }`}
                >
                  {val}×
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={() => onApplyTraffic?.(selectedRoad.id, trafficMultiplier)}
            className="w-full bg-amber-600 hover:bg-amber-500 text-black font-black py-2 rounded transition-colors text-xs shadow-lg cursor-pointer"
          >
            Apply Traffic Delay
          </button>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* 8. FLOATING CONTROL CARD: BLOCK ROAD                           */}
      {/* ------------------------------------------------------------- */}
      {mapMode === 'select_road_block' && selectedRoad && (
        <div className="absolute bottom-6 left-6 z-40 w-80 bg-gray-950/95 border border-orange-500/70 rounded-xl shadow-2xl p-4 text-xs backdrop-blur-md animate-fadeIn">
          <div className="flex items-center justify-between mb-2">
            <span className="font-bold text-orange-300 text-sm flex items-center gap-1.5">
              <span>🚧</span> Road Edge Status
            </span>
            <button onClick={() => onSelectRoad?.(null)} className="text-gray-400 hover:text-white cursor-pointer">✕</button>
          </div>
          <div className="bg-gray-900/90 p-2.5 rounded border border-gray-800 mb-3 space-y-1 text-[11px]">
            <div className="flex justify-between">
              <span className="text-gray-400">Edge ID:</span>
              <span className="font-mono font-bold text-white">{selectedRoad.id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Endpoints:</span>
              <span className="text-gray-200">
                {nodeMap[selectedRoad.from_node]?.label || selectedRoad.from_node} ↔ {nodeMap[selectedRoad.to_node]?.label || selectedRoad.to_node}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Current Status:</span>
              <span className={`font-bold ${selectedRoad.blocked ? 'text-red-400' : 'text-emerald-400'}`}>
                {selectedRoad.blocked ? '✕ BLOCKED' : '✓ OPEN'}
              </span>
            </div>
          </div>
          <button
            onClick={() => onApplyRoadBlock?.(selectedRoad.id, !selectedRoad.blocked)}
            className={`w-full font-bold py-2 rounded transition-colors text-xs flex items-center justify-center gap-1 shadow-lg cursor-pointer ${
              selectedRoad.blocked
                ? 'bg-emerald-600 hover:bg-emerald-500 text-white'
                : 'bg-red-600 hover:bg-red-500 text-white'
            }`}
          >
            <span>{selectedRoad.blocked ? '✓ Reopen Road Edge' : '✕ Block Road Edge'}</span>
          </button>
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* 9. COMPACT ON-GRAPH LEGEND (Bottom-Right)                      */}
      {/* ------------------------------------------------------------- */}
      <div className="absolute bottom-3 right-3 z-30 bg-[#0c121e]/90 border border-gray-800/90 rounded-lg p-2 shadow-xl backdrop-blur-md text-[10px] space-y-1.5 pointer-events-auto">
        <div className="flex items-center justify-between border-b border-gray-800/80 pb-1 gap-3">
          <span className="text-[9px] font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1">
            <span>🗺️</span> Network Legend
          </span>
          <button
            onClick={() => setLegendVisible(v => !v)}
            className="text-[9px] text-gray-500 hover:text-gray-300 cursor-pointer"
          >
            {legendVisible ? 'Hide' : 'Show'}
          </button>
        </div>

        {legendVisible && (
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-gray-300 text-[9.5px]">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full border border-sky-400 bg-sky-950 flex items-center justify-center text-[7px] text-sky-400 font-bold">●</span>
              <span>Central Depot</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full border border-gray-500 bg-slate-900" />
              <span>Location Node</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="px-1 py-0.5 rounded text-[7.5px] font-mono font-bold bg-blue-950/80 border border-blue-500 text-blue-300">📦 2</span>
              <span>Standard Orders</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="px-1 py-0.5 rounded text-[7.5px] font-mono font-bold bg-red-950/80 border border-red-500 text-red-300">★ 2</span>
              <span>P1 Rush Orders</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3.5 h-0.5 bg-amber-400 inline-block rounded" />
              <span>Congested Edge</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3.5 h-0.5 border-b border-dashed border-red-500 inline-block" />
              <span>Blocked Edge</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
