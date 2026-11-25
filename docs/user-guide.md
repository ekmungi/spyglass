# Spyglass user guide

This guide is for someone who uses Spyglass but does not write code. It explains the daily routine,
how to follow subjects, how to connect Slack and Gmail, and what to do when something does not
work. Words in **bold** are buttons or headings on the screen. Menu names in other programs, such
as Slack and Gmail, change from time to time, so the names below may differ slightly from what you
see.

## 1. What Spyglass does for you

Spyglass looks at the sources you have chosen, throws away most of what is not relevant to you, and
prepares a short brief each morning. The brief is finite. When you reach the line "You are caught
up", there is nothing more to read until tomorrow.

It runs on your own computer. To use it, open a browser and go to `http://localhost:7777/`, or
double-click `scripts\spyglass.cmd` in the Spyglass folder, which starts the program if needed and
opens it in its own window.

If you installed Spyglass with its Windows installer, open it from the Start menu instead. The
first time, it asks where to keep its data and which Obsidian vault to use. Setup also asked which
parts to install, such as PDF reading, the local AI model and YouTube transcripts. To add or remove
one later, choose Spyglass in **Settings > Apps > Installed apps** in Windows, then **Modify**.
The **General** tab of Spyglass's own **Settings** page lists the parts that are not installed and
what each one changes.

## 2. The daily routine

1. Open Spyglass. You land on **Today**.
2. Read the opening lines, then go down the sections: top stories, the companies and labs you
   watch, other items worth knowing, papers, anything you sent in yourself, and a list of headlines
   to skim. Each story has two labelled parts: **What it says** is a plain account of the piece,
   and **Why it matters** says in general terms why the piece is important. Neither part tries to
   tie the piece to your own work. The top section opens with one lead story, and its other
   stories sit in two columns.
3. To see more of a section, look beside its heading. A count such as "4-6 of 15" with two small
   arrows pages through the stories that Spyglass judged for that section and did not pick, after
   the ones it did pick. A grey ring before a headline marks a story that was not picked; point at
   the ring to read what it means. A section keeps at most twelve such stories. When more were
   judged, point at the count to read how many, and look in the Feed for the rest. A brief that
   was composed before this version has no such stories, so its sections show no arrows.
4. Click a story to open it in the reader. The summary is at the top: a few key points, then **Why
   it matters**. The article follows, and an assistant panel sits on the right. The bar of icons at
   the top has **Back**, the buttons for the previous and the next story, and the thumbs. Next to
   the buttons, a count such as "3 of 12 in Today" gives your place in the list you came from,
   which is Today or the Feed. The **J** key opens the next story and the **K** key the previous
   one, unless you are typing. The bar stays in place while the next story loads, and a story
   counts as opened once it has been drawn, so a story you step past while it is still loading is
   not counted. **Back** leaves the reader in one step, however many stories you read.
5. In the assistant panel, press a quick action (Explain, How is this relevant to me, Draft a
   message for colleagues, Draft a LinkedIn post, Outline a blog post) or type your own question.
   To ask about one passage only, select the text in the article first.
6. Tell Spyglass what you think of a story: press the thumbs-up (**More like this**) or the
   thumbs-down (**Less like this**) at the end of its row, or in the reader's bar. On a row the
   thumbs appear when you point at it, tab to it or select it with the keyboard, and a thumb that
   is set stays visible. Press the same thumb again to take the vote back. A thumbs-up on a story
   with a grey ring says that it should have been picked. Spyglass learns from your votes,
   together with what you open, read, save and ask about. A story you vote down is left out of the
   next briefs, but an item you sent in yourself stays, and the Feed still lists the story.
7. Save what you want to keep (section 5), then go back to Today.

When you want something older or something that was filtered out of the brief, open **Feed**. It
lists everything that was collected. At the top is one search box, which looks in titles,
summaries and full text. Beside it are the chat icon **Ask your feed**, which opens the assistant
about the whole Feed, and the **Filters** icon, whose menu holds the kinds of item (News, Papers
and so on), **Show filtered-out items** and **Filed**. When one of these is on, the icon shows how
many are on. Under the search box are two strips of tabs. The first strip chooses the view:
**Everything**, **Missed**, **Saved**, **From you** and, where filing is set up, **To file**. The
second strip chooses the section: **All sections**, or one section of your profile. Each row shows
the headline, one line of what the piece says, and then the source, the time and the section, with
the thumbs and the save button at its end.

