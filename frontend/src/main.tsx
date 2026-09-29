import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

const root = createRoot(document.getElementById('root')!)

// /cardlab is a development page (pages/CardLab.tsx). The condition is a build-time
// constant, so a production build drops the import and the page with it.
if (import.meta.env.DEV && window.location.pathname === '/cardlab') {
  import('./pages/CardLab.tsx').then(({ default: CardLab }) => {
    root.render(<StrictMode><CardLab /></StrictMode>)
  })
} else {
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}
