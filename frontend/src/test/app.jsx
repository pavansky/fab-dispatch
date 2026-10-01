// Render the whole app (auth + workspace) against the fake backend.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App.jsx'
import { AuthProvider } from '../auth.jsx'
import { mockApi, workspaceRoutes } from './api.js'

export function renderApp() {
  const user = userEvent.setup()
  render(<AuthProvider><App /></AuthProvider>)
  return user
}

/** Mock the API, sign in with the demo role, and wait for the first plan to render. */
export async function signInAs(role, routes = workspaceRoutes()) {
  const api = mockApi(routes)
  const user = renderApp()
  await user.click(await screen.findByRole('button', { name: `Continue as ${role[0].toUpperCase()}${role.slice(1)}` }))
  await screen.findByRole('region', { name: 'Recommendation' }, { timeout: 4000 })
  return { api, user }
}

/** EventSource stand-in: tests push server events with emit(). */
export class FakeEventSource {
  static instances = []
  constructor(url) {
    this.url = url
    this.listeners = {}
    this.closed = false
    FakeEventSource.instances.push(this)
    queueMicrotask(() => this.onopen?.())
  }
  addEventListener(kind, fn) { (this.listeners[kind] ??= []).push(fn) }
  emit(event) { (this.listeners[event.kind] ?? []).forEach((fn) => fn({ data: JSON.stringify(event) })) }
  close() { this.closed = true }
  static latest() { return FakeEventSource.instances.at(-1) }
}