Newest first, the list is split by day: a heading reads "Today", "Yesterday", then the weekday and
date ("Tuesday 10 November"), with how many items that day holds. The heading of the day you are
reading stays pinned under the bars as a tinted bar as you scroll. The headings are left out of the
lists that are ordered by something other than time: items close in meaning, which you reach with
**Show related in the Feed** in the reader's **More** menu, the items an assistant answer cited, and
**Missed**. A line above such a list says what it is, and **Clear** returns to the whole Feed.

**Missed.** If you were away for a few days, press **Missed** in the Feed. It lists the top and
notable items of the last 7 days that you have never opened, saved or filed, and that you did not
send in yourself, best first. The number on the tab is how many there are. An item you open from
this list stays in it, shown as read, until you open the list again.

## 3. Following subjects

A followed subject is a topic Spyglass searches the news for on every collection, and favours when
it judges items.

- **From an article.** Open an article and press **Follow**. Spyglass reads the article, lists the
  subjects it found as a short checklist, and follows the ones you tick.
- **From a link.** Press **Add link** in the left rail, paste an address, and choose to follow
  subjects from it as well.
- **Seeing and removing them.** Open **Watch**. The topics you follow are listed at the bottom of
  the page, under **Topics you follow**, and each one has a menu with **Edit**, **Pause** and
  **Stop following**. When you follow none, the page shows one line with a **Follow a topic** link.

The **Profile** page holds your interests in your own words, on six tabs: **About you**,
**Sections**, **Topics**, **Your projects**, **Leave out** and **Learned**. The sections start as
models, labs, agents, health, industry and direction. You can rename each one and say what belongs
in it. The **Topics** tab shows how many topics you have, and **Your projects** shows how many
projects have a line the assistant may see ("2 shared"). That count comes from what is saved, so it
changes only after you save. One **Save profile** bar at the bottom serves every tab. It saves the project lines together
with the rest, and **Discard changes** undoes everything you have not saved. If a tab holds
something that cannot be saved, the page opens that tab and says what to fix. **Learned** only
lists the titles that your saves, votes and links taught Spyglass. Changing the profile changes
how everything is judged from the next collection onward. Edit it whenever your focus changes.

The **Sources** page shows where your material comes from and whether each source works. Its parts
are tabs on one strip: **From you** (Slack, Raindrop and Gmail), **Feeds**, **Searches** and **FDA
decisions**. A tab shows a red mark only when a source on it is set up and failing, and a screen
reader reads out how many ("1 feed is failing"). A source that is only not set up gets no mark, and
neither does a feed you switched off. Under **Feeds**, the feeds that need a look are listed first, and one
line of counts stands in for the feeds that work; press **Show the working feeds** to list them. A
feed you have just switched on or off stays where it was, with the focus, until you fold or unfold
that list, so it does not move under your pointer.

## 4. The watch list

**Watch** lists the companies, labs and regulators Spyglass checks every day. The page has these
parts, from the top: **Watching**, with its **Paused** list; **Suggested this month**; **Not of
interest**; and **Topics you follow**.

**Watching.** Each name is a chip, and the chips sit in groups such as "AI labs". A green
chip is watched. Click it once to pause it: it turns grey where it is, and a message offers
**Undo**. Spyglass then stops searching for it, and nothing it already found is deleted. Click the
grey chip to watch it again. The chip does not move while you click, so the page stays still under
your pointer. The next time you open the page, each name is where its status puts it: a paused name
is in **Paused**, with the name of its group beside it, and a watched name is in its group. The
**Paused** list is closed at first; open it and click a name to watch it again.

Move your pointer over a chip, or tab to it, and a small button with three dots appears. Its menu
holds **Details**, **Move to another group**, **See its items in the Feed** and **Remove**. **Details**
shows why the name is on the list, its other spellings and its three latest items. **Remove**
deletes the name, which pausing never does.

