# search

```ts
search(query: string): SearchResult[]
```

Returns an **array** of `SearchResult` objects (`{ id, title, score }`) sorted
by descending relevance score.

Iterate the results directly:

```ts
const hits = search("typescript");
hits.forEach(r => console.log(r.title, r.score));
```
