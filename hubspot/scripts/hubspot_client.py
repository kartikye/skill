#!/usr/bin/env python3
"""
HubSpot CRM API Client

A lightweight wrapper around the HubSpot REST API v3 for common CRM operations.
Uses direct HTTP calls via `requests` for full API coverage and transparency.

Authentication: Set HUBSPOT_API_KEY environment variable to your private app access token.

Usage:
    from hubspot_client import HubSpotClient
    client = HubSpotClient()  # reads HUBSPOT_API_KEY from env
    contacts = client.search("contacts", filters=[...])
"""

import os
import sys
import json
import time
from typing import Any, Optional
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("Installing requests...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests


class HubSpotAPIError(Exception):
    """Raised when the HubSpot API returns an error response."""

    def __init__(self, status_code: int, message: str, detail: Any = None):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HubSpot API {status_code}: {message}")


class HubSpotClient:
    """Client for HubSpot CRM REST API v3."""

    BASE_URL = "https://api.hubapi.com"

    # Standard CRM object types
    OBJECT_TYPES = ["contacts", "companies", "deals", "tickets"]

    # Default association type IDs for common relationships
    ASSOCIATION_TYPES = {
        ("contacts", "companies"): 1,
        ("companies", "contacts"): 2,
        ("deals", "contacts"): 3,
        ("contacts", "deals"): 4,
        ("deals", "companies"): 5,
        ("companies", "deals"): 6,
        ("tickets", "contacts"): 15,
        ("contacts", "tickets"): 16,
        ("tickets", "companies"): 25,
        ("companies", "tickets"): 26,
        ("deals", "tickets"): 27,
        ("tickets", "deals"): 28,
    }

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token or os.environ.get("HUBSPOT_API_KEY")
        if not self.access_token:
            raise ValueError(
                "No access token provided. Set HUBSPOT_API_KEY environment variable "
                "or pass access_token to HubSpotClient()."
            )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            }
        )

    # ── Core HTTP ────────────────────────────────────────────────────────

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make an authenticated request to the HubSpot API.

        Handles rate limiting with automatic retry (up to 3 attempts).
        """
        url = f"{self.BASE_URL}{endpoint}"
        retries = 0
        while retries < 3:
            response = self.session.request(method, url, **kwargs)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 10))
                print(f"Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                retries += 1
                continue
            if response.status_code == 204:
                return {}
            if not response.ok:
                try:
                    error_body = response.json()
                    message = error_body.get("message", response.text)
                except Exception:
                    error_body = None
                    message = response.text
                raise HubSpotAPIError(response.status_code, message, error_body)
            return response.json()
        raise HubSpotAPIError(429, "Rate limit exceeded after 3 retries")

    # ── CRM Objects (CRUD) ───────────────────────────────────────────────

    def create(self, object_type: str, properties: dict, associations: Optional[list] = None) -> dict:
        """Create a CRM object.

        Args:
            object_type: e.g. "contacts", "companies", "deals", "tickets"
            properties: dict of property name -> value
            associations: optional list of association dicts, each with:
                         {"to": {"id": 123}, "types": [{"associationCategory": "...", "associationTypeId": N}]}

        Returns:
            The created object with id, properties, createdAt, updatedAt.
        """
        payload: dict[str, Any] = {"properties": properties}
        if associations:
            payload["associations"] = associations
        return self._request("POST", f"/crm/v3/objects/{object_type}", json=payload)

    def get(self, object_type: str, object_id: str, properties: Optional[list] = None) -> dict:
        """Get a single CRM object by ID.

        Args:
            object_type: e.g. "contacts", "companies"
            object_id: the object's HubSpot ID
            properties: optional list of property names to return
        """
        params = {}
        if properties:
            params["properties"] = ",".join(properties)
        return self._request("GET", f"/crm/v3/objects/{object_type}/{object_id}", params=params)

    def update(self, object_type: str, object_id: str, properties: dict) -> dict:
        """Update a CRM object's properties.

        Args:
            object_type: e.g. "contacts", "companies"
            object_id: the object's HubSpot ID
            properties: dict of property name -> new value
        """
        return self._request(
            "PATCH",
            f"/crm/v3/objects/{object_type}/{object_id}",
            json={"properties": properties},
        )

    def delete(self, object_type: str, object_id: str) -> dict:
        """Archive (soft-delete) a CRM object."""
        return self._request("DELETE", f"/crm/v3/objects/{object_type}/{object_id}")

    def list_objects(
        self,
        object_type: str,
        limit: int = 100,
        properties: Optional[list] = None,
        after: Optional[str] = None,
    ) -> dict:
        """List CRM objects with pagination.

        Args:
            object_type: e.g. "contacts", "companies"
            limit: max results per page (max 100)
            properties: optional list of property names to include
            after: pagination cursor from a previous response
        """
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if properties:
            params["properties"] = ",".join(properties)
        if after:
            params["after"] = after
        return self._request("GET", f"/crm/v3/objects/{object_type}", params=params)

    def list_all(self, object_type: str, properties: Optional[list] = None, max_records: int = 10000) -> list:
        """Fetch all objects of a type, paginating automatically.

        Args:
            object_type: e.g. "contacts"
            properties: property names to include
            max_records: safety limit to prevent runaway pagination (default 10,000)

        Returns:
            List of all result dicts.
        """
        results = []
        after = None
        while len(results) < max_records:
            page = self.list_objects(object_type, limit=100, properties=properties, after=after)
            results.extend(page.get("results", []))
            paging = page.get("paging", {})
            next_page = paging.get("next", {})
            after = next_page.get("after")
            if not after:
                break
        return results[:max_records]

    # ── Search ───────────────────────────────────────────────────────────

    def search(
        self,
        object_type: str,
        filter_groups: Optional[list] = None,
        query: Optional[str] = None,
        properties: Optional[list] = None,
        sorts: Optional[list] = None,
        limit: int = 100,
        after: Optional[int] = None,
    ) -> dict:
        """Search CRM objects with filters.

        Filter groups use AND within a group, OR between groups.

        Args:
            object_type: e.g. "contacts", "deals"
            filter_groups: list of filter group dicts. Each group has a "filters" list.
                Example: [{"filters": [{"propertyName": "email", "operator": "CONTAINS_TOKEN", "value": "example.com"}]}]
            query: free-text search string (searches default searchable fields)
            properties: property names to return
            sorts: list of sort dicts, e.g. [{"propertyName": "createdate", "direction": "DESCENDING"}]
            limit: max results (max 200)
            after: pagination offset

        Returns:
            Dict with "total", "results", and "paging" keys.

        Operators: EQ, NEQ, LT, LTE, GT, GTE, BETWEEN, IN, NOT_IN,
                   HAS_PROPERTY, NOT_HAS_PROPERTY, CONTAINS_TOKEN, NOT_CONTAINS_TOKEN
        """
        payload: dict[str, Any] = {"limit": min(limit, 200)}
        if filter_groups:
            payload["filterGroups"] = filter_groups
        if query:
            payload["query"] = query
        if properties:
            payload["properties"] = properties
        if sorts:
            payload["sorts"] = sorts
        if after is not None:
            payload["after"] = after
        return self._request("POST", f"/crm/v3/objects/{object_type}/search", json=payload)

    def search_all(
        self,
        object_type: str,
        filter_groups: Optional[list] = None,
        query: Optional[str] = None,
        properties: Optional[list] = None,
        sorts: Optional[list] = None,
        max_records: int = 10000,
    ) -> list:
        """Search with automatic pagination. Returns all matching results up to max_records.

        Note: HubSpot search API has a hard cap of 10,000 results per query.
        """
        results = []
        after = 0
        while len(results) < max_records:
            page = self.search(
                object_type,
                filter_groups=filter_groups,
                query=query,
                properties=properties,
                sorts=sorts,
                limit=200,
                after=after,
            )
            results.extend(page.get("results", []))
            total = page.get("total", 0)
            paging = page.get("paging", {})
            next_page = paging.get("next", {})
            next_after = next_page.get("after")
            if not next_after or len(results) >= total:
                break
            after = int(next_after)
        return results[:max_records]

    # ── Batch Operations ─────────────────────────────────────────────────

    def batch_create(self, object_type: str, inputs: list) -> dict:
        """Create multiple objects in one request (max 100 per batch).

        Args:
            inputs: list of dicts, each with a "properties" key.
                    e.g. [{"properties": {"email": "a@b.com", "firstname": "Ada"}}]
        """
        return self._request(
            "POST",
            f"/crm/v3/objects/{object_type}/batch/create",
            json={"inputs": inputs},
        )

    def batch_update(self, object_type: str, inputs: list) -> dict:
        """Update multiple objects in one request (max 100 per batch).

        Args:
            inputs: list of dicts, each with "id" and "properties" keys.
                    e.g. [{"id": "123", "properties": {"phone": "555-1234"}}]
        """
        return self._request(
            "POST",
            f"/crm/v3/objects/{object_type}/batch/update",
            json={"inputs": inputs},
        )

    def batch_read(self, object_type: str, ids: list, properties: Optional[list] = None) -> dict:
        """Read multiple objects by ID in one request (max 100).

        Args:
            ids: list of object ID strings
            properties: property names to return
        """
        inputs = [{"id": str(i)} for i in ids]
        payload: dict[str, Any] = {"inputs": inputs}
        if properties:
            payload["properties"] = properties
        return self._request(
            "POST",
            f"/crm/v3/objects/{object_type}/batch/read",
            json=payload,
        )

    # ── Associations ─────────────────────────────────────────────────────

    def associate(
        self,
        from_type: str,
        from_id: str,
        to_type: str,
        to_id: str,
        association_type_id: Optional[int] = None,
    ) -> dict:
        """Create an association between two objects.

        If association_type_id is not provided, it will try to use the default
        from ASSOCIATION_TYPES lookup.
        """
        if association_type_id is None:
            key = (from_type, to_type)
            association_type_id = self.ASSOCIATION_TYPES.get(key)
            if association_type_id is None:
                raise ValueError(
                    f"No default association type for {from_type} -> {to_type}. "
                    "Provide association_type_id explicitly."
                )
        return self._request(
            "PUT",
            f"/crm/v3/objects/{from_type}/{from_id}/associations/{to_type}/{to_id}/{association_type_id}",
        )

    def get_associations(self, object_type: str, object_id: str, to_type: str) -> dict:
        """Get all associations from one object to another type.

        Example: get_associations("contacts", "123", "companies")
        """
        return self._request(
            "GET",
            f"/crm/v3/objects/{object_type}/{object_id}/associations/{to_type}",
        )

    def remove_association(
        self,
        from_type: str,
        from_id: str,
        to_type: str,
        to_id: str,
        association_type_id: Optional[int] = None,
    ) -> dict:
        """Remove an association between two objects."""
        if association_type_id is None:
            key = (from_type, to_type)
            association_type_id = self.ASSOCIATION_TYPES.get(key)
            if association_type_id is None:
                raise ValueError(
                    f"No default association type for {from_type} -> {to_type}. "
                    "Provide association_type_id explicitly."
                )
        return self._request(
            "DELETE",
            f"/crm/v3/objects/{from_type}/{from_id}/associations/{to_type}/{to_id}/{association_type_id}",
        )

    # ── Properties ───────────────────────────────────────────────────────

    def get_properties(self, object_type: str) -> dict:
        """Get all property definitions for an object type."""
        return self._request("GET", f"/crm/v3/properties/{object_type}")

    def get_property(self, object_type: str, property_name: str) -> dict:
        """Get a single property definition (useful for enum options)."""
        return self._request("GET", f"/crm/v3/properties/{object_type}/{property_name}")

    def create_property(self, object_type: str, property_def: dict) -> dict:
        """Create a new property on an object type.

        Args:
            property_def: dict with at minimum "name", "label", "type", "fieldType", "groupName".
                          For enumerations, include "options" list.
        """
        return self._request("POST", f"/crm/v3/properties/{object_type}", json=property_def)

    # ── Owners ───────────────────────────────────────────────────────────

    def list_owners(self, email: Optional[str] = None, limit: int = 100, after: Optional[str] = None) -> dict:
        """List owners (users who can be assigned to CRM records).

        Args:
            email: optional filter by email
            limit: max results
            after: pagination cursor
        """
        params: dict[str, Any] = {"limit": limit}
        if email:
            params["email"] = email
        if after:
            params["after"] = after
        return self._request("GET", "/crm/v3/owners/", params=params)

    def get_owner(self, owner_id: str) -> dict:
        """Get a single owner by ID."""
        return self._request("GET", f"/crm/v3/owners/{owner_id}")

    # ── Pipelines ────────────────────────────────────────────────────────

    def list_pipelines(self, object_type: str) -> dict:
        """List all pipelines for an object type (deals or tickets)."""
        return self._request("GET", f"/crm/v3/pipelines/{object_type}")

    def get_pipeline(self, object_type: str, pipeline_id: str) -> dict:
        """Get a single pipeline with its stages."""
        return self._request("GET", f"/crm/v3/pipelines/{object_type}/{pipeline_id}")

    # ── Convenience / Helpers ────────────────────────────────────────────

    def find_contact_by_email(self, email: str, properties: Optional[list] = None) -> Optional[dict]:
        """Find a single contact by email address. Returns None if not found."""
        result = self.search(
            "contacts",
            filter_groups=[{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
            properties=properties,
        )
        results = result.get("results", [])
        return results[0] if results else None

    def find_company_by_domain(self, domain: str, properties: Optional[list] = None) -> Optional[dict]:
        """Find a single company by domain. Returns None if not found."""
        result = self.search(
            "companies",
            filter_groups=[{"filters": [{"propertyName": "domain", "operator": "EQ", "value": domain}]}],
            properties=properties,
        )
        results = result.get("results", [])
        return results[0] if results else None

    def find_deals_by_stage(self, stage: str, properties: Optional[list] = None) -> list:
        """Find all deals in a given stage."""
        return self.search_all(
            "deals",
            filter_groups=[{"filters": [{"propertyName": "dealstage", "operator": "EQ", "value": stage}]}],
            properties=properties,
        )

    def get_deal_pipeline_stages(self, pipeline_id: str = "default") -> list:
        """Get all stages in a deal pipeline. Returns list of stage dicts."""
        pipeline = self.get_pipeline("deals", pipeline_id)
        return pipeline.get("stages", [])


# ── CLI for quick testing ────────────────────────────────────────────────

if __name__ == "__main__":
    client = HubSpotClient()

    if len(sys.argv) < 2:
        print("Usage: python hubspot_client.py <command> [args]")
        print("Commands: list_contacts, search_contacts <query>, get_contact <id>, list_owners")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list_contacts":
        result = client.list_objects("contacts", limit=10)
        print(json.dumps(result, indent=2))

    elif cmd == "search_contacts" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        result = client.search("contacts", query=query, limit=10)
        print(json.dumps(result, indent=2))

    elif cmd == "get_contact" and len(sys.argv) > 2:
        result = client.get("contacts", sys.argv[2])
        print(json.dumps(result, indent=2))

    elif cmd == "list_owners":
        result = client.list_owners()
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
