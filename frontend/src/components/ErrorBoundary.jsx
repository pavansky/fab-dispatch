import { Component } from 'react'
import { LINKS, reportProblemUrl } from '../lib/links.js'

/** Last line of defence: a render error shows a way forward, not a blank page. */
export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('UI error', error, info?.componentStack) // reaches the browser console and any log drain
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <main className="signin" role="alert">
        <div className="signin-card card">
          <div className="brand" style={{ marginBottom: 18 }}><span className="brand-mark"><span /></span>Fab Dispatch</div>
          <h1>Something went wrong</h1>
          <p className="help">The page hit an unexpected error. Your shifts are safe on the server. Reloading usually fixes it.</p>
          <pre className="error-detail">{String(error.message || error)}</pre>
          <div className="signin-roles">
            <button className="btn primary" onClick={() => location.reload()}>Reload</button>
            <a className="btn" href={reportProblemUrl({ title: `UI error: ${String(error.message || error).slice(0, 80)}`, error: error.message })} target="_blank" rel="noopener noreferrer">Report this problem</a>
          </div>
          <p className="help" style={{ marginTop: 14 }}><a href={LINKS.support} target="_blank" rel="noopener noreferrer">Support</a> · <a href={LINKS.docs} target="_blank" rel="noopener noreferrer">Documentation</a></p>
        </div>
      </main>
    )
  }
}
