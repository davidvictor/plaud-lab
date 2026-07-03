# Plaud Internal API Notes

These endpoints are observed from Plaud Web and are not a public API contract.

## File List

```text
GET https://api.plaud.ai/file/simple/web?skip=0&limit=99999&is_trash=2&sort_by=start_time&is_desc=true
```

Observed query parameters:

- `skip`: offset for pagination.
- `limit`: page size. Plaud Web has used `99999` for all-files and `5` for recent files.
- `is_trash`: `0` for active files, `2` for all files including trash. `1` is treated as trash-only by the exporter.
- `sort_by`: usually `start_time` or `edit_time`.
- `is_desc`: `true` for newest first.

Useful response fields:

- `data_file_total`
- `data_file_list[]`
- `id`
- `filename`
- `start_time`
- `end_time`
- `duration`
- `is_trash`
- `is_trans`
- `is_summary`
- `scene`
- `serial_number`

## File Detail

```text
GET https://api.plaud.ai/file/detail/{file_id}
```

Useful response fields:

- `data.file_id`
- `data.file_name`
- `data.content_list[]`

Useful `content_list[].data_type` values:

- `transaction`: original transcript JSON, commonly `file_transcript/{id}/trans_result.json.gz`.
- `auto_sum_note`: generated summary Markdown, commonly `file_summary/{id}/ai_content.md.gz`.
- `transaction_polish`: polished transcript JSON.
- `outline`: topic outline JSON.
- `ask_note`, `mark_memo`, `high_light`, `sum_multi_note`, `consumer_note`: additional generated or user-created note types.

`content_list[].data_link` values are short-lived signed S3 URLs. Download them immediately after fetching file detail, and do not save the signed query string.

## Headers

Common Plaud Web headers:

```text
Authorization: Bearer <workspace token>
X-Request-ID: <random id>
app-language: en
app-platform: web
edit-from: web
timezone: America/Los_Angeles
x-device-id: <optional>
x-pld-user: <optional>
Origin: https://web.plaud.ai
Referer: https://web.plaud.ai/
```

The exporter can also pass a raw `Cookie` header. Keep tokens and cookies in environment variables or another local secret store.
