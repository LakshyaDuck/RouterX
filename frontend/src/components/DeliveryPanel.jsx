import { useState } from 'react'
import { STATUS_COLORS, PRIORITY_LABELS, PRIORITY_COLORS } from '../utils'

/**
 * DeliveryPanel — filterable, scrollable list of all deliveries.
 */
export default function DeliveryPanel({ deliveries = [] }) {
  const [filter, setFilter] = useState('ALL')
  const [search, setSearch] = useState('')

  const filtered = deliveries.filter(d => {
    const statusMatch = filter === 'ALL' || d.status === filter
    const searchMatch = search === '' ||
      d.id.toLowerCase().includes(search.toLowerCase()) ||
      d.location.toLowerCase().includes(search.toLowerCase())
    return statusMatch && searchMatch
  })

  const counts = deliveries.reduce((acc, d) => {
    acc[d.status] = (acc[d.status] || 0) + 1
    return acc
  }, {})

  const FILTERS = ['ALL', 'PENDING', 'IN_PROGRESS', 'DELIVERED', 'CANCELLED', 'FAILED']

  return (
    <div className="flex flex-col gap-2 h-full">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400">
        Deliveries ({deliveries.length})
      </h2>

      {/* Status summary chips */}
      <div className="flex flex-wrap gap-1">
        {FILTERS.map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-2 py-0.5 rounded text-xs font-medium transition-colors
              ${filter === f ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}
          >
            {f === 'ALL' ? `All ${deliveries.length}` : `${f.replace('_', ' ')} ${counts[f] || 0}`}
          </button>
        ))}
      </div>

      {/* Search */}
      <input
        className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500"
        placeholder="Search delivery ID or node…"
        value={search}
        onChange={e => setSearch(e.target.value)}
      />

      {/* Delivery rows */}
      <div className="overflow-y-auto flex-1 sidebar-panel">
        {filtered.length === 0 && (
          <div className="text-gray-500 text-xs text-center py-4">No deliveries found</div>
        )}
        {filtered.map(d => {
          const bgColor = d.priority === 1 ? 'border-l-red-500' : d.priority === 2 ? 'border-l-yellow-500' : 'border-l-green-500'
          return (
            <div
              key={d.id}
              className={`mb-1.5 border-l-4 ${bgColor} bg-gray-800 rounded-r px-2 py-1.5`}
            >
              <div className="flex justify-between items-center">
                <span className="font-mono text-xs font-semibold text-white">{d.id}</span>
                <span className={`text-xs font-medium ${STATUS_COLORS[d.status] || 'text-gray-400'}`}>
                  {d.status}
                </span>
              </div>
              <div className="text-xs text-gray-400 mt-0.5">
                📍 {d.location} · {d.demand} kg · P{d.priority}
              </div>
              <div className="text-xs text-gray-500">
                ⏰ {Math.round(d.time_window_start)}–{Math.round(d.time_window_end)} min
                {d.assigned_vehicle && ` · ${d.assigned_vehicle}`}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
