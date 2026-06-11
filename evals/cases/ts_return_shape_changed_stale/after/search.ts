export interface SearchPage {
  results: { id: string; title: string; score: number }[];
  total: number;
  nextCursor: string | null;
}

/**
 * Search for documents matching `query`.
 * @returns A SearchPage object containing results and pagination info.
 */
export function search(query: string): SearchPage {
  // ... implementation
  return { results: [], total: 0, nextCursor: null };
}
