# DecisionOS — PILOT-01 Controlled Operational Pilot Runbook

## Support Ticket SLA & Queue Operations Pilot

---

## 1. Startup & Environment Setup
- **Analytics Service Startup**:
  ```bash
  cd services/analytics
  .venv\Scripts\python.exe -m uvicorn decisionos_analytics.api:app --host 0.0.0.0 --port 8100 --reload
  ```
- **Web Frontend Startup**:
  ```bash
  cd apps/web
  npm run dev
  ```
- **Environment Variables**:
  - `DATA_DIR`: Path to control store & parquet storage (default: `c:\Users\AMD\Desktop\DecisionOS\services\analytics\data`).
  - `SQLITE_DB`: Control-plane SQLite database filename (`control.sqlite3`).
  - `PORT`: REST API port (`8100`).

---

## 2. User & Tenant Assumptions
- **Supported Tenants**:
  - `tenant_alpha`: Northline Telecom (Synthetic Operations)
  - `tenant_beta`: Harbor Retail Bank (Synthetic Operations)
- **Demo Security Boundary**:
  - API authentication relies on `X-Tenant` and `X-User` demo headers (e.g. `X-Tenant: tenant_alpha`, `X-User: alpha.manager`).
  - **Security Gate Status**: `INTERNAL EVALUATION ONLY`. External customer pilot is **BLOCKED** until full SAML/SSO security gate is satisfied.

---

## 3. Data Onboarding & Guided Setup
1. Navigate to `/pilot/setup`.
2. Select or upload ticket dataset (CSV / Parquet format).
3. Validate Required Fields:
   - `ticket_id` (case ID)
   - `timestamp` / `created_at` (event timestamp)
   - `status` (event activity)
4. Confirm Data Quality Gate:
   - System checks for unparseable timestamps, out-of-order events, and completion before creation.
   - Status: `PASS` | `WARNING` | `BLOCKED`.
5. Map Workflow Columns & Confirm SLA Rules (24h UTC Calendar SLA).
6. Click **Bootstrap Pilot Infrastructure** to activate pilot contract, seed Support Operations semantic pack, configure monitoring rules, and initialize D3-A risk classification target.

---

## 4. Dataset Refresh Workflow
- **Manual Ingestion Refresh**:
  - Upload updated dataset revision via `/v1/pilots/{id}/refresh`.
  - System assigns incremented revision number (e.g., Revision #2), creates new parquet object, and updates active published revision pointer.
- **Immutability Guarantee**:
  - Historical revisions are strictly preserved.
  - Previous decision evidence bindings and predictions remain tied to their original dataset revision.

---

## 5. Operation & Decision Review Loop
1. **Executive Command Center (`/pilot`)**: Inspect active alerts, high-risk cases, open decisions, and reviews due.
2. **Predictive Risk Queue (`/risk`)**: Review cases flagged with high 24h SLA breach probability ($\ge 50\%$).
3. **Investigation & Claims (`/investigations`)**: Launch investigation, capture evidence digest, and structure findings.
4. **Decision Brief & Register (`/decisions`)**: Create decision brief, bind evidence artifacts, accept & freeze context.
5. **Outcome Review Workspace (`/decisions`)**: Post implementation, enter measurement window (e.g., 14 days), compare baseline vs observed results, select review verdict (`supported_improvement`, `no_clear_change`, etc.), and close decision.

---

## 6. Health Checks, Backup & Recovery
- **Health Check Endpoint**:
  ```http
  GET http://localhost:8100/v1/health
  ```
- **Backup Procedures**:
  - Backup `data/control.sqlite3` and `data/objects/` directory.
- **Recovery Procedures**:
  - In case of failed refresh or bad data upload, previous valid dataset revision remains published and active. Retry upload with corrected CSV.

---

## 7. Known Limitations
- **Business-Time SLA**: Business hours / work-calendar SLA is currently **UNSUPPORTED**. System displays `BUSINESS-TIME SLA NOT SUPPORTED` and evaluates using UTC calendar time.
- **Predictive Approval State**: Evaluation models remain strictly `EVALUATION ONLY` / `NOT APPROVED FOR REAL WORLD`.
