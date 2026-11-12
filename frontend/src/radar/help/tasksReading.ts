// How-to content: Reading, Tuning (telling Spyglass what you like) and Settings and safety.
// These groups are shorter than the others; the list of gaps is in the hand-over report.
import type { HelpGroup } from './types'

export const READING_GROUP: HelpGroup = {
  id: 'reading',
  heading: 'Reading',
  tasks: [
    {
      id: 'read-todays-brief',
      title: "Read today's brief, or an earlier day's",
      purpose: 'Go through the short, finite list of what matters today.',
      steps: [
        'Open {{Today}}. Click an item to open it in the reader.',
        'For an earlier day, press {{Earlier briefs}} and choose a date. {{Go to the latest}} returns to today.',
      ],
      next: 'Spyglass composes one brief per publishing day from what passed your filters; the brief ends at "You are caught up."',
      target: { name: 'today' },
      keywords: ['brief', 'today', 'earlier', 'day'],
    },
    {
      id: 'use-the-feed-filters',
      title: 'Use the Feed and its filters',
      purpose: 'Find older items, or items the brief left out.',
      steps: [
        'Open {{Feed}}. Type in the search box, or press {{Related}} first to search by meaning.',
        'Press a section chip such as {{All sections}}, or the chips {{Saved}}, {{From you}}, {{To file}} (shown only when filing is set up) and {{Missed}}.',
        'Open {{Filters}} for the kind of item, {{Show filtered-out items}} and {{Filed}}.',
      ],
      next: 'The address changes with each filter, so the same view can be bookmarked or opened again.',
      target: { name: 'feed', params: {} },
      keywords: ['search', 'missed', 'saved', 'related', 'filter', 'section'],
    },
    {
      id: 'reading-width-and-font',
      title: 'Change the reading width and font',
      purpose: 'Make the text easier on your eyes.',
      steps: [
        'In the reader, open {{More actions}} and choose {{Narrower text}} or {{Wider text}}.',
        'For fonts, open {{Settings}}, find {{Appearance}} and pick a reading font.',
      ],
      next: 'The change applies at once and is remembered on this device.',
      target: { name: 'settings' },
      keywords: ['font', 'width', 'size', 'theme', 'dark'],
    },
  ],
}

export const TUNING_GROUP: HelpGroup = {
  id: 'tuning',
  heading: 'Tuning what you see',
  tasks: [
    {
      id: 'more-or-less-like-this',
      title: 'More like this and Less like this',
      purpose: 'Teach Spyglass what you want more or less of.',
      steps: ['Open an item in the reader.', 'Open {{More actions}} and choose {{More like this}} or {{Less like this}}.'],
      next: 'Spyglass counts your vote with what you open, save and ask about, and uses it in the next judging.',
      target: { name: 'feed', params: {} },
      keywords: ['vote', 'learn', 'like'],
    },
    {
      id: 'follow-from-an-article',
      title: 'Follow topics from an article',
      purpose: 'Turn an article into topics Spyglass keeps searching for.',
      steps: ['Open the article and press {{Follow}}.', 'Tick the topics in {{Follow more like this}} and confirm.'],
      next: 'Spyglass reads the article, lists topics it found, and searches the news for each one you keep.',
      target: { name: 'watch' },
      keywords: ['topics', 'follow'],
    },
    {
      id: 'edit-your-profile',
      title: 'Edit your profile and projects',
      purpose: 'Say who you are and what you need to know, so everything is judged against it.',
      steps: [
        'Open {{Profile}}.',
        'Edit {{About you}}, {{Sections}}, {{Topics}} and {{Leave out}}, then save.',
        'Under {{Your projects}} describe the projects the assistant may mention.',
      ],
      next: 'Changes to the profile take effect from the next collection onward.',
      target: { name: 'profile' },
      keywords: ['interests', 'sections', 'projects'],
    },
  ],
}

export const SETTINGS_GROUP: HelpGroup = {
  id: 'settings',
  heading: 'Settings and safety',
  tasks: [
    {
      id: 'privacy-brief-time-and-appearance',
      title: 'Privacy switches, brief time and appearance',
      purpose: 'Control what leaves your computer, when the brief is made, and how the app looks.',
      steps: [
        'Open {{Settings}}.',
        'Under {{Privacy}} switch off what you do not want sent to AI or outside services.',
        'Under {{Daily brief}} set {{Brief time}} and press {{Save brief settings}}.',
        'Under {{Appearance}} choose {{Theme}}, text size and width.',
      ],
      next: 'Privacy and brief settings are saved in Spyglass; appearance is saved on this device only.',
      target: { name: 'settings' },
      keywords: ['privacy', 'theme', 'dark', 'time', 'usage', 'backup'],
    },
  ],
}
