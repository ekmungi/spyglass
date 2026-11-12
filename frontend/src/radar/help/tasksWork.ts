// How-to content: Sending things in, Keeping (saving and filing) and Asking (the assistant).
import type { HelpGroup } from './types'

export const SENDING_GROUP: HelpGroup = {
  id: 'sending',
  heading: 'Sending things in',
  tasks: [
    {
      id: 'install-the-browser-extension',
      title: 'Install the browser extension and send a page or a selection',
      purpose: 'Send any page, even one behind a paywall or a bot check, from the browser you are reading it in.',
      steps: [
        'Open {{Settings}} and find {{Browser extension (recommended)}}.',
        'Open your browser\'s extensions page and press {{Load unpacked}}; choose the folder named browser-extension.',
        'Pin its button, open its settings, paste the {{Key}} shown in Settings (press {{Copy}}) and press {{Test connection}}.',
        'On a page, click the extension\'s button to send the page, or select text first to send only the selection.',
      ],
      next: 'The extension reads the page in your own browser and hands the text to Spyglass, which adds it under From you and analyses it.',
      target: { name: 'settings', section: 'bring-in' },
      keywords: ['chrome', 'vivaldi', 'send to spyglass', 'key', 'paywall', 'bookmarklet'],
    },
    {
      id: 'add-a-link',
      title: 'Add a link',
      purpose: 'Bring one web page into Spyglass by its address.',
      steps: [
        'Press {{Add link}} in the left rail.',
        'Paste the address in {{Web address}} and, if you like, write {{Note for yourself (optional)}}.',
        'Press {{Add}}. When it is done, {{Open}} shows the item and {{Follow more like this}} suggests topics from it.',
      ],
      next: 'Spyglass reads the page and adds it to today\'s From you section.',
      target: { name: 'feed', params: { from_user: 'true' } },
      keywords: ['url', 'address', 'paste', 'from you'],
    },
    {
      id: 'paste-text-or-add-a-file',
      title: 'Paste text or add a file',
      purpose: 'Bring in an article Spyglass could not read, or a saved file.',
      steps: [
        'Press {{Add link}} in the left rail, then choose {{Paste the text}} or {{add a saved file}} at the bottom of the dialog.',
        'For text: give the {{Web address of the article}} and paste {{The article\'s text}}. For a file: give the {{Web address of the page}} and choose the {{File}}.',
        'Confirm with the button at the bottom of the dialog.',
      ],
      next: 'Spyglass uses the text or file you supplied in place of fetching the page, and files the item under From you.',
      target: { name: 'feed', params: { from_user: 'true' } },
      keywords: ['pdf', 'upload', 'copy', 'paywall'],
    },
  ],
}

