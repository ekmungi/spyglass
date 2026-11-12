// How-to content: Sources (feeds, FDA decisions, link channels), Watch (organisations and topics)
// and Find papers. Every step was checked against the screens' own labels.
import type { HelpGroup } from './types'

export const SOURCES_GROUP: HelpGroup = {
  id: 'sources',
  heading: 'Sources: where material comes from',
  tasks: [
    {
      id: 'add-a-feed',
      title: 'Add a feed',
      purpose: 'Make Spyglass read a blog, newsletter or journal for new items.',
      steps: [
        'Open {{Sources}} in the left rail.',
        'Under {{Feeds}}, find the box labelled {{Add a feed}} and paste the address of the feed, or of a page that has one.',
        'Press {{Add feed}}. The address must start with http:// or https://.',
        'If the address was a web page, Spyglass lists the feeds it found. Press {{Follow}} beside the one you want.',
      ],
      next: 'Spyglass checks the new feed at every collection and puts what is new into your Feed.',
      target: { name: 'sources' },
      keywords: ['rss', 'subscribe', 'blog', 'newsletter', 'journal', 'source'],
    },
    {
      id: 'pause-or-remove-a-feed',
      title: 'Pause or remove a feed',
      purpose: 'Stop a feed that is noisy, either for a while or for good.',
      steps: [
        'Open {{Sources}}, then find the feed under {{Feeds}}.',
        'To pause it, switch off the toggle named "[feed name] on or off". Switch it on again later to resume.',
        'To remove it, open the menu named "Actions for [feed name]", choose {{Remove…}} and press {{Remove feed}}.',
      ],
      next: 'A paused feed is skipped at collection but keeps its items. Removing a feed deletes the feed and every item it collected, and cannot be undone.',
      target: { name: 'sources' },
      keywords: ['stop', 'delete', 'unsubscribe', 'mute'],
    },
    {
      id: 'check-a-feed-delivers',
      title: 'Check that a feed delivers',
      purpose: 'See whether a feed is working and when it last brought something.',
      steps: [
        'Open {{Sources}} and look at the feed under {{Feeds}}.',
        'Read the status beside its name: it says whether the feed is working, and shows {{Failing}} with the reason when it is not.',
        'Read the line below it: when it was last fetched and how many items it has brought.',
      ],
      next: 'Spyglass records the result of every fetch for each feed, and the row shows the newest result.',
      target: { name: 'sources' },
      keywords: ['working', 'failing', 'broken', 'status', 'last fetched'],
    },
    {
      id: 'follow-fda-decisions',
      title: 'Follow FDA decisions by product code or keyword',
      purpose: 'Get FDA device decisions for whoever makes a kind of device, not only for companies you watch.',
      steps: [
        'Open {{Sources}} and find {{FDA device decisions}} ({{Clearances, approvals and recalls}}).',
        'Switch the section on with its toggle named "FDA device decisions on or off".',
        'In {{Product codes}}, type three-character FDA product codes separated by commas. In {{Device keywords}}, type words from a device name, also separated by commas. Both are optional.',
        'Press {{Save lists}}.',
      ],
      next: 'Once a day Spyglass asks the public FDA database for decisions matching your codes, your keywords and your watched companies, and adds each as an item from the regulator.',
      target: { name: 'sources' },
      keywords: ['510k', 'fda', 'regulator', 'recall', 'device', 'openfda'],
    },
    {
      id: 'set-up-raindrop-slack-mail',
      title: 'Set up Raindrop, Slack and the mail label',
      purpose: 'Send links into Spyglass from your bookmarks, a Slack channel or a Gmail label.',
      steps: [
        'Open {{Sources}} and find the section {{From you}}.',
        'Read the row for Raindrop, Slack or {{Gmail label}}: it says what that channel needs and shows a {{setup guide}} link.',
        'Follow the setup guide. The keys and addresses go in the .env file; the Slack steps are in the user guide, section "Connecting Slack".',
        'Restart Spyglass, then reopen {{Sources}}. The row should say Configured.',
      ],
      next: 'A configured channel is read on each collection, and every link it finds becomes an item marked as sent by you.',
      target: { name: 'sources' },
      keywords: ['bookmark', 'gmail', 'email', 'token', 'channel', 'integration'],
    },
  ],
}