**Groups.** You choose the order of the groups. The menu beside a group's name has **Move up** and
**Move down**, and also **Pause this group**, **Rename group**, **Move all to another group** and
**Remove this group**. Once you have moved a group, a new group goes last; until then every group,
a new one included, is in alphabetical order. Each group shows how many items it brought in this
week ("6 items this week").

**Pause this group** turns every name in the group's row grey where it is, as a click on each chip
would, and nothing moves until your next visit. A message such as "Paused all 3 names in Labs."
offers **Undo**, which watches again exactly the names the pause changed. When every name in the
row is grey, the same menu offers **Watch this group again**, which watches the names in the row
again, also with **Undo**. Names that were already in **Paused** when you opened the page stay
paused.

**Suggested this month.** Under the groups, Spyglass suggests organisations you do not watch yet:
companies, labs, universities, hospital groups and regulators, never products, people or news
sites. There are at most five for each section of your profile, chosen by how many of your top and
notable items from the last 30 days name them, and each chip shows that number. Spyglass looks at
the list again after every collection, so a name that is no longer in the news leaves it. Right
after you update Spyglass, the older suggestions are not shown until the first collection has
sorted them into the sections of your profile, which happens within about two hours of Spyglass
starting.

- **Click a name** to watch it at once. The chip turns green and stays where it is, and a message
  names the group it joins on your next visit. Click it again to undo.
- **Click the cross** on a chip to say it is not of interest. The chip is struck through and stays
  until the next visit, and Spyglass never suggests that name again. Click the struck chip to take
  it back.
- **Hide the rest for good** says the same for every suggestion you have not decided on, with one
  **Undo** for all of them. That message stays for ten seconds.

Names that a topic search found (see below) wait in their own row, "From your search", for 30 days.

**Not of interest.** This closed list shows every name you have marked not of interest. A name you
strike on this visit joins it at once, while its chip stays struck in its row. Press **Take back**
on a name to allow it to be suggested again.

To find who matters for a subject, press **Add**, then **Find who matters for a topic**. Spyglass
proposes organisations, which appear in the "From your search" row of **Suggested this month**. You
click the ones you want to watch. **Add** also lets you follow a topic or
add one organisation yourself, and **Review with AI** suggests changes to the whole list.

What the watched organisations publish appears in the brief under "On your watch list".

Each group on **Watch** shows how many items it brought in this week ("6 items this week"). Click
that number to open the Feed with exactly those items, under a "Watch: AI labs" chip. **Clear** on
the chip goes back to the whole Feed.

**FDA decisions.** Once a day Spyglass also asks the public FDA database (openFDA) whether any
company on your watch list has had a device decision in the last 30 days: a 510(k) clearance, a De
Novo grant, a PMA approval or a recall. Each decision becomes one item from the regulator, linked
to the official FDA record and shown under that company on **Watch**. A name must match the FDA's
firm name exactly or start with it as whole words, so "Olympus" finds "Olympus Medical Systems" but
never an unrelated firm. On the **FDA decisions** tab of **Sources**, you can switch this off and
list FDA product codes or device keywords to follow whoever makes them. At most 120 requests are
made a day, so a very long watch list is covered over several days.

**Find papers** is separate: type a topic and Spyglass returns the few papers that matter, each with
one line on how it relates to your field.

## 5. Saving and the vault

There are three steps, and each needs your click.

1. **Feed.** Everything collected is here automatically.
2. **Saved.** Press **Save for later** on an item to keep it inside Spyglass. It stays in the Saved
   filter of the Feed. This does not leave your computer.
3. **To file.** Press **File in vault** on an item to add it to your filing queue. Nothing opens
   and nothing is written; the button then reads **Waiting to be filed**, and a message lets you
   undo it. The small arrow beside the button offers **File as…**, where you choose the kind of
   note (resource, to explore, learning or feature idea), a project and a note for the filing
   session of up to 2,000 characters, which can run over several lines: Enter starts a new line,
   and Ctrl+Enter adds the item to the queue. On a waiting item you can remove it from the queue or
   change those choices.

   When you have queued a few items, open the **Feed** and press **To file**. A status line shows
   the state of filing, and the waiting items are listed under **Waiting**. **File now** opens one
   Claude Code session in your notes vault. There the bundled `spyglass-file` skill reads the queue,
   shows one table of where each item will go and waits for your single yes. Your own vault skills
   then write the notes one at a time, and each item leaves the queue as it is filed. **See the
   request** shows the exact text sent to Claude Code first.

