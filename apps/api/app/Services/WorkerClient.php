<?php

namespace App\Services;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;

/**
 * Documented Python worker protocol (spec 21.3): JSON over authenticated loopback HTTP,
 * synchronous RPC for bounded interactive calls, durable enqueue for long jobs.
 * Laravel and Python do not share any queue wire format.
 */
class WorkerClient
{
    public function presignedUploadUrl(string $key, int $sizeBytes): string
    {
        return rtrim(config('decisionos.object_store.endpoint'), '/').'/'.config('decisionos.object_store.bucket_raw').'/'.$key.'?signature=demo';
    }

    public function call(string $method, array $payload): array
    {
        try {
            $res = Http::withToken(config('decisionos.worker.token'))
                ->timeout(30)
                ->retry(2, 200, throw: false)
                ->post(rtrim(config('decisionos.worker.url'), '/').'/rpc/'.$method, $payload);
        } catch (ConnectionException) {
            abort(503, json_encode(['code' => 'analytics_unavailable']));
        }
        abort_unless($res->successful(), 502, json_encode(['code' => 'analytics_error']));

        return $res->json();
    }

    public function enqueueJob(string $type, array $payload): object
    {
        $jobId = (string) \Illuminate\Support\Str::uuid();
        \Illuminate\Support\Facades\DB::table('job')->insert([
            'id' => $jobId, 'type' => $type, 'payload' => json_encode($payload),
            'state' => 'queued', 'created_at' => now(),
        ]);

        return (object) ['id' => $jobId];
    }
}
