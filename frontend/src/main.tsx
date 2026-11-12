// Entry point: renders the redesigned Spyglass interface (the radar app).
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './radar/styles.css'
import RadarApp from './radar/App'
import { initAppearance } from './radar/appearance/appearanceStore'

initAppearance()
document.title = 'Spyglass'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RadarApp />
  </StrictMode>,
)
