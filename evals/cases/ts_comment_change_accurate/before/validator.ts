/**
 * Returns true if the email address looks syntactically valid.
 * Does NOT perform DNS or deliverability checks.
 */
export function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}
