# vcam-bridge Error Reference

## Exit Codes

| Exit Code | Constant               | `error.code`                  | Retryable | Description |
|-----------|------------------------|-------------------------------|-----------|-------------|
| 0         | EXIT_OK                | —                             | —         | Success |
| 1         | EXIT_RUNTIME           | `INTERNAL`                    | false     | Unexpected internal error |
| 2         | EXIT_USAGE             | —                             | —         | Bad CLI arguments (argparse) |
| 3         | EXIT_CONFIG            | `CONFIG_ERROR`                | false     | Invalid or missing configuration |
| 4         | EXIT_AUTH              | `AUTH_ERROR`                  | false     | Authentication / authorisation failure |
| 5         | EXIT_NOT_FOUND         | `NOT_FOUND`                   | false     | Resource not found (layer uid, VC uid, etc.) |
| 6         | EXIT_CONFLICT          | `CONFLICT`                    | false     | Write conflict (e.g. config file already exists) |
| 7         | EXIT_TIMEOUT           | `TIMEOUT`                     | **true**  | Designer Python execution timed out |
| 8         | EXIT_EXTERNAL          | `EXTERNAL_DEPENDENCY`         | **true**  | HTTP / network / Designer unreachable |
| 9         | EXIT_PARTIAL           | `PARTIAL_FAILURE`             | **true**  | Some chunks injected, some failed |
| 10        | EXIT_PROBE_FAILED      | `PROBE_FAILED`                | false     | Probe operation failed (probe is **read-only** — dumps module type + field names) |
| 11        | EXIT_VERIFY_TOLERANCE  | `VERIFY_TOLERANCE_EXCEEDED`   | false     | --verify readback exceeded tolerance |
| 12        | EXIT_CONVENTION_LOCK   | `CONVENTION_LOCK_FAILED`      | false     | Cannot determine forward-axis/euler-order |
| 13        | EXIT_INVALID_FBX       | `INVALID_FBX`                 | false     | FBX file missing, unreadable, or has no camera |
| 130       | EXIT_SIGINT            | —                             | —         | Interrupted (Ctrl-C) |

## Error Envelope Shape

```json
{
  "schema_version": "1.0",
  "status": "error",
  "operation_id": "<op>",
  "error": {
    "code": "CONFIG_ERROR",
    "exit_code": 3,
    "message": "human-readable description",
    "retryable": false,
    "details": {}
  },
  "meta": { "request_id": "...", "duration_ms": 0, "timestamp": "..." }
}
```

## Agent Decision Rules
- Retry ONLY when `error.retryable == true` (exit codes 7, 8, 9).
- For exit 7 (TIMEOUT): retry with smaller `--chunk-size` (halving recommended).
- For exit 8 (EXTERNAL): check Director connectivity before retrying.
- For exit 9 (PARTIAL): `details.missing` lists unwritten fields; retry the operation.
- All other exit codes are deterministic — fix the input, don't retry blindly.
