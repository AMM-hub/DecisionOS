<?php

namespace App\Http\Controllers\V1;

use App\Http\Controllers\Controller;
use App\Models\Upload;
use App\Services\UploadService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;

class UploadController extends Controller
{
    public function __construct(private readonly UploadService $uploads) {}

    /** POST /v1/uploads — durable acceptance only; parsing happens in bounded workers (spec 8.1, 8.2). */
    public function initiate(Request $request): JsonResponse
    {
        $data = $request->validate([
            'filename' => ['required', 'string', 'max:255'],
            'size_bytes' => ['required', 'integer', 'min:1', 'max:'.config('decisionos.max_upload_bytes')],
            'workspace_id' => ['required', 'string'],
        ]);

        $upload = $this->uploads->initiate(
            tenantId: $request->attributes->get('tenant_id'),
            userId: $request->user()->id,
            workspaceId: $data['workspace_id'],
            filename: $data['filename'],
            sizeBytes: $data['size_bytes'],
        );

        return response()->json([
            'upload_id' => $upload->id,
            'method' => 'PUT',
            'target_path' => $upload->quarantine_url,
            'expires_at' => $upload->expires_at->toIso8601String(),
            'status' => 'initiated',
        ], 201);
    }

    public function show(Request $request, Upload $upload): JsonResponse
    {
        abort_unless($upload->tenant_id === $request->attributes->get('tenant_id'), 404);

        return response()->json([
            'upload_id' => $upload->id,
            'status' => $upload->status,
            'scan' => $upload->scan_result,
        ]);
    }

    /** POST finalize — moves bytes to quarantine, enqueues scan + bounded parse job (202 + job link). */
    public function finalize(Request $request, Upload $upload): JsonResponse
    {
        abort_unless($upload->tenant_id === $request->attributes->get('tenant_id'), 404);
        $job = $this->uploads->finalize($upload);

        return response()->json(['upload_id' => $upload->id, 'status' => 'quarantined', 'job_id' => $job->id, 'job_url' => "/v1/jobs/{$job->id}"], 202);
    }

    public function cancel(Request $request, Upload $upload): JsonResponse
    {
        abort_unless($upload->tenant_id === $request->attributes->get('tenant_id'), 404);
        $this->uploads->cancel($upload);

        return response()->json(['upload_id' => $upload->id, 'status' => 'cancelled']);
    }

    public function preview(Request $request, Upload $upload): JsonResponse
    {
        abort_unless($upload->tenant_id === $request->attributes->get('tenant_id'), 404);
        abort_if($upload->status !== 'parsed', 409, json_encode(['code' => 'preview_not_ready']));

        return response()->json($upload->parse_preview);
    }
}
