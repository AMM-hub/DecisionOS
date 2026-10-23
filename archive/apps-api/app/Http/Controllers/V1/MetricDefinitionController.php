<?php

namespace App\Http\Controllers\V1;

use App\Http\Controllers\Controller;
use App\Services\SemanticService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class MetricDefinitionController extends Controller
{
    public function __construct(private readonly SemanticService $semantics) {}

    public function index(Request $request): JsonResponse
    {
        return response()->json($this->semantics->listDefinitions($request->attributes->get('tenant_id')));
    }

    /** POST — creates a definition_version in `proposed` state; immutable content. */
    public function propose(Request $request): JsonResponse
    {
        $data = $request->validate([
            'metric_id' => ['required', 'string'],
            'name' => ['required', 'string', 'max:200'],
            'kind' => ['required', 'in:ratio,count,sum,duration_percentile'],
            'expression' => ['required', 'array'],
            'eligibility' => ['required', 'string'],
            'time_basis' => ['required', 'string'],
            'timezone' => ['required', 'string'],
        ]);
        $version = $this->semantics->propose($request->attributes->get('tenant_id'), $request->user()->id, $data);

        return response()->json($version, 201);
    }

    /** POST approve — optimistic concurrency via version; approver must differ from proposer. */
    public function approve(Request $request, string $metric): JsonResponse
    {
        $data = $request->validate([
            'version' => ['required', 'integer'],
            'change_reason' => ['required', 'string', 'max:2000'],
            'if_match' => ['sometimes', 'integer'],
        ]);
        $approved = $this->semantics->approve($request->attributes->get('tenant_id'), $request->user()->id, $metric, $data);

        return response()->json($approved);
    }

    public function withdraw(Request $request, string $metric): JsonResponse
    {
        $this->semantics->withdraw($request->attributes->get('tenant_id'), $request->user()->id, $metric, $request->validate(['version' => ['required', 'integer'], 'reason' => ['required', 'string']]));

        return response()->json(['metric_id' => $metric, 'status' => 'withdrawn']);
    }
}
