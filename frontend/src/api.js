import axios from 'axios'

// Resolve backend API URL.
// In Vite, client-accessible env vars MUST be prefixed with VITE_.
// Supports VITE_API_URL, VITE_API_BASE_URL, or VITE_BACKEND_URL.
function resolveApiBase() {
  const envUrl = (
    import.meta.env.VITE_API_URL ||
    import.meta.env.VITE_API_BASE_URL ||
    import.meta.env.VITE_BACKEND_URL ||
    ''
  ).trim()

  if (!envUrl) {
    // Default to relative '/api' (works with Vite dev proxy and Nginx reverse proxy)
    return '/api'
  }

  // Remove any trailing slashes
  const clean = envUrl.replace(/\/+$/, '')

  // If already ends with '/api' or is relative '/api', use directly
  if (clean === '/api' || clean.endsWith('/api')) {
    return clean
  }

  // If given a domain/host URL like 'https://routerx.onrender.com' or 'http://localhost:8000',
  // append '/api' so all endpoints like `${BASE}/state` reach `${clean}/api/state`.
  return `${clean}/api`
}

const BASE = resolveApiBase()

export const api = {
  getState:     () => axios.get(`${BASE}/state`),
  getVehicles:  () => axios.get(`${BASE}/vehicles`),
  getDeliveries:() => axios.get(`${BASE}/deliveries`),
  getRoutes:    () => axios.get(`${BASE}/routes`),
  getNodes:     () => axios.get(`${BASE}/nodes`),
  getRoads:     () => axios.get(`${BASE}/roads`),
  getEvents:    () => axios.get(`${BASE}/events`),
  createEvent:  (eventData) => axios.post(`${BASE}/events`, eventData),
  postTrafficEvent: (data) => axios.post(`${BASE}/events/traffic`, data),
  postBreakdownEvent: (data) => axios.post(`${BASE}/events/breakdown`, data),
  postNewDeliveryEvent: (data) => axios.post(`${BASE}/events/new-delivery`, data),
  postCancelDeliveryEvent: (data) => axios.post(`${BASE}/events/cancel-delivery`, data),
  postRoadBlockEvent: (data) => axios.post(`${BASE}/events/road-block`, data),
  postTimeWindowChangeEvent: (data) => axios.post(`${BASE}/events/time-window-change`, data),
  optimize:     (options) => axios.post(`${BASE}/optimize`, options || {}),
  health:       () => axios.get(`${BASE}/health`),

  // Scenario Builder entity creation
  addVehicle:   (data) => axios.post(`${BASE}/vehicles`, data),
  addDelivery:  (data) => axios.post(`${BASE}/deliveries`, data),
  addNode:      (data) => axios.post(`${BASE}/nodes`, data),

  // Simulation & Hackathon Demo Walkthrough
  resetSimulation: (data) => axios.post(`${BASE}/simulation/reset`, data || {}),
  freshSimulation: (data) => axios.post(`${BASE}/simulation/fresh`, data || {}),
  getSimulationState: () => axios.get(`${BASE}/simulation/state`),
  getSimulationTime: () => axios.get(`${BASE}/simulation/time`),
  setSimulationTime: (data) => axios.post(`${BASE}/simulation/time`, data),
  advanceSimulationTime: (minutes) => axios.post(`${BASE}/simulation/time/advance`, { minutes: Number(minutes) }),
  controlSimulationTime: (data) => axios.post(`${BASE}/simulation/time/control`, data),
  getDemoEvents: () => axios.get(`${BASE}/simulation/demo-events`),
  executeDemoStep: (stepId) => axios.post(`${BASE}/simulation/event/${stepId}`),
}
