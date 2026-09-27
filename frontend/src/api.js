import axios from 'axios'

const rawBase = import.meta.env.VITE_API_BASE_URL || '/api'
const BASE = rawBase.replace(/\/+$/, '')

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
