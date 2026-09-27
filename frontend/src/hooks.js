import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from './api'
import { computeRouteTimelineMap } from './utils/routeTiming'

function getEtaTimeline(state) {
  if (!state) return {}
  return computeRouteTimelineMap(
    state.routes || [],
    state.vehicles || [],
    state.deliveries || [],
    state.nodes || [],
    state.roads || [],
  )
}

function getScenarioSnapshotKey(state) {
  if (!state) return null
  // Include every input to ETA calculation and the event log. A repeated GET of
  // the same accepted snapshot must not erase its visible comparison.
  return JSON.stringify({
    routes: state.routes || [],
    vehicles: state.vehicles || [],
    deliveries: state.deliveries || [],
    nodes: state.nodes || [],
    roads: state.roads || [],
    events: state.events || [],
    simulation_time: state.simulation_time,
  })
}

function compareEtaTimelines(previousTimeline, nextTimeline, nextState) {
  const changes = {}
  const activeStatuses = new Set(['PENDING', 'IN_PROGRESS'])

  for (const delivery of nextState?.deliveries || []) {
    const before = previousTimeline?.[delivery.id]
    const after = nextTimeline[delivery.id]
    const previousEta = before?.arrivalTime
    const currentEta = after?.arrivalTime

    if (
      !activeStatuses.has(delivery.status) ||
      !activeStatuses.has(before?.delivery?.status) ||
      !Number.isFinite(previousEta) ||
      !Number.isFinite(currentEta)
    ) continue

    const delta = Number((currentEta - previousEta).toFixed(1))
    if (delta !== 0) {
      changes[delivery.id] = { previousEta, currentEta, delta }
    }
  }

  return changes
}

/**
 * Custom hook: fetches the full fleet state from the backend and
 * provides a manual refresh function and authoritative clock controls.
 * Auto-refreshes every `interval` ms (default 10s).
 */
export function useFleetState(interval = 10_000) {
  const [state, setStateInternal] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [etaChangesByDelivery, setEtaChangesByDelivery] = useState({})
  const latestRequest = useRef(0)
  const previousEtaTimeline = useRef(null)
  const acceptedSnapshotKey = useRef(null)
  const tickAccumulator = useRef(0)

  const acceptState = useCallback((nextState, { resetEtaHistory = false, forceTransition = false } = {}) => {
    const nextTimeline = getEtaTimeline(nextState)
    const nextSnapshotKey = getScenarioSnapshotKey(nextState)
    const isNewScenarioState = acceptedSnapshotKey.current !== null &&
      (forceTransition || nextSnapshotKey !== acceptedSnapshotKey.current)

    if (resetEtaHistory) {
      setEtaChangesByDelivery({})
    } else if (isNewScenarioState) {
      setEtaChangesByDelivery(compareEtaTimelines(previousEtaTimeline.current, nextTimeline, nextState))
    }

    previousEtaTimeline.current = nextTimeline
    acceptedSnapshotKey.current = nextSnapshotKey
    setStateInternal(nextState)
    setError(null)
    setLastUpdated(new Date())
    setLoading(false)
  }, [])

  // Accept each authoritative snapshot before replacing React state so the prior
  // ETA baseline cannot be lost to batching or an immediately following refresh.
  const setState = useCallback((nextState, options) => {
    latestRequest.current += 1
    acceptState(nextState, options)
  }, [acceptState])

  const fetchState = useCallback(async () => {
    const requestId = ++latestRequest.current
    try {
      const { data } = await api.getState()
      if (requestId !== latestRequest.current) return
      acceptState(data)
    } catch (err) {
      if (requestId !== latestRequest.current) return
      setError(err?.response?.data?.detail || err.message || 'Unknown error')
    } finally {
      if (requestId === latestRequest.current) setLoading(false)
    }
  }, [acceptState])

  // Simulation Clock API Actions
  const advanceTime = useCallback(async (minutes) => {
    try {
      const { data } = await api.advanceSimulationTime(minutes)
      if (data) setState(data)
      return data
    } catch (err) {
      console.error('Failed to advance simulation time:', err)
      throw err
    }
  }, [setState])

  const setSimulationClockTime = useCallback(async (options) => {
    try {
      const payload = typeof options === 'number'
        ? { simulation_time: options }
        : typeof options === 'string'
        ? { target_time_str: options }
        : options
      const { data } = await api.setSimulationTime(payload)
      if (data) setState(data)
      return data
    } catch (err) {
      console.error('Failed to set simulation time:', err)
      throw err
    }
  }, [setState])

  const togglePlayPause = useCallback(async () => {
    try {
      const isRunning = !(state?.is_running)
      const { data } = await api.controlSimulationTime({
        is_running: isRunning,
        speed_multiplier: state?.speed_multiplier || 1.0,
      })
      if (data) setState(data)
      return data
    } catch (err) {
      console.error('Failed to toggle play/pause:', err)
    }
  }, [state?.is_running, state?.speed_multiplier, setState])

  const setSpeedMultiplier = useCallback(async (speed) => {
    try {
      const { data } = await api.controlSimulationTime({
        is_running: state?.is_running ?? true,
        speed_multiplier: Number(speed),
      })
      if (data) setState(data)
      return data
    } catch (err) {
      console.error('Failed to set speed multiplier:', err)
    }
  }, [state?.is_running, setState])

  // Periodic polling
  useEffect(() => {
    fetchState()
    const timer = setInterval(fetchState, interval)
    return () => clearInterval(timer)
  }, [fetchState, interval])

  // Running Clock Ticker: when simulation is unpaused, smoothly ticks simulation time
  useEffect(() => {
    if (!state?.is_running) {
      tickAccumulator.current = 0
      return
    }

    const intervalMs = 1000
    const speed = state.speed_multiplier || 1.0
    // Minutes advanced per second: speed * (1 / 60)
    const minsPerSec = speed / 60.0

    const ticker = setInterval(async () => {
      tickAccumulator.current += minsPerSec

      // Sync with backend every 5 simulated seconds or when accumulated >= 1.0 min
      if (tickAccumulator.current >= 0.5) {
        const toAdvance = Math.round(tickAccumulator.current * 10) / 10
        tickAccumulator.current = 0
        try {
          const { data } = await api.advanceSimulationTime(toAdvance)
          if (data) setState(data)
        } catch {
          // ignore background tick sync error
        }
      } else {
        // Optimistic local state update for silky-smooth clock display
        setStateInternal(prev => {
          if (!prev) return prev
          const nextSimTime = (prev.simulation_time || 0) + minsPerSec
          return {
            ...prev,
            simulation_time: nextSimTime,
          }
        })
      }
    }, intervalMs)

    return () => clearInterval(ticker)
  }, [state?.is_running, state?.speed_multiplier, setState])

  return {
    state,
    setState,
    loading,
    error,
    lastUpdated,
    refresh: fetchState,
    etaChangesByDelivery,
    advanceTime,
    setSimulationClockTime,
    togglePlayPause,
    setSpeedMultiplier,
  }
}

