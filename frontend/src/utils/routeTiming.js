/**
 * routeTiming.js — Authoritative Client-Side Route Simulation & Timing Utility
 *
 * Implements the exact same deterministic route traversal timeline simulation
 * as backend `simulate_route_timeline` in `app/optimizer.py`.
 */

export function computeShortestPath(startNodeId, endNodeId, nodes = [], roads = []) {
  if (startNodeId === endNodeId) return [startNodeId]

  const adj = {}
  for (const r of roads) {
    if (r.blocked) continue // Blocked roads have infinite impedance
    const mult = r.traffic_multiplier || 1.0
    const time = Math.max(0.1, (r.base_time || 1.0) * mult)

    if (!adj[r.from_node]) adj[r.from_node] = []
    if (!adj[r.to_node]) adj[r.to_node] = []
    adj[r.from_node].push({ to: r.to_node, time })
    adj[r.to_node].push({ to: r.from_node, time })
  }

  const dist = {}
  const prev = {}
  const unvisited = new Set()

  for (const n of nodes) {
    dist[n.id] = Infinity
    unvisited.add(n.id)
  }
  dist[startNodeId] = 0

  while (unvisited.size > 0) {
    let curr = null
    let minDist = Infinity
    for (const id of unvisited) {
      if (dist[id] < minDist) {
        minDist = dist[id]
        curr = id
      }
    }

    if (curr === null || dist[curr] === Infinity) break
    if (curr === endNodeId) break

    unvisited.delete(curr)

    for (const edge of (adj[curr] || [])) {
      if (!unvisited.has(edge.to)) continue
      const alt = dist[curr] + edge.time
      if (alt < dist[edge.to]) {
        dist[edge.to] = alt
        prev[edge.to] = curr
      }
    }
  }

  if (dist[endNodeId] === Infinity) {
    return [startNodeId, endNodeId]
  }

  const path = []
  let u = endNodeId
  while (u) {
    path.unshift(u)
    u = prev[u]
  }
  return path
}

export function computeRouteTimelineMap(routes = [], vehicles = [], deliveries = [], nodes = [], roads = []) {
  const vehicleMap = Object.fromEntries(vehicles.map(v => [v.id, v]))
  const deliveryMap = Object.fromEntries(deliveries.map(d => [d.id, d]))
  const nodeMap = Object.fromEntries(nodes.map(n => [n.id, n]))
  const depot = nodes.find(n => n.is_depot) || nodes[0]

  const timelineMap = {}

  for (const r of routes) {
    const v = vehicleMap[r.vehicle_id]
    if (!v) continue

    let currentLocation = v.current_location || (depot ? depot.id : 'depot')
    let currentTime = 0.0
    const serviceTime = 5.0

    // Full node sequence for route
    const stopLocations = []
    if (depot) stopLocations.push(depot.id)
    for (const did of r.delivery_ids) {
      const d = deliveryMap[did]
      if (d) stopLocations.push(d.location)
    }
    if (depot && r.delivery_ids.length > 0) stopLocations.push(depot.id)

    for (let idx = 0; idx < r.delivery_ids.length; idx++) {
      const did = r.delivery_ids[idx]
      const deliv = deliveryMap[did]
      if (!deliv) continue

      // Leg transit time along shortest path
      const pathNodes = computeShortestPath(currentLocation, deliv.location, nodes, roads)
      let legTime = 0.0
      for (let i = 0; i < pathNodes.length - 1; i++) {
        const u = pathNodes[i], w = pathNodes[i + 1]
        const road = roads.find(rd => (rd.from_node === u && rd.to_node === w) || (rd.from_node === w && rd.to_node === u))
        if (road) {
          legTime += Math.max(0.1, (road.base_time || 1.0) * (road.traffic_multiplier || 1.0))
        } else {
          legTime += 2.0
        }
      }

      const arrivalTime = currentTime + legTime
      const isLate = arrivalTime > deliv.time_window_end
      const lateness = Math.max(0, arrivalTime - deliv.time_window_end)
      const spareTime = Math.max(0, deliv.time_window_end - arrivalTime)

      // Serviceability determination
      let isServiceable = true
      let serviceabilityReason = 'Feasible & On Schedule'

      if (v.status === 'BREAKDOWN') {
        isServiceable = false
        serviceabilityReason = 'Assigned vehicle has broken down'
      } else if (v.status === 'NOTACTIVATED') {
        isServiceable = false
        serviceabilityReason = 'Vehicle not activated'
      } else if (!r.feasible) {
        isServiceable = false
        serviceabilityReason = 'Route violates fleet constraints'
      } else if (isLate) {
        isServiceable = false
        serviceabilityReason = `Late delivery (+${Math.round(lateness * 10) / 10}m over window)`
      }

      timelineMap[did] = {
        did,
        delivery: deliv,
        vehicleId: v.id,
        vehicleName: v.name,
        vehicleStatus: v.status,
        route: r,
        stopIndex: idx + 1,
        totalStops: r.delivery_ids.length,
        arrivalTime: Math.round(arrivalTime * 10) / 10,
        isLate,
        lateness: Math.round(lateness * 10) / 10,
        spareTime: Math.round(spareTime * 10) / 10,
        isServiceable,
        serviceabilityReason,
        routeSequence: stopLocations,
        routeSequenceLabels: stopLocations.map(nid => nodeMap[nid]?.label || nid),
      }

      const serviceStart = Math.max(arrivalTime, deliv.time_window_start)
      currentTime = serviceStart + serviceTime
      currentLocation = deliv.location
    }
  }

  // Cover any unassigned or non-routed deliveries
  for (const d of deliveries) {
    if (!timelineMap[d.id]) {
      const isCancelled = d.status === 'CANCELLED'
      const assignedVeh = d.assigned_vehicle ? vehicleMap[d.assigned_vehicle] : null

      timelineMap[d.id] = {
        did: d.id,
        delivery: d,
        vehicleId: assignedVeh?.id || null,
        vehicleName: assignedVeh?.name || null,
        vehicleStatus: assignedVeh?.status || null,
        route: null,
        stopIndex: null,
        totalStops: 0,
        arrivalTime: null,
        isLate: false,
        lateness: 0,
        spareTime: 0,
        isServiceable: !isCancelled && Boolean(assignedVeh),
        serviceabilityReason: isCancelled
          ? 'Order cancelled by customer'
          : 'Pending assignment — run Optimize Scenario',
        routeSequence: [],
        routeSequenceLabels: [],
      }
    }
  }

  return timelineMap
}
