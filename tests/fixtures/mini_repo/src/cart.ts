export function formatPrice(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

export class CartService {
  addItem(sku: string): void {
    console.log(`Adding item: ${sku}`);
  }
}
