import { useState, useEffect } from 'react'
import { api } from '../api'
import OrderInspector from './OrderInspector'
import {
  formatSimulationTime,
  formatSimulationDate,
  formatTimeWindow,
  formatDuration,
  minutesToTimeInput,
  timeInputToMinutes,
} from '../utils/time'

/**
 * ScenarioBuilderPanel — Unified Scenario Builder & Modifier for RouterX.
 *
 * Replaces the deprecated Demo Walkthrough and Quick Events sections with ONE
 * coherent, uncluttered control tower interface for judges to:
 *   1. Inspect Live Scenario Status
 *   2. Modify Fleet, Deliveries, Network Conditions, and Constraints
 *   3. Run Curated Scenario Presets
 *   4. Track Pending Scenario Changes
 *   5. Trigger Scenario Optimization
 *   6. Review Scenario Change History
 *   7. Fresh Scenario (blank slate) & Authoritative Order Inspector
 */
export default function ScenarioBuilderPanel({
  state,
  timelineMap,
  etaChangesByDelivery,
  onEventProcessed,
  onOptimize,
  onReset,
  onFreshScenario,
  selectedDeliveryId,
  onSelectDelivery,
  onSelectVehicle,
  optimizing,
  loadingEvent,
  setLoadingEvent,
  lastEventResponse,
  mapMode,
  setMapMode,
  newStopDraft,
  setNewStopDraft,
  selectedRoadId,
  setSelectedRoadId,
  onAdvanceTime,
  onSetSimulationClockTime,
  onTogglePlayPause,
  onSetSpeedMultiplier,
}) {
  const { vehicles = [], deliveries = [], roads = [], nodes = [], events = [], metrics = {} } = state || {}

  // Mode tabs: 'controls' | 'orders'
  const [panelTab, setPanelTab] = useState('controls')
  const [showFreshConfirm, setShowFreshConfirm] = useState(false)
  const [isFreshState, setIsFreshState] = useState(false)

  // Active drawer/form: null | 'vehicle' | 'delivery' | 'node' | 'traffic' | 'breakdown' | 'block' | 'timewindow' | 'cancel' | 'presets'
  const [activeAction, setActiveAction] = useState(null)
  const [pendingChangesCount, setPendingChangesCount] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [actionFeedback, setActionFeedback] = useState(null)

  // Switch to orders tab when an order is selected
  useEffect(() => {
    if (selectedDeliveryId) {
      setPanelTab('orders')
    }
  }, [selectedDeliveryId])

  // Local form states
  const [vehForm, setVehForm] = useState({ name: 'Sprint Van', capacity: 120, driverHours: 8, location: 'depot' })
  const [delForm, setDelForm] = useState({ location: 'n01', demand: 15, priority: 1, twStart: 30, twEnd: 180, autoAssign: false })
  const [nodeForm, setNodeForm] = useState({ label: 'North Hub', lat: null, lon: null, connectTo: '' })
  const [trafficForm, setTrafficForm] = useState({ roadId: roads[0]?.id || 'road_000', multiplier: 3.5 })
  const [breakdownForm, setBreakdownForm] = useState({ vehicleId: vehicles.find(v => v.status === 'ACTIVE')?.id || 'v03', reason: 'Engine overheating' })
  const [blockForm, setBlockForm] = useState({ roadId: roads[0]?.id || 'road_000', blocked: true })
  const [twForm, setTwForm] = useState({ deliveryId: deliveries.find(d => d.status === 'PENDING')?.id || 'd01', start: 10, end: 90 })
  const [cancelForm, setCancelForm] = useState({ deliveryId: deliveries.find(d => d.status === 'PENDING')?.id || 'd01', reason: 'Customer requested cancellation' })

  // Synchronize road selection from map to traffic & block forms
  useEffect(() => {
    if (selectedRoadId) {
      setTrafficForm(prev => ({ ...prev, roadId: selectedRoadId }))
      setBlockForm(prev => ({ ...prev, roadId: selectedRoadId }))
    }
  }, [selectedRoadId])

  // Synchronize stop draft from map to node form
  useEffect(() => {
    if (newStopDraft) {
      setNodeForm(prev => ({
        ...prev,
        label: newStopDraft.label || prev.label || `Stop n${nodes.length + 1}`,
        lat: newStopDraft.lat ?? prev.lat,
        lon: newStopDraft.lon ?? prev.lon,
        connectTo: newStopDraft.connectToNodeId ?? prev.connectTo,
      }))
    }
  }, [newStopDraft, nodes.length])

  // Presets
  const [activePresetStep, setActivePresetStep] = useState(null)

  // Simulation Clock state
  const [showSetTimeModal, setShowSetTimeModal] = useState(false)
  const [customTimeVal, setCustomTimeVal] = useState('14:30')

  const handleApplyCustomTime = async () => {
    try {
      setLoadingEvent(true)
      const targetMins = timeInputToMinutes(state?.simulation_start_time, customTimeVal)
      if (onSetSimulationClockTime) {
        await onSetSimulationClockTime(targetMins)
      }
      setShowSetTimeModal(false)
      showFeedback(`Simulation clock set to ${formatSimulationTime(state?.simulation_start_time, targetMins)}`)
    } catch (err) {
      showFeedback(err?.message || 'Failed to set simulation time', true)
    } finally {
      setLoadingEvent(false)
    }
  }

  const showFeedback = (msg, isError = false) => {
    setActionFeedback({ text: msg, isError })
    setTimeout(() => setActionFeedback(null), 4000)
  }

  const handleToggleAction = (actionKey) => {
    if (activeAction === actionKey) {
      setActiveAction(null)
      if (setMapMode) setMapMode(null)
      if (setNewStopDraft) setNewStopDraft(null)
      if (setSelectedRoadId) setSelectedRoadId(null)
    } else {
      setActiveAction(actionKey)
      if (actionKey === 'node') {
        if (setMapMode) setMapMode('add_stop')
        if (setNewStopDraft) setNewStopDraft(null)
      } else if (actionKey === 'traffic') {
        if (setMapMode) setMapMode('select_road_traffic')
      } else if (actionKey === 'block') {
        if (setMapMode) setMapMode('select_road_block')
      } else {
        if (setMapMode) setMapMode(null)
      }
    }
  }

  const executeAction = async (fn, actionDesc) => {
    setSubmitting(true)
    if (setLoadingEvent) setLoadingEvent(true)
    try {
      const res = await fn()
      setPendingChangesCount(prev => prev + 1)
      showFeedback(`Applied: ${actionDesc}`)
      if (res?.data && onEventProcessed) {
        onEventProcessed(res.data)
      }
      setActiveAction(null)
      if (setMapMode) setMapMode(null)
      if (setNewStopDraft) setNewStopDraft(null)
      if (setSelectedRoadId) setSelectedRoadId(null)
    } catch (err) {
      console.error('Scenario action error:', err)
      showFeedback(err?.response?.data?.detail || err.message || 'Action failed', true)
    } finally {
      setSubmitting(false)
      if (setLoadingEvent) setLoadingEvent(false)
    }
  }

  // --- Handlers for Scenario Actions ---
  const handleAddVehicle = () => executeAction(async () => {
    const res = await api.addVehicle({
      name: vehForm.name,
      capacity: Number(vehForm.capacity),
      driver_hours_remaining: Number(vehForm.driverHours),
      current_location: vehForm.location,
    })
    return res
  }, `Vehicle ${vehForm.name}`)

  const handleAddDelivery = () => executeAction(async () => {
    const res = await api.addDelivery({
      location: delForm.location,
      demand: Number(delForm.demand),
      priority: Number(delForm.priority),
      time_window_start: Number(delForm.twStart),
      time_window_end: Number(delForm.twEnd),
      auto_assign: Boolean(delForm.autoAssign),
    })
    return res
  }, `Order at ${delForm.location} (P${delForm.priority})`)

  const handleAddNode = () => executeAction(async () => {
    const lat = newStopDraft?.lat ?? nodeForm.lat
    const lon = newStopDraft?.lon ?? nodeForm.lon
    const connectTo = newStopDraft?.connectToNodeId || nodeForm.connectTo
    const label = (newStopDraft?.label || nodeForm.label || `Stop n${nodes.length + 1}`).trim()

    if (lat === null || lon === null) {
      throw new Error('Please click on the map to place the new stop location first')
    }
    if (!connectTo) {
      throw new Error('Please click an existing stop on the map or select from dropdown to connect')
    }

    const res = await api.addNode({
      label: label,
      lat: Number(lat),
      lon: Number(lon),
      connect_to_node: connectTo,
    })
    return res
  }, `Stop ${nodeForm.label || 'New Stop'}`)

  const handleTrafficUpdate = () => executeAction(async () => {
    const res = await api.postTrafficEvent({
      road_id: trafficForm.roadId,
      traffic_multiplier: Number(trafficForm.multiplier),
    })
    return res
  }, `Traffic on ${trafficForm.roadId} (${trafficForm.multiplier}×)`)

  const handleBreakdown = () => executeAction(async () => {
    const res = await api.postBreakdownEvent({
      vehicle_id: breakdownForm.vehicleId,
      reason: breakdownForm.reason,
    })
    return res
  }, `Breakdown ${breakdownForm.vehicleId}`)

  const handleBlockRoad = (shouldBlock) => executeAction(async () => {
    const res = await api.postRoadBlockEvent({
      road_id: blockForm.roadId,
      blocked: shouldBlock,
    })
    return res
  }, `${shouldBlock ? 'Blocked' : 'Reopened'} ${blockForm.roadId}`)

  const handleTimeWindowChange = () => executeAction(async () => {
    const res = await api.postTimeWindowChangeEvent({
      delivery_id: twForm.deliveryId,
      new_window_start: Number(twForm.start),
      new_window_end: Number(twForm.end),
    })
    return res
  }, `Window for ${twForm.deliveryId}`)

  const handleCancelDelivery = () => executeAction(async () => {
    const res = await api.postCancelDeliveryEvent({
      delivery_id: cancelForm.deliveryId,
      reason: cancelForm.reason,
    })
    return res
  }, `Cancelled ${cancelForm.deliveryId}`)

  const handlePreset = (stepId, title) => executeAction(async () => {
    setActivePresetStep(stepId)
    const res = await api.executeDemoStep(stepId)
    setActivePresetStep(null)
    return res
  }, `Preset #${stepId}: ${title}`)

  const handleOptimizeScenario = async () => {
    setPendingChangesCount(0)
    if (onOptimize) await onOptimize()
  }

  const handleResetScenario = async () => {
    setPendingChangesCount(0)
    setActiveAction(null)
    setIsFreshState(false)
    if (onReset) await onReset()
  }

  const handleConfirmFreshScenario = async () => {
    setShowFreshConfirm(false)
    setPendingChangesCount(0)
    setActiveAction(null)
    setIsFreshState(true)
    if (onFreshScenario) await onFreshScenario()
  }

  const handleOpenTimeWindowForm = (deliv) => {
    setPanelTab('controls')
    setActiveAction('timewindow')
    setTwForm({
      deliveryId: deliv.id,
      start: deliv.time_window_start,
      end: deliv.time_window_end,
    })
  }

  const handleOpenCancelForm = (deliv) => {
    setPanelTab('controls')
    setActiveAction('cancel')
    setCancelForm({
      deliveryId: deliv.id,
      reason: 'Customer requested cancellation',
    })
  }

  // --- Derived Scenario Stats ---
  const activeVehicles = vehicles.filter(v => v.status === 'ACTIVE').length
  const breakdownVehicles = vehicles.filter(v => v.status === 'BREAKDOWN').length
  const pendingDeliveries = deliveries.filter(d => d.status === 'PENDING').length
  const p1Deliveries = deliveries.filter(d => d.status === 'PENDING' && d.priority === 1).length
  const blockedRoads = roads.filter(r => r.blocked).length
  const totalViolations = metrics?.total_violations ?? 0

  const isBusy = submitting || loadingEvent || optimizing

  return (
    <div className="flex-1 flex flex-col h-full min-h-0 bg-[#0a0e17] text-gray-100 overflow-hidden select-none border-l border-gray-800">
      {/* 1. TOP HEADER: TITLE & BADGE */}
      <div className="px-3 py-2 border-b border-gray-800 flex items-center justify-between bg-gray-950/90 flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-base">🛠️</span>
          <div>
            <div className="text-xs font-black uppercase tracking-wider text-white">Scenario Builder</div>
            <div className="text-[10px] text-gray-400">Logistics Condition Modifier</div>
          </div>
        </div>

        {/* Status Pill */}
        {pendingChangesCount > 0 ? (
          <span className="inline-flex items-center gap-1 text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40 px-2 py-0.5 rounded-full animate-pulse">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            {pendingChangesCount} modified
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-[10px] font-medium bg-emerald-950/60 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            Synchronized
          </span>
        )}
      </div>

      {/* Scenario-level actions */}
      <div className="px-3 py-1.5 border-b border-gray-800 bg-gray-950/50 flex-shrink-0">
        <div className="flex items-center justify-between gap-1.5">
          <span className="text-[9px] font-bold uppercase tracking-wider text-gray-500 whitespace-nowrap">Scenario</span>
          <div className="flex items-center gap-1.5 flex-1 justify-end">
            <button
              onClick={() => setShowFreshConfirm(true)}
              disabled={isBusy}
              className="flex-1 max-w-[130px] bg-purple-950/40 hover:bg-purple-900/60 border border-purple-600/50 hover:border-purple-500 text-purple-300 hover:text-purple-100 font-bold text-[10px] py-1 px-1.5 rounded transition-all flex items-center justify-center gap-1 cursor-pointer disabled:opacity-40 shadow-sm"
              title="Start a blank scenario: clears vehicles, deliveries, routes and events"
            >
              <span>✨</span>
              <span>+ Fresh</span>
            </button>
            <button
              onClick={handleResetScenario}
              disabled={isBusy}
              className="flex-1 max-w-[130px] bg-gray-900 hover:bg-gray-800 border border-gray-700/80 text-gray-300 hover:text-white font-bold text-[10px] py-1 px-1.5 rounded transition-colors flex items-center justify-center gap-1 cursor-pointer disabled:opacity-40 shadow-sm"
              title="Restore predefined RouterX demo scenario (8 vehicles, 40 deliveries)"
            >
              <span>🔄</span>
              <span>Reset</span>
            </button>
          </div>
        </div>
      </div>

      {/* SIMULATION CLOCK CONTROLLER */}
      <div className="px-3 py-1.5 border-b border-gray-800 bg-[#070b12] flex-shrink-0">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-1.5">
            <span className="text-xs">🕒</span>
            <span className="text-[9.5px] font-black uppercase tracking-wider text-cyan-400">Simulation Clock</span>
            <span className="text-[9px] text-gray-500 font-mono ml-0.5">
              {formatSimulationDate(state?.simulation_start_time, state?.simulation_time || 0)}
            </span>
          </div>
          <span className={`text-[8.5px] font-bold px-1.5 py-0.5 rounded-full border ${
            state?.is_running
              ? 'bg-emerald-950/60 text-emerald-300 border-emerald-500/40 animate-pulse'
              : 'bg-gray-900 text-gray-400 border-gray-700'
          }`}>
            {state?.is_running ? `▶ ${state?.speed_multiplier || 1}×` : '⏸ Paused'}
          </span>
        </div>

        {/* Digital Readout & Controls in clean row */}
        <div className="flex items-center justify-between gap-1">
          <div className="font-mono text-xs font-black text-cyan-300 tracking-tight bg-black/60 border border-gray-800/80 rounded px-1.5 py-0.5 whitespace-nowrap">
            {formatSimulationTime(state?.simulation_start_time, state?.simulation_time || 0, { includeSeconds: true })}
          </div>

          <div className="flex items-center gap-1 flex-1 justify-end">
            <button
              onClick={() => onAdvanceTime?.(-15)}
              disabled={isBusy}
              title="Rewind simulation by 15 minutes"
              className="bg-gray-900 hover:bg-gray-800 border border-gray-800 hover:border-gray-700 text-gray-300 font-mono text-[9.5px] px-1.5 py-0.5 rounded transition-colors disabled:opacity-40 cursor-pointer"
            >
              -15m
            </button>

            <button
              onClick={onTogglePlayPause}
              disabled={isBusy}
              title={state?.is_running ? 'Pause simulation clock' : 'Resume simulation clock'}
              className={`px-2 py-0.5 rounded text-[10px] font-bold transition-colors cursor-pointer border ${
                state?.is_running
                  ? 'bg-amber-600/20 border-amber-500/40 text-amber-300 hover:bg-amber-600/30'
                  : 'bg-emerald-600/20 border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/30'
              }`}
            >
              {state?.is_running ? '⏸' : '▶'}
            </button>

            <button
              onClick={() => onAdvanceTime?.(15)}
              disabled={isBusy}
              title="Advance simulation by 15 minutes"
              className="bg-gray-900 hover:bg-gray-800 border border-gray-800 hover:border-gray-700 text-gray-300 font-mono text-[9.5px] px-1.5 py-0.5 rounded transition-colors disabled:opacity-40 cursor-pointer"
            >
              +15m
            </button>

            {/* Speed Pills */}
            <div className="flex bg-gray-950 border border-gray-800 rounded p-0.5">
              {[1, 5, 10].map(sp => (
                <button
                  key={sp}
                  onClick={() => onSetSpeedMultiplier?.(sp)}
                  className={`text-[8.5px] px-1 py-0.2 rounded font-mono font-bold transition-colors cursor-pointer ${
                    (state?.speed_multiplier || 1) === sp
                      ? 'bg-cyan-600 text-white'
                      : 'text-gray-400 hover:text-gray-200'
                  }`}
                >
                  {sp}×
                </button>
              ))}
            </div>

            <button
              onClick={() => {
                setCustomTimeVal(minutesToTimeInput(state?.simulation_start_time, state?.simulation_time || 0))
                setShowSetTimeModal(v => !v)
              }}
              disabled={isBusy}
              title="Set custom simulation clock time"
              className="px-1.5 py-0.5 bg-gray-900 hover:bg-gray-800 border border-gray-800 hover:border-cyan-500/50 text-cyan-400 text-[9.5px] font-bold rounded transition-colors cursor-pointer"
            >
              Set
            </button>
          </div>
        </div>

        {/* Set Time Modal/Popover */}
        {showSetTimeModal && (
          <div className="mt-1.5 p-2 bg-gray-900 border border-cyan-500/50 rounded-lg text-xs space-y-1.5 shadow-xl">
            <div className="flex items-center justify-between text-[10px] text-gray-300 font-bold">
              <span>Set Simulation Time</span>
              <button onClick={() => setShowSetTimeModal(false)} className="text-gray-400 hover:text-white cursor-pointer">✕</button>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="time"
                value={customTimeVal}
                onChange={e => setCustomTimeVal(e.target.value)}
                className="flex-1 bg-black/80 border border-gray-700 rounded px-2 py-1 text-xs text-white font-mono focus:border-cyan-400 outline-none"
              />
              <button
                onClick={handleApplyCustomTime}
                className="bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-[10px] px-3 py-1 rounded transition-colors cursor-pointer"
              >
                Apply
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 1B. MODE TABS: SCENARIO CONTROLS vs ORDER INSPECTOR */}
      <div className="grid grid-cols-2 p-1 bg-gray-950/95 border-b border-gray-800 gap-1 flex-shrink-0">
        <button
          onClick={() => setPanelTab('controls')}
          className={`py-1 px-2 rounded text-[11px] font-bold transition-all flex items-center justify-center gap-1.5 cursor-pointer ${
            panelTab === 'controls'
              ? 'bg-blue-600 text-white shadow-sm'
              : 'text-gray-400 hover:text-gray-200 hover:bg-gray-900'
          }`}
        >
          <span>🛠️</span>
          <span>Controls</span>
        </button>

        <button
          onClick={() => setPanelTab('orders')}
          className={`py-1 px-2 rounded text-[11px] font-bold transition-all flex items-center justify-center gap-1.5 cursor-pointer ${
            panelTab === 'orders'
              ? 'bg-blue-600 text-white shadow-sm'
              : 'text-gray-400 hover:text-gray-200 hover:bg-gray-900'
          }`}
        >
          <span>📦</span>
          <span>Orders ({deliveries.length})</span>
        </button>
      </div>

      {panelTab === 'orders' ? (
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <OrderInspector
            state={state}
            timelineMap={timelineMap}
            etaChangesByDelivery={etaChangesByDelivery}
            selectedDeliveryId={selectedDeliveryId}
            onSelectDelivery={onSelectDelivery}
            onSelectVehicle={onSelectVehicle}
            onOpenTimeWindowForm={handleOpenTimeWindowForm}
            onOpenCancelForm={handleOpenCancelForm}
          />
        </div>
      ) : (
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {/* Subtle Fresh Scenario status banner */}
          {(isFreshState || (vehicles.length === 0 && deliveries.length === 0)) && (
            <div className="mx-3 mt-2 p-2 bg-purple-950/30 border border-purple-500/40 rounded-lg text-xs flex-shrink-0">
              <div className="font-black text-purple-300 text-[10.5px] flex items-center gap-1.5">
                <span>✨</span> FRESH SCENARIO
              </div>
              <div className="text-[10px] text-purple-200/80 mt-0.5">
                Build your fleet and delivery network using + Vehicle, + Delivery, or + Stop below.
              </div>
            </div>
          )}

          {/* Quick link to selected order if user is on controls tab */}
          {selectedDeliveryId && (
            <div className="mx-3 mt-1.5 px-2.5 py-1 rounded bg-cyan-950/50 border border-cyan-500/40 flex items-center justify-between text-xs flex-shrink-0">
              <span className="text-gray-300 text-[10px]">
                Selected Order: <strong className="font-mono text-cyan-300">{selectedDeliveryId.toUpperCase()}</strong>
              </span>
              <button
                onClick={() => setPanelTab('orders')}
                className="text-[10px] text-cyan-400 hover:underline font-bold cursor-pointer"
              >
                Inspect Details ›
              </button>
            </div>
          )}

          {/* SCROLLABLE MAIN CONTENT */}
          <div className="flex-1 overflow-y-auto min-h-0 divide-y divide-gray-800/60">
        
        {/* 2. SCENARIO LIVE SUMMARY */}
        <div className="p-3 bg-gray-900/40">
          <div className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2 flex items-center justify-between">
            <span>Scenario Environment</span>
            <span className="text-[9px] text-gray-500 font-mono">Live PostgreSQL</span>
          </div>

          <div className="grid grid-cols-3 gap-1.5">
            <div className="bg-gray-950/70 border border-gray-800/80 rounded p-1.5 text-center">
              <div className="text-[9px] text-gray-400">Fleet Active</div>
              <div className="text-xs font-black text-blue-400">{activeVehicles}/{vehicles.length}</div>
            </div>

            <div className="bg-gray-950/70 border border-gray-800/80 rounded p-1.5 text-center">
              <div className="text-[9px] text-gray-400">Pending Orders</div>
              <div className="text-xs font-black text-yellow-400">{pendingDeliveries} <span className="text-[9px] text-red-400">({p1Deliveries} P1)</span></div>
            </div>

            <div className="bg-gray-950/70 border border-gray-800/80 rounded p-1.5 text-center">
              <div className="text-[9px] text-gray-400">Delivered Orders</div>
              <div className="text-xs font-black text-emerald-400">
                {deliveries.filter(d => d.status === 'DELIVERED').length}/{deliveries.length}
              </div>
            </div>

            <div className="bg-gray-950/70 border border-gray-800/80 rounded p-1.5 text-center">
              <div className="text-[9px] text-gray-400">Breakdowns</div>
              <div className={`text-xs font-black ${breakdownVehicles > 0 ? 'text-red-400' : 'text-gray-400'}`}>
                {breakdownVehicles}
              </div>
            </div>

            <div className="bg-gray-950/70 border border-gray-800/80 rounded p-1.5 text-center">
              <div className="text-[9px] text-gray-400">Blocked Roads</div>
              <div className={`text-xs font-black ${blockedRoads > 0 ? 'text-orange-400' : 'text-gray-400'}`}>
                {blockedRoads}
              </div>
            </div>

            <div className="bg-gray-950/70 border border-gray-800/80 rounded p-1.5 text-center">
              <div className="text-[9px] text-gray-400">Network Nodes</div>
              <div className="text-xs font-black text-cyan-400">{nodes.length}</div>
            </div>
          </div>
        </div>

        {/* 3. SCENARIO BUILDER CONTROLS */}
        <div className="p-3 space-y-3">
          {/* GROUP 1: SCENARIO ASSETS */}
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-cyan-400 mb-1.5 flex items-center justify-between">
              <span>Scenario Assets</span>
              <span className="text-[9px] text-gray-500 font-mono">Structural</span>
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              <ActionTab
                icon="➕"
                title="Vehicle"
                desc="Deploy van"
                active={activeAction === 'vehicle'}
                onClick={() => handleToggleAction('vehicle')}
              />
              <ActionTab
                icon="📦"
                title="Delivery"
                desc="New order"
                active={activeAction === 'delivery'}
                onClick={() => handleToggleAction('delivery')}
              />
              <ActionTab
                icon="📍"
                title="Stop"
                desc="Graph node"
                active={activeAction === 'node'}
                onClick={() => handleToggleAction('node')}
              />
            </div>
          </div>

          {/* GROUP 2: OPERATIONAL EVENTS */}
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider text-amber-400 mb-1.5 flex items-center justify-between">
              <span>Operational Events</span>
              <span className="text-[9px] text-gray-500 font-mono">Disruptions</span>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              <ActionTab
                icon="🚦"
                title="Traffic Jam"
                desc="Congest edge"
                active={activeAction === 'traffic'}
                onClick={() => handleToggleAction('traffic')}
              />
              <ActionTab
                icon="🔧"
                title="Breakdown"
                desc="Disable van"
                active={activeAction === 'breakdown'}
                onClick={() => handleToggleAction('breakdown')}
              />
              <ActionTab
                icon="🚧"
                title="Block Road"
                desc="Cut network edge"
                active={activeAction === 'block'}
                onClick={() => handleToggleAction('block')}
              />
              <ActionTab
                icon="⏱️"
                title="Time Window"
                desc="Expedite window"
                active={activeAction === 'timewindow'}
                onClick={() => handleToggleAction('timewindow')}
              />
              <ActionTab
                icon="❌"
                title="Cancel Order"
                desc="Drop stop"
                active={activeAction === 'cancel'}
                onClick={() => handleToggleAction('cancel')}
              />
            </div>
          </div>

          {/* INLINE MODIFIER FORM DRAWER */}
          {activeAction && (
            <div className="bg-gray-900 border border-blue-500/40 rounded-lg p-3 shadow-xl mb-2 animate-fadeIn text-xs">
              
              {/* Form 1: Add Vehicle */}
              {activeAction === 'vehicle' && (
                <div className="space-y-2">
                  <div className="font-bold text-white flex items-center justify-between border-b border-gray-800 pb-1">
                    <span>➕ Add Vehicle to Fleet</span>
                    <button onClick={() => setActiveAction(null)} className="text-gray-400 hover:text-white">✕</button>
                  </div>
                  <div>
                    <label className="text-[10px] text-gray-400">Vehicle Name</label>
                    <input
                      type="text"
                      value={vehForm.name}
                      onChange={e => setVehForm({ ...vehForm, name: e.target.value })}
                      className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="text-[10px] text-gray-400">Capacity (kg)</label>
                      <input
                        type="number"
                        value={vehForm.capacity}
                        onChange={e => setVehForm({ ...vehForm, capacity: e.target.value })}
                        className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] text-gray-400">Shift (Hours)</label>
                      <input
                        type="number"
                        value={vehForm.driverHours}
                        onChange={e => setVehForm({ ...vehForm, driverHours: e.target.value })}
                        className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] text-gray-400">Starting Location</label>
                    <select
                      value={vehForm.location}
                      onChange={e => setVehForm({ ...vehForm, location: e.target.value })}
                      className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                    >
                      <option value="depot">Central Depot (depot)</option>
                      {nodes.filter(n => !n.is_depot).map(n => (
                        <option key={n.id} value={n.id}>{n.label || n.id} ({n.id})</option>
                      ))}
                    </select>
                  </div>
                  <button
                    onClick={handleAddVehicle}
                    disabled={isBusy}
                    className="w-full bg-blue-600 hover:bg-blue-500 font-bold py-1.5 rounded text-white text-xs transition-colors"
                  >
                    Deploy Vehicle
                  </button>
                </div>
              )}

              {/* Form 2: Add Delivery */}
              {activeAction === 'delivery' && (
                <div className="space-y-2">
                  <div className="font-bold text-white flex items-center justify-between border-b border-gray-800 pb-1">
                    <span>📦 Add Delivery Order</span>
                    <button onClick={() => setActiveAction(null)} className="text-gray-400 hover:text-white">✕</button>
                  </div>
                  <div>
                    <label className="text-[10px] text-gray-400">Delivery Location</label>
                    <select
                      value={delForm.location}
                      onChange={e => setDelForm({ ...delForm, location: e.target.value })}
                      className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                    >
                      {nodes.filter(n => !n.is_depot).map(n => (
                        <option key={n.id} value={n.id}>{n.label || n.id} ({n.id})</option>
                      ))}
                    </select>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="text-[10px] text-gray-400">Demand (kg)</label>
                      <input
                        type="number"
                        value={delForm.demand}
                        onChange={e => setDelForm({ ...delForm, demand: e.target.value })}
                        className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] text-gray-400">Priority Tier</label>
                      <select
                        value={delForm.priority}
                        onChange={e => setDelForm({ ...delForm, priority: Number(e.target.value) })}
                        className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                      >
                        <option value={1}>P1 — Urgent / Medical</option>
                        <option value={2}>P2 — Standard Business</option>
                        <option value={3}>P3 — Flexible E-comm</option>
                      </select>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="text-[10px] text-gray-400">Window Start Time</label>
                      <input
                        type="time"
                        value={minutesToTimeInput(state?.simulation_start_time, delForm.twStart)}
                        onChange={e => setDelForm({ ...delForm, twStart: timeInputToMinutes(state?.simulation_start_time, e.target.value) })}
                        className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs font-mono"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] text-gray-400">Window End Time</label>
                      <input
                        type="time"
                        value={minutesToTimeInput(state?.simulation_start_time, delForm.twEnd)}
                        onChange={e => setDelForm({ ...delForm, twEnd: timeInputToMinutes(state?.simulation_start_time, e.target.value) })}
                        className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs font-mono"
                      />
                    </div>
                  </div>
                  <div className="text-[9.5px] text-cyan-400 font-mono">
                    Window: {formatTimeWindow(state?.simulation_start_time, delForm.twStart, delForm.twEnd)} ({formatDuration(delForm.twEnd - delForm.twStart)})
                  </div>
                  <div className="flex items-center gap-2 pt-1">
                    <input
                      type="checkbox"
                      id="autoAssign"
                      checked={delForm.autoAssign}
                      onChange={e => setDelForm({ ...delForm, autoAssign: e.target.checked })}
                      className="rounded bg-black border-gray-700"
                    />
                    <label htmlFor="autoAssign" className="text-[10px] text-gray-300">Auto-route immediately via Event Engine</label>
                  </div>
                  <button
                    onClick={handleAddDelivery}
                    disabled={isBusy}
                    className="w-full bg-yellow-600 hover:bg-yellow-500 font-bold py-1.5 rounded text-white text-xs transition-colors"
                  >
                    Add Order to Scenario
                  </button>
                </div>
              )}

              {/* Form 3: Add Stop / Node (Map-Based Workflow) */}
              {activeAction === 'node' && (
                <div className="space-y-2">
                  <div className="font-bold text-white flex items-center justify-between border-b border-gray-800 pb-1">
                    <span className="flex items-center gap-1.5 text-cyan-300">
                      <span>📍</span> Add Routable Stop (Map-Based)
                    </span>
                    <button onClick={() => handleToggleAction('node')} className="text-gray-400 hover:text-white">✕</button>
                  </div>

                  {/* Interactive Map Step Tracker */}
                  <div className="bg-cyan-950/40 border border-cyan-800/50 rounded-lg p-2.5 space-y-2">
                    <div className="flex items-center gap-2">
                      <span className={`w-5 h-5 rounded-full flex items-center justify-center font-bold text-[10px] ${
                        newStopDraft?.lat ? 'bg-green-600 text-white' : 'bg-cyan-600 text-white animate-pulse'
                      }`}>
                        {newStopDraft?.lat ? '✓' : '1'}
                      </span>
                      <div className="flex-1">
                        <div className="text-xs font-semibold text-gray-200">
                          {newStopDraft?.lat ? 'Stop Location Placed' : 'Click Map for Stop Location'}
                        </div>
                        <div className="text-[10px] text-gray-400">
                          {newStopDraft?.lat
                            ? `Lat: ${newStopDraft.lat.toFixed(4)}, Lon: ${newStopDraft.lon.toFixed(4)}`
                            : 'Click anywhere on the map to set the stop coordinates'}
                        </div>
                      </div>
                      {newStopDraft?.lat && (
                        <button
                          onClick={() => setNewStopDraft(null)}
                          className="text-[10px] text-cyan-400 hover:underline"
                        >
                          Re-pick
                        </button>
                      )}
                    </div>

                    <div className="flex items-center gap-2 border-t border-cyan-900/50 pt-2">
                      <span className={`w-5 h-5 rounded-full flex items-center justify-center font-bold text-[10px] ${
                        newStopDraft?.connectToNodeId
                          ? 'bg-green-600 text-white'
                          : newStopDraft?.lat
                          ? 'bg-cyan-600 text-white animate-pulse'
                          : 'bg-gray-800 text-gray-400'
                      }`}>
                        {newStopDraft?.connectToNodeId ? '✓' : '2'}
                      </span>
                      <div className="flex-1">
                        <div className="text-xs font-semibold text-gray-200">
                          {newStopDraft?.connectToNodeId ? 'Linked to Existing Stop' : 'Select Stop to Connect'}
                        </div>
                        <div className="text-[10px] text-gray-400">
                          {newStopDraft?.connectToNodeId
                            ? `${nodes.find(n => n.id === newStopDraft.connectToNodeId)?.label || newStopDraft.connectToNodeId}`
                            : newStopDraft?.lat
                            ? 'Click an existing node marker on the map or pick below'
                            : 'Place stop location on map first'}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div>
                    <label className="text-[10px] text-gray-400">Stop Name / Label</label>
                    <input
                      type="text"
                      value={nodeForm.label}
                      onChange={e => {
                        setNodeForm({ ...nodeForm, label: e.target.value })
                        if (newStopDraft) setNewStopDraft({ ...newStopDraft, label: e.target.value })
                      }}
                      placeholder="e.g. North Terminal"
                      className="w-full bg-black/60 border border-gray-700 rounded px-2.5 py-1 text-white text-xs focus:border-cyan-500 outline-none"
                    />
                  </div>

                  <div>
                    <label className="text-[10px] text-gray-400">Connect to Existing Node (or click on map)</label>
                    <select
                      value={newStopDraft?.connectToNodeId || nodeForm.connectTo}
                      onChange={e => {
                        setNodeForm({ ...nodeForm, connectTo: e.target.value })
                        if (newStopDraft) setNewStopDraft({ ...newStopDraft, connectToNodeId: e.target.value })
                      }}
                      className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                    >
                      <option value="">-- Click map or choose node --</option>
                      {nodes.map(n => (
                        <option key={n.id} value={n.id}>{n.label || n.id} ({n.id})</option>
                      ))}
                    </select>
                  </div>

                  <button
                    onClick={handleAddNode}
                    disabled={isBusy || !newStopDraft?.lat || (!newStopDraft?.connectToNodeId && !nodeForm.connectTo)}
                    className="w-full bg-cyan-600 hover:bg-cyan-500 disabled:opacity-40 disabled:hover:bg-cyan-600 font-bold py-1.5 rounded text-white text-xs transition-colors flex items-center justify-center gap-1 shadow-lg"
                  >
                    <span>✓</span> Deploy Stop & Connect Road
                  </button>
                </div>
              )}

              {/* Form 4: Traffic Update (Map Click Supported) */}
              {activeAction === 'traffic' && (
                <div className="space-y-2">
                  <div className="font-bold text-white flex items-center justify-between border-b border-gray-800 pb-1">
                    <span className="flex items-center gap-1.5 text-amber-300">
                      <span>🚦</span> Modify Traffic Multiplier
                    </span>
                    <button onClick={() => handleToggleAction('traffic')} className="text-gray-400 hover:text-white">✕</button>
                  </div>

                  <div className="bg-amber-950/30 border border-amber-800/40 rounded p-2 text-[11px] text-amber-300 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping flex-shrink-0" />
                    <span>Click any road on the map to select it, or pick below:</span>
                  </div>

                  <div>
                    <label className="text-[10px] text-gray-400">Road Segment</label>
                    <select
                      value={trafficForm.roadId}
                      onChange={e => {
                        setTrafficForm({ ...trafficForm, roadId: e.target.value })
                        if (setSelectedRoadId) setSelectedRoadId(e.target.value)
                      }}
                      className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs font-mono"
                    >
                      {roads.map(r => (
                        <option key={r.id} value={r.id}>
                          {r.id}: {r.from_node} ↔ {r.to_node} (Current: {r.traffic_multiplier}×)
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <div className="flex justify-between text-[10px] text-gray-400 mb-1">
                      <span>Multiplier: <strong className="text-amber-400 text-xs">{trafficForm.multiplier}×</strong></span>
                      <span>1.0× (Normal) to 5.0× (Gridlock)</span>
                    </div>
                    <input
                      type="range"
                      min="1.0"
                      max="5.0"
                      step="0.5"
                      value={trafficForm.multiplier}
                      onChange={e => setTrafficForm({ ...trafficForm, multiplier: Number(e.target.value) })}
                      className="w-full accent-amber-500"
                    />
                    <div className="flex justify-between gap-1 mt-1">
                      {[1.0, 2.0, 3.5, 5.0].map(val => (
                        <button
                          key={val}
                          onClick={() => setTrafficForm({ ...trafficForm, multiplier: val })}
                          className={`flex-1 py-0.5 rounded text-[10px] font-bold border transition-colors ${
                            Number(trafficForm.multiplier) === val
                              ? 'bg-amber-500 text-black border-amber-400'
                              : 'bg-gray-900 text-gray-300 border-gray-700 hover:border-amber-500/50'
                          }`}
                        >
                          {val}×
                        </button>
                      ))}
                    </div>
                  </div>
                  <button
                    onClick={handleTrafficUpdate}
                    disabled={isBusy}
                    className="w-full bg-amber-600 hover:bg-amber-500 font-bold py-1.5 rounded text-white text-xs transition-colors shadow-lg"
                  >
                    Apply Traffic Spike
                  </button>
                </div>
              )}

              {/* Form 5: Vehicle Breakdown */}
              {activeAction === 'breakdown' && (
                <div className="space-y-2">
                  <div className="font-bold text-white flex items-center justify-between border-b border-gray-800 pb-1">
                    <span>🔧 Force Vehicle Breakdown</span>
                    <button onClick={() => handleToggleAction('breakdown')} className="text-gray-400 hover:text-white">✕</button>
                  </div>
                  <div>
                    <label className="text-[10px] text-gray-400">Active Vehicle</label>
                    <select
                      value={breakdownForm.vehicleId}
                      onChange={e => setBreakdownForm({ ...breakdownForm, vehicleId: e.target.value })}
                      className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                    >
                      {vehicles.filter(v => v.status === 'ACTIVE').map(v => (
                        <option key={v.id} value={v.id}>
                          {v.name} ({v.id}) — Load: {v.current_load.toFixed(1)}kg
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-gray-400">Failure Reason</label>
                    <input
                      type="text"
                      value={breakdownForm.reason}
                      onChange={e => setBreakdownForm({ ...breakdownForm, reason: e.target.value })}
                      className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                    />
                  </div>
                  <button
                    onClick={handleBreakdown}
                    disabled={isBusy}
                    className="w-full bg-red-600 hover:bg-red-500 font-bold py-1.5 rounded text-white text-xs transition-colors"
                  >
                    Trigger Breakdown Event
                  </button>
                </div>
              )}

              {/* Form 6: Block / Reopen Road (Map Click Supported) */}
              {activeAction === 'block' && (
                <div className="space-y-2">
                  <div className="font-bold text-white flex items-center justify-between border-b border-gray-800 pb-1">
                    <span className="flex items-center gap-1.5 text-orange-300">
                      <span>🚧</span> Block / Reopen Road
                    </span>
                    <button onClick={() => handleToggleAction('block')} className="text-gray-400 hover:text-white">✕</button>
                  </div>

                  <div className="bg-orange-950/30 border border-orange-800/40 rounded p-2 text-[11px] text-orange-300 flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-orange-400 animate-ping flex-shrink-0" />
                    <span>Click any road on the map to select it, or pick below:</span>
                  </div>

                  <div>
                    <label className="text-[10px] text-gray-400">Road Segment</label>
                    <select
                      value={blockForm.roadId}
                      onChange={e => {
                        setBlockForm({ ...blockForm, roadId: e.target.value })
                        if (setSelectedRoadId) setSelectedRoadId(e.target.value)
                      }}
                      className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs font-mono"
                    >
                      {roads.map(r => (
                        <option key={r.id} value={r.id}>
                          {r.id}: {r.from_node} ↔ {r.to_node} ({r.blocked ? 'BLOCKED' : 'OPEN'})
                        </option>
                      ))}
                    </select>
                  </div>

                  {(() => {
                    const curRoad = roads.find(r => r.id === blockForm.roadId)
                    return (
                      <div className="bg-gray-950 p-2 rounded border border-gray-800 text-[11px] flex justify-between">
                        <span className="text-gray-400">Current Status:</span>
                        <span className={`font-bold ${curRoad?.blocked ? 'text-red-400' : 'text-green-400'}`}>
                          {curRoad?.blocked ? '🚧 BLOCKED' : '🟢 OPEN & TRAVERSABLE'}
                        </span>
                      </div>
                    )
                  })()}

                  <div className="flex gap-2">
                    <button
                      onClick={() => handleBlockRoad(true)}
                      disabled={isBusy}
                      className="flex-1 bg-orange-700 hover:bg-orange-600 font-bold py-1.5 rounded text-white text-xs transition-colors shadow"
                    >
                      Block Road
                    </button>
                    <button
                      onClick={() => handleBlockRoad(false)}
                      disabled={isBusy}
                      className="flex-1 bg-green-700 hover:bg-green-600 font-bold py-1.5 rounded text-white text-xs transition-colors shadow"
                    >
                      Reopen Road
                    </button>
                  </div>
                </div>
              )}

              {/* Form 7: Time Window Change */}
              {activeAction === 'timewindow' && (
                <div className="space-y-2">
                  <div className="font-bold text-white flex items-center justify-between border-b border-gray-800 pb-1">
                    <span>⏱️ Reschedule Delivery Window</span>
                    <button onClick={() => setActiveAction(null)} className="text-gray-400 hover:text-white">✕</button>
                  </div>
                  <div>
                    <label className="text-[10px] text-gray-400">Pending Delivery</label>
                    <select
                      value={twForm.deliveryId}
                      onChange={e => setTwForm({ ...twForm, deliveryId: e.target.value })}
                      className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                    >
                      {deliveries.filter(d => d.status === 'PENDING').map(d => (
                        <option key={d.id} value={d.id}>
                          {d.id} @ {d.location} (Current: {formatTimeWindow(state?.simulation_start_time, d.time_window_start, d.time_window_end)})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="text-[10px] text-gray-400">New Window Start</label>
                      <input
                        type="time"
                        value={minutesToTimeInput(state?.simulation_start_time, twForm.start)}
                        onChange={e => setTwForm({ ...twForm, start: timeInputToMinutes(state?.simulation_start_time, e.target.value) })}
                        className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs font-mono"
                      />
                    </div>
                    <div>
                      <label className="text-[10px] text-gray-400">New Window End</label>
                      <input
                        type="time"
                        value={minutesToTimeInput(state?.simulation_start_time, twForm.end)}
                        onChange={e => setTwForm({ ...twForm, end: timeInputToMinutes(state?.simulation_start_time, e.target.value) })}
                        className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs font-mono"
                      />
                    </div>
                  </div>
                  <div className="text-[9.5px] text-cyan-400 font-mono">
                    New Window: {formatTimeWindow(state?.simulation_start_time, twForm.start, twForm.end)} ({formatDuration(twForm.end - twForm.start)})
                  </div>
                  <button
                    onClick={handleTimeWindowChange}
                    disabled={isBusy}
                    className="w-full bg-cyan-600 hover:bg-cyan-500 font-bold py-1.5 rounded text-white text-xs transition-colors"
                  >
                    Update Delivery Window
                  </button>
                </div>
              )}

              {/* Form 8: Cancel Delivery */}
              {activeAction === 'cancel' && (
                <div className="space-y-2">
                  <div className="font-bold text-white flex items-center justify-between border-b border-gray-800 pb-1">
                    <span>❌ Cancel Delivery</span>
                    <button onClick={() => setActiveAction(null)} className="text-gray-400 hover:text-white">✕</button>
                  </div>
                  <div>
                    <label className="text-[10px] text-gray-400">Delivery to Cancel</label>
                    <select
                      value={cancelForm.deliveryId}
                      onChange={e => setCancelForm({ ...cancelForm, deliveryId: e.target.value })}
                      className="w-full bg-black/60 border border-gray-700 rounded px-2 py-1 text-white text-xs"
                    >
                      {deliveries.filter(d => d.status === 'PENDING').map(d => (
                        <option key={d.id} value={d.id}>
                          {d.id} @ {d.location} ({d.demand}kg · Veh: {d.assigned_vehicle || 'None'})
                        </option>
                      ))}
                    </select>
                  </div>
                  <button
                    onClick={handleCancelDelivery}
                    disabled={isBusy}
                    className="w-full bg-red-800 hover:bg-red-700 font-bold py-1.5 rounded text-white text-xs transition-colors"
                  >
                    Confirm Cancellation
                  </button>
                </div>
              )}

            </div>
          )}

          {/* 4. PRESET SCENARIO TEMPLATES (Absorbed cleanly from old Demo Walkthrough) */}
          <div className="mt-3 pt-3 border-t border-gray-800/80">
            <div className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-1.5 flex items-center justify-between">
              <span>Benchmark Presets</span>
              <span className="text-[9px] text-emerald-400 font-bold">1-Click Curated</span>
            </div>

            <div className="grid grid-cols-2 gap-1.5">
              <PresetButton
                icon="🚦"
                title="1. Traffic Jam"
                detail="Central Artery 4.5×"
                active={activePresetStep === 1}
                disabled={isBusy}
                onClick={() => handlePreset(1, 'Traffic Jam on Central Artery')}
              />
              <PresetButton
                icon="🔧"
                title="2. Van Failure"
                detail="V03 Breakdown & Offload"
                active={activePresetStep === 2}
                disabled={isBusy}
                onClick={() => handlePreset(2, 'Vehicle V03 Breakdown')}
              />
              <PresetButton
                icon="⚡"
                title="3. Rush Order"
                detail="P1 Medical at n07"
                active={activePresetStep === 3}
                disabled={isBusy}
                onClick={() => handlePreset(3, 'Urgent P1 Medical Order')}
              />
              <PresetButton
                icon="⏰"
                title="4. Expedited"
                detail="d12 Window to 25m"
                active={activePresetStep === 4}
                disabled={isBusy}
                onClick={() => handlePreset(4, 'Expedited Customer Window')}
              />
            </div>
          </div>
        </div>

        {/* 5. PRIMARY OPTIMIZATION & SCENARIO ACTIONS */}
        <div className="p-3 bg-gray-950/90 border-t border-gray-800/80 space-y-2 flex-shrink-0">
          {/* Main Optimize button */}
          <button
            onClick={handleOptimizeScenario}
            disabled={isBusy}
            className={`w-full font-black text-xs py-2 px-3 rounded-lg shadow-lg flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
              pendingChangesCount > 0 || totalViolations > 0
                ? 'bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white shadow-blue-500/25 ring-2 ring-blue-400 animate-pulse'
                : 'bg-blue-600 hover:bg-blue-500 text-white'
            } disabled:opacity-40`}
          >
            <span>⚡</span>
            <span>{optimizing ? 'Optimizing Fleet...' : 'Optimize Scenario'}</span>
          </button>
        </div>

        {/* 6. COMPACT OPTIMIZATION RESULT SUMMARY (When available) */}
        {lastEventResponse && (
          <div className="p-3 bg-gray-900/60 border-t border-gray-800">
            <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-400 mb-1 flex items-center gap-1">
              <span>✅</span> Optimization Complete
            </div>
            
            {/* Before -> After mini metrics */}
            <div className="bg-black/40 rounded p-2 border border-gray-800 space-y-1 text-[11px]">
              <div className="flex justify-between">
                <span className="text-gray-400">Total Distance:</span>
                <span className="font-mono text-gray-200">
                  {lastEventResponse.before_metrics?.total_distance ?? lastEventResponse.before?.distance ?? '—'} km
                  {' → '}
                  <strong className="text-cyan-400">{lastEventResponse.after_metrics?.total_distance ?? lastEventResponse.after?.distance ?? '—'} km</strong>
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Total Travel Time:</span>
                <span className="font-mono text-gray-200">
                  {Math.round(lastEventResponse.before_metrics?.total_travel_time ?? lastEventResponse.before?.travel_time ?? 0)} m
                  {' → '}
                  <strong className="text-cyan-400">{Math.round(lastEventResponse.after_metrics?.total_travel_time ?? lastEventResponse.after?.travel_time ?? 0)} m</strong>
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Total Violations:</span>
                <span className="font-mono text-gray-200">
                  {lastEventResponse.before_metrics?.total_violations ?? lastEventResponse.before?.total_violations ?? 0}
                  {' → '}
                  <strong className="text-emerald-400">{lastEventResponse.after_metrics?.total_violations ?? lastEventResponse.after?.total_violations ?? 0}</strong>
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Routes Changed:</span>
                <strong className="text-amber-400">
                  {(lastEventResponse.changed_routes || lastEventResponse.routes_changed || []).length}
                </strong>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Orders Reassigned:</span>
                <strong className="text-blue-400">
                  {(lastEventResponse.reassigned_deliveries || lastEventResponse.deliveries_reassigned || []).length}
                </strong>
              </div>
            </div>

            {/* Decision explanation text */}
            {(lastEventResponse.decision_explanation || lastEventResponse.explanation) && (
              <p className="text-[10px] text-gray-300 mt-1.5 leading-relaxed bg-blue-950/20 p-1.5 rounded border border-blue-900/40">
                {lastEventResponse.decision_explanation || lastEventResponse.explanation}
              </p>
            )}
          </div>
        )}

        {/* 7. SCENARIO HISTORY TIMELINE */}
        <div className="p-3">
          <div className="text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-2 flex items-center justify-between">
            <span>Scenario Change History</span>
            <span className="text-[9px] text-gray-500 font-mono">{events.length} logged</span>
          </div>

          {events.length === 0 ? (
            <div className="text-[11px] text-gray-500 italic py-2 text-center">
              No modifications yet. Select a tool above to inject scenario changes.
            </div>
          ) : (
            <div className="space-y-1 max-h-40 overflow-y-auto pr-1">
              {[...events].reverse().slice(0, 10).map((ev, i) => (
                <div key={ev.id || i} className="text-[10px] bg-black/30 border border-gray-800/80 rounded px-2 py-1 flex items-center justify-between">
                  <div className="flex items-center gap-1.5 truncate">
                    <span>{getEventIcon(ev.event_type)}</span>
                    <span className="font-semibold text-gray-200">{formatEventType(ev.event_type)}</span>
                    <span className="text-gray-400 font-mono truncate max-w-[100px]">{ev.affected_entity_id}</span>
                  </div>
                  <span className="text-[9px] text-gray-500 flex-shrink-0 font-mono">
                    {ev.timestamp ? `${Math.round(ev.timestamp)}m` : 'now'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )}

      {/* CONFIRMATION DIALOG: START FRESH SCENARIO */}
      {showFreshConfirm && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#0f172a] border border-purple-500/60 rounded-xl shadow-2xl max-w-md w-full p-5 space-y-4 text-gray-200 animate-fadeIn">
            <div className="flex items-center gap-2.5 text-purple-400">
              <span className="text-xl">✨</span>
              <h3 className="text-sm font-black uppercase tracking-wider text-white">Start Fresh Scenario?</h3>
            </div>

            <div className="text-xs text-gray-300 space-y-2.5">
              <p className="text-gray-400">
                This will clear the current operational scenario so you can build a completely new scenario from scratch:
              </p>
              <ul className="grid grid-cols-2 gap-1 text-[11px] font-mono text-gray-300 bg-black/40 p-2.5 rounded border border-gray-800">
                <li className="flex items-center gap-1.5 text-red-300">✕ Vehicles ({vehicles.length})</li>
                <li className="flex items-center gap-1.5 text-red-300">✕ Deliveries ({deliveries.length})</li>
                <li className="flex items-center gap-1.5 text-red-300">✕ Active Routes ({vehicles.length})</li>
                <li className="flex items-center gap-1.5 text-red-300">✕ Incidents & Events</li>
                <li className="flex items-center gap-1.5 text-gray-400">• Traffic modifications</li>
                <li className="flex items-center gap-1.5 text-gray-400">• Blocked roads</li>
                <li className="flex items-center gap-1.5 text-gray-400">• Breakdowns</li>
                <li className="flex items-center gap-1.5 text-gray-400">• Optimization history</li>
              </ul>
              <p className="text-[11px] text-emerald-400/90 flex items-center gap-1 font-medium">
                <span>✓</span> Core network nodes, depot, and road graph remain available for routing.
              </p>
            </div>

            <div className="flex gap-2 pt-1">
              <button
                onClick={() => setShowFreshConfirm(false)}
                className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-300 font-bold py-2 rounded-lg text-xs transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmFreshScenario}
                className="flex-1 bg-purple-600 hover:bg-purple-500 text-white font-black py-2 rounded-lg text-xs shadow-lg shadow-purple-600/30 transition-all flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <span>Confirm Fresh Scenario</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ActionTab({ icon, title, desc, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`text-left p-2 rounded-lg border transition-all flex items-start gap-2 ${
        active
          ? 'bg-blue-950/60 border-blue-500 text-white shadow-md'
          : 'bg-gray-900/70 hover:bg-gray-800/80 border-gray-800 text-gray-300'
      }`}
    >
      <span className="text-sm mt-0.5 leading-none">{icon}</span>
      <div className="min-w-0">
        <div className="text-[11px] font-bold leading-tight truncate">{title}</div>
        <div className="text-[9px] text-gray-500 truncate">{desc}</div>
      </div>
    </button>
  )
}

function PresetButton({ icon, title, detail, active, disabled, onClick }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`p-1.5 text-left rounded border transition-all flex items-center gap-1.5 ${
        active
          ? 'bg-emerald-950/80 border-emerald-500 text-emerald-200'
          : 'bg-gray-950/70 hover:bg-gray-800 border-gray-800/90 text-gray-300'
      } disabled:opacity-40`}
    >
      <span className="text-xs">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-bold leading-tight truncate">{title}</div>
        <div className="text-[8px] text-gray-500 truncate">{detail}</div>
      </div>
    </button>
  )
}

function getEventIcon(type) {
  switch (type) {
    case 'TRAFFIC_UPDATE': return '🚦'
    case 'VEHICLE_BREAKDOWN': return '🔧'
    case 'NEW_DELIVERY': return '📦'
    case 'DELIVERY_CANCELLED': return '❌'
    case 'ROAD_BLOCKED': return '🚧'
    case 'TIME_WINDOW_CHANGE': return '⏱️'
    default: return '⚡'
  }
}

function formatEventType(type) {
  switch (type) {
    case 'TRAFFIC_UPDATE': return 'Traffic Spike'
    case 'VEHICLE_BREAKDOWN': return 'Breakdown'
    case 'NEW_DELIVERY': return 'New Delivery'
    case 'DELIVERY_CANCELLED': return 'Order Cancelled'
    case 'ROAD_BLOCKED': return 'Road Blocked'
    case 'TIME_WINDOW_CHANGE': return 'Time Window'
    default: return type || 'Event'
  }
}
