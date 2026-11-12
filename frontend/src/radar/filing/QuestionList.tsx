// QuestionList: the open "Link this to a project?" questions, one line per item, each with its
// choices as one single-choice group. ONE Submit sends every answered line; unanswered lines are
// left as they are. Nothing is written to the vault here: the next background run applies answers.
import { useId, useState } from 'react'
import { submitFilingAnswers } from '../api/client'
import { errorMessage } from '../api/errors'
import type { FilingQuestion } from '../api/types'
import { ItemLink } from '../components/ItemLink'
import { Button, SectionHeading, toast } from '../ui'

/** The toast after a submit. */
export const ANSWERS_TOAST = 'Answers saved. The next filing run adds the links.'

export interface QuestionListProps {
  questions: FilingQuestion[]
  /** Whether Submit is the view's one filled button. */
  primary?: boolean
  /** Called after a successful submit, so the view reloads. */
  onSubmitted: () => void
}

/** The Questions group of the To file view. */
export function QuestionList({ questions, primary = true, onSubmitted }: QuestionListProps) {
  const [choices, setChoices] = useState<ReadonlyMap<number, string>>(new Map())
  const [sending, setSending] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const headingId = useId()
  const answered = [...choices.entries()].filter(([id]) => questions.some((question) => question.id === id))

  const choose = (questionId: number, option: string) => {
    const next = new Map(choices)
    next.set(questionId, option)
    setChoices(next)
    setProblem(null)
  }

  const submit = async () => {
    setSending(true)
    setProblem(null)
    try {
      await submitFilingAnswers(answered.map(([question_id, choice]) => ({ question_id, choice })))
      toast(ANSWERS_TOAST)
      setChoices(new Map())
      onSubmitted()
    } catch (cause) {
      setProblem(errorMessage(cause))
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="r-filing__group r-appear" aria-labelledby={headingId}>
      <SectionHeading id={headingId} note={`${questions.length} open`}>
        Questions
      </SectionHeading>
      <ul className="r-rows r-filing__questions">
        {questions.map((question) => (
          <li key={question.id} className="r-filing__question">
            <ItemLink id={question.item_id} className="r-filing__headline">
              {question.headline}
            </ItemLink>
            <span className="r-filing__ask">{question.question}</span>
            <span className="r-filing__options" role="radiogroup" aria-label={`${question.question} ${question.headline}`}>
              {question.options.map((option) => (
                <label key={option} className="r-filing__option">
                  <input type="radio" name={`filing-question-${question.id}`} value={option} checked={choices.get(question.id) === option} onChange={() => choose(question.id, option)} />
                  <span>{option}</span>
                </label>
              ))}
            </span>
          </li>
        ))}
      </ul>
      <div className="r-filing__actions">
        <Button variant={primary ? 'primary' : 'secondary'} size="sm" disabled={answered.length === 0 || sending} onClick={() => void submit()}>
          {sending ? 'Saving…' : 'Submit answers'}
        </Button>
        <span className="r-meta">{answered.length ? `${answered.length} of ${questions.length} answered.` : 'An unanswered question changes nothing and goes after 14 days.'}</span>
      </div>
      {problem && (
        <p className="r-filing__problem" role="alert">
          {problem}
        </p>
      )}
    </section>
  )
}
