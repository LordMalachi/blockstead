# Field-level validation contract

Shared contract between the Blockstead API and the dashboard. Backend and frontend must
both conform to exactly this shape. Additive changes only.

## Error envelope

Today every API error is:

```json
{ "error": { "code": "REQUEST_INVALID", "message": "…", "recovery": "…" } }
```

Field-level failures add an optional `fields` array. Existing clients that only read
`code`/`message`/`recovery` keep working unchanged.

```json
{
  "error": {
    "code": "REQUEST_INVALID",
    "message": "Some submitted information was invalid.",
    "recovery": "Review the highlighted fields and try again.",
    "fields": [
      {
        "field": "directory_name",
        "reason": "INVALID_CHARACTERS",
        "message": "Use only lowercase letters, numbers, hyphens and underscores.",
        "rule": "Start with a lowercase letter or number, then up to 63 more lowercase letters, numbers, hyphens or underscores.",
        "suggestion": "family-server"
      }
    ]
  }
}
```

### `fields[]` entry

| key          | type             | required | meaning |
|--------------|------------------|----------|---------|
| `field`      | string           | yes      | Request body key, dotted for nesting (`variants.0.name`). Matches the frontend form control's name. |
| `reason`     | string           | yes      | Stable machine code from the list below. Never localized, never reworded. |
| `message`    | string           | yes      | What is wrong, one plain sentence, household English. |
| `rule`       | string \| null   | no       | How to format it correctly — the allowed character set, length, casing. |
| `suggestion` | string \| null   | no       | A host-safe corrected value that is **guaranteed to pass validation**. Present whenever one can be derived. Powers the one-click auto-fix. |

### `reason` codes

`REQUIRED`, `TOO_SHORT`, `TOO_LONG`, `INVALID_CHARACTERS`, `UPPERCASE_NOT_ALLOWED`,
`MUST_START_WITH_LETTER_OR_NUMBER`, `MUST_END_WITH_LETTER_OR_NUMBER`,
`CONSECUTIVE_SEPARATORS`, `RESERVED_NAME`, `ALREADY_EXISTS`, `NOT_ALLOWED_VALUE`,
`PATH_NOT_WRITABLE`, `PATH_NOT_FOUND`, `INCOMPATIBLE_LOADER`.

Add new codes here first; do not invent them ad hoc at a call site.

## Sanitization must agree on both sides

`directory_name` is the canonical case. Both implementations must produce identical output
for identical input:

- Backend: `backend/src/blockstead/validation.py`
- Frontend: `frontend/src/lib/server-directory.ts` (`normalizeServerDirectoryName`)

Rule (pattern `^[a-z0-9][a-z0-9_-]{0,63}$`): trim, lowercase, replace every run of
disallowed characters with a single `-`, collapse repeated separators, strip leading and
trailing non-alphanumerics, truncate to 64 characters, strip trailing non-alphanumerics
again, and fall back to `minecraft-server` when nothing survives.

Both sides must have a test asserting the same table of input → output pairs, including:
`"  Family Server  "` → `"family-server"`, `"My__Server!!"` → `"my_server"`,
`"---"` → `"minecraft-server"`, `"Ünïcødé"` → `"n-c-d"` (each non-ASCII letter is its own disallowed run), `"A"*80` → 64 chars ending
alphanumeric.

## Frontend consumption

- `api()` in `frontend/src/api/client.ts` throws an error carrying the parsed `fields`
  array (not just a flattened string) so forms can map `field` → control.
- A form renders, per invalid control: `aria-invalid="true"`, an inline message element
  referenced by `aria-describedby`, and — when `suggestion` is present — a button that
  sets the control to the suggestion in one click.
- Default values the UI pre-fills (server folder names, profile names) must already
  satisfy the pattern, so a user who accepts the defaults is never blocked.
