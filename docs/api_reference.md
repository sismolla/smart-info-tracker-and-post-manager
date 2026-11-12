# REST API Reference Documentation
## Market Intelligence Platform API (v1)

### Base URL
```
https://yourdomain.com/api/v1/
```

### Authentication
External applications authenticate by providing an authorized API Key in the HTTP header:
```http
X-API-KEY: mkt_live_sample_key_998877665544332211
```
Or via standard Authorization header:
```http
Authorization: Api-Key mkt_live_sample_key_998877665544332211
```

---

### Endpoints

#### 1. List Intelligence Items
```http
GET /api/v1/items/
```
**Query Parameters:**
- `status`: Filter by status (`approved`, `published`, `ai_processed`, `duplicate`)
- `category`: Filter by category slug (e.g. `tenders-and-procurement`, `job-opportunities`, `healthcare-news`)
- `source_id`: Filter by specific information source ID
- `min_score`: Filter by minimum relevance score (e.g. `75`)
- `search`: Search title, body, and organization name
- `page`: Page number (default: 1)

**Sample Response:**
```json
{
  "count": 42,
  "next": "https://yourdomain.com/api/v1/items/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "external_id": "tg_tender_001",
      "title": "National Tender: Procurement of Diagnostic Ultrasound & MRI Spare Parts",
      "canonical_url": "https://t.me/ethio_tenders_official/4092",
      "source_name": "Ethiopian Procurement & Tenders",
      "source_type": "channel",
      "published_at": "2026-11-12T14:00:00Z",
      "collected_at": "2026-11-12T14:05:00Z",
      "language": "en",
      "status": "approved",
      "categories": [
        {"id": 1, "name": "Tenders and Procurement", "slug": "tenders-and-procurement", "color": "#f59e0b"}
      ],
      "entities": {
        "organization": "Ethiopian Pharmaceuticals Supply Agency (EPSA)",
        "contact_person": "Ato Samuel Bekele",
        "phone_number": "+251 911 445566",
        "email": "tender@epsa.gov.et",
        "location": "Addis Ababa",
        "price": "250,000 ETB",
        "tender_deadline": "2026-12-15 at 10:00 AM"
      },
      "ai_analysis": {
        "model_name": "gemini-1.5-flash",
        "short_summary": "EPSA national competitive bid for 15 diagnostic ultrasound machines and MRI spare assemblies.",
        "detailed_summary": "National competitive bid EPSA/MOH/NCB/2026/042 open to registered medical equipment distributors...",
        "business_implications": "Key commercial opportunity for medical imaging vendors in Ethiopia.",
        "relevance_score": 100,
        "relevance_explanation": {
          "source_reliability": 25.0,
          "information_completeness": 25.0,
          "recency": 25.0,
          "business_importance": 25.0
        }
      }
    }
  ]
}
```

---

#### 2. Item Editorial Actions
- **Approve an Item**:
  ```http
  POST /api/v1/items/{id}/approve/
  ```
- **Reject an Item**:
  ```http
  POST /api/v1/items/{id}/reject/
  ```
- **Publish an Item (triggers webhooks)**:
  ```http
  POST /api/v1/items/{id}/publish/
  ```

---

#### 3. Executive Intelligence Summary
```http
GET /api/v1/summary/
```
Returns curated high-priority tenders, recent jobs, and market trends in a single request.

---

#### 4. Trigger On-Demand Source Synchronization
```http
POST /api/v1/sources/{id}/sync/
```
Triggers an immediate fetch for the specified source.

---

### Outgoing Webhook Payloads
When an item is published, registered webhooks receive an HTTP POST with:
```http
Content-Type: application/json
X-Event-Type: item.published
X-Hub-Signature-256: sha256=abcdef123456...
```
Verification:
Compute `HMAC-SHA256(payload_body, secret_token)` and compare with `X-Hub-Signature-256`.