export const WATCH_GROUP: HelpGroup = {
  id: 'watch',
  heading: 'Watch: organisations and topics',
  tasks: [
    {
      id: 'find-organisations-for-a-topic',
      title: 'Find the organisations for a topic',
      purpose: 'Get a list of companies, labs and regulators that matter for a subject.',
      steps: [
        'Open {{Watch}} and press {{Add}}.',
        'Choose {{Find who matters for a topic}}.',
        'Type the topic (at least two letters) in {{Topic}} and press {{Find}}.',
        'Under {{Suggested}}, press {{Accept}} on the names you want and {{Dismiss}} on the rest.',
      ],
      next: 'Spyglass asks the AI to propose organisations for the topic and keeps your accepted names on the watch list.',
      target: { name: 'watch' },
      keywords: ['company', 'lab', 'regulator', 'discover', 'who matters'],
    },
    {
      id: 'follow-a-topic',
      title: 'Follow a topic',
      purpose: 'Have Spyglass search the news for a subject every day.',
      steps: [
        'Open {{Watch}} and press {{Add}}.',
        'Choose {{Follow a topic}}.',
        'Fill in {{Name}}, optionally a {{Search phrase}} (left empty, it searches for the name) and a {{Section}}.',
        'Press {{Follow}}. The topic appears under {{Topics you follow}}, where its menu has {{Edit}} and {{Stop following}}.',
      ],
      next: 'On every collection Spyglass searches the news for the topic and puts what it finds in your Feed.',
      target: { name: 'watch' },
      keywords: ['subject', 'search', 'news', 'stop following', 'topic'],
    },
    {
      id: 'add-one-organisation',
      title: 'Add one organisation',
      purpose: 'Put a company, lab or regulator you already know on the watch list.',
      steps: ['Open {{Watch}} and press {{Add}}.', 'Choose {{Add one organisation}}.', 'Fill in the form and press {{Add}}.'],
      next: 'Spyglass checks that name every day and shows what it publishes in the brief.',
      target: { name: 'watch' },
      keywords: ['company', 'name', 'regulator'],
    },
    {
      id: 'accept-or-dismiss-a-suggestion',
      title: 'Accept or dismiss a suggestion',
      purpose: 'Decide whether a name Spyglass found belongs on your watch list.',
      steps: ['Open {{Watch}} and find the section {{Suggested}}.', 'Press {{Accept}} to keep a name, or {{Dismiss}} to drop it.'],
      next: 'An accepted name joins the watch list; a dismissed one is removed from the suggestions.',
      target: { name: 'watch' },
      keywords: ['suggested', 'proposal'],
    },
    {
      id: 'manage-a-watch-group',
      title: 'Pause, rename, move or remove a group',
      purpose: 'Tidy a group of watched names.',
      steps: [
        'Open {{Watch}} and open the menu named "Actions for the group [name]" on the group heading.',
        'Choose {{Pause this group}}, {{Rename group…}}, {{Move all to another group…}} or {{Remove this group…}}.',
        'A paused group shows {{Paused}}; press {{Resume}} to bring it back.',
        'For a single name, use the menu named "Actions for [name]" on its row: it has {{Edit}}, {{Mute}} or {{Watch again}}, and {{Remove…}}.',
      ],
      next: 'A paused group is skipped at collection but keeps its names. Removing a name stops the checks and forgets which items mention it; the items stay in your Feed.',
      target: { name: 'watch' },
      keywords: ['rename', 'delete', 'mute', 'category'],
    },
    {
      id: 'review-the-watch-list-with-ai',
      title: 'Review the watch list with AI',
      purpose: 'Get suggested clean-ups of the whole list in one pass.',
      steps: ['Open {{Watch}} and press {{Review with AI}}.', 'Tick the changes you agree with.', 'Press {{Apply selected}}, or {{Cancel}} to change nothing.'],
      next: 'The AI reads the list and proposes changes; only the changes you tick are applied.',
      target: { name: 'watch' },
      keywords: ['clean up', 'tidy', 'merge', 'duplicates'],
    },
    {
      id: 'see-a-groups-items-in-the-feed',
      title: "See a group's items in the Feed",
      purpose: 'Read everything the names in one group brought this week.',
      steps: [
        'Open {{Watch}}.',
        'On the group heading, press the line that shows how many items it brought this week ({{Show these items in the Feed}}).',
        'The Feed opens with a chip "Watch: [group]". Press {{Clear}} on the chip to return to the whole Feed.',
      ],
      next: 'The Feed is filtered to the items about the names in that group from the last seven days.',
      target: { name: 'watch' },
      keywords: ['group', 'week', 'chip'],
    },
  ],
}

export const PAPERS_GROUP: HelpGroup = {
  id: 'papers',
  heading: 'Papers',
  tasks: [
    {
      id: 'find-papers-for-a-topic',
      title: 'Find papers for a topic',
      purpose: 'Get the few papers that matter for a subject, ranked against your profile.',
      steps: [
        'Open {{Find papers}} in the left rail.',
        'Type a subject in the box {{What do you want to read about?}}, or pick one of the {{Topics from your profile}}.',
        'Read each result: {{How it relates to you}} is one line on its fit, {{Abstract}} opens the summary, and {{Open}} or {{PDF}} opens the paper.',
      ],
      next: 'Spyglass searches paper sources for the topic and ranks the results against your profile.',
      target: { name: 'papers' },
      keywords: ['research', 'arxiv', 'literature', 'pdf'],
    },
    {
      id: 'follow-a-paper-search',
      title: 'Follow a paper search',
      purpose: 'Keep getting new papers on a subject without searching again.',
      steps: [
        'Open {{Watch}} and press {{Add}}, then choose {{Follow a topic}}.',
        'Give the topic a {{Name}}, choose a {{Section}}, and press {{Follow}}.',
      ],
      next: 'The topic is searched on every collection, and new papers join the Feed. The Find papers page has no Follow button of its own, so this is how a paper search is repeated.',
      target: { name: 'watch' },
      keywords: ['alert', 'subscribe', 'keep', 'arxiv'],
    },
  ],
}
