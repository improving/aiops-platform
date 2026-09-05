import type { UIMessage } from "ai";

// Conversations stay in this browser only (design section 3.4), one per
// signed-in user and target, so two people sharing a browser never see
// each other's history; sign-out clears every conversation.
const STORAGE_PREFIX = "aiops.chat.";

export function chatStorageKey(userKey: string, target: string): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(userKey)}.${target}`;
}

export function loadMessages(userKey: string, target: string): UIMessage[] {
  try {
    const raw = window.localStorage.getItem(chatStorageKey(userKey, target));
    return raw ? (JSON.parse(raw) as UIMessage[]) : [];
  } catch {
    return [];
  }
}

export function saveMessages(
  userKey: string,
  target: string,
  messages: UIMessage[]
) {
  try {
    const key = chatStorageKey(userKey, target);
    if (messages.length === 0) {
      window.localStorage.removeItem(key);
    } else {
      window.localStorage.setItem(key, JSON.stringify(messages));
    }
  } catch {
    // Storage can be unavailable (private mode); the chat still works.
  }
}

/** Remove every stored conversation (called on sign-out). */
export function clearChatHistory() {
  try {
    const keys: string[] = [];
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (key && key.startsWith(STORAGE_PREFIX)) keys.push(key);
    }
    keys.forEach((key) => window.localStorage.removeItem(key));
  } catch {
    // Nothing to clear when storage is unavailable.
  }
}
