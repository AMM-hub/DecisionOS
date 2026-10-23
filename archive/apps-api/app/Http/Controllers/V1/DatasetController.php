<?php

namespace App\Http\Controllers\V1;

use App\Http\Controllers\Controller;
use App\Services\DatasetService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class DatasetController extends Controller
{
    public function __construct(private readonly DatasetService $datasets) {}

    public function index(Request $request): JsonResponse
    {
        return response()->json($this->datasets->listForTenant($request->attributes->get('tenant_id')));
    }

    public function show(Request $request, string $dataset): JsonResponse
    {
        return response()->json($this->datasets->detail($request->attributes->get('tenant_id'), $dataset));
    }

    /** GET grain-candidates — uniqueness proven over the complete committed candidate dataset (spec 9.2). */
    public function grainCandidates(Request $request, string $dataset): JsonResponse
    {
        return response()->json($this->datasets->grainCandidates($request->attributes->get('tenant_id'), $dataset));
    }

    /** POST grain-confirmation — business meaning confirmed by an authorized human actor. */
    public function confirmGrain(Request $request, string $dataset): JsonResponse
    {
        $data = $request->validate([
            'key_columns' => ['required', 'array', 'min:1'],
            'key_columns.*' => ['required', 'string'],
        ]);
        $this->datasets->confirmGrain($request->attributes->get('tenant_id'), $request->user()->id, $dataset, $data['key_columns']);

        return response()->json(['dataset_id' => $dataset, 'grain_confirmed' => true]);
    }

    /** POST publish — atomic manifest pointer commit + outbox event (spec 8.5). */
    public function publish(Request $request, string $dataset, int $revision): JsonResponse
    {
        $this->datasets->publishRevision($request->attributes->get('tenant_id'), $request->user()->id, $dataset, $revision);

        return response()->json(['dataset_id' => $dataset, 'published_revision' => $revision, 'status' => 'published']);
    }
}
