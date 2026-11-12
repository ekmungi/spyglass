# Privacy and safety

Spyglass runs on your own computer. To collect and read the news for you, it has to contact
other services: news sites, feeds, search services and the AI model that judges what matters to
you. This page lists every service Spyglass contacts, what each one receives, and the rules the
code follows when it does so. It also says plainly what these rules cannot protect.

The same list, with the values in effect on your machine, is available in the app at
`/api/radar/privacy/outbound`. It shows the exact profile text the judging AI receives, the
example titles it is sent, and which services are switched on.

## What Spyglass never does

- **It never signs in to a website.** Spyglass has no accounts on the sites it reads. The only
  credentials it holds are the keys and tokens you configure for the services listed below, and
  each one can only be sent to its own service. A key for the AI provider cannot be sent to a news
  site, to a search service or to any other address, because the code checks the destination
  before every request that carries a key.
- **It never posts, publishes or sends a message.** Slack and Gmail are only read. The mailbox is
  opened read-only, and Slack is asked only for the history of your capture channel. The one
  write Spyglass makes outside your computer belongs to the older card view. When you delete an
  item there that came from Raindrop, the bookmark is moved into a "Processed" collection in your
  own Raindrop account.
- **It never fills in or submits a form.** Pages are fetched with read requests only. The one
  exception is the automated browser check described under the switches below.
- **It never sends cookies when it fetches a page, and it keeps none.** Fetched pages get a fixed,
  generic browser identification that contains no user name, computer name, e-mail address or
  file path.
- **It never lets an AI model browse, run a program, use a tool, write a file or send anything.**
  What a model writes is text that you read. The few places where a model's answer affects a
  request are listed under "How the rules are enforced".
- **It never puts your keys, your e-mail address or file paths from your computer into a prompt.**
  These are removed from every message before it is sent to any AI model.

## Who receives what

| Service | When | What it receives | Carries a key |
| --- | --- | --- | --- |
| News sites and other web pages | When an item is read or judged | The page address and a generic browser identification | No |
| Feeds you follow | On every collection | The feed address and a generic browser identification | No |
| Article images | When you open an article | Fetched by Spyglass, not by your browser (see the switches) | No |
| AI provider (OpenRouter by default, or Claude Code, or another engine you configure) | Judging items, writing summaries, answering assistant questions | Your profile (statement, sections, topics, avoid list, example titles), item titles, snippets and article text, your assistant questions | Yes, its own key |
| Google News | Daily searches | Search text built from your topics, your watch list and subjects you follow | No |
| arXiv | Find papers | The topic you type | No |
| Hacker News search, Hugging Face daily papers | Daily collection | A fixed search phrase, or a request for the day's list | No |
| FDA device decisions (openFDA, `api.fda.gov`) | Once a day, for the companies on your watch list | The company names (and any product codes or keywords you list) as search text, with a date range. Nothing about you, no key. FDA record pages (`www.accessdata.fda.gov`) are only linked, and are fetched like any other page | No |
| GitHub | When an item links to a repository | The repository name | No |
| YouTube | When an item is a video | The video address. The player in the reader uses YouTube's privacy-enhanced address | No |
| Slack (`slack.com`, `files.slack.com`) | Reading your capture channel; downloading files and pictures you post there | Your bot token and channel id, and your app token for the live connection. The bot token goes to `files.slack.com`, and only there, to download a file (PDF, PNG, JPEG, WebP, text or Markdown, at most 20 MB) | Yes, its own tokens |
| Gmail | Reading newsletters and links you mail yourself | Your address and app password | Yes, its own password |
| Raindrop | Reading your bookmarks | Your Raindrop token | Yes, its own token |
| Jina Reader (outside page renderer) | Only when switched on | The address of the page being read | Its own key, if you set one |
| Automated browser checks (for example Cloudflare) | When a site checks the built-in browser | Technical details of the built-in browser | No |
| Hugging Face | Once, to download the small local model that finds related items | A request for the model files | No |

## How the rules are enforced

The rules are written into the code in a few central places, and tests check each one.

- **Keys.** A single table binds each key to the exact host names it may go to. The check runs
  before a request leaves, and the clients that carry keys never follow a redirect, so a server's
  answer cannot pass the key on to another address. A key you store for an assistant server of
  your own is bound to that server's address.
- **Page fetching.** The pages, search results and images the radar fetches go through one kind
  of guarded connection. The few exceptions are listed at the end of this page. Only public internet addresses are accepted, and every redirect is
  checked again. The connection sends read requests only. Cookie and login headers are stripped,
  whatever added them, and no cookie a site sets is ever sent back. The connection goes to the
  network address that passed the check, not to a second lookup of the name.
- **The built-in browser.** Some pages only show their text in a real browser. For those,
  Spyglass starts a hidden browser on your computer, one fresh and empty browser for each page. It
  grants no permissions (location, notifications, clipboard, camera, microphone), refuses
  downloads, uses a fixed language and time zone instead of your computer's, and lets through
  read requests only. It blocks requests from a public page to addresses on your own network.
- **Prompts.** Before any message reaches an AI model, Spyglass removes every configured key and
  token, your e-mail address, file paths inside your home folder (shown as `~`), and your
  computer's user and machine names where they appear inside a file path. Text that came from the
  web is marked as material to analyse, and the model is told that such material is not
  instructions. It is also told never to put your profile, notes or questions into links,
  images or web addresses.
