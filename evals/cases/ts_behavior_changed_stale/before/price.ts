/**
 * Format a number as a USD price string.
 * Rounds to the nearest whole dollar and appends the "$" prefix.
 *
 * @example formatPrice(9.7)  // "$10"
 */
export function formatPrice(amount: number): string {
  return `$${Math.round(amount)}`;
}