Spyglass never writes into your notes vault itself. To choose the vault, open **Settings**, then
the **Vault and filing** tab, and set **Vault folder**: Claude Code is opened in it. If you do not use a notes
folder, ignore this step; Saved is enough.

**If Claude Code says it cannot find the item.** Claude Code finds Spyglass through the file
`.mcp.json` in your vault folder, which Spyglass writes when it starts (unless you switched that
off). If you run more than one copy of Spyglass, for example a test copy on another port, the copy
started last owns that entry. Before opening Claude Code, Spyglass reads the file: when it names
another Spyglass, or none, **File now** and **Open in Claude Code** are unavailable and the
message says which port the vault is connected to and which one this is. Restart the Spyglass you
want to use, with the vault folder set, and try again. Each request also tells the session which
Spyglass sent it and to stop, instead of searching for Spyglass's files, when its tools do not know
the item; the `radar_about` tool shows which Spyglass a session reached.

### Filing into your vault

Background filing is not available in this version. Filing happens only when you click **File now**,
and the steps above describe the whole of it: one Claude Code session in your vault, one table, one
yes.

Filing stays hidden until you name your own Claude Code filing plugin and skills in the settings
file. Set `SPYGLASS_RADAR_FILING_PLUGIN` to the plugin, and `SPYGLASS_RADAR_FILING_INGEST_SKILL` and
`SPYGLASS_RADAR_FILING_MANAGE_SKILL` to the skills that bring material into the vault and that write
and update its notes. Restart Spyglass after you change them.

## 6. Appearance

Open **Settings** and choose the **Appearance** tab. The page has six tabs on one strip, at the
same width as **Profile** and **Sources**: **General**, **AI engines**, **Appearance**, **Bringing
things in**, **Vault and filing** and **Privacy and usage**. Text boxes and menus on these pages
share one text size and one shade. On **Appearance**, every change applies at once and is remembered
on the device you made it on. Other parts save with their own button, and report success or failure
beside it.

- **Theme:** light, dark, or follow your system. The sun or moon button at the bottom of the left
  rail switches between light and dark.
- **Reading font** and **Interface font:** pick from the samples shown.
- **Text size:** scales everything. Comfortable is the designed size.
- **Text width:** the slider sets how wide the centre column is. A narrower column is easier to read
  in a wide window.
- **Reset to defaults** undoes all of it.

## 7. Choosing the AI

Open **Settings** and choose the **AI engines** tab. It lists the AI engines. Each one says whether
it is ready, and the engines that are not set up are folded away behind one button. For an
engine that needs a key (OpenRouter, Anthropic, OpenAI, Google Gemini), paste the key into its box
and save; it is kept in the Windows credential store. For a program running on your own computer
(Ollama or LM Studio) nothing is needed except that it is running. Then choose which engine and
model the assistant starts with. You can change engine for any single question using the list in
the assistant panel.

The judging that happens in the background, before you see anything, has its own setting: under
the engines list, **AI for the daily judging** lets you choose which engine does it and the order
of the engines to fall back to. You can also set it in the `.env` file (section 8 explains how to
edit it). The default is OpenRouter.

### AI usage

Every time Spyglass asks an AI model something, it keeps a note of how much the model read and how
much it wrote, counted in tokens (a token is a short piece of a word). This covers your questions in
the assistant, the sorting and summarising of new items in the background, and the smaller writing
jobs such as the brief's opening. Nothing is counted for services that do not report their figures;
those calls are counted as calls only. The notes are kept on your computer and the ones older than
180 days are removed.

- **Under an answer.** Hover over an answer, or tab to it, and a quiet line appears, for example
  "sonnet · Read 12,400 tokens, 91% from cache · wrote 380". "Read" is everything the model was
  given for that answer: the instructions, the article and the conversation so far. "Wrote" is the
  length of the answer.
