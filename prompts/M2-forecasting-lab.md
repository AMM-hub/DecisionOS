You are building M2 — the Forecasting Lab for DecisionOS at C:\Users\AMD\Desktop\DecisionOS.

## SPEC REFERENCE (spec §16 — Forecasting and Predictive Risk)

### Design principles
1. Historical data can support forecasts but does not guarantee reliable predictions
2. A complex model must earn its place by outperforming a simpler baseline
3. Every forecast shows horizon, assumptions, evaluation results, and limitations
4. When forecasting is unsupported, refuse and identify what additional data is needed

### Workflow
1. Check whether available data supports the requested prediction
2. Establish a simple baseline (naive/seasonal naive)
3. Compare suitable models using historical holdout periods
4. Show forecast error and prediction intervals
5. Monitor accuracy after deployment
6. Reduce confidence or suspend forecasts when performance deteriorates

### Types of forecasting
- Time-series: volumes, rates (StatsForecast)
- Classification risk: probability models (scikit-learn)
- Survival/backlog: time-to-event (lifelines) — stretch goal
- Backlog projection: stock-flow with censoring

## CURRENT STATE OF THE PROJECT

### Running services
- **Python API** on :8100 with FastAPI, polars, pydantic, uvicorn
- **Nuxt frontend** on :3000 with Vue 3 composition API
- **Laravel API** on :8000 with SQLite fallback

### Python analytics at services/analytics/
- Virtual env at .venv/ (Python 3.14.6)
- Dependencies: polars>=1.16, pydantic>=2.9, fastapi>=0.115, uvicorn>=0.32
- Test framework: pytest 9.x with 25 passing tests
- Modules: api.py, execution.py, grain.py, parsing.py, pipeline.py, semantics.py, store.py, serve.py, config.py, objectstore.py, scanning.py

### Frontend at apps/web/
- Running Nuxt 3.21 SPA
- composables/api.ts — fetch wrapper with X-Tenant/X-User headers, error handling
- shared/types.ts — full API type definitions
- Pages: index.vue (dashboard), uploads.vue, datasets.vue, metrics.vue

## YOUR TASK

### 1. Install StatsForecast in the analytics venv
```bash
cd C:\Users\AMD\Desktop\DecisionOS\services\analytics
.venv\Scripts\python -m pip install statsforecast scipy scikit-learn
```

### 2. Create services/analytics/decisionos_analytics/forecasting.py
A module with these functions:

```
train_model(data, metric_config, horizon)
  - data: polars DataFrame with time_basis column and value column
  - metric_config: dict with frequency, season_length, etc.
  - Returns: model_spec dict including model_name, params, training_end, evaluation_metrics

predict(model_spec, horizon, prediction_intervals=True)
  - Returns: predictions polars DataFrame with ds, yhat, yhat_lower, yhat_upper

evaluate(data, test_size=0.2)
  - Splits data into train/test
  - Runs multiple models (Naive, SeasonalNaive, AutoARIMA, AutoETS, AutoTheta)
  - Returns comparison with MAPE, MASE, RMSE for each model
  - Refuses if data has < 12 periods (spec §16.4)

check_suitability(data, min_periods=12)
  - Checks if data supports forecasting
  - Returns suitability dict with sufficient, reason, recommended_actions
```

### 3. Add forecast API endpoints to api.py
```
POST /v1/forecasts/suitability — check if a dataset/metric supports forecasting
  Input: { dataset_id, metric_id, time_basis }
  Output: { sufficient: bool, reason, recommended_actions }

POST /v1/forecasts/train — train a forecast model
  Input: { dataset_id, metric_id, time_basis, horizon, frequency, season_length }
  Output: { model_spec_id, status, evaluation, suitability }

POST /v1/forecasts/predict — generate predictions from a trained model
  Input: { model_spec_id, horizon, prediction_intervals: true }
  Output: { predictions: [{ds, yhat, yhat_lower, yhat_upper}], model_info }

POST /v1/forecasts/evaluate — compare models on holdout data
  Input: { dataset_id, metric_id, time_basis, test_size: 0.2 }
  Output: { comparisons: [{model_name, mape, mase, rmse}] }
```

### 4. Create frontend forecast page
Create apps/web/pages/forecasts.vue with:
- Dataset/metric selector (reuse existing API composable)
- "Check suitability" button
- Training form (horizon, frequency selector)
- Results chart using ECharts or canvas showing predictions with uncertainty bands
- Evaluation table comparing models

Use the existing Card/Badge/Muted CSS styles from app.vue.

### 5. Add new API types to shared/types.ts
Add types for: ForecastSuitability, ForecastTrainRequest, ForecastTrainResponse, ForecastPredictRequest, ForecastPredictResponse, ForecastEvaluation, ForecastComparison

## CONSTRAINTS
- Stay ONLY under C:\Users\AMD\Desktop\DecisionOS
- Add tests for forecasting module to tests/test_forecasting.py (at least 6 tests)
- Don't break existing 25 passing tests
- Use Python 3.14.6 compatible packages
- CORS already enabled — new endpoints automatically available to frontend
- New endpoints use /v1 prefix and X-Tenant/X-User headers (same pattern as existing)