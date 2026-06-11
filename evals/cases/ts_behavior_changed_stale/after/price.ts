/**
 * Format a number as a USD price string.
 * Always shows two decimal places.
 *
 * @example formatPrice(9.7)  // "$9.70"
 */
export function formatPrice(amount: number): string {
  return `$${amount.toFixed(2)}`;
}
