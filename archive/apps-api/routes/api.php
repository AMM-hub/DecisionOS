<?php

use App\Http\Controllers\V1\DatasetController;
use App\Http\Controllers\V1\MetricDefinitionController;
use App\Http\Controllers\V1\MetricQueryController;
use App\Http\Controllers\V1\UploadController;
use Illuminate\Support\Facades\Route;

// In local demo mode without a provisioned identity provider, tenant context is
// resolved from headers (see ResolveTenantContext). Production always authenticates.
$demoMode = app()->environment('local') && config('decisionos.trust_demo_headers');

Route::prefix('v1')->middleware($demoMode ? ['tenant.context'] : ['auth:sanctum', 'tenant.context'])->group(function () {
    // Uploads: initiate multipart upload, finalize, scan status, cancel (spec 23.2)
    Route::post('uploads', [UploadController::class, 'initiate'])->middleware('idempotency');
    Route::get('uploads/{upload}', [UploadController::class, 'show']);
    Route::post('uploads/{upload}/finalize', [UploadController::class, 'finalize']);
    Route::post('uploads/{upload}/cancel', [UploadController::class, 'cancel']);
    Route::get('uploads/{upload}/preview', [UploadController::class, 'preview']);

    // Datasets: schema/profile, grain candidates/confirm, revisions, publish
    Route::get('datasets', [DatasetController::class, 'index']);
    Route::get('datasets/{dataset}', [DatasetController::class, 'show']);
    Route::get('datasets/{dataset}/grain-candidates', [DatasetController::class, 'grainCandidates']);
    Route::post('datasets/{dataset}/grain-confirmation', [DatasetController::class, 'confirmGrain'])->middleware('idempotency');
    Route::post('datasets/{dataset}/revisions/{revision}/publish', [DatasetController::class, 'publish']);

    // Definitions: propose/approve/withdraw, versions, publications
    Route::get('metrics/definitions', [MetricDefinitionController::class, 'index']);
    Route::post('metrics/definitions', [MetricDefinitionController::class, 'propose'])->middleware('idempotency');
    Route::post('metrics/definitions/{metric}/approve', [MetricDefinitionController::class, 'approve'])->middleware('idempotency');
    Route::post('metrics/definitions/{metric}/withdraw', [MetricDefinitionController::class, 'withdraw']);

    // Metrics: validate plan, query
    Route::post('metrics/query', [MetricQueryController::class, 'query']);
});
