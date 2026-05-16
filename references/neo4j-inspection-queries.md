# Neo4j Direct Inspection Queries for MemOS

When the MemOS REST API `get_all` endpoint returns cryptic results (1 node when Neo4j has 1,000+), query Neo4j directly via its HTTP API. Credentials: `neo4j:12345678` at `http://localhost:7474`.

## Helper function (Python)

```python
import subprocess, json

def neo4j_query(cypher, params=None):
    result = subprocess.run([
        'curl', '-s', '-u', 'neo4j:12345678',
        'http://localhost:7474/db/neo4j/tx/commit',
        '-H', 'Content-Type: application/json',
        '-d', json.dumps({"statements": [{"statement": cypher, "parameters": params or {}}]})
    ], capture_output=True, text=True, timeout=15)
    res = json.loads(result.stdout)["results"][0]
    return [dict(zip(res["columns"], r["row"])) for r in res["data"]]
```

## Essential Queries

### Total counts by memory type
```cypher
MATCH (n:Memory)
RETURN n.memory_type AS type, count(*) AS cnt
ORDER BY cnt DESC
```

### Node property key distribution
Shows which properties exist across all Memory nodes:
```cypher
MATCH (n:Memory)
UNWIND keys(n) AS key
WITH key, count(*) AS cnt
RETURN key, cnt
ORDER BY cnt DESC
```
Key insight: `n.memory` contains the text content (NOT `n.content`); `n.key` is the title/summary; `n.background` is the background context.

### Inspect node properties (sample)
```cypher
MATCH (n:Memory)
RETURN properties(n) AS props
LIMIT 3
```
This reveals the full schema per node. Common properties: `id`, `memory`, `key`, `background`, `tags`, `memory_type`, `user_id`, `status`, `confidence`, `created_at`, `updated_at`, `session_id`, `sources`, `type`, `vector_sync`, `version`, `working_binding`.

SkillMemory nodes additionally have: `name`, `description`, `procedure`, `url`, `examples`, `scripts`, `others`, `experience`.

### Content samples by type
```cypher
MATCH (n:Memory)
WHERE n.memory IS NOT NULL
RETURN n.memory_type AS mt, n.key AS key, n.memory AS mem, n.created_at AS ts
ORDER BY n.created_at DESC
LIMIT 10
```

### Tag frequency
```cypher
MATCH (n:Memory)
UNWIND n.tags AS tag
WITH tag, count(*) AS cnt
RETURN tag, cnt
ORDER BY cnt DESC
LIMIT 20
```

### Time range
```cypher
MATCH (n:Memory)
WHERE n.created_at IS NOT NULL
RETURN min(n.created_at) AS earliest, max(n.created_at) AS latest
```

### Search by content substring
```cypher
MATCH (n:Memory)
WHERE n.memory CONTAINS 'search_term_here'
RETURN n.memory_type, n.key, n.memory
LIMIT 10
```

## REST API vs Neo4j Direct

| Operation | REST API | Neo4j Direct | Recommendation |
|-----------|----------|-------------|----------------|
| Semantic search | `/product/search` ✅ | N/A (no vectors) | Use REST |
| Get all / count | `/product/get_all` ❌ (cryptic) | `MATCH...RETURN count(*)` ✅ | Use Neo4j |
| Inspect structure | N/A | `UNWIND keys(n)` ✅ | Use Neo4j |
| Add memory | `/product/add` ✅ | N/A (risks stale vector) | Use REST |
| Delete memory | `/product/delete_memory` ✅ | Possible but risky | Use REST |

**Rule**: Use Neo4j direct queries for inspection/auditing. Use REST API for operations (add/delete/search) so Qdrant vectors stay in sync.
