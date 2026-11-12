// Profile sections: the stable keys and their default labels, used when the profile has not loaded.
// These are exactly the default profile's labels; no component shortens a label.
import type { ProfileSection } from '../api/types'

export const DEFAULT_SECTIONS: ProfileSection[] = [
  { key: 'models', label: 'Models & platforms', description: '' },
  { key: 'labs', label: 'Labs & research', description: '' },
  { key: 'agents', label: 'Building with agents', description: '' },
  { key: 'health', label: 'Healthcare AI & medtech', description: '' },
  { key: 'industry', label: 'Industry & use cases', description: '' },
  { key: 'direction', label: 'Where AI is heading', description: '' },
]
