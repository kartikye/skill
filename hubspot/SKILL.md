---
name: hubspot
description: "HubSpot CRM operations via the REST API — searching contacts, creating deals, updating companies, managing pipelines, analyzing CRM data, and any task involving HubSpot records. Use this skill whenever the user mentions HubSpot, CRM data, contacts, deals, companies, tickets, sales pipelines, or wants to look up, create, update, or analyze customer/prospect records, even if they don't say 'HubSpot' explicitly."
---

# HubSpot CRM Skill

This skill handles day-to-day HubSpot CRM operations through the REST API v3. It covers the full lifecycle of CRM records: searching, creating, updating, associating, and analyzing contacts, companies, deals, and tickets.

## Authentication

The HubSpot private app access token must be available as the `HUBSPOT_API_KEY` environment variable. If it's missing, tell the user to set it before proceeding:

```
export HUBSPOT_API_KEY="pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

## The Python Client

A ready-to-use client lives at `scripts/hubspot_client.py` in this skill's directory. Use it for all API calls — it handles auth, rate limiting, pagination, and error handling so you don't have to build any of that from scratch.

Import it in any Python script you write:

```python
import sys
sys.path.insert(0, "<this-skill-directory>/scripts")
from hubspot_client import HubSpotClient

client = HubSpotClient()
```

Replace `<this-skill-directory>` with the actual path to this skill's folder.

## Core Operations

### Reading Records

**Get a single record by ID:**
```python
contact = client.get("contacts", "123", properties=["email", "firstname", "lastname", "phone"])
```

**List records with pagination:**
```python
page = client.list_objects("contacts", limit=100, properties=["email", "firstname"])
# page["results"] has the records, page["paging"]["next"]["after"] has the cursor
```

**Fetch all records (auto-paginates):**
```python
all_contacts = client.list_all("contacts", properties=["email", "firstname"])
```

### Searching Records

The search API is the workhorse for finding specific records. Filters within a group use AND logic; separate groups use OR logic.

```python
# Find contacts at a specific company
results = client.search(
    "contacts",
    filter_groups=[{
        "filters": [
            {"propertyName": "company", "operator": "EQ", "value": "Acme Corp"}
        ]
    }],
    properties=["email", "firstname", "lastname", "company"]
)
```

**Available operators:** `EQ`, `NEQ`, `LT`, `LTE`, `GT`, `GTE`, `BETWEEN`, `IN`, `NOT_IN`, `HAS_PROPERTY`, `NOT_HAS_PROPERTY`, `CONTAINS_TOKEN`, `NOT_CONTAINS_TOKEN`

**Quick lookups by email or domain:**
```python
contact = client.find_contact_by_email("jane@acme.com")
company = client.find_company_by_domain("acme.com")
```

**Search constraints to keep in mind:**
- Max 5 filter groups, 6 filters per group, 18 filters total
- Max 200 results per page, 10,000 total per search query
- Search API rate limit: 5 requests/second (stricter than the general limit)
- Date filters use Unix timestamps in milliseconds
- Free-text `query` searches default fields only (contacts: name/email/phone; deals: name/pipeline/stage)

### Creating Records

```python
new_contact = client.create("contacts", {
    "email": "jane@acme.com",
    "firstname": "Jane",
    "lastname": "Doe",
    "phone": "555-1234"
})
print(f"Created contact {new_contact['id']}")
```

For deals, you need at minimum a `dealname` and `dealstage`:
```python
new_deal = client.create("deals", {
    "dealname": "Acme Enterprise License",
    "dealstage": "appointmentscheduled",
    "amount": "50000",
    "pipeline": "default"
})
```

### Updating Records

```python
client.update("contacts", "123", {"phone": "555-9999", "lifecyclestage": "customer"})
```

### Deleting (Archiving)

HubSpot delete is a soft-delete (archive). Confirm with the user before deleting.
```python
client.delete("contacts", "123")
```

### Batch Operations

For bulk work (importing lists, mass updates), use batch endpoints to avoid hammering rate limits. Max 100 per batch.

```python
# Batch create
client.batch_create("contacts", [
    {"properties": {"email": "a@example.com", "firstname": "Alice"}},
    {"properties": {"email": "b@example.com", "firstname": "Bob"}},
])

