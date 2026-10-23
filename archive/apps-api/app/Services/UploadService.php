<?php

namespace App\Services;

use App\Models\Upload;
use Illuminate\Support\Str;

class UploadService
{
    public function __construct(private readonly WorkerClient $worker) {}

    public function initiate(string $tenantId, string $userId, string $workspaceId, string $filename, int $sizeBytes): Upload
    {
        $extension = strtolower(pathinfo($filename, PATHINFO_EXTENSION));
        abort_unless(in_array($extension, config('decisionos.allowed_extensions'), true), 422, json_encode(['code' => 'unsupported_format']));

        $id = (string) Str::uuid();
        $quarantineKey = "quarantine/{$tenantId}/{$workspaceId}/{$id}/".Str::slug($filename).'.'.$extension;

        return Upload::query()->create([
            'id' => $id,
            'tenant_id' => $tenantId,
            'workspace_id' => $workspaceId,
            'created_by' => $userId,
            'original_filename' => $filename,
            'declared_size_bytes' => $sizeBytes,
            'quarantine_key' => $quarantineKey,
            'quarantine_url' => $this->worker->presignedUploadUrl($quarantineKey, $sizeBytes),
            'status' => 'initiated',
            'expires_at' => now()->addMinutes(config('decisionos.upload_ttl_minutes')),
        ]);
    }

    public function finalize(Upload $upload): object
    {
        // Durable acceptance only: enqueue scan + bounded parse; acknowledge without implying completion.
        $upload->update(['status' => 'quarantined']);

        return $this->worker->enqueueJob('ingest.parse', [
            'tenant_id' => $upload->tenant_id,
            'upload_id' => $upload->id,
            'quarantine_key' => $upload->quarantine_key,
        ]);
    }

    public function cancel(Upload $upload): void
    {
        $upload->update(['status' => 'cancelled']);
    }
}