- **In Settings, on the Privacy and usage tab, under Usage.** A table of the last 7 days by job:
  how many calls, how much the models read, how much of that came from the cache, and how much
  they wrote.
- **What "from cache" means.** When the beginning of a request is the same as a recent one, the
  provider re-reads it from a cache at a fraction of the cost. So the same article, asked about
  again within the hour, is cheap the second time. Spyglass keeps the beginning of every request
  identical from one question to the next (the instructions, your profile, the article) and puts
  what changes at the end, so that the cache can be used. Anthropic models, also through OpenRouter,
  are told explicitly what to cache; OpenAI, Gemini and DeepSeek cache by themselves.
- **"Earlier messages were condensed to save usage."** In a very long conversation the model would
  re-read every earlier message with each new question. When the conversation has grown by about
  20,000 tokens, Spyglass asks the engine's cheaper model for a short summary of the earlier messages
  and carries on from the summary. You still see the whole conversation; only what is sent to the
  model is shorter.
- **Long articles.** For an article too long to send whole, the assistant is given the beginning,
  and for your first question, the passages from the rest that are closest to what you asked.
  Later questions in the same conversation do not get new passages.
- **Automatic.** For engines where Spyglass knows a cheaper and a stronger model (Claude Code,
  Anthropic, OpenRouter, Gemini), the model list has an "Automatic" choice. It uses the cheaper model
  for Explain and for short questions, and the stronger one for drafting a message, a post or an
  outline and for long questions. It is never chosen for you; the usage line names the model that
  wrote each answer.

When the assistant runs through your own Claude Code, Spyglass starts it without Claude Code's memory
notes and instruction files. Those would otherwise be sent with every question.

## 8. Connecting Slack

With Slack, you paste a link into one private channel from your phone or any computer, and the item
appears in Spyglass, already analysed, within a second or two. You need permission to add an app to
your Slack workspace.

1. **Make a private channel** in Slack for yourself, for example `spyglass-links`. Find its channel
   ID: open the channel, click its name at the top, choose **About**, and look at the bottom for
   "Channel ID" (it starts with the letter C or G). Copy it.
2. **Create the app.** Go to `https://api.slack.com/apps` and press **Create New App**, then **From
   scratch**. Name it Spyglass and pick your workspace.
3. **Switch on Socket Mode.** In the app's left menu choose **Socket Mode** and turn on **Enable
   Socket Mode**. Slack asks you to create an app-level token. Name it anything, add the scope
   `connections:write`, and press **Generate**. Copy the token that starts with `xapp-`. This is
   the first of two tokens.
4. **Add the permissions.** Choose **OAuth & Permissions**. Under **Bot Token Scopes** add
   `channels:history` (for a public channel) and `groups:history` (for a private channel). Adding
   both is fine. Also add `files:read`, which lets Spyglass download the pictures and files you
   post (see "Files and pictures" below). Without it links still work, and files are recorded with
   a note that Spyglass was not allowed to read them.
5. **Subscribe to messages.** Choose **Event Subscriptions** and turn on **Enable Events**. Under
   **Subscribe to bot events** add `message.channels` and `message.groups`, then save.
6. **Install the app.** Go back to **OAuth & Permissions** and press **Install to Workspace**, then
   **Allow**. Copy the **Bot User OAuth Token**, which starts with `xoxb-`. This is the second
   token.
7. **Invite the app to the channel.** In your channel, type `/invite @Spyglass` and send it.
8. **Give the details to Spyglass.** Open the `.env` file in the Spyglass folder with Notepad. If
   the file does not exist, copy `.env.example` to `.env` first. Add three lines, using your own
   values:

   ```
   SPYGLASS_SLACK_APP_TOKEN=xapp-your-token
   SPYGLASS_SLACK_BOT_TOKEN=xoxb-your-token
   SPYGLASS_SLACK_CAPTURE_CHANNEL=C0123456789
   ```

9. **Restart Spyglass** (section 9 explains how), then open **Sources**. On the **From you** tab,
   the Slack row should say "Configured". Post a link in the channel to test it.

