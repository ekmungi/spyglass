// FocusChip: the line above a Feed list that says what the list is narrowed to ("Related to ...",
// "Watch: AI labs") with a way back to the whole feed.

/** A pill with the narrowing in words and a Clear link. */
export function FocusChip({ text, onClear }: { text: string; onClear: () => void }) {
  return (
    <p className="r-feed-focus">
      <span className="r-feed-focus__chip">
        <span className="r-feed-focus__text">{text}</span>
        <span aria-hidden="true">·</span>
        <button type="button" onClick={onClear}>
          Clear
        </button>
      </span>
    </p>
  )
}
