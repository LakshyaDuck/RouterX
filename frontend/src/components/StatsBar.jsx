import routerxLogo from '../assets/routerx-logo.png'
import { formatSimulationTime, formatSimulationDate } from '../utils/time'

/**
 * StatsBar — Top KPI Dashboard Header.
 *
 * Requirements:
 * 1. Clear dashboard hierarchy with high-contrast KPI cards.
 * 7. Visible "Incremental Reoptimization" label/tag.
 * 10. Compact height (h-11) optimized for 1366x768 laptop displays.
 */
export default function StatsBar({
  state,
  loading,
  error,
  lastUpdated,
  onRefresh,
  onOptimize,
  optimizing,
  loadingEvent,
  onResetSimulation,
  lastEventResponse,
}) {
  const { vehicles = [], deliveries = [], routes = [] } = state || {}

  const totalVehicles = vehicles.length
  const activeVehicles = vehicles.filter(v => v.status === 'ACTIVE').length
  const breakdownVehicles = vehicles.filter(v => v.status === 'BREAKDOWN').length
  const totalDeliveries = deliveries.length
  const pendingDeliveries = deliveries.filter(d => d.status === 'PENDING').length
  const inProgressDeliveries = deliveries.filter(d => d.status === 'IN_PROGRESS').length
  const deliveredCount = deliveries.filter(d => d.status === 'DELIVERED').length
  const cancelledCount = deliveries.filter(d => d.status === 'CANCELLED').length
  const totalDist = routes.reduce((s, r) => s + (r.total_distance || 0), 0)

  // Operational delay / fleet travel time change from the most recent event or optimization:
  const timeBefore =
    lastEventResponse?.before_metrics?.total_travel_time ??
    lastEventResponse?.before?.total_travel_time
  const timeAfter =
    lastEventResponse?.after_metrics?.total_travel_time ??
    lastEventResponse?.after?.total_travel_time

  const hasTimeDelta = timeBefore != null && timeAfter != null
  const travelTimeDelta = hasTimeDelta ? Math.round(timeAfter - timeBefore) : 0

  const isWorking = optimizing || loadingEvent

  return (
    <header
      className="border-b border-gray-800/80 px-3 flex items-center justify-between flex-shrink-0 z-10 h-11"
      style={{ background: '#0a0e17' }}
    >
      {/* 1. BRAND */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <img
          src={routerxLogo}
          alt="RouterX Logo"
          className="h-7 w-auto object-contain select-none"
        />
        <span className="text-sm font-black text-white tracking-tight">RouterX</span>
      </div>

      {/* 2. CENTER: HIGH-IMPACT DASHBOARD KPIS */}
      <div className="flex items-center gap-1.5 overflow-x-auto flex-1 justify-center px-2">
        <KPICard
          icon="🕒"
          label="Time"
          value={formatSimulationTime(state?.simulation_start_time, state?.simulation_time || 0)}
          color="text-cyan-300 font-mono"
          title={`${formatSimulationDate(state?.simulation_start_time, state?.simulation_time || 0)} · Simulation Clock`}
        />
        <KPICard
          icon="🚗"
          label="Vehicles"
          value={`${activeVehicles}/${totalVehicles}`}
          color={breakdownVehicles > 0 ? 'text-amber-400' : 'text-blue-400'}
          alert={breakdownVehicles > 0}
          alertText={`${breakdownVehicles} broken`}
        />
        <KPICard
          icon="📦"
          label="Pending"
          value={pendingDeliveries}
          color="text-yellow-400"
          title={`${pendingDeliveries} of ${totalDeliveries} orders awaiting dispatch`}
        />
        <KPICard
          icon="🚚"
          label="In Transit"
          value={inProgressDeliveries}
          color={inProgressDeliveries > 0 ? 'text-blue-400 font-bold' : 'text-gray-400'}
          title={`${inProgressDeliveries} of ${totalDeliveries} orders currently being serviced`}
        />
        <KPICard
          icon="✅"
          label="Delivered"
          value={deliveredCount}
          color={deliveredCount > 0 ? 'text-green-400 font-bold' : 'text-gray-400'}
          title={`${deliveredCount} of ${totalDeliveries} orders fulfilled`}
          alert={cancelledCount > 0}
          alertText={cancelledCount > 0 ? `${cancelledCount} cancelled` : undefined}
        />
        <KPICard
          icon="🛣"
          label="Distance"
          value={`${totalDist.toFixed(1)} km`}
          color="text-cyan-400"
        />
        <KPICard
          icon="⏱"
          label="Delay"
          value={
            travelTimeDelta > 0
              ? `+${travelTimeDelta} min`
              : travelTimeDelta < 0
              ? `${travelTimeDelta} min`
              : '0 min'
          }
          color={
            travelTimeDelta > 0
              ? 'text-amber-400'
              : travelTimeDelta < 0
              ? 'text-emerald-400'
              : 'text-gray-300'
          }
          alert={travelTimeDelta > 0}
        />
      </div>

      {/* 3. RIGHT: STATUS & PRESENTATION ACTION CONTROLS */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {/* Working status / Live indicator */}
        <div className="flex items-center gap-1.5 mr-1">
          {isWorking ? (
            <span className="text-xs text-yellow-400 font-bold animate-pulse flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-yellow-400 animate-ping" />
              Re-optimizing...
            </span>
          ) : (
            <div className="flex items-center gap-1">
              <div
                className={`w-2 h-2 rounded-full ${
                  loading ? 'bg-yellow-400 animate-pulse'
                  : error ? 'bg-red-500'
                  : 'bg-green-500'
                }`}
              />
              <span className="text-[10px] text-gray-500 hidden xl:inline">LIVE</span>
            </div>
          )}
        </div>

        <button
          onClick={onRefresh}
          disabled={isWorking}
          title="Refresh backend state"
          className="w-7 h-7 flex items-center justify-center bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-gray-400 hover:text-white transition-colors text-xs disabled:opacity-40"
        >
          ↻
        </button>

        <button
          onClick={onOptimize}
          disabled={isWorking}
          className="text-xs bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-bold px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1 shadow"
          title="Run full fleet optimizer"
        >
          ⚡ Optimize
        </button>

        <button
          onClick={onResetSimulation}
          disabled={isWorking}
          className="text-xs bg-gray-800 hover:bg-red-900/60 border border-gray-700 hover:border-red-700/60 text-gray-200 hover:text-red-300 font-bold px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1 disabled:opacity-40"
          title="Reset to deterministic initial state"
        >
          🔄 Reset Scenario
        </button>
      </div>
    </header>
  )
}

function KPICard({ icon, label, value, color, alert, alertText, highlight }) {
  return (
    <div
      className={`flex items-center gap-1 px-2 py-0.5 rounded border transition-colors flex-shrink-0 ${
        highlight
          ? 'bg-red-950/40 border-red-800/60'
          : 'bg-gray-900/70 border-gray-800/80'
      }`}
    >
      <span className="text-xs leading-none">{icon}</span>
      <div className="flex items-baseline gap-1 leading-none">
        <span className="text-[10px] text-gray-500 font-medium">{label}:</span>
        <span className={`text-xs font-bold ${color}`}>{value}</span>
        {alert && alertText && (
          <span className="text-[9px] text-red-400 font-bold">({alertText})</span>
        )}
      </div>
    </div>
  )
}