# Batch update
client.batch_update("contacts", [
    {"id": "123", "properties": {"phone": "555-0001"}},
    {"id": "456", "properties": {"phone": "555-0002"}},
])

# Batch read
client.batch_read("contacts", ["123", "456", "789"], properties=["email", "firstname"])
```

## Associations

Associations link CRM objects together (contact belongs to company, deal tied to contact, etc.). The client knows the default association type IDs for standard relationships.

```python
# Link a contact to a company
client.associate("contacts", "123", "companies", "456")

# Link a deal to a contact
client.associate("deals", "789", "contacts", "123")

# Check what companies a contact is associated with
assocs = client.get_associations("contacts", "123", "companies")

# Remove an association
client.remove_association("contacts", "123", "companies", "456")
```

## Properties and Pipelines

**Discover what fields exist on an object type:**
```python
props = client.get_properties("contacts")
for p in props["results"]:
    print(f"{p['name']}: {p['label']} ({p['type']})")
```

**Get enum options for a specific property (like deal stages or lifecycle stages):**
```python
prop = client.get_property("contacts", "lifecyclestage")
for opt in prop.get("options", []):
    print(f"{opt['value']}: {opt['label']}")
```

**List deal pipeline stages:**
```python
stages = client.get_deal_pipeline_stages("default")
for s in stages:
    print(f"{s['id']}: {s['label']}")
```

## Owners

Owners are the HubSpot users who can be assigned to records.

```python
owners = client.list_owners()
for o in owners["results"]:
    print(f"{o['id']}: {o['firstName']} {o['lastName']} ({o['email']})")
```

## Workflow Guidelines

When handling a user's HubSpot request, follow this general approach:

1. **Understand the data model first.** If you're unsure what properties exist on an object type, call `client.get_properties()` or fetch a few sample records with `client.list_objects()` to see what fields are populated. This avoids guessing at property names.

2. **Confirm before writing.** Always show the user what you're about to create or update and get their approval before calling `create`, `update`, `batch_create`, `batch_update`, or `delete`. Present it as a clear table or summary. This is important because CRM changes are visible to the whole sales team.

3. **Use search, not list, for targeted lookups.** If the user asks "find contacts at Acme," use `search()` with a filter rather than listing all contacts and filtering in Python. The search API is faster and respects HubSpot's indexing.

4. **Paginate for completeness.** When the user needs a full dataset (e.g., "export all deals"), use `search_all()` or `list_all()`. Check the `total` count in search results to confirm you fetched everything.

5. **Respect rate limits.** The general limit is ~100 requests per 10 seconds. The search API is stricter at 5/second. The client handles retries on 429 responses, but for large batch operations, add a small delay between batches.

6. **Use batch endpoints for bulk work.** If you need to create or update more than a handful of records, use `batch_create` or `batch_update` (100 per call) instead of individual create/update calls in a loop.

7. **Dates are in milliseconds.** HubSpot stores timestamps as Unix milliseconds. When filtering by date, convert accordingly:
   ```python
   import datetime
   ms = int(datetime.datetime(2024, 1, 1).timestamp() * 1000)
   ```

## Common Scenarios

### "Show me my open deals"
Search deals filtered by stage, include amount and close date, present as a table.

### "Create a contact and link them to a company"
Create the contact, then use `associate()` to link them. If the company doesn't exist yet, create that first.

### "Update all contacts from X company with a new lifecycle stage"
Search contacts by company, present the list for confirmation, then batch update.

### "What's in our pipeline?"
Fetch pipeline stages, then search deals grouped by stage with amounts. Summarize totals per stage.

### "Find duplicate contacts"
Search by email domain, group by email, flag duplicates. Present for review.

## Error Handling

The client raises `HubSpotAPIError` with the status code and HubSpot's error message. Common errors:

- **401**: Token expired or invalid. Ask the user to check their `HUBSPOT_API_KEY`.
- **403**: Token doesn't have the required scope. The user needs to add the relevant scope in their HubSpot private app settings.
- **404**: Object not found. Verify the ID and object type.
- **409**: Conflict (e.g., creating a contact with an email that already exists).
- **429**: Rate limit. The client retries automatically, but if you're doing heavy batch work, space out your calls.
