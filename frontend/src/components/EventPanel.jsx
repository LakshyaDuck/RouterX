import { useState } from 'react'
import { api } from '../api'
import { EVENT_TYPE_LABELS } from '../utils'

/**
 * EventPanel — Right-side live event control panel.
 *
 * Sections:
 * 1. Hackathon Demo Stepper (4 scripted events)
 * 2. Arbitrary event quick buttons
 * 3. Live event audit timeline
 */
export default function EventPanel({
  state,
  onEventProcessed,
  lastEventResponse,
  loadingEvent,
  setLoadingEvent,
  onReset,
  optimizing,
}) {
  const { vehicles = [], deliveries = [], roads = [], events = [] } = state || {}
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [completedSteps, setCompletedSteps] = useState(new Set())
  const [activeStep, setActiveStep] = useState(null)

  const withLoading = async (fn) => {
    setIsSubmitting(true)
    setLoadingEvent(true)
    try {
      await fn()
    } catch (err) {
      console.error('Event error:', err)
    } finally {
      setIsSubmitting(false)
      setLoadingEvent(false)
    }
  }

  const handleDemoStep = (stepId) => withLoading(async () => {
    setActiveStep(stepId)
    const res = await api.executeDemoStep(stepId)
    if (res?.data && onEventProcessed) {
      onEventProcessed(res.data)
      setCompletedSteps(prev => new Set([...prev, stepId]))
    }
    setActiveStep(null)
  })

  const handleQuickEvent = (type) => withLoading(async () => {
    let res
    if (type === 'TRAFFIC_UPDATE') {
      const road = roads.find(r => !r.blocked) || roads[0]
      if (road) res = await api.postTrafficEvent({ road_id: road.id, traffic_multiplier: 3.5 })
    } else if (type === 'VEHICLE_BREAKDOWN') {
      const activeV = vehicles.find(v => v.status === 'ACTIVE')
      if (activeV) res = await api.postBreakdownEvent({ vehicle_id: activeV.id, reason: 'Engine failure' })
    } else if (type === 'NEW_DELIVERY') {
      const did = `d_rush_${Math.floor(Math.random() * 900 + 100)}`
      res = await api.postNewDeliveryEvent({ delivery_id: did, location: 'n05', demand: 22.0, priority: 1, time_window_start: 30.0, time_window_end: 240.0 })
    } else if (type === 'DELIVERY_CANCELLED') {
      const d = deliveries.find(d => d.assigned_vehicle && d.status === 'PENDING')
      if (d) res = await api.postCancelDeliveryEvent({ delivery_id: d.id, reason: 'Customer cancelled' })
    } else if (type === 'ROAD_BLOCKED') {
      const road = roads.find(r => !r.blocked) || roads[0]
      if (road) res = await api.postRoadBlockEvent({ road_id: road.id, blocked: true })
    } else if (type === 'TIME_WINDOW_CHANGE') {
      const d = deliveries.find(d => d.assigned_vehicle && d.status === 'PENDING')
      if (d) res = await api.postTimeWindowChangeEvent({ delivery_id: d.id, new_window_start: Math.max(0, d.time_window_start - 30), new_window_end: d.time_window_end + 60 })
    }
    if (res?.data && onEventProcessed) onEventProcessed(res.data)
  })

  const handleReset = () => withLoading(async () => {
    setCompletedSteps(new Set())
    setActiveStep(null)
    if (onReset) await onReset()
  })

  const DEMO_STEPS = [
    {
      id: 1,
      icon: '🚦',
      title: '1. Traffic Congestion',
      detail: 'Central Artery road_000 4.5× slowdown → only reroute affected vehicles',
      color: 'amber',
      gradient: 'from-amber-950/40 to-transparent',
      border: 'border-amber-500/50',
      badge: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
    },
    {
      id: 2,
      icon: '🔧',
      title: '2. Vehicle Breakdown',
      detail: 'Vehicle V03 fails → offload 3 packages & reassign to feasible active fleet',
      color: 'red',
      gradient: 'from-red-950/40 to-transparent',
      border: 'border-red-500/50',
      badge: 'bg-red-500/20 text-red-300 border-red-500/40',
    },
    {
      id: 3,
      icon: '⚡',
      title: '3. Rush P1 Order',
      detail: 'Urgent medical order to Riverside Plaza (n07) → +6.6 km route detour',
      color: 'blue',
      gradient: 'from-blue-950/40 to-transparent',
      border: 'border-blue-500/50',
      badge: 'bg-blue-500/20 text-blue-300 border-blue-500/40',
    },
    {
      id: 4,
      icon: '⏰',
      title: '4. Window Expedited',
      detail: 'Order d12 expedited to 25m deadline → +5.4 km sequence re-optimization',
      color: 'cyan',
      gradient: 'from-cyan-950/40 to-transparent',
      border: 'border-cyan-500/50',
      badge: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40',
    },
  ]

  const QUICK_EVENTS = [
    { type: 'TRAFFIC_UPDATE', icon: '🚗', label: 'Traffic Spike', desc: '3.5× delay' },
    { type: 'VEHICLE_BREAKDOWN', icon: '💥', label: 'Breakdown', desc: 'Active van' },
    { type: 'NEW_DELIVERY', icon: '📦', label: 'Rush Order', desc: 'P1 urgent' },
    { type: 'DELIVERY_CANCELLED', icon: '❌', label: 'Cancel Order', desc: 'Remove stop' },
    { type: 'ROAD_BLOCKED', icon: '🚧', label: 'Block Road', desc: 'Full detour' },
    { type: 'TIME_WINDOW_CHANGE', icon: '⏱', label: 'Time Window', desc: 'Reschedule' },
  ]

  const eventTypeColor = {
    TRAFFIC_UPDATE: 'text-amber-400',
    VEHICLE_BREAKDOWN: 'text-red-400',
    NEW_DELIVERY: 'text-blue-400',
    DELIVERY_CANCELLED: 'text-gray-400',
    ROAD_BLOCKED: 'text-orange-400',
    TIME_WINDOW_CHANGE: 'text-cyan-400',
  }

  return (
    <div className="flex flex-col h-full" style={{ background: '#0d1117' }}>
      {/* Panel header */}
      <div className="px-3 py-2.5 border-b border-gray-800 flex items-center justify-between flex-shrink-0">
        <div>
          <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400">Event Control</h2>
          <div className="text-[10px] text-gray-600 mt-0.5">Real-time fleet event injection</div>
        </div>
        <button
          onClick={handleReset}
          disabled={isSubmitting || optimizing}
          className="text-[10px] font-bold bg-gray-800 hover:bg-red-900/50 border border-gray-700 hover:border-red-700/60 text-gray-400 hover:text-red-300 px-2.5 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 disabled:opacity-40"
          title="Reset to fresh demo scenario"
        >
          🔄 Reset
        </button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">

        {/* === HACKATHON DEMO STEPPER === */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1.5">
              <span className="text-sm">🏆</span>
              <span className="text-xs font-bold text-white">Demo Walkthrough</span>
            </div>
            <span className="text-[10px] text-gray-600 font-medium">
              {completedSteps.size}/4 done
            </span>
          </div>

          {/* Progress bar */}
          <div className="w-full bg-gray-800 rounded-full h-1 mb-3 overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-500"
              style={{ width: `${(completedSteps.size / 4) * 100}%` }}
            />
          </div>

          <div className="space-y-1.5">
            {DEMO_STEPS.map(step => {
              const isDone = completedSteps.has(step.id)
              const isActive = activeStep === step.id

              return (
                <button
                  key={step.id}
                  onClick={() => handleDemoStep(step.id)}
                  disabled={isSubmitting}
                  className={`w-full text-left rounded-xl border p-2.5 transition-all duration-200 flex items-center gap-3
                    ${isDone
                      ? `bg-gradient-to-r ${step.gradient} ${step.border} opacity-70`
                      : `bg-gray-900/80 border-gray-700/80 hover:${step.border} hover:bg-gray-900`
                    }
                    ${isActive ? `${step.border} ring-1 ring-inset ring-current` : ''}
                    disabled:cursor-not-allowed`}
                >
                  {/* Step number */}
                  <div className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 text-sm
                    ${isDone
                      ? 'bg-green-900/60 border border-green-600/60'
                      : `${step.badge} border`
                    }`}
                  >
                    {isDone ? '✓' : isActive
                      ? <span className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin block" />
                      : step.id
                    }
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm">{step.icon}</span>
                      <span className={`text-xs font-bold ${isDone ? 'text-gray-400' : 'text-white'}`}>
                        {step.title}
                      </span>
                    </div>
                    <div className="text-[10px] text-gray-500 mt-0.5 truncate">{step.detail}</div>
                  </div>

                  {/* Arrow */}
                  {!isDone && (
                    <span className="text-gray-600 text-xs flex-shrink-0">▶</span>
                  )}
                </button>
              )
            })}
          </div>
        </section>

        {/* Divider */}
        <div className="flex items-center gap-2">
          <div className="flex-1 h-px bg-gray-800" />
          <span className="text-[10px] text-gray-600 font-medium uppercase tracking-wider">Or inject arbitrary</span>
          <div className="flex-1 h-px bg-gray-800" />
        </div>

        {/* === QUICK EVENT BUTTONS === */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold text-gray-400">Quick Events</span>
            {isSubmitting && (
              <span className="text-[10px] text-yellow-400 animate-pulse font-bold flex items-center gap-1">
                <span className="w-2 h-2 bg-yellow-400 rounded-full animate-ping" />
                Re-optimizing...
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {QUICK_EVENTS.map(ev => (
              <button
                key={ev.type}
                onClick={() => handleQuickEvent(ev.type)}
                disabled={isSubmitting}
                className="bg-gray-900/80 hover:bg-gray-800 border border-gray-800 hover:border-gray-600
                  p-1.5 rounded-lg text-left transition-all flex items-center gap-2 text-gray-300
                  hover:text-white disabled:opacity-40 disabled:cursor-not-allowed group"
              >
                <span className="text-base flex-shrink-0 group-hover:scale-110 transition-transform">{ev.icon}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] font-bold truncate text-gray-200 group-hover:text-white leading-tight">{ev.label}</div>
                  <div className="text-[9px] text-gray-500 truncate leading-tight">{ev.desc}</div>
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* === DECISION EXPLANATION CARD === */}
        {lastEventResponse && (
          <section className="bg-gradient-to-b from-blue-950/40 to-gray-900 border border-blue-500/50 rounded-xl p-2.5 space-y-1.5 shadow-lg">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-blue-400 font-bold text-[10px] uppercase tracking-wider">
                <span>🧠</span> Optimization Result
              </span>
              <span className="text-[9px] bg-blue-500/20 text-blue-300 font-mono px-1.5 py-0.5 rounded border border-blue-500/30">
                Scope: {((lastEventResponse.reoptimization_scope || 0) * 100).toFixed(0)}%
              </span>
            </div>

            <div className="text-gray-100 text-[11px] leading-relaxed bg-black/40 p-2 rounded-lg border border-gray-800 font-medium">
              "{lastEventResponse.decision_explanation || lastEventResponse.explanation}"
            </div>

            {/* Scope counts and entities modified */}
            <div className="flex flex-wrap gap-1 text-[9px]">
              <div className="bg-blue-950/60 border border-blue-700/60 text-blue-300 px-1.5 py-0.5 rounded font-medium">
                Routes: <strong className="text-amber-300">{lastEventResponse.changed_routes?.length || 0}/8</strong>
              </div>
              <div className="bg-blue-950/60 border border-blue-700/60 text-blue-300 px-1.5 py-0.5 rounded font-medium">
                Deliveries: <strong className="text-emerald-300">{lastEventResponse.reassigned_deliveries?.length || 0}/40</strong>
              </div>
              {lastEventResponse.changed_routes?.length > 0 && (
                <div className="bg-yellow-950/50 border border-yellow-700/60 text-yellow-300 px-1.5 py-0.5 rounded font-semibold font-mono">
                  {lastEventResponse.changed_routes.join(', ')}
                </div>
              )}
              {lastEventResponse.reassigned_deliveries?.length > 0 && (
                <div className="bg-green-950/50 border border-green-700/60 text-green-300 px-1.5 py-0.5 rounded font-semibold font-mono">
                  {lastEventResponse.reassigned_deliveries.join(', ')}
                </div>
              )}
            </div>
          </section>
        )}

        {/* === LIVE EVENT TIMELINE === */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold text-gray-400">Live Event Feed</span>
            <span className="text-[10px] text-gray-600">{events.length} events</span>
          </div>

          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {events.length === 0 ? (
              <div className="text-center py-6 text-gray-600 text-[11px]">
                <div className="text-2xl mb-2">📡</div>
                No events yet. Trigger one above!
              </div>
            ) : (
              [...events].reverse().map((ev, idx) => (
                <div
                  key={ev.id}
                  className="bg-gray-900/60 border border-gray-800/60 rounded-lg px-2.5 py-2 flex gap-2.5"
                >
                  {/* Timeline dot */}
                  <div className="flex flex-col items-center flex-shrink-0 pt-0.5">
                    <div className={`w-2 h-2 rounded-full flex-shrink-0 ${eventTypeColor[ev.event_type]?.replace('text-', 'bg-') || 'bg-gray-500'}`} />
                    {idx < events.length - 1 && (
                      <div className="w-px flex-1 bg-gray-800 mt-1" />
                    )}
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-1">
                      <span className={`text-[10px] font-bold uppercase tracking-wide ${eventTypeColor[ev.event_type] || 'text-gray-400'}`}>
                        {EVENT_TYPE_LABELS[ev.event_type] || ev.event_type}
                      </span>
                      <span className="text-[9px] text-gray-600 flex-shrink-0">
                        T+{Math.round(ev.timestamp)}m
                      </span>
                    </div>
                    <div className="text-[10px] text-gray-400 mt-0.5">
                      <span className="font-mono">{ev.affected_entity_id}</span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

      </div>
    </div>
  )
}
