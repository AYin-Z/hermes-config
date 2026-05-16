# Pydantic `internal_info` Fix — Exact Patch

**File**: `/home/ayin/memos-server/src/memos/memories/textual/item.py`  
**Method**: `TextualMemoryItem.from_dict` (line ~313)  
**Trigger**: Re-apply after every `git pull` of memos-server

## Original code

```python
    @classmethod
    def from_dict(cls, data: dict) -> "TextualMemoryItem":
        return cls(**data)
```

## Patched code

```python
    @classmethod
    def from_dict(cls, data: dict) -> "TextualMemoryItem":
        # Parse JSON strings in metadata that Neo4j stores as text
        if "metadata" in data and isinstance(data["metadata"], dict):
            meta = data["metadata"]
            for key in ("internal_info", "info", "others", "scripts", "experience", "tags"):
                if key in meta and isinstance(meta[key], str):
                    try:
                        import json
                        meta[key] = json.loads(meta[key])
                    except (json.JSONDecodeError, TypeError):
                        pass
        return cls(**data)
```

## Why

Neo4j stores compound fields (`internal_info`, `info`, `scripts`, `others`, `experience`, `tags`) as JSON strings. When MemOS reads memory nodes back from Neo4j and passes them to `TextualMemoryItem.from_dict`, these string fields cause Pydantic validation errors because the model expects `dict` or `list` types.

The `_coerce_metadata` field validator only handles the top-level `metadata` field (dict → proper Metadata class), not the nested string-typed sub-fields.

The fix parses JSON strings inside the metadata dict before Pydantic sees them. Fields that are already dicts/list are left untouched.

## Verification

```bash
# Search should return non-zero results
curl -s -X POST http://127.0.0.1:8000/product/search \
  -H "Content-Type: application/json" \
  -d '{"user_id":"hermes","query":"QQ"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['data']['text_mem'][0]['memories']))"
# Expected: > 0

# No more dict_type errors in logs
echo "YINZ0732" | sudo -S docker logs memos-api-docker 2>&1 | grep -c "dict_type"
# Expected: 0 (or only old pre-fix entries)
```

## Notes

- No container restart needed — volume mount `../src:/app/src` means changes are live immediately
- The `json` import is inside the try block to avoid polluting module namespace; it's harmless on repeated calls
- If `git pull` overwrites this, search silently breaks again — always verify after updates
