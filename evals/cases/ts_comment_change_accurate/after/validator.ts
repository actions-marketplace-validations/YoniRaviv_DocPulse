/**
 * Returns true if the email address looks syntactically valid.
 * Note: only checks format — no DNS lookup is performed.
 */
export function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}