- **What a model's answer can change.** Model answers are text. They affect a request in three
  bounded ways, and each one is checked:
  - Suggested watch-list names and subjects to follow become search text for Google News. That
    text must be one line of at most 200 characters with no web address in it, and it is only ever
    sent as the search text.
  - The paper finder searches arXiv with your own topic. The model only ranks the results it is
    shown.
  - The publisher address found for a Google News link must be a public web address before it is
    stored.
- **AI programs on your computer.** Claude Code runs with every tool, setting, plugin, server and
  command switched off, so it can only answer in text. A test fails if any of those switches is
  ever removed. Codex is not offered for now, because it cannot yet be run without access to your
  files.
- **Filing into your vault.** Spyglass never writes into your notes vault. **File in vault** only
  adds an item to a queue inside Spyglass. **File now** opens one Claude Code session of your own
  in the vault, with a short fixed request that holds a count and no article text or titles. The
  session reads the queue through the Spyglass tools, where every headline, summary, key point,
  address and assistant answer is wrapped in a marked block that says it is material from the web
  and never instructions, and any copy of the mark inside the text is removed first. The full
  article text is available only through a separate tool. The notes themselves are written by
  your own vault skills, after you have approved one table of where each item goes.
- **Images in articles.** With image proxying on, your browser asks Spyglass for each image, and
  Spyglass fetches it. Spyglass serves an image only if the address appears in an article it has
  stored, only if the answer is a picture (never SVG), and only up to 8 MB. Anything refused is
  replaced by a blank image so the page layout stays intact.
- **A standing check.** One test reads the source code. It fails if new code builds its own
  internet connection instead of using the guarded ones, names an outside service that is missing
  from the destinations list, or calls an AI model without going through the cleaning step.

## Switches

You can change each switch on the settings page, or with the environment variable shown (for
example `SPYGLASS_PRIVACY_SEND_EXAMPLES=false`).

| Switch | Default | What it does |
| --- | --- | --- |
| Example titles (`privacy_send_examples`) | On | Sends the titles of items you saved or turned down to the judging AI as examples of your taste. Only items the radar itself placed in one of your sections qualify, at most 25 of each kind, so a personal bookmark about money or health never becomes an example. Off: the AI sees only your profile. |
| Image proxying (`privacy_proxy_images`) | On | Spyglass fetches the images inside articles, so your browser never contacts the sites that host them. Off: your browser loads images directly, and those sites see your browser's request. |
| Outside page renderer (`jina_enabled`) | Off | Lets an outside service (Jina Reader) fetch pages that refuse every other method. That service learns which pages you read. |
| Automated browser checks (`privacy_allow_bot_checks`) | On | Lets the built-in browser complete a site's automated check, so about one article in six (including the main research-lab blogs) can be read. The browser may then send technical details of itself to the checking service's own check addresses, and nowhere else. It never sends a login or anything about you. Off: the browser only reads, waits up to eight seconds for a check to clear on its own, and otherwise reports "The site asked for an automated browser check." You can still bring such a page in from your own browser. |

## What these rules do not protect

- **The AI provider sees what it judges.** To judge items for you, the provider receives your
  profile, the example titles (unless you switch them off), the text of the items it judges, and
  your assistant questions with the item you ask about. That is how the service works, so choose a
  provider you trust with it. Claude Code sends the same material to Anthropic.
- **Search services see your search topics.** Google News sees the search text built from your
  topics, watch list and followed subjects, arXiv sees the topics you type into Find papers, and
  openFDA sees the names of the companies on your watch list and your own product codes and
  keywords.
- **Sites see your network address.** When Spyglass fetches a page or an image, the site sees that
  a computer at your internet address asked for it. Image proxying keeps your browser and its
  cookies away from those sites, but not your network address.
- **A name can still change its answer for some browser requests.** Page fetching, the
  browser-like fetch and the hidden browser's own page connect to the network address that was
  checked. The other files a page loads in the hidden browser (scripts, images) are checked by
  name and then looked up again by the browser. A name that answers with a public address for the
  check and a private one a moment later could still reach your network. The browser's own
  local-network protection narrows this gap. Requests sent through a proxy you have configured are
  looked up by the proxy.
- **Cleaning prompts is exact, not clever.** Keys are removed when the exact value appears. A key
  that is stored only in your computer's keyring for an assistant server of your own is not on the
  removal list. Personal details you write into your profile statement in your own words are sent,
  because the statement is meant to describe you. User and machine names are removed only as
  whole words inside file paths.
- **Marking web text reduces the risk of hidden instructions in a page, but it cannot remove it.**
  A page can still try to steer what a model writes. What protects you is that the model cannot
  act. It has no tools, and its answers are shown as text. Images in assistant answers are never
  loaded. Links are shown, but they open only when you click them, so check a link before you open
  it.
- **Feeds and the older card view now use the guarded connection.** The feed library fetches
  through a session with the same address check and the same pinning, on every redirect, and the
  older card and page fetching code uses the guarded connection too. A feed on a private or local
  address is refused with a plain reason. One test reads the older modules and fails if one builds
  an unguarded connection.
- **The Google News link decoder does not use the guarded connection.** It is a separate library
  that makes its own requests (with a consent cookie, which the guarded connection would strip),
  so it is only ever given links on `news.google.com`, and the address it returns must be public
  before it is stored. It sends Google its own article identifiers and a fixed consent marker,
  which identifies nobody, to learn the publisher's address.
- **One judging path is not yet fully covered.** One part of the judging code still calls the
  OpenRouter client directly. Keys and personal details are still removed from those messages at
  the client, but the article text in those calls is not yet marked as material.
