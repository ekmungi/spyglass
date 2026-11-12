// ClaudeDialogHost: mounted once by the app shell; shows the "Open in Claude Code" dialog while an
// opener (reader menu, summary block, assistant) has asked for it.
import { ClaudeCodeDialog } from './ClaudeCodeDialog'
import { useClaudeDialog } from './claudeStore'

/** Renders the dialog for the current request, or nothing. */
export function ClaudeDialogHost() {
  const request = useClaudeDialog()
  return request ? <ClaudeCodeDialog key={request.token} request={request} /> : null
}
