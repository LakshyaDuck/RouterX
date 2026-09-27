/**
 * time.js — Centralized Time Utility Module for RouterX Frontend.
 *
 * Implements authoritative time arithmetic and formatting:
 *   Current Simulation DateTime = Simulation Start DateTime + Elapsed Simulation Minutes
 *
 * Formats:
 *   - 12-hour clock times: "12:42 PM", "1:17 PM", "12:42:18 PM"
 *   - Delivery windows: "1:00 PM – 2:00 PM"
 *   - Operational durations: "15 min", "1h 30m"
 *   - ETA deltas: "↑ +15 min", "↓ -9 min"
 *   - Simulation date: "Sep 27, 2026"
 */

export function getBrowserLocalIso() {
  return new Date().toISOString()
}

export function parseDateTime(val) {
  if (!val) return new Date()
  if (val instanceof Date) return val
  const d = new Date(val)
  return isNaN(d.getTime()) ? new Date() : d
}

export function toSimulationDate(startIso, elapsedMinutes = 0) {
  const base = parseDateTime(startIso)
  return new Date(base.getTime() + (Number(elapsedMinutes) || 0) * 60_000)
}

export function toElapsedMinutes(startIso, dateObjOrIso) {
  const base = parseDateTime(startIso)
  const target = parseDateTime(dateObjOrIso)
  return Math.round(((target.getTime() - base.getTime()) / 60_000) * 10) / 10
}

/**
 * Format a time to 12-hour AM/PM string, e.g. "12:42 PM" or "12:42:18 PM".
 * Accepts either elapsed minutes (+ startIso) or an ISO/Date object.
 */
export function formatSimulationTime(startIso, elapsedOrDate, { includeSeconds = false } = {}) {
  let dt
  if (typeof elapsedOrDate === 'number') {
    dt = toSimulationDate(startIso, elapsedOrDate)
  } else {
    dt = parseDateTime(elapsedOrDate)
  }

  let hours = dt.getHours()
  const minutes = dt.getMinutes()
  const seconds = dt.getSeconds()
  const ampm = hours >= 12 ? 'PM' : 'AM'

  hours = hours % 12
  hours = hours ? hours : 12 // the hour '0' should be '12'

  const minStr = minutes < 10 ? `0${minutes}` : minutes
  const secStr = seconds < 10 ? `0${seconds}` : seconds

  if (includeSeconds) {
    return `${hours}:${minStr}:${secStr} ${ampm}`
  }
  return `${hours}:${minStr} ${ampm}`
}

/**
 * Format simulation date, e.g. "Sep 27, 2026".
 */
export function formatSimulationDate(startIso, elapsedOrDate = 0) {
  let dt
  if (typeof elapsedOrDate === 'number') {
    dt = toSimulationDate(startIso, elapsedOrDate)
  } else {
    dt = parseDateTime(elapsedOrDate)
  }

  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${months[dt.getMonth()]} ${dt.getDate()}, ${dt.getFullYear()}`
}

/**
 * Format delivery window: "1:00 PM – 2:00 PM"
 */
export function formatTimeWindow(startIso, startMin, endMin) {
  const sStr = formatSimulationTime(startIso, Number(startMin) || 0)
  const eStr = formatSimulationTime(startIso, Number(endMin) || 0)
  return `${sStr} – ${eStr}`
}

/**
 * Format duration (for travel time, delay, etc.): "42 min" or "1h 15m"
 */
export function formatDuration(minutes) {
  const mins = Math.round(Number(minutes) || 0)
  if (Math.abs(mins) < 60) {
    return `${mins} min`
  }
  const hours = Math.floor(Math.abs(mins) / 60)
  const rem = Math.abs(mins) % 60
  const sign = mins < 0 ? '-' : ''
  if (rem === 0) {
    return `${sign}${hours}h`
  }
  return `${sign}${hours}h ${rem}m`
}

/**
 * Format ETA delta: "↑ +15 min", "↓ -9 min", or "0 min"
 */
export function formatEtaDelta(deltaMinutes) {
  const d = Math.round((Number(deltaMinutes) || 0) * 10) / 10
  if (d > 0) {
    return `↑ +${d} min`
  } else if (d < 0) {
    return `↓ -${Math.abs(d)} min`
  }
  return '0 min'
}

/**
 * Converts elapsed minutes to "HH:MM" (24-hour) suitable for HTML <input type="time">
 */
export function minutesToTimeInput(startIso, elapsedMinutes = 0) {
  const dt = toSimulationDate(startIso, elapsedMinutes)
  const h = String(dt.getHours()).padStart(2, '0')
  const m = String(dt.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}

/**
 * Converts HTML <input type="time"> value "HH:MM" to elapsed minutes relative to startIso.
 * Automatically handles midnight transitions.
 */
export function timeInputToMinutes(startIso, hhmmString) {
  if (!hhmmString) return 0
  const [hStr, mStr] = hhmmString.split(':')
  const hours = parseInt(hStr, 10) || 0
  const minutes = parseInt(mStr, 10) || 0

  const base = parseDateTime(startIso)
  const target = new Date(base.getTime())
  target.setHours(hours, minutes, 0, 0)

  // If target time is before base time by more than 3 hours, assume it crosses into the next day
  const diffMins = (target.getTime() - base.getTime()) / 60_000
  if (diffMins < -180) {
    target.setDate(target.getDate() + 1)
  }

  return Math.round(((target.getTime() - base.getTime()) / 60_000) * 10) / 10
}

/**
 * Parses user input like "2:30 PM", "14:30", "9:00 AM" into elapsed minutes.
 */
export function parseClockToMinutes(startIso, inputStr) {
  if (!inputStr) return 0
  const cleaned = String(inputStr).trim().toUpperCase()

  const m12 = cleaned.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)$/)
  const m24 = cleaned.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/)

  let hour = 0
  let minute = 0

  if (m12) {
    let h = parseInt(m12[1], 10)
    minute = parseInt(m12[2], 10)
    const meridian = m12[4]
    if (meridian === 'PM' && h < 12) h += 12
    if (meridian === 'AM' && h === 12) h = 0
    hour = h
  } else if (m24) {
    hour = parseInt(m24[1], 10)
    minute = parseInt(m24[2], 10)
  } else {
    const num = parseFloat(cleaned)
    return isNaN(num) ? 0 : num
  }

  const base = parseDateTime(startIso)
  const target = new Date(base.getTime())
  target.setHours(hour, minute, 0, 0)

  const diffMins = (target.getTime() - base.getTime()) / 60_000
  if (diffMins < -180) {
    target.setDate(target.getDate() + 1)
  }

  return Math.round(((target.getTime() - base.getTime()) / 60_000) * 10) / 10
}