Keep the two tokens private. They are as sensitive as a password, and `.env` is excluded from git.
If you leave out the app token (step 3), Spyglass still works, but it checks the channel once a
minute instead of at once.

Each link you post becomes an item marked as sent by you. The words you type next to the link are
kept as your note and shown with the item. Links to private or internal addresses are refused.

**Files and pictures.** A PDF, PNG, JPEG, WebP, plain text or Markdown file that you post in the
channel becomes an item too, under **From you**, analysed at once. A PDF is read like one you add
with **Add file**; a picture is shown in the item's document; a text file is shown as text. The
words you type with the file are the note of every item the message creates. A file larger than
20 MB, or of any other type (a Word file, a zip, an SVG), is not downloaded: the item carries the
file's name and one sentence saying why. This needs the `files:read` permission. If you add it
after installing the app, press **Reinstall to Workspace** on **OAuth & Permissions** and copy the
bot token again if Slack gives you a new one. Spyglass sends the bot token only to Slack, to
`files.slack.com`, to download a file. A picture or PDF that you send in is kept for good in the
`media/from_you` folder of the data folder, which the weekly clean-up never trims, and is removed
only when you delete its item. If that file is ever missing, the item shows a sentence saying so
instead of a broken image.

## 9. Starting with Windows

Spyglass has to be running to collect and to compose the brief. In the installed app, tick **Start
with Windows** in setup, or switch it on in **Settings**, on the **General** tab, under **Spyglass
on this computer**. The steps below are for a copy run from the Spyglass folder. To start that copy automatically every
time you sign in to Windows:

1. Open the Spyglass folder in File Explorer, click the address bar, type `powershell`, and press
   Enter.
2. Run: `powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1`

**What it does.** It registers one scheduled task named Spyglass for your Windows account only. At
sign-in, after a delay of 30 seconds, the task starts the Spyglass service hidden in the
background, with no window. It does not need administrator rights and changes nothing for other
accounts. If the service crashes it is restarted up to three times. It keeps running on battery.

To start it right now without signing out, run `Start-ScheduledTask -TaskName Spyglass`. To restart
it after changing `.env`, run `Stop-ScheduledTask -TaskName Spyglass` and then
`Start-ScheduledTask -TaskName Spyglass`. If you started Spyglass by hand in a terminal window,
close that window first.

**To undo it,** run `powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
-Uninstall`. This removes the task. It does not delete any of your data, and it does not stop a copy
that is running at that moment.

## 10. Connecting Gmail

Gmail is read with an app password, a separate password that Google creates for one program, so
your normal password is never used.

1. **Turn on 2-step verification** for your Google account if it is not on: go to
   `https://myaccount.google.com/security` and choose **2-Step Verification**.
2. **Create an app password.** Go to `https://myaccount.google.com/apppasswords`, name it Spyglass,
   and press **Create**. Google shows 16 letters once. Copy them. If the page is missing, your
   account may be managed by an employer or school, or may use Google's Advanced Protection, which
   do not allow app passwords. Use a personal account.
3. **Make the labels and the filter.** In Gmail open **Settings**, then **See all settings**, then
   **Filters and Blocked Addresses**, then **Create a new filter**.
   - For newsletters: type the sender's address in **From**, press **Create filter**, tick **Apply
     the label**, choose **New label**, and name it `Newsletters`. Tick **Also apply filter to
     matching conversations** to include the ones you already have. Repeat for each sender, or
     put several addresses in **From** separated by `OR`.
   - For links you email to yourself: create a second filter with your own address in both **From**
     and **To**, and apply a new label named `Spyglass`.
4. **Give the details to Spyglass.** Add these lines to your `.env` file, using your own values.
   The app password is the 16 letters, with or without spaces:

   ```
   SPYGLASS_GMAIL_ADDRESS=you@example.com
   SPYGLASS_GMAIL_APP_PASSWORD=abcd efgh ijkl mnop
   ```

   If you chose other label names, also add `SPYGLASS_GMAIL_NEWSLETTER_LABEL=...` and
   `SPYGLASS_GMAIL_CAPTURE_LABEL=...`.