export const KEEPING_GROUP: HelpGroup = {
  id: 'keeping',
  heading: 'Keeping: saving and filing',
  tasks: [
    {
      id: 'save-for-later',
      title: 'Save for later',
      purpose: 'Keep an item inside Spyglass so you can find it again.',
      steps: [
        'On an item row or at the top of the reader, press the bookmark button {{Save for later}}.',
        'To see saved items, open {{Feed}} and press the chip {{Saved}}.',
      ],
      next: 'Spyglass marks the item as saved on your computer; nothing leaves it.',
      target: { name: 'feed', params: { saved: 'true' } },
      keywords: ['bookmark', 'keep', 'star'],
    },
    {
      id: 'file-in-vault',
      title: 'File in vault, and File as',
      purpose: 'Queue an item to become a note in your notes vault.',
      steps: [
        'At the top of the reader, press {{File in vault}}. It then reads {{Waiting to be filed}}.',
        'For more choices, press the small arrow beside it and choose {{File as…}}.',
        'In {{File it as}}, pick the kind of note, a {{Project}} (or {{No project}}), an optional note, and confirm.',
      ],
      next: 'The item joins your filing queue and nothing is written yet; the vault is written only when you choose File now and say yes in Claude Code.',
      target: { name: 'feed', params: { filing: 'waiting' } },
      keywords: ['obsidian', 'queue', 'note', 'project'],
      needs: 'filing',
    },
    {
      id: 'file-now-and-approve-the-plan',
      title: 'File now',
      purpose: 'Turn the queued items into notes.',
      steps: [
        'Open {{Feed}} and press the chip {{To file}}.',
        'Under {{Waiting}} press {{File now}}; {{See the request}} shows exactly what is sent to Claude Code.',
        'Claude Code opens in your notes vault and shows one table of where each item goes.',
        'Say yes in Claude Code. The items then show as filed.',
      ],
      next: 'One Claude Code session opens in your vault, shows one table of where each item goes and waits for your yes; it writes the notes one at a time.',
      target: { name: 'feed', params: { filing: 'waiting' } },
      keywords: ['claude code', 'vault', 'approve', 'queue', 'file now'],
      needs: 'filing',
    },
    {
      id: 'discuss-an-item-in-claude-code',
      title: 'Open an item in Claude Code to discuss it',
      purpose: 'Talk about one item in a full Claude Code session.',
      steps: [
        'Open the item in the reader.',
        'Open the menu {{More actions}} and choose {{Open in Claude Code…}}.',
        'Write what Claude Code should do with the item and confirm; the box {{Exactly what will be sent}} shows the request.',
      ],
      next: 'Claude Code opens in your notes vault with this item, and you see and approve everything it does there.',
      target: { name: 'feed', params: {} },
      keywords: ['claude', 'session', 'discuss'],
    },
  ],
}

export const ASKING_GROUP: HelpGroup = {
  id: 'asking',
  heading: 'Asking the assistant',
  tasks: [
    {
      id: 'ask-about-an-article',
      title: 'Ask about an article or a passage',
      purpose: 'Get an explanation or an answer about what you are reading.',
      steps: [
        'Open an item in the reader. If the assistant is closed, press {{Ask the assistant}}.',
        'Press a starter such as {{Explain}} or {{How is this relevant to me?}}, or type a question in the box and press {{Send}}.',
        'To ask about one passage, select the text in the article and choose {{Ask}}, {{Explain}} or {{Why is this so?}} on the small bar.',
      ],
      next: 'Spyglass sends the article (and your selection) with your question to the engine you chose and streams the answer back.',
      target: { name: 'feed', params: {} },
      keywords: ['assistant', 'explain', 'chat', 'selection', 'quote'],
    },
    {
      id: 'ask-your-feed',
      title: 'Ask your whole Feed',
      purpose: 'Ask across everything collected and get an answer that cites items.',
      steps: [
        'Open {{Feed}} and press {{Ask your feed}}.',
        'Type a question, or press {{What matters most this week?}} or {{Which themes run through my feed?}}.',
        'Under an answer, press {{Show these in the Feed}} to list the items it cited.',
      ],
      next: 'Spyglass finds the items closest to your question, gives them to the engine and links each citation to its item.',
      target: { name: 'feed', params: {} },
      keywords: ['cited', 'citations', 'week', 'themes'],
    },
    {
      id: 'choose-engine-and-model',
      title: 'Choose the engine and model, and read the usage line',
      purpose: 'Pick which AI answers, and see what an answer cost in tokens.',
      steps: [
        'In the assistant panel, open the list at the top (named {{Engine}}) and choose an engine and model.',
        'To set the starting engine or add a key, open {{Settings}}.',
        'Hover over an answer: a quiet line shows the model, how much it read, how much came from cache, and how much it wrote.',
        'For totals, open {{Settings}} and find {{Usage}}.',
      ],
      next: 'Each question goes to the engine chosen at that moment, and every call is recorded as tokens on your computer.',
      target: { name: 'settings' },
      keywords: ['model', 'tokens', 'usage', 'openrouter', 'claude', 'key'],
    },
  ],
}
