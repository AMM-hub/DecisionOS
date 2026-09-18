<?php

namespace App\Services;

use Illuminate\Support\Facades\DB;

class DatasetService
{
    public function __construct(private readonly WorkerClient $worker) {}

    public function listForTenant(string $tenantId): array
    {
        return DB::table('dataset')
            ->where('tenant_id', $tenantId)
            ->get(['id', 'workspace_id', 'name', 'published_revision', 'grain_confirmed_at'])
            ->map(fn ($d) => [
                'dataset_id' => $d->id,
                'workspace_id' => $d->workspace_id,
                'name' => $d->name,
                'revision' => $d->published_revision,
                'grain_confirmed' => $d->grain_confirmed_at !== null,
            ])->all();
    }

    public function detail(string $tenantId, string $datasetId): array
    {
        $d = DB::table('dataset')->where(['tenant_id' => $tenantId, 'id' => $datasetId])->first();
        abort_if($d === null, 404);
        $grain = DB::table('grain_confirmation')->where(['tenant_id' => $tenantId, 'dataset_id' => $datasetId])->first();

        return [
            'dataset_id' => $d->id,
            'name' => $d->name,
            'revision' => $d->published_revision,
            'grain_confirmed' => $grain !== null,
            'grain' => $grain?->key_columns ? json_decode($grain->key_columns) : null,
        ];
    }

    /** Delegates empirical uniqueness checks to the bounded analytics worker (spec 9.2). */
    public function grainCandidates(string $tenantId, string $datasetId): array
    {
        $this->assertDataset($tenantId, $datasetId);

        return $this->worker->call('dataset.grain_candidates', ['tenant_id' => $tenantId, 'dataset_id' => $datasetId]);
    }

    public function confirmGrain(string $tenantId, string $userId, string $datasetId, array $keyColumns): void
    {
        $this->assertDataset($tenantId, $datasetId);
        $candidates = $this->grainCandidates($tenantId, $datasetId);
        $match = collect($candidates)->first(fn ($c) => $c['key_columns'] === $keyColumns);
        abort_if($match === null || ! $match['unique_over_full_data'], 422, json_encode(['code' => 'grain_not_proven']));

        DB::table('grain_confirmation')->upsert([
            'tenant_id' => $tenantId,
            'dataset_id' => $datasetId,
            'key_columns' => json_encode($keyColumns),
            'confirmed_by' => $userId,
            'confirmed_at' => now(),
        ], ['tenant_id', 'dataset_id']);
    }

    /** Atomic publication: manifest pointer + checkpoint in one transaction, outbox event (spec 8.5). */
    public function publishRevision(string $tenantId, string $userId, string $datasetId, int $revision): void
    {
        $this->assertDataset($tenantId, $datasetId);
        abort_unless(DB::table('grain_confirmation')->where(['tenant_id' => $tenantId, 'dataset_id' => $datasetId])->exists(), 422, json_encode(['code' => 'grain_unconfirmed']));
        $attempt = DB::table('dataset_revision')->where(['tenant_id' => $tenantId, 'dataset_id' => $datasetId, 'revision' => $revision, 'state' => 'validated'])->first();
        abort_if($attempt === null, 409, json_encode(['code' => 'revision_not_publishable']));

        DB::transaction(function () use ($tenantId, $datasetId, $revision, $userId) {
            $updated = DB::table('dataset')->where([
                'tenant_id' => $tenantId, 'id' => $datasetId,
            ])->where('published_revision', '<', $revision)->update([
                'published_revision' => $revision,
                'published_at' => now(),
                'published_by' => $userId,
            ]);
            abort_unless($updated === 1, 409, json_encode(['code' => 'concurrent_publish_conflict']));
            DB::table('outbox_event')->insert([
                'event_id' => (string) \Illuminate\Support\Str::uuid(),
                'event_type' => 'dataset.revision_published',
                'schema_version' => '1.0',
                'tenant_id' => $tenantId,
                'aggregate_id' => $datasetId,
                'aggregate_version' => $revision,
                'occurred_at' => now(),
                'payload' => json_encode(['revision_id' => (string) $revision]),
            ]);
        });
    }

    private function assertDataset(string $tenantId, string $datasetId): void
    {
        abort_unless(DB::table('dataset')->where(['tenant_id' => $tenantId, 'id' => $datasetId])->exists(), 404);
    }
}