5. **Restart Spyglass** and look at the **From you** tab of **Sources**. The Gmail row should say
   "Configured".

Spyglass only reads the two labels. It never marks a message as read and never moves, deletes or
sends anything. Each newsletter becomes one item that you can open in the reader. For a message in
the second label, the first link in it is captured as an item sent by you.

## 11. Switching from the older version

Earlier versions of Spyglass lived inside an Obsidian plugin and used a linked Claude session. The
new version does not need either.

- The new version uses the same database, so the items you already collected are still there.
  Items that have not been judged under the new system are judged gradually.
- Stop the plugin from starting the old service: in Obsidian, turn off the Spyglass plugin, or turn
  on its **Connect only** setting. Two copies cannot use the same port.
- Your feeds, Raindrop token and key settings carry over because they live in `.env` and in the
  database. Check them on **Sources** and **Settings**.
- Notes the old version wrote into your vault stay where they are.
- The old plugin and Claude skills remain in the repository. You may use or delete them; the new
  version does not call them.

## 12. When something goes wrong

**There is no brief this morning.**
When there is no brief for today, **Today** says so and offers **Compose now**. The usual causes,
in order of likelihood:
- The computer was off or asleep at the brief time. Spyglass composes a missed brief shortly after
  it is running again, so wait a few minutes. To make one at once, press **Compose now**.
- Spyglass was not running. Check that it is started (section 9).
- The AI had no credit or was not signed in. Open **Settings** and look at the AI engines. A
  message such as "out of credit" or "not signed in" names the fix. Add credit, or sign in the
  command-line engine, or switch the background judging to another engine under **AI for the
  daily judging** in Settings (or in `.env`, with `SPYGLASS_RADAR_LLM_PROVIDER` and
  `SPYGLASS_RADAR_LLM_FALLBACK`).
- A quiet day. When very little was relevant, the brief says so and is short.

**An article will not open.**
Some sites block automated readers, and some articles are behind a payment page. When the reader
cannot get the text, it says why and offers a link to the original page, which you can open in your
browser. Try again after a few minutes, because a temporary block often clears. For a paper, the
**PDF** button at the top of the reader switches between the text and the PDF. If a whole site
always fails, send in a link to a copy of the article from another site instead.

**The assistant says there is no credit.**
That message comes from the engine you chose, not from Spyglass. Open **Settings**, check the
engine's account with its provider (for OpenRouter, the credits page of your account), add credit,
or choose a different engine from the list in the assistant panel. A local engine (Ollama or LM
Studio) never needs credit.

**My computer has no recent backup of the database.**
Spyglass copies its database into the `backups` folder of its data folder at start-up, after a
manual refresh and once a day at 03:00 (change the time with `SPYGLASS_RADAR_BACKUP_TIME`, for
example `04:30`). The daily copy waits until no collection is running. If the computer was asleep
at that hour, the copy is taken within half an hour of it running again, whenever the newest copy
is more than 26 hours old. Spyglass keeps the two newest copies and, for each of the five days
before today, the last copy of that day, so a day with several copies does not push the older days
out (at most seven copies; `SPYGLASS_BACKUP_KEEP` sets that upper limit). A copy is about as large
as the database. When the disk has less free space than twice the newest copy, Spyglass skips the
copy and the **Activity** list says so.

**Slack or Gmail says "Set up, but failing".**
The row on the **From you** tab of **Sources** shows the reason, and the tab carries a red mark
while a channel on it fails. For Slack the usual cause is that the app was not invited
to the channel (step 7) or a permission is missing (step 4 or 5). For Gmail it is usually a wrong
app password, or a label name that does not match the one in `.env`.

**The page will not load at all.**
Spyglass is not running. Start it with `scripts\spyglass.cmd`, or see section 9.

**Everything is slow, or the disk is filling.**
Spyglass tidies itself once a week: it removes the stored text of old items you never opened,
saved or sent in, trims its caches and clears old logs. The length of time it keeps that text is
`SPYGLASS_RADAR_RETENTION_DAYS` in `.env` (120 by default; 0 keeps everything). The items and their
judgements are always kept.
