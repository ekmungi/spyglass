// LearnedBlock: read-only titles Spyglass derived from what the reader saved, voted for and sent in.
import { SectionHeading } from '../../ui'
import type { LearnedExamples } from './api'

/** How many titles to list before "and N more". */
const SHOWN = 8

function TitleList({ heading, titles, empty }: { heading: string; titles: readonly string[]; empty: string }) {
  return (
    <div className="rpr-learned__col">
      <h3 className="rpr-learned__title">{heading}</h3>
      {titles.length === 0 ? (
        <p className="r-meta">{empty}</p>
      ) : (
        <ul className="rpr-learned__list">
          {titles.slice(0, SHOWN).map((title) => (
            <li key={title}>{title}</li>
          ))}
        </ul>
      )}
      {titles.length > SHOWN && <p className="r-meta">and {titles.length - SHOWN} more</p>}
    </div>
  )
}

/** Two columns of example titles; these come from your own history and cannot be edited here. */
export function LearnedBlock({ examples }: { examples: LearnedExamples }) {
  return (
    <section aria-labelledby="profile-learned" className="rpr-section">
      <SectionHeading id="profile-learned">What Spyglass has learned</SectionHeading>
      <p className="r-meta rpr-lede">
        Titles from your own history. Saving an item, voting “more like this”, or sending a link in teaches Spyglass what you like; voting “less”
        teaches what you do not. You cannot edit these here.
      </p>
      <div className="rpr-learned">
        <TitleList heading="You liked" titles={examples.liked} empty="Nothing yet." />
        <TitleList heading="You did not like" titles={examples.disliked} empty="Nothing yet." />
      </div>
    </section>
  )
}
