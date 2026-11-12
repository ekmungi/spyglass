// The Profile page's only door to the server. GET and PUT /profile answer {profile, examples};
// the shared client reads that reply (and tolerates a bare profile) into a ProfileResponse.
import { getProfile, putProfile } from '../../api/client'
import type { Profile, ProfileExamples, ProfileResponse } from '../../api/types'

export { parseProfileReply } from '../../api/client'

export type LearnedExamples = ProfileExamples
export type ProfileReply = ProfileResponse

/** Load the profile and the example titles Spyglass derived from the reader's history. */
export const loadProfile = (signal?: AbortSignal): Promise<ProfileReply> => getProfile(signal)

/** The vault projects and the one line the AI may see for each (null when this service has no projects endpoint). */
export { loadProjects, saveProjects } from '../../api/projects'

/** Replace the profile; the server bumps `version` and returns the stored document. */
export const saveProfile = (profile: Profile): Promise<ProfileReply> => putProfile(profile)
