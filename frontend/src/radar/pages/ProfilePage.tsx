// Profile page: the description of the reader that Spyglass judges every item against. Editable
// statement, sections, topics, projects and avoid list; a read-only block of what Spyglass has learned.
// The parts are tabs; every part stays mounted (the unselected ones are hidden) so an edit made on one
// tab is still there on the next and one Save bar covers them all, the project lines included.
import './profile/profile.css'
import { useEffect, useId, useState, type ReactNode } from 'react'
import { errorMessage } from '../api/errors'
import type { Profile } from '../api/types'
import { Button, SectionHeading, Skeleton, Tabs, type TabItem } from '../ui'
import { loadProfile, saveProfile, type ProfileReply } from './profile/api'
import { AvoidEditor } from './profile/AvoidEditor'
import { forgetDraft, recallDraft, rememberDraft } from './profile/draftMemory'
import { LearnedBlock } from './profile/LearnedBlock'
import { firstTabWithProblem, PROFILE_TABS, type ProfileTabKey } from './profile/profileTabs'
import { ProjectsSection } from './profile/ProjectsSection'
import { SectionsEditor } from './profile/SectionsEditor'
import { TopicsEditor } from './profile/TopicsEditor'
import { useProjectsDraft } from './profile/useProjectsDraft'
import { cleanProfile, countErrors, LIMITS, sameProfile, validateProfile } from './profile/validate'
import { useLoad } from './sources/useLoad'

/** What the Save bar says after a save: a confirmation, or which part was not saved and why. */
type SaveOutcome = { ok: boolean; message: string }

/** The bar's sentences after a save in which a part failed: each part that was sent, saved or not (with why). */
function describeFailure(parts: { label: string; error: string | null }[]): string {
  return parts.map((part) => (part.error === null ? `${part.label} saved.` : `${part.label} not saved. ${part.error}`)).join(' ')
}

/** One tab's content. It stays in the page when it is not selected, only hidden, so its state is kept. */
function Panel({ shown, children }: { shown: boolean; children: ReactNode }) {
  return (
    <div role="tabpanel" className="rpr-panel" hidden={!shown}>
      {children}
    </div>
  )
}

