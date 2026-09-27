import { useState } from 'react'

/**
 * BeforeAfterPanel — Hackathon Presentation Optimization Result Card.
 *
 * Requirements Met:
 * - Clean before/after metrics comparison with delta badges.
 * - Prominent "Reoptimization" badge and scope summary.
 * - Bounded, non-overflowing Decision Rationale with internal scroll.
 * - Expandable Popover for reviewing long explanations and complete lists of affected routes/orders.
 * - Resilient to long text and multi-entity modifications without breaking the desktop layout.
 */
export default function BeforeAfterPanel({
  response,
  totalRoutes = 8,
  totalDeliveries = 40,
  onDismiss,
}) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!response) return null

  // Normalize metrics from both event engine and demo step formats
  const before = response.before_metrics || response.metrics?.before || response.before
  const after  = response.after_metrics  || response.metrics?.after  || response.after

  const title       = response.title       || response.event_type || 'Event Reoptimization'
  const changed     = response.changed_routes  || response.routes_changed || []
  const reassigned  = response.reassigned_deliveries || response.deliveries_reassigned || []
  const explanation = response.decision_explanation || response.explanation || ''

  const distBefore = before?.distance         ?? before?.total_distance  ?? 0
  const distAfter  = after?.distance          ?? after?.total_distance   ?? 0
  const timeBefore = before?.travel_time      ?? before?.total_travel_time ?? 0
  const timeAfter  = after?.travel_time       ?? after?.total_travel_time  ?? 0
  const lateBefore = before?.late_deliveries  ?? before?.time_window_violations ?? before?.number_of_late_deliveries ?? 0
  const lateAfter  = after?.late_deliveries   ?? after?.time_window_violations   ?? after?.number_of_late_deliveries ?? 0
  const unaBefore  = before?.unassigned_deliveries ?? before?.number_of_unassigned_deliveries ?? 0
  const unaAfter   = after?.unassigned_deliveries  ?? after?.number_of_unassigned_deliveries  ?? 0
  const violBefore = before?.total_violations
  const violAfter  = after?.total_violations

  const hasMetrics = before && after

  const routesChangedCount = changed.length
  const ordersReassignedCount = reassigned.length
  const routesPct = Math.round((routesChangedCount / Math.max(1, totalRoutes)) * 100)
  const ordersPct = Math.round((ordersReassignedCount / Math.max(1, totalDeliveries)) * 100)

  return (
    <div
      className="border-t border-gray-800 flex-shrink-0 flex items-stretch gap-0 shadow-2xl relative z-20"
      style={{ background: '#0a0e17', minHeight: 82, maxHeight: 104 }}
    >
      {/* 1. LEFT: Incremental Reoptimization Badge & Scope */}
      <div className="flex-shrink-0 w-44 xl:w-50 px-3 py-1.5 flex flex-col justify-center border-r border-gray-800/80 gap-0.5">
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
          <span className="text-[9px] font-black uppercase tracking-wider text-emerald-400 bg-emerald-950/60 px-1.5 py-0.5 rounded border border-emerald-500/30">
            ⚡ Reoptimization
          </span>
        </div>
        <div className="text-xs font-bold text-white truncate mt-0.5" title={title}>
          {title}
        </div>
        {/* Scope comparison */}
        <div className="text-[10px] text-gray-400 font-medium flex items-center gap-1.5">
          <span>Routes: <strong className="text-amber-400">{routesChangedCount}/{totalRoutes}</strong> ({routesPct}%)</span>
          <span className="text-gray-600">·</span>
          <span>Orders: <strong className="text-blue-400">{ordersReassignedCount}/{totalDeliveries}</strong> ({ordersPct}%)</span>
        </div>
      </div>

      {/* 2. CENTER: Before vs After Metrics Comparison */}
      {hasMetrics && (
        <div className="flex items-center px-2.5 py-1 gap-2.5 border-r border-gray-800/80 overflow-x-auto flex-shrink-0">
          {/* Before */}
          <div className="flex flex-col gap-0.5">
            <span className="text-[8px] font-bold text-gray-500 uppercase tracking-widest">BEFORE</span>
            <div className="flex gap-1.5">
              <MiniStat label="Dist" value={`${distBefore.toFixed(1)}km`} />
              <MiniStat label="Time" value={`${timeBefore.toFixed(0)}m`} />
              <MiniStat label="Violations" value={violBefore ?? '—'} alert={violBefore > 0} />
              <MiniStat label="Late" value={lateBefore} alert={lateBefore > 0} />
              <MiniStat label="Unassigned" value={unaBefore} alert={unaBefore > 0} />
            </div>
          </div>

          <div className="text-gray-600 text-xs font-bold">→</div>

          {/* After */}
          <div className="flex flex-col gap-0.5">
            <span className="text-[8px] font-bold text-cyan-400 uppercase tracking-widest">AFTER REPAIR</span>
            <div className="flex gap-1.5">
              <MiniStat
                label="Dist"
                value={`${distAfter.toFixed(1)}km`}
                delta={distAfter - distBefore}
                unit="km"
                lowerIsBetter
              />
              <MiniStat
                label="Time"
                value={`${timeAfter.toFixed(0)}m`}
                delta={timeAfter - timeBefore}
                unit="m"
                lowerIsBetter
              />
              <MiniStat
                label="Violations"
                value={violAfter ?? '—'}
                delta={violAfter - violBefore}
                alert={violAfter > 0}
                good={violAfter < violBefore}
                lowerIsBetter
              />
              <MiniStat
                label="Late"
                value={lateAfter}
                delta={lateAfter - lateBefore}
                alert={lateAfter > 0}
                good={lateAfter < lateBefore}
                lowerIsBetter
              />
              <MiniStat
                label="Unassigned"
                value={unaAfter}
                delta={unaAfter - unaBefore}
                alert={unaAfter > 0}
                good={unaAfter < unaBefore}
                lowerIsBetter
              />
            </div>
          </div>
        </div>
      )}

      {/* 3. RIGHT: Algorithm Decision Explanation & Affected Entities */}
      <div className="flex-1 min-w-0 px-3 py-1 flex flex-col justify-center gap-1 overflow-hidden">
        {/* Header row: Title + Compact Badges + Expand Toggle */}
        <div className="flex items-center justify-between gap-2 flex-shrink-0 min-w-0">
          <div className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-wider text-blue-400 flex-shrink-0">
            <span>🧠</span>
            <span className="truncate">Decision Rationale</span>
          </div>

          {/* Compact Entity Badges & Expand Button */}
          <div className="flex items-center gap-1.5 min-w-0 overflow-hidden">
            {changed.length > 0 && (
              <span
                className="bg-yellow-950/60 border border-yellow-700/60 text-yellow-300 px-1.5 py-0.5 rounded font-mono font-bold text-[9px] truncate max-w-[150px] cursor-default"
                title={`Affected Routes (${changed.length}): ${changed.join(', ')}`}
              >
                Routes: {changed.slice(0, 3).join(', ')}{changed.length > 3 ? ` +${changed.length - 3}` : ''}
              </span>
            )}
            {reassigned.length > 0 && (
              <span
                className="bg-emerald-950/60 border border-emerald-700/60 text-emerald-300 px-1.5 py-0.5 rounded font-mono font-bold text-[9px] truncate max-w-[170px] cursor-default"
                title={`Reassigned Orders (${reassigned.length}): ${reassigned.join(', ')}`}
              >
                Orders: {reassigned.slice(0, 3).join(', ')}{reassigned.length > 3 ? ` +${reassigned.length - 3}` : ''}
              </span>
            )}
            <button
              onClick={() => setIsExpanded(prev => !prev)}
              className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 hover:text-white transition-colors flex items-center gap-0.5 flex-shrink-0 cursor-pointer"
              title={isExpanded ? 'Collapse rationale popover' : 'Expand full rationale details'}
            >
              <span>{isExpanded ? '⤡ Close' : '⤢ Details'}</span>
            </button>
          </div>
        </div>

        {/* Scrollable Explanation text area — bounded, internal scrollbar, no text clipping */}
        {explanation && (
          <div
            className="text-[11px] text-gray-200 leading-snug font-medium bg-black/40 p-1.5 rounded border border-gray-800/80 overflow-y-auto max-h-[48px] select-text"
            style={{ scrollbarWidth: 'thin' }}
          >
            "{explanation}"
          </div>
        )}
      </div>

      {/* Floating Expanded Popover Modal when isExpanded is true */}
      {isExpanded && (
        <div className="absolute bottom-full right-4 mb-2 w-[480px] max-w-[90vw] max-h-[300px] bg-[#0c121e] border border-blue-500/60 rounded-xl p-3.5 shadow-2xl z-[1001] flex flex-col gap-2 overflow-hidden animate-fadeIn backdrop-blur-md">
          <div className="flex items-center justify-between border-b border-gray-800 pb-2">
            <div className="flex items-center gap-2">
              <span className="text-base">🧠</span>
              <div className="text-xs font-bold text-white uppercase tracking-wider">
                Full Optimization Decision Rationale
              </div>
            </div>
            <button
              onClick={() => setIsExpanded(false)}
              className="text-gray-400 hover:text-white text-xs px-1.5 py-0.5 rounded hover:bg-gray-800 transition-colors cursor-pointer"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 overflow-y-auto pr-1 space-y-2 text-xs text-gray-200 leading-relaxed" style={{ scrollbarWidth: 'thin' }}>
            <p className="bg-blue-950/30 border border-blue-900/50 p-2.5 rounded-lg text-blue-100 font-medium">
              "{explanation}"
            </p>

            {changed.length > 0 && (
              <div>
                <div className="text-[10px] font-bold uppercase text-yellow-400 mb-1">
                  Changed Routes ({changed.length}):
                </div>
                <div className="flex flex-wrap gap-1 font-mono text-[10px]">
                  {changed.map(r => (
                    <span key={r} className="bg-yellow-950/60 border border-yellow-700/60 text-yellow-300 px-1.5 py-0.5 rounded">
                      {r}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {reassigned.length > 0 && (
              <div>
                <div className="text-[10px] font-bold uppercase text-emerald-400 mb-1">
                  Reassigned Deliveries ({reassigned.length}):
                </div>
                <div className="flex flex-wrap gap-1 font-mono text-[10px]">
                  {reassigned.map(d => (
                    <span key={d} className="bg-emerald-950/60 border border-emerald-700/60 text-emerald-300 px-1.5 py-0.5 rounded">
                      {d}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Dismiss Button */}
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="w-7 flex items-center justify-center text-gray-500 hover:text-white hover:bg-gray-800/50 transition-colors flex-shrink-0 text-sm cursor-pointer"
          title="Dismiss result panel"
        >
          ✕
        </button>
      )}
    </div>
  )
}

function MiniStat({ label, value, delta, unit = '', alert, good, lowerIsBetter }) {
  let deltaColor = 'text-gray-500'
  if (delta !== undefined && Math.abs(delta) > 0.01) {
    const isImprovement = lowerIsBetter ? delta < 0 : delta > 0
    deltaColor = isImprovement ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'
  }

  return (
    <div className={`px-1.5 py-0.5 rounded border text-center min-w-[46px] ${
      alert
        ? 'bg-red-950/40 border-red-800/60 text-red-300'
        : good
        ? 'bg-emerald-950/40 border-emerald-800/60 text-emerald-300'
        : 'bg-gray-900/80 border-gray-800 text-gray-300'
    }`}>
      <div className="text-[8px] text-gray-500 leading-none">{label}</div>
      <div className="text-xs font-bold leading-tight mt-0.5">{value}</div>
      {delta !== undefined && Math.abs(delta) > 0.01 && (
        <div className={`text-[8px] leading-none ${deltaColor}`}>
          {delta > 0 ? `+${delta.toFixed(0)}` : delta.toFixed(0)}{unit}
        </div>
      )}
    </div>
  )
}
