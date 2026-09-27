// Colour palette for vehicles (up to 8)
export const VEHICLE_COLORS = [
  '#3b82f6', // blue
  '#10b981', // emerald
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // violet
  '#06b6d4', // cyan
  '#f97316', // orange
  '#84cc16', // lime
]

export const PRIORITY_LABELS = { 1: 'HIGH', 2: 'MEDIUM', 3: 'LOW' }
export const PRIORITY_COLORS = { 1: 'bg-red-500', 2: 'bg-yellow-500', 3: 'bg-green-500' }

export const STATUS_COLORS = {
  ACTIVE:       'text-green-400',
  DELAYED:      'text-yellow-400',
  BREAKDOWN:    'text-red-400',
  NOTACTIVATED: 'text-gray-400',
  PENDING:      'text-gray-300',
  IN_PROGRESS:  'text-blue-400',
  DELIVERED:    'text-green-400',
  FAILED:       'text-red-400',
  CANCELLED:    'text-gray-500',
}

/** Return a colour for a vehicle by index */
export function vehicleColor(index) {
  return VEHICLE_COLORS[index % VEHICLE_COLORS.length]
}

/** Format minutes as h:mm */
export function fmtMinutes(mins) {
  const h = Math.floor(mins / 60)
  const m = Math.round(mins % 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

export const EVENT_TYPE_LABELS = {
  TRAFFIC_UPDATE: 'Traffic Update',
  VEHICLE_BREAKDOWN: 'Vehicle Breakdown',
  NEW_DELIVERY: 'New Delivery',
  DELIVERY_CANCELLED: 'Delivery Cancelled',
  ROAD_BLOCKED: 'Road Blocked',
  TIME_WINDOW_CHANGE: 'Time Window Change',
}

