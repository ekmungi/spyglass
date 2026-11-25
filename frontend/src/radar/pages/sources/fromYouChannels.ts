// The channels of the From you group (Slack, Raindrop, Gmail), the collector row that reports on each,
// and the rule for "Set up, but failing", which decides both the row's words and the mark on its tab.
import type { CollectorRow } from './api'
import { collectorStatus, isNotConfigured } from './describe'

export interface Channel {
  id: string
  /** Collector keys that report on this channel, in order of preference. */
  keys: string[]
  name: string
  how: string
  /** What the channel needs, in a few words (shown before the pointer to the settings file). */
  needs: string
}

export const CHANNELS: Channel[] = [
  {
    id: 'slack',
    keys: ['slack'],
    name: 'Slack channel',
    how: 'Post a link in your Spyglass channel and it appears under From you.',
    needs: 'Slack needs a bot token and the channel to read.',
  },
  {
    id: 'raindrop',
    keys: ['raindrop'],
    name: 'Raindrop',
    how: 'Bookmark a page in Raindrop and it arrives here.',
    needs: 'Raindrop needs your access token.',
  },
  {
    id: 'gmail',
    keys: ['gmail', 'newsletter'],
    name: 'Gmail label',
    how: 'Mail yourself a link under the label Spyglass, or label newsletters Newsletters.',
    needs: 'Gmail needs your address and an app password.',
  },
]

/** The collector row that reports on a channel: the first of its keys the service lists, if any. */
export function channelRow(channel: Channel, collectors: readonly CollectorRow[]): CollectorRow | undefined {
  return channel.keys.map((key) => collectors.find((row) => row.key === key)).find(Boolean)
}

/** Whether a channel reads "Set up, but failing": it is set up, and its status reads as a problem. */
export function isChannelFailing(row: CollectorRow | undefined): boolean {
  return row !== undefined && !isNotConfigured(row) && collectorStatus(row).tone === 'problem'
}
