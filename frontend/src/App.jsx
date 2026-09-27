import { useMemo, useState } from 'react'
import { useFleetState } from './hooks'
import { api } from './api'
import { computeRouteTimelineMap } from './utils/routeTiming'
import NetworkGraph from './components/NetworkGraph'
import VehiclePanel from './components/VehiclePanel'
import ScenarioBuilderPanel from './components/ScenarioBuilderPanel'
import StatsBar from './components/StatsBar'
import BeforeAfterPanel from './components/BeforeAfterPanel'

export default function App() {
  const {
    state,
    setState,
    loading,
    error,
    lastUpdated,
    refresh,
    etaChangesByDelivery,
    advanceTime,
    setSimulationClockTime,
    togglePlayPause,
    setSpeedMultiplier,
  } = useFleetState(10_000)
  const timelineMap = useMemo(
    () => computeRouteTimelineMap(state?.routes || [], state?.vehicles || [], state?.deliveries || [], state?.nodes || [], state?.roads || []),
    [state?.routes, state?.vehicles, state?.deliveries, state?.nodes, state?.roads],
  )
  const [selectedVehicle, setSelectedVehicle] = useState(null)
  const [selectedDeliveryId, setSelectedDeliveryId] = useState(null)
  const [optimizing, setOptimizing] = useState(false)
  const [lastEventResponse, setLastEventResponse] = useState(null)
  const [loadingEvent, setLoadingEvent] = useState(false)
  const [highlightedVehicles, setHighlightedVehicles] = useState([])
  const [highlightedDeliveries, setHighlightedDeliveries] = useState([])

  // Collapsible panel states
  const [fleetCollapsed, setFleetCollapsed] = useState(false)
  const [scenarioCollapsed, setScenarioCollapsed] = useState(false)

  // Map/Graph interactive modes: null | 'add_stop' | 'select_road_traffic' | 'select_road_block'
  const [mapMode, setMapMode] = useState(null)
  const [newStopDraft, setNewStopDraft] = useState(null)
  const [selectedRoadId, setSelectedRoadId] = useState(null)

  const handleMapModeCancel = () => {
    setMapMode(null)
    setNewStopDraft(null)
    setSelectedRoadId(null)
  }

  const handleFleetCollapse = () => {
    setFleetCollapsed(c => !c)
  }

  const handleScenarioCollapse = () => {
    setScenarioCollapsed(c => !c)
  }

  const handleConfirmNewStop = async (draft) => {
    try {
      setLoadingEvent(true)
      const res = await api.addNode({
        label: draft.label || `Stop n${(state?.nodes?.length || 0) + 1}`,
        lat: Number(draft.lat),
        lon: Number(draft.lon),
        connect_to_node: draft.connectToNodeId,
      })
      if (res?.data) {
        handleEventProcessed(res.data)
      }
      setMapMode(null)
      setNewStopDraft(null)
    } catch (err) {
      console.error('Failed to add stop:', err)
      alert(err?.response?.data?.detail || err.message || 'Failed to add stop')
    } finally {
      setLoadingEvent(false)
    }
  }

  const handleApplyTraffic = async (roadId, multiplier) => {
    try {
      setLoadingEvent(true)
      const res = await api.postTrafficEvent({
        road_id: roadId,
        traffic_multiplier: Number(multiplier),
      })
      if (res?.data) {
        handleEventProcessed(res.data)
      }
      setMapMode(null)
      setSelectedRoadId(null)
    } catch (err) {
      console.error('Failed to update traffic:', err)
      alert(err?.response?.data?.detail || err.message || 'Failed to update traffic')
    } finally {
      setLoadingEvent(false)
    }
  }

  const handleApplyRoadBlock = async (roadId, blocked) => {
    try {
      setLoadingEvent(true)
      const res = await api.postRoadBlockEvent({
        road_id: roadId,
        blocked: Boolean(blocked),
      })
      if (res?.data) {
        handleEventProcessed(res.data)
      }
      setMapMode(null)
      setSelectedRoadId(null)
    } catch (err) {
      console.error('Failed to update road block:', err)
      alert(err?.response?.data?.detail || err.message || 'Failed to update road block')
    } finally {
      setLoadingEvent(false)
    }
  }

  const handleVehicleSelect = (vehicleId) => {
    setSelectedVehicle(vehicleId === selectedVehicle ? null : vehicleId)
  }

  const handleEventProcessed = async (response) => {
    setLastEventResponse(response)
    // Highlight affected vehicles/deliveries for graph animation
    const affV = response?.affected_vehicles || response?.changed_routes || []
    const affD = response?.affected_deliveries || response?.reassigned_deliveries || []
    setHighlightedVehicles(affV)
    setHighlightedDeliveries(affD)
    if (response?.full_state) {
      setState(response.full_state, { forceTransition: true })
    }
    await refresh()
    // Clear highlights after 10s
    setTimeout(() => {
      setHighlightedVehicles([])
      setHighlightedDeliveries([])
    }, 10000)
  }

  const handleResetSimulation = async () => {
    try {
      setOptimizing(true)
      const { data } = await api.resetSimulation({ start_time: new Date().toISOString() })
      if (data?.state) setState(data.state, { resetEtaHistory: true, forceTransition: true })
      setLastEventResponse(null)
      setHighlightedVehicles([])
      setHighlightedDeliveries([])
      setSelectedVehicle(null)
      setSelectedDeliveryId(null)
    } catch (err) {
      console.error('Reset simulation error:', err)
    } finally {
      setOptimizing(false)
    }
  }

  const handleFreshScenario = async () => {
    try {
      setOptimizing(true)
      const { data } = await api.freshSimulation({ start_time: new Date().toISOString() })
      if (data?.state) setState(data.state, { resetEtaHistory: true, forceTransition: true })
      setLastEventResponse(null)
      setHighlightedVehicles([])
      setHighlightedDeliveries([])
      setSelectedVehicle(null)
      setSelectedDeliveryId(null)
    } catch (err) {
      console.error('Fresh scenario error:', err)
    } finally {
      setOptimizing(false)
    }
  }

  const handleSelectDelivery = (deliveryId) => {
    setSelectedDeliveryId(deliveryId)
    if (deliveryId && scenarioCollapsed) {
      setScenarioCollapsed(false)
    }
  }

  const handleOptimize = async () => {
    try {
      setOptimizing(true)
      const { data } = await api.optimize()
      setLastEventResponse(data)
      const affV = data?.affected_vehicles || data?.changed_routes || data?.routes_changed || []
      const affD = data?.affected_deliveries || data?.reassigned_deliveries || data?.deliveries_reassigned || []
      setHighlightedVehicles(affV)
      setHighlightedDeliveries(affD)
      if (data?.full_state) {
        setState(data.full_state, { forceTransition: true })
      }
      await refresh()
      setTimeout(() => {
        setHighlightedVehicles([])
        setHighlightedDeliveries([])
      }, 10000)
    } catch (err) {
      console.error('Optimization error:', err)
    } finally {
      setOptimizing(false)
    }
  }

  if (loading && !state) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-center">
          <div className="relative inline-flex mb-6">
            <div className="w-16 h-16 bg-cyan-600/20 rounded-full flex items-center justify-center border border-cyan-500/40">
              <span className="text-3xl animate-spin inline-block">⚙️</span>
            </div>
            <div className="absolute -top-1 -right-1 w-4 h-4 bg-emerald-500 rounded-full animate-pulse" />
          </div>
          <div className="text-white text-xl font-bold mb-1">RouterX</div>
          <div className="text-gray-400 text-sm">Connecting to logistics control network…</div>
        </div>
      </div>
    )
  }

  if (error && !state) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="text-center max-w-md mx-auto p-6">
          <div className="text-5xl mb-4">⚠️</div>
          <div className="text-red-400 text-xl font-bold mb-2">Backend Unreachable</div>
          <div className="text-gray-400 text-sm mb-6">{error}</div>
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 text-left text-sm text-gray-300 mb-4">
            <div className="font-semibold mb-3 text-gray-200">Start the backend:</div>
            <div className="space-y-1 font-mono text-xs bg-black/40 p-3 rounded-lg">
              <div><span className="text-gray-500">$ </span><span className="text-green-400">docker start ps5-postgres</span></div>
              <div><span className="text-gray-500">$ </span><span className="text-green-400">cd backend</span></div>
              <div><span className="text-gray-500">$ </span><span className="text-green-400">uvicorn main:app --reload --port 8000</span></div>
            </div>
          </div>
          <button
            onClick={refresh}
            className="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-6 py-2.5 rounded-lg transition-colors cursor-pointer"
          >
            Retry Connection
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-screen bg-[#080c14] text-gray-100 overflow-hidden">
      {/* TOP — Header Stats Bar */}
      <StatsBar
        state={state}
        loading={loading}
        error={error}
        lastUpdated={lastUpdated}
        onRefresh={refresh}
        onOptimize={handleOptimize}
        optimizing={optimizing}
        loadingEvent={loadingEvent}
        onResetSimulation={handleResetSimulation}
        lastEventResponse={lastEventResponse}
      />

      {/* MAIN WORKSPACE — Three columns */}
      <div className="flex flex-1 overflow-hidden min-h-0 relative">

        {/* LEFT — Fleet Status Panel (collapsible) */}
        <aside
          className="flex-shrink-0 border-r border-gray-800 flex flex-col overflow-hidden transition-all duration-300 ease-in-out h-full"
          style={{
            width: fleetCollapsed ? '28px' : '240px',
            minWidth: fleetCollapsed ? '28px' : '240px',
            background: '#0d1117',
          }}
        >
          {/* Collapse toggle */}
          <button
            onClick={handleFleetCollapse}
            className="w-full flex items-center justify-center h-7 flex-shrink-0 border-b border-gray-800 hover:bg-gray-800/60 transition-colors text-gray-500 hover:text-gray-300 group cursor-pointer"
            title={fleetCollapsed ? 'Expand Fleet Status' : 'Collapse Fleet Status'}
          >
            <span className={`text-xs transition-transform duration-300 ${fleetCollapsed ? 'rotate-180' : ''}`}>
              {fleetCollapsed ? '›' : '‹'}
            </span>
            {!fleetCollapsed && (
              <span className="text-[9px] text-gray-600 ml-1 group-hover:text-gray-400 transition-colors">Fleet</span>
            )}
          </button>

          {/* Panel content */}
          <div
            className="flex-1 flex flex-col min-h-0 overflow-hidden transition-opacity duration-200"
            style={{ opacity: fleetCollapsed ? 0 : 1, pointerEvents: fleetCollapsed ? 'none' : 'auto' }}
          >
            <VehiclePanel
              vehicles={state?.vehicles || []}
              routes={state?.routes || []}
              deliveries={state?.deliveries || []}
              selectedVehicle={selectedVehicle}
              onSelect={handleVehicleSelect}
              highlightedVehicles={highlightedVehicles}
            />
          </div>
        </aside>

        {/* CENTER — Interactive Logistics Network Graph */}
        <main className="flex-1 relative min-w-0 bg-[#080c14] overflow-hidden">
          {state ? (
            <NetworkGraph
              state={state}
              timelineMap={timelineMap}
              etaChangesByDelivery={etaChangesByDelivery}
              selectedVehicle={selectedVehicle}
              selectedDeliveryId={selectedDeliveryId}
              onSelectDelivery={handleSelectDelivery}
              affectedVehicles={highlightedVehicles}
              affectedDeliveries={highlightedDeliveries}
              onVehicleClick={handleVehicleSelect}
              mapMode={mapMode}
              onMapModeCancel={handleMapModeCancel}
              newStopDraft={newStopDraft}
              onNewStopDraftChange={setNewStopDraft}
              onConfirmNewStop={handleConfirmNewStop}
              selectedRoadId={selectedRoadId}
              onSelectRoad={setSelectedRoadId}
              onApplyTraffic={handleApplyTraffic}
              onApplyRoadBlock={handleApplyRoadBlock}
            />
          ) : (
            <div className="h-full flex items-center justify-center bg-[#080c14]">
              <div className="text-gray-500 font-mono text-xs">Loading logistics network graph…</div>
            </div>
          )}

          {/* Loading overlay during event processing */}
          {(loadingEvent || optimizing) && (
            <div className="absolute inset-0 z-40 bg-black/60 backdrop-blur-[2px] flex items-center justify-center">
              <div className="bg-gray-900 border border-cyan-500/80 rounded-xl px-8 py-5 flex items-center gap-4 shadow-2xl">
                <div className="w-6 h-6 border-3 border-cyan-400 border-t-transparent rounded-full animate-spin" />
                <div className="flex flex-col">
                  <span className="text-white font-bold text-base tracking-wide">Re-optimizing Fleet...</span>
                  <span className="text-cyan-400 text-xs">Incrementally repairing affected route edges</span>
                </div>
              </div>
            </div>
          )}
        </main>

        {/* RIGHT — Scenario Builder & Order Inspector Panel (collapsible) */}
        <aside
          className="flex-shrink-0 border-l border-gray-800 flex flex-col overflow-hidden transition-all duration-300 ease-in-out h-full"
          style={{
            width: scenarioCollapsed ? '28px' : '360px',
            minWidth: scenarioCollapsed ? '28px' : '360px',
            background: '#0d1117',
          }}
        >
          {/* Collapse toggle */}
          <button
            onClick={handleScenarioCollapse}
            className="w-full flex items-center justify-center h-7 flex-shrink-0 border-b border-gray-800 hover:bg-gray-800/60 transition-colors text-gray-500 hover:text-gray-300 group cursor-pointer"
            title={scenarioCollapsed ? 'Expand Scenario Builder' : 'Collapse Scenario Builder'}
          >
            {!scenarioCollapsed && (
              <span className="text-[9px] text-gray-600 mr-1 group-hover:text-gray-400 transition-colors">Scenario</span>
            )}
            <span className={`text-xs transition-transform duration-300 ${scenarioCollapsed ? 'rotate-180' : ''}`}>
              {scenarioCollapsed ? '‹' : '›'}
            </span>
          </button>

          {/* Panel content */}
          <div
            className="flex-1 flex flex-col min-h-0 overflow-hidden transition-opacity duration-200"
            style={{ opacity: scenarioCollapsed ? 0 : 1, pointerEvents: scenarioCollapsed ? 'none' : 'auto' }}
          >
            <ScenarioBuilderPanel
              state={state}
              timelineMap={timelineMap}
              etaChangesByDelivery={etaChangesByDelivery}
              onEventProcessed={handleEventProcessed}
              onOptimize={handleOptimize}
              onReset={handleResetSimulation}
              onFreshScenario={handleFreshScenario}
              selectedDeliveryId={selectedDeliveryId}
              onSelectDelivery={handleSelectDelivery}
              onSelectVehicle={handleVehicleSelect}
              lastEventResponse={lastEventResponse}
              loadingEvent={loadingEvent}
              setLoadingEvent={setLoadingEvent}
              optimizing={optimizing}
              mapMode={mapMode}
              setMapMode={setMapMode}
              newStopDraft={newStopDraft}
              setNewStopDraft={setNewStopDraft}
              selectedRoadId={selectedRoadId}
              setSelectedRoadId={setSelectedRoadId}
              onAdvanceTime={advanceTime}
              onSetSimulationClockTime={setSimulationClockTime}
              onTogglePlayPause={togglePlayPause}
              onSetSpeedMultiplier={setSpeedMultiplier}
            />
          </div>
        </aside>
      </div>

      {/* BOTTOM — Optimization Result / What Changed Panel */}
      {lastEventResponse && (
        <BeforeAfterPanel
          response={lastEventResponse}
          totalRoutes={state?.routes?.length || 8}
          totalDeliveries={state?.deliveries?.length || 40}
          onDismiss={() => setLastEventResponse(null)}
        />
      )}
    </div>
  )
}
