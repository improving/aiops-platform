// Runs once when the Next.js server starts (see src/proxy.ts for what the
// disabled mode changes). The guard keeps the line to the Node.js runtime.
export function register() {
  if (
    process.env.NEXT_RUNTIME === "nodejs" &&
    process.env.AUTH_MODE === "disabled"
  ) {
    console.warn("AUTH_MODE=disabled: the UI is unauthenticated");
  }
}
