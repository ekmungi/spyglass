// Secondary pages (Watch, Find papers, Sources, Profile, Settings) are built in their own files,
// each a default-export component with no props. They are collected with an eager glob so a page
// that does not exist yet shows a placeholder instead of breaking the build.
import type { ComponentType } from 'react'
import { EmptyState } from '../ui'

type PageModule = { default: ComponentType }

const modules = import.meta.glob<PageModule>(
  ['../pages/WatchPage.tsx', '../pages/PapersPage.tsx', '../pages/SourcesPage.tsx', '../pages/ProfilePage.tsx', '../pages/SettingsPage.tsx'],
  { eager: true },
)

export type SecondaryName = 'watch' | 'papers' | 'sources' | 'profile' | 'settings'

const FILES: Record<SecondaryName, { file: string; title: string }> = {
  watch: { file: '../pages/WatchPage.tsx', title: 'Watch' },
  papers: { file: '../pages/PapersPage.tsx', title: 'Find papers' },
  sources: { file: '../pages/SourcesPage.tsx', title: 'Sources' },
  profile: { file: '../pages/ProfilePage.tsx', title: 'Profile' },
  settings: { file: '../pages/SettingsPage.tsx', title: 'Settings' },
}

/** Render the secondary page for a route name, or a "being built" placeholder if its file is missing. */
export function SecondaryPage({ name }: { name: SecondaryName }) {
  const entry = FILES[name]
  const Page = modules[entry.file]?.default
  if (Page) return <Page />
  return (
    <div className="r-page">
      <h1 className="r-page-title">{entry.title}</h1>
      <EmptyState title="This page is being built" body="It will appear here in the next version of Spyglass." />
    </div>
  )
}
