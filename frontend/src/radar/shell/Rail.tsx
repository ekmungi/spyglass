// Rail: the narrow left navigation (wordmark, main pages, Add link, settings pages, theme).
// Collapses to icons under 1100px; icons label navigation targets, never decoration. The rail
// itself never animates with a page change; only its active marker glides to the new entry.
import { useState, type ReactNode } from 'react'
import { buildHash, navigate, type Route, type RouteName } from '../router'
import { useTheme } from '../hooks/useTheme'
import {
  IconAdd,
  IconFeed,
  IconHelp,
  IconPapers,
  IconProfile,
  IconSettings,
  IconSources,
  IconThemeDark,
  IconThemeLight,
  IconToday,
  IconWatch,
  Tooltip,
} from '../ui'
import { AddLinkDialog } from './AddLinkDialog'

interface NavEntry {
  name: RouteName
  label: string
  icon: ReactNode
  route: Route
}

const MAIN: NavEntry[] = [
  { name: 'today', label: 'Today', icon: <IconToday size={18} />, route: { name: 'today' } },
  { name: 'feed', label: 'Feed', icon: <IconFeed size={18} />, route: { name: 'feed', params: {} } },
  { name: 'watch', label: 'Watch', icon: <IconWatch size={18} />, route: { name: 'watch' } },
  { name: 'papers', label: 'Find papers', icon: <IconPapers size={18} />, route: { name: 'papers' } },
]

const LOWER: NavEntry[] = [
  { name: 'sources', label: 'Sources', icon: <IconSources size={18} />, route: { name: 'sources' } },
  { name: 'profile', label: 'Profile', icon: <IconProfile size={18} />, route: { name: 'profile' } },
  { name: 'settings', label: 'Settings', icon: <IconSettings size={18} />, route: { name: 'settings' } },
  { name: 'help', label: 'Help', icon: <IconHelp size={18} />, route: { name: 'help' } },
]

/**
 * One navigation link; intercepts the click so history depth is tracked by the router. The active
 * link carries the marker element, which a page-change view transition moves from the old entry
 * to the new one (see shell.css).
 */
function NavLink({ entry, active }: { entry: NavEntry; active: boolean }) {
  return (
    <Tooltip label={entry.label} side="right">
      <a
        href={buildHash(entry.route)}
        className="r-rail__link"
        aria-current={active ? 'page' : undefined}
        onClick={(event) => {
          if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
          event.preventDefault()
          navigate(entry.route)
        }}
      >
        {active && <span className="r-rail__marker" aria-hidden="true" />}
        {entry.icon}
        <span className="r-rail__label">{entry.label}</span>
      </a>
    </Tooltip>
  )
}

/** The left rail; `active` is the page shown in the main column (the page under an open reader). */
export function Rail({ active }: { active: RouteName }) {
  const [adding, setAdding] = useState(false)
  const { resolved, toggle } = useTheme()
  return (
    <nav className="r-rail" aria-label="Main">
      <a
        href="#/today"
        className="r-rail__brand"
        onClick={(event) => {
          event.preventDefault()
          navigate({ name: 'today' })
        }}
      >
        <span className="r-rail__wordmark">Spyglass</span>
        <span className="r-rail__monogram" aria-hidden="true">
          S
        </span>
      </a>
      <div className="r-rail__group">
        {MAIN.map((entry) => (
          <NavLink key={entry.name} entry={entry} active={active === entry.name} />
        ))}
      </div>
      <div className="r-rail__group">
        <Tooltip label="Add link" side="right">
          <button type="button" className="r-rail__link r-rail__add" onClick={() => setAdding(true)}>
            <IconAdd size={18} />
            <span className="r-rail__label">Add link</span>
          </button>
        </Tooltip>
      </div>
      <div className="r-rail__spacer" />
      <div className="r-rail__group">
        {LOWER.map((entry) => (
          <NavLink key={entry.name} entry={entry} active={active === entry.name} />
        ))}
        <Tooltip label={resolved === 'dark' ? 'Light theme' : 'Dark theme'} side="right">
          <button type="button" className="r-rail__link" onClick={toggle} aria-label={resolved === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
            {resolved === 'dark' ? <IconThemeLight size={18} /> : <IconThemeDark size={18} />}
            <span className="r-rail__label" aria-hidden="true">
              {resolved === 'dark' ? 'Light theme' : 'Dark theme'}
            </span>
          </button>
        </Tooltip>
      </div>
      <AddLinkDialog open={adding} onClose={() => setAdding(false)} />
    </nav>
  )
}
