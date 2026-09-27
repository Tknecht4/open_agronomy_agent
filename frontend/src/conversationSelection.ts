/** Remember the active conversation separately for each field/example/general scope. */
const KEY = 'open-agronomy-agent.conversation-selection.v1'
const selections = (): Record<string, string> => {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(KEY) || '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
    return Object.fromEntries(Object.entries(value).filter(([scope, key]) =>
      typeof key === 'string' && (key === scope || key.startsWith(`${scope}:chat:`))))
  } catch { return {} }
}
export const selectedConversation = (scope: string): string => selections()[scope] || scope
export const rememberConversation = (scope: string, conversation: string): void => {
  if (conversation !== scope && !conversation.startsWith(`${scope}:chat:`)) return
  try { window.localStorage.setItem(KEY, JSON.stringify({ ...selections(), [scope]: conversation })) } catch { /* Browsers may prohibit persistence. */ }
}
