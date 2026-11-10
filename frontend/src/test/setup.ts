// Vitest global setup: registers jest-dom matchers for all test files.
import '@testing-library/jest-dom/vitest'

// jsdom lacks ResizeObserver, which the list virtualizer (virtua) requires. A no-op
// stub lets virtua run in tests; with zero measured heights it estimates sizes and
// renders the (small) test datasets in full, so row assertions still hold.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver ?? (ResizeObserverStub as unknown as typeof ResizeObserver)
