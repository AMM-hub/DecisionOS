<?php

return [
    'max_upload_bytes' => env('DECISIONOS_MAX_UPLOAD_BYTES', 100 * 1024 * 1024),
    'allowed_extensions' => ['csv', 'xlsx'],
    'upload_ttl_minutes' => env('DECISIONOS_UPLOAD_TTL_MINUTES', 60),
    'trust_demo_headers' => env('DECISIONOS_TRUST_DEMO_HEADERS', false),
    'object_store' => [
        'endpoint' => env('OBJECT_STORE_ENDPOINT', 'http://127.0.0.1:9000'),
        'bucket_raw' => env('OBJECT_STORE_BUCKET_RAW', 'decisionos-raw-quarantine'),
        'bucket_revisions' => env('OBJECT_STORE_BUCKET_REVISIONS', 'decisionos-revisions'),
    ],
    'worker' => [
        'url' => env('ANALYTICS_WORKER_URL', 'http://127.0.0.1:8100'),
        'token' => env('ANALYTICS_WORKER_TOKEN'),
    ],
    'limits' => [
        'parse_max_rows' => 2_000_000,
        'parse_max_columns' => 500,
        'parse_max_cell_len' => 32_767,
        'parse_timeout_seconds' => 120,
        'parse_memory_mb' => 2048,
    ],
];
