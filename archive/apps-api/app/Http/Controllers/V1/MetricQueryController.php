<?php

namespace App\Http\Controllers\V1;

use App\Http\Controllers\Controller;
use App\Services\MetricExecutionService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class MetricQueryController extends Controller
{
    public function __construct(private readonly MetricExecutionService $execution) {}

    /**
     * POST /v1/metrics/query — MetricQuery request per spec 10.3.
     * Server resolves definitions, snapshot set, joins, and security predicates;
     * physical identifiers are never accepted from the client.
     */
    public function query(Request $request): JsonResponse
    {
        $data = $request->validate([
            'schema_version' => ['required', 'string'],
            'metric_id' => ['required', 'string'],
            'semantic_release_id' => ['sometimes', 'string'],
            'dimensions' => ['sometimes', 'array'],
            'filters' => ['sometimes', 'array'],
            'window' => ['required', 'array'],
            'window.start' => ['required', 'date'],
            'window.end' => ['required', 'date', 'after:window.start'],
            'window.timezone' => ['required', 'string'],
            'limit' => ['sometimes', 'integer', 'max:10000'],
        ]);

        $result = $this->execution->query($request->attributes->get('tenant_id'), $request->user()->id, $data);

        return response()->json($result);
    }
}
