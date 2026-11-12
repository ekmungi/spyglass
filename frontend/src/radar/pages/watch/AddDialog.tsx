// AddDialog: the one door for adding to Watch. It offers three choices (find who matters for a
// topic, follow a topic, add one organisation) and shows the chosen step inside the same dialog.
import { useId, useState } from 'react'
import { Button, Dialog } from '../../ui'
import type { DiscoverResult, EntryFields } from './api'
import { DiscoverPane } from './DiscoverPane'
import { EntityForm } from './EntityForm'
import { FollowPane, type FollowFields } from './FollowPane'

type Step = 'choose' | 'discover' | 'follow' | 'organisation'

const CHOICES: { step: Exclude<Step, 'choose'>; title: string; body: string }[] = [
  { step: 'discover', title: 'Find who matters for a topic', body: 'Name a topic and Spyglass proposes the organisations to watch for it.' },
  { step: 'follow', title: 'Follow a topic', body: 'Search the news for a subject every day, such as a technique or a product.' },
  { step: 'organisation', title: 'Add one organisation', body: 'A company, lab or regulator you already know.' },
]

const TITLES: Record<Step, string> = {
  choose: 'Add to Watch',
  discover: 'Find who matters for a topic',
  follow: 'Follow a topic',
  organisation: 'Add one organisation',
}

export interface AddDialogProps {
  /** Group names already in use, offered as suggestions for a new organisation. */
  categories: string[]
  onClose: () => void
  discover: (topic: string) => Promise<DiscoverResult>
  /** The register changed (discovery stored new suggestions), so the page should reload it. */
  onDiscovered: () => void
  onFollow: (fields: FollowFields) => Promise<void>
  onAddOrganisation: (fields: EntryFields) => Promise<void>
}

/** Mount it while it should be open (it starts at the three choices each time). */
export function AddDialog({ categories, onClose, discover, onDiscovered, onFollow, onAddOrganisation }: AddDialogProps) {
  const [step, setStep] = useState<Step>('choose')
  const [saving, setSaving] = useState(false)
  const formId = useId()
  const back = () => setStep('choose')

  return (
    <Dialog open onClose={onClose} title={TITLES[step]} contentKey={step}>
      {step === 'choose' && (
        <ul className="rw-choices">
          {CHOICES.map((choice) => (
            <li key={choice.step}>
              <button type="button" className="rw-choice" onClick={() => setStep(choice.step)}>
                <span className="rw-choice__title">{choice.title}</span>
                <span className="rw-choice__body">{choice.body}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {step === 'discover' && <DiscoverPane discover={discover} onDone={onDiscovered} onBack={back} />}
      {step === 'follow' && <FollowPane onFollow={onFollow} onBack={back} />}
      {step === 'organisation' && (
        <>
          <EntityForm entry={null} categories={categories} formId={formId} onSave={onAddOrganisation} onSavingChange={setSaving} />
          <div className="r-dialog__footer">
            <Button variant="quiet" onClick={back} disabled={saving}>
              Back
            </Button>
            <Button variant="primary" type="submit" form={formId} disabled={saving}>
              Add
            </Button>
          </div>
        </>
      )}
    </Dialog>
  )
}
