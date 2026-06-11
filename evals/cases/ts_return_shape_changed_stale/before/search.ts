export interface SearchResult {
  id: string;
  title: string;
  score: number;
}

/**
 * Search for documents matching `query`.
 * @returns An array of SearchResult objects sorted by descending score.
 */
export function search(query: string): SearchResult[] {
  // ... implementation
  return [];
}
