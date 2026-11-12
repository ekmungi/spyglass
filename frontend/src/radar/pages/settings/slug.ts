// Ids for custom servers.

/** Turn a display name into the id part the service accepts: lowercase letters, digits and dashes. */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 30)
}