/** The Profile page (no props). */
export default function ProfilePage() {
  const load = useLoad<ProfileReply>((signal) => loadProfile(signal))
  const saved = load.data?.profile ?? null
  // `edits` is null until the reader changes something; a draft left behind earlier is picked up.
  const [edits, setEdits] = useState<Profile | null>(null)
  const recalled = saved ? recallDraft(saved.version) : null
  const current = edits ?? recalled ?? saved
  const dirty = current !== null && saved !== null && !sameProfile(current, saved)
  // The project lines are loaded and saved through their own call, but the same Save bar covers them.
  const projects = useProjectsDraft()
  const changed = dirty || projects.dirty
  const [showErrors, setShowErrors] = useState(false)
  const [saving, setSaving] = useState(false)
  const [outcome, setOutcome] = useState<SaveOutcome | null>(null)
  const statementId = useId()
  const [tab, setTab] = useState<ProfileTabKey>('about')

  useEffect(() => {
    if (!changed) return
    // The browser's own "leave this page?" prompt, for closing the tab or reloading with unsaved edits.
    const guard = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [changed])

  if (load.error && !load.data) {
    return (
      <div className="r-page r-page--wide">
        <h1 className="r-page-title">Profile</h1>
        <div className="rpr-error" role="alert">
          <p className="r-error-text">{load.error}</p>
          <Button onClick={load.reload}>Try again</Button>
        </div>
      </div>
    )
  }
  if (!current || !saved) {
    return (
      <div className="r-page r-page--wide">
        <h1 className="r-page-title">Profile</h1>
        <div aria-busy="true" aria-label="Loading your profile" className="rpr-skeleton">
          <Skeleton lines={4} />
          <Skeleton width="30%" height={14} />
          <Skeleton lines={5} />
        </div>
      </div>
    )
  }

  const errors = validateProfile(current)
  const problems = countErrors(errors)
  const shown = showErrors ? errors : { sections: {}, topics: {}, avoid: {}, lists: [] }

  // The projects count is read from the saved rows: it says what the assistant sees now.
  const counts: Partial<Record<ProfileTabKey, string>> = {
    topics: `${current.topics.length}`,
    ...(projects.sharedCount !== null && { projects: `${projects.sharedCount} shared` }),
  }
  const tabs: TabItem[] = PROFILE_TABS.map(({ key, label }) => ({ key, label, count: counts[key] }))

  /** Apply one edit to the current draft and remember it for later. */
  const change = (update: (profile: Profile) => Profile) => {
    const next = update(current)
    setEdits(next)
    setOutcome(null)
    if (sameProfile(next, saved)) forgetDraft()
    else rememberDraft(saved.version, next)
  }

  const editProjects: typeof projects.edit = (update) => {
    projects.edit(update)
    setOutcome(null)
  }

  const discard = () => {
    forgetDraft()
    setEdits(saved)
    projects.discard()
    setShowErrors(false)
    setOutcome(null)
  }

  /** Save the profile, when it changed. Returns the error message, or null when it was saved. */
  const saveProfilePart = async (): Promise<string | null> => {
    try {
      const reply = await saveProfile(cleanProfile(current))
      forgetDraft()
      load.replace(reply)
      setEdits(null)
      setShowErrors(false)
      return null
    } catch (cause) {
      return errorMessage(cause)
    }
  }

  /** Save the project lines, when they changed. Returns the error message, or null when they were saved. */
  const saveProjectsPart = async (): Promise<string | null> => {
    try {
      await projects.save()
      return null
    } catch (cause) {
      return errorMessage(cause)
    }
  }

  // Each part that changed is saved through its own call; a part that fails stays changed and is named.
  const save = async () => {
    if (dirty) {
      setShowErrors(true)
      if (problems > 0) {
        // The problem may sit on a tab that is hidden; open the first one that has one.
        const where = firstTabWithProblem(errors, current)
        if (where) setTab(where)
        return
      }
    }
    setSaving(true)
    setOutcome(null)
    const parts = [
      ...(dirty ? [{ label: 'Your profile was', error: await saveProfilePart() }] : []),
      ...(projects.dirty ? [{ label: 'Your projects were', error: await saveProjectsPart() }] : []),
    ]
    setSaving(false)
    if (parts.some((part) => part.error !== null)) {
      setOutcome({ ok: false, message: describeFailure(parts) })
    } else if (dirty) {
      setOutcome({ ok: true, message: 'Saved. Changes apply to items collected from now on.' })
    } else {
      setOutcome({ ok: true, message: 'Saved. The assistant may now mention the projects you described.' })
    }
  }

  return (
    <div className="r-page r-page--wide">
      <h1 className="r-page-title">Profile</h1>
      <p className="r-page-meta">
        Spyglass judges every item it collects against this profile. The more exactly it describes you and what you want left out, the
        better your daily brief.
      </p>

      {recalled !== null && edits === null && dirty && (
        <p className="r-meta rpr-restored" role="status">
          Your unsaved edits from earlier are back. Save them or discard them below.
        </p>
      )}

      <Tabs label="Profile" tabs={tabs} value={tab} onChange={(key) => setTab(key as ProfileTabKey)} />

      <Panel shown={tab === 'about'}>
        <section aria-labelledby="profile-statement" className="rpr-section">
          <SectionHeading id="profile-statement">About you</SectionHeading>
          <div className="r-field">
            <label htmlFor={statementId}>Who you are and what you need to know</label>
            <textarea
              id={statementId}
              className="r-textarea"
              rows={5}
              value={current.statement}
              aria-invalid={shown.statement ? true : undefined}
              aria-describedby={shown.statement ? `${statementId}-error` : undefined}
              onChange={(event) => change((profile) => ({ ...profile, statement: event.target.value }))}
            />
            <span className="r-meta">
              {current.statement.length} of {LIMITS.statement} characters
            </span>
            {shown.statement && (
              <span id={`${statementId}-error`} className="r-error-text">
                {shown.statement}
              </span>
            )}
          </div>
        </section>
      </Panel>

      <Panel shown={tab === 'sections'}>
        <section aria-labelledby="profile-sections" className="rpr-section">
          <SectionHeading id="profile-sections" note="How your brief is organised">
            Sections
          </SectionHeading>
          <SectionsEditor
            sections={current.sections}
            errors={shown.sections}
            onChange={(index, patch) =>
              change((profile) => ({ ...profile, sections: profile.sections.map((section, i) => (i === index ? { ...section, ...patch } : section)) }))
            }
          />
        </section>
      </Panel>

      <Panel shown={tab === 'topics'}>
        <section aria-labelledby="profile-topics" className="rpr-section">
          <SectionHeading id="profile-topics" note={`${current.topics.length}`}>
            Topics
          </SectionHeading>
          <TopicsEditor
            topics={current.topics}
            sections={current.sections}
            errors={shown.topics}
            onChange={(index, patch) =>
              change((profile) => ({ ...profile, topics: profile.topics.map((topic, i) => (i === index ? { ...topic, ...patch } : topic)) }))
            }
            onRemove={(index) => change((profile) => ({ ...profile, topics: profile.topics.filter((_, i) => i !== index) }))}
            onAdd={(topic) => change((profile) => ({ ...profile, topics: [...profile.topics, topic] }))}
          />
        </section>
      </Panel>

      <Panel shown={tab === 'projects'}>
        <ProjectsSection projects={{ ...projects, edit: editProjects }} />
      </Panel>

      <Panel shown={tab === 'avoid'}>
        <section aria-labelledby="profile-avoid" className="rpr-section">
          <SectionHeading id="profile-avoid" note="Never in your brief">
            Leave out
          </SectionHeading>
          <AvoidEditor
            items={current.avoid}
            errors={shown.avoid}
            onChange={(index, value) => change((profile) => ({ ...profile, avoid: profile.avoid.map((entry, i) => (i === index ? value : entry)) }))}
            onRemove={(index) => change((profile) => ({ ...profile, avoid: profile.avoid.filter((_, i) => i !== index) }))}
            onAdd={(value) => change((profile) => ({ ...profile, avoid: [...profile.avoid, value] }))}
          />
        </section>
      </Panel>

      <Panel shown={tab === 'learned'}>
        <LearnedBlock examples={load.data?.examples ?? { liked: [], disliked: [] }} />
      </Panel>

      <div className="rpr-savebar">
        <div className="rpr-savebar__text" role="status" aria-live="polite">
          {showErrors && problems > 0 ? (
            <span className="r-error-text">
              {problems === 1 ? 'One thing needs fixing before you can save.' : `${problems} things need fixing before you can save.`}
              {shown.lists.length > 0 && ` ${shown.lists.join(' ')}`}
            </span>
          ) : outcome ? (
            <span className={outcome.ok ? 'rpr-saved' : 'r-error-text'}>{outcome.message}</span>
          ) : dirty ? (
            <span className="r-meta">You have unsaved changes. They apply to items collected after you save.</span>
          ) : projects.dirty ? (
            <span className="r-meta">You have unsaved changes to your projects.</span>
          ) : (
            <span className="r-meta">Changes apply to newly collected items; items already collected keep their earlier judgement.</span>
          )}
        </div>
        <Button variant="quiet" disabled={!changed || saving} onClick={discard}>
          Discard changes
        </Button>
        <Button variant="primary" disabled={!changed || saving} onClick={() => void save()}>
          {saving ? 'Saving…' : 'Save profile'}
        </Button>
      </div>
    </div>
  )
}
