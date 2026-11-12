// Profile page: the description of the reader that Spyglass judges every item against. Editable
// statement, sections, topics and avoid list; a read-only block of what Spyglass has learned.
import './profile/profile.css'
import { useEffect, useId, useState } from 'react'
import { errorMessage } from '../api/errors'
import type { Profile } from '../api/types'
import { Button, SectionHeading, Skeleton } from '../ui'
import { loadProfile, saveProfile, type ProfileReply } from './profile/api'
import { AvoidEditor } from './profile/AvoidEditor'
import { forgetDraft, recallDraft, rememberDraft } from './profile/draftMemory'
import { LearnedBlock } from './profile/LearnedBlock'
import { ProjectsSection } from './profile/ProjectsSection'
import { SectionsEditor } from './profile/SectionsEditor'
import { TopicsEditor } from './profile/TopicsEditor'
import { cleanProfile, countErrors, LIMITS, sameProfile, validateProfile } from './profile/validate'
import { useLoad } from './sources/useLoad'

/** The Profile page (no props). */
export default function ProfilePage() {
  const load = useLoad<ProfileReply>((signal) => loadProfile(signal))
  const saved = load.data?.profile ?? null
  // `edits` is null until the reader changes something; a draft left behind earlier is picked up.
  const [edits, setEdits] = useState<Profile | null>(null)
  const recalled = saved ? recallDraft(saved.version) : null
  const current = edits ?? recalled ?? saved
  const dirty = current !== null && saved !== null && !sameProfile(current, saved)
  const [showErrors, setShowErrors] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [justSaved, setJustSaved] = useState(false)
  const statementId = useId()

  useEffect(() => {
    if (!dirty) return
    // The browser's own "leave this page?" prompt, for closing the tab or reloading with unsaved edits.
    const guard = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])

  if (load.error && !load.data) {
    return (
      <div className="r-page">
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
      <div className="r-page">
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

  /** Apply one edit to the current draft and remember it for later. */
  const change = (update: (profile: Profile) => Profile) => {
    const next = update(current)
    setEdits(next)
    setJustSaved(false)
    setSaveError(null)
    if (sameProfile(next, saved)) forgetDraft()
    else rememberDraft(saved.version, next)
  }

  const discard = () => {
    forgetDraft()
    setEdits(saved)
    setShowErrors(false)
    setSaveError(null)
  }

  const save = async () => {
    setShowErrors(true)
    if (problems > 0) return
    setSaving(true)
    setSaveError(null)
    try {
      const reply = await saveProfile(cleanProfile(current))
      forgetDraft()
      load.replace(reply)
      setEdits(null)
      setShowErrors(false)
      setJustSaved(true)
    } catch (cause) {
      setSaveError(errorMessage(cause))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="r-page">
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

      <ProjectsSection />

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

      <LearnedBlock examples={load.data?.examples ?? { liked: [], disliked: [] }} />

      <div className="rpr-savebar">
        <div className="rpr-savebar__text" role="status" aria-live="polite">
          {showErrors && problems > 0 ? (
            <span className="r-error-text">
              {problems === 1 ? 'One thing needs fixing before you can save.' : `${problems} things need fixing before you can save.`}
              {shown.lists.length > 0 && ` ${shown.lists.join(' ')}`}
            </span>
          ) : saveError ? (
            <span className="r-error-text">{saveError}</span>
          ) : justSaved ? (
            <span className="rpr-saved">Saved. Changes apply to items collected from now on.</span>
          ) : dirty ? (
            <span className="r-meta">You have unsaved changes. They apply to items collected after you save.</span>
          ) : (
            <span className="r-meta">Changes apply to newly collected items; items already collected keep their earlier judgement.</span>
          )}
        </div>
        <Button variant="quiet" disabled={!dirty || saving} onClick={discard}>
          Discard changes
        </Button>
        <Button variant="primary" disabled={!dirty || saving} onClick={() => void save()}>
          {saving ? 'Saving…' : 'Save profile'}
        </Button>
      </div>
    </div>
  )
}
