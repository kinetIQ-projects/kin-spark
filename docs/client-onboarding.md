# Client Onboarding Runbook

How to set up a new Spark client from scratch.

---

## Prerequisites

- Access to the Spark Supabase instance (SQL Editor)
- Python 3 (for key generation)
- The `.env` file in `api/` (for PostgREST orientation upload)

---

## Step 1: Create Supabase Auth User

In the Spark Supabase dashboard: **Authentication > Users > Add User**

- **Email:** The client's login email
- **Password:** Generate a strong password
- **Auto Confirm:** Yes (skip email verification)

Copy the **user UUID** from the created row.

---

## Step 2: Generate API Key

```bash
python3 -c "
import secrets, hashlib
key = 'sk_spark_' + secrets.token_urlsafe(32)
key_hash = hashlib.sha256(key.encode()).hexdigest()
print(f'API Key (give to client):  {key}')
print(f'Key Hash (store in DB):    {key_hash}')
"
```

Save both values:
- **Plaintext key** goes in the embed snippet (publishable, visible in page source by design)
- **Hash** goes in `spark_clients.api_key_hash`

---

## Step 3: Insert Client Record

Run in Supabase SQL Editor:

```sql
INSERT INTO spark_clients (
    user_id,
    name,
    slug,
    api_key_hash,
    settling_config,
    max_turns,
    rate_limit_rpm,
    active
) VALUES (
    '<user-uuid-from-step-1>',
    'Client Name',
    'client-slug',
    '<key-hash-from-step-2>',
    '{"company_name": "Client Name", "orientation_template": "core"}'::jsonb,
    20,
    30,
    true
);
```

This is the minimal config. The `settling_config` only needs `company_name` and `orientation_template` — everything else (tone, greeting, custom instructions, jailbreak responses) is built out through the portal's onboarding flow or set in the orientation.

The `user_id` link is what makes the portal work: admin JWT's `sub` claim matches `spark_clients.user_id`.

---

## Step 4: Upload Orientation

The Supabase SQL Editor struggles with dollar-quoting on long text. Use PostgREST instead.

Save the orientation text to a file (e.g., `orientation.md`), then:

```bash
cd api/

# Source env vars
export $(grep -E '^(SUPABASE_URL|SUPABASE_SERVICE_KEY)' .env | xargs)

python3 -c "
import json, os, httpx

url = os.environ['SUPABASE_URL'] + '/rest/v1/spark_clients?slug=eq.<client-slug>'
key = os.environ['SUPABASE_SERVICE_KEY']
text = open('orientation.md').read()

r = httpx.patch(url, json={'client_orientation': text}, headers={
    'apikey': key,
    'Authorization': f'Bearer {key}',
    'Content-Type': 'application/json',
    'Prefer': 'return=minimal',
})
print(f'{r.status_code} — {\"Done\" if r.status_code == 204 else r.text}')
"
```

**Verify it took:**

```sql
SELECT slug, LEFT(client_orientation, 100) AS preview, LENGTH(client_orientation) AS chars
FROM spark_clients
WHERE slug = '<client-slug>';
```

---

## Step 5: Hand Off to Client

Give the client:

1. **Portal credentials:** Email + password for `app.trykin.ai`
2. **Embed snippet** (for when their site is ready):

```html
<script
  src="https://api.trykin.ai/static/spark/widget.js"
  data-spark-key="<plaintext-key-from-step-2>"
  data-api-base="https://api.trykin.ai/spark"
  data-accent="#<brand-color>"
  data-position="bottom-right"
  data-title="Chat with <Client Name>">
</script>
```

---

## Step 6: Client Self-Service (Portal)

Once logged in at `app.trykin.ai`, the client can:

1. **Fill onboarding questionnaire** — Purpose, values, brand voice, procedures
2. **Upload knowledge** — PDFs, docs, pasted text, website URL
3. **Run ingestion pipeline** — Processes sources into embedded knowledge + generated profiles
4. **Review profiles** — Approve or request changes on generated voice, values, boundaries, ICP, procedures
5. **Edit orientation** — Directly edit or replace the system prompt
6. **Monitor conversations** — View transcripts, leads, dashboard metrics

---

## Security Notes

- The API key is **publishable** (like Stripe publishable keys) — visible in HTML source by design
- The key only grants access to: `POST /spark/chat`, `POST /spark/lead`, `POST /spark/event`
- All admin endpoints (conversations, leads, knowledge, ingestion) require **JWT auth** via the portal
- Rate limiting: 30 req/min per client+IP (widget), 60 req/min per user (admin)
- Rate limiter is in-memory — resets on deploy (Redis on roadmap)

---

## Checklist

- [ ] Supabase auth user created
- [ ] API key generated (plaintext saved securely)
- [ ] `spark_clients` row inserted with `user_id` link
- [ ] Orientation uploaded (if pre-written)
- [ ] `spark-uploads` storage bucket exists (for file uploads)
- [ ] Client can log into `app.trykin.ai`
- [ ] Embed snippet tested on a page
