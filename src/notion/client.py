"""
Notion client for interacting with Notion pages and databases.
"""

import os
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
import requests
from datetime import datetime
import json

# Load environment variables
load_dotenv()


class NotionClient:
    """Client for interacting with Notion API."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Notion client with API key.

        Args:
            api_key: Optional API key. If not provided, will try to get from environment.
        """
        self.api_key = api_key or os.getenv("NOTION_INTERNAL_INTEGRATION_SECRET")
        if not self.api_key:
            raise ValueError(
                "NOTION_INTERNAL_INTEGRATION_SECRET must be provided or set in environment"
            )

        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

    def get_page(self, page_id: str) -> Dict[str, Any]:
        """
        Retrieve a Notion page by its ID.

        Args:
            page_id: The ID of the Notion page

        Returns:
            Dict containing the page data
        """
        url = f"{self.base_url}/pages/{page_id}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_database(self, database_id: str) -> Dict[str, Any]:
        """
        Retrieve a Notion database by its ID.

        Args:
            database_id: The ID of the Notion database

        Returns:
            Dict containing the database data
        """
        url = f"{self.base_url}/databases/{database_id}"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def query_database(
        self, database_id: str, filter_criteria: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """
        Query a Notion database with optional filter criteria.

        Args:
            database_id: The ID of the Notion database
            filter_criteria: Optional filter criteria for the query

        Returns:
            List of pages matching the query
        """
        url = f"{self.base_url}/databases/{database_id}/query"
        payload = {"filter": filter_criteria} if filter_criteria else {}

        response = requests.post(url, headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()["results"]

    def get_page_content(self, page_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve the content blocks of a Notion page.

        Args:
            page_id: The ID of the Notion page

        Returns:
            List of content blocks
        """
        url = f"{self.base_url}/blocks/{page_id}/children"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()["results"]

    def append_block_children(
        self, block_id: str, children: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Append content blocks to a Notion page.

        Args:
            block_id: The ID of the parent block
            children: List of block objects to append

        Returns:
            Dict containing the response data
        """
        url = f"{self.base_url}/blocks/{block_id}/children"
        payload = {"children": children}

        response = requests.patch(url, headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()

    def update_page_properties(
        self, page_id: str, properties: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update properties of a Notion page.

        Args:
            page_id: The ID of the Notion page
            properties: Dict of properties to update

        Returns:
            Dict containing the updated page data
        """
        url = f"{self.base_url}/pages/{page_id}"
        payload = {"properties": properties}

        response = requests.patch(url, headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()

    def create_page(
        self,
        parent_id: str,
        properties: Dict[str, Any],
        content: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new page in a Notion database or as a child of another page.

        Args:
            parent_id: The ID of the parent (database or page)
            properties: Dict of page properties
            content: Optional list of content blocks

        Returns:
            Dict containing the created page data
        """
        url = f"{self.base_url}/pages"

        # Determine if parent is a database or page
        parent_type = "database_id" if parent_id.startswith("database_") else "page_id"

        payload = {"parent": {parent_type: parent_id}, "properties": properties}

        if content:
            payload["children"] = content

        response = requests.post(url, headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()

    def markdown_to_notion_blocks(self, markdown: str) -> List[Dict[str, Any]]:
        """
        Convert markdown text to Notion block format.
        This is a basic implementation that can be extended based on needs.

        Args:
            markdown: Markdown text to convert

        Returns:
            List of Notion block objects
        """
        blocks = []
        lines = markdown.split("\n")

        for line in lines:
            if not line.strip():
                continue

            if line.startswith("# "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_1",
                        "heading_1": {
                            "rich_text": [
                                {"type": "text", "text": {"content": line[2:]}}
                            ]
                        },
                    }
                )
            elif line.startswith("## "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {
                            "rich_text": [
                                {"type": "text", "text": {"content": line[3:]}}
                            ]
                        },
                    }
                )
            elif line.startswith("### "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [
                                {"type": "text", "text": {"content": line[4:]}}
                            ]
                        },
                    }
                )
            elif line.startswith("- "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [
                                {"type": "text", "text": {"content": line[2:]}}
                            ]
                        },
                    }
                )
            else:
                blocks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": line}}]
                        },
                    }
                )

        return blocks

    def notion_blocks_to_markdown(self, blocks: List[Dict[str, Any]]) -> str:
        """
        Convert Notion blocks to markdown text.
        This is a basic implementation that can be extended based on needs.

        Args:
            blocks: List of Notion block objects

        Returns:
            Markdown text
        """
        markdown_lines = []

        for block in blocks:
            block_type = block.get("type")
            if not block_type:
                continue

            rich_text = None
            if block_type == "paragraph":
                rich_text = block.get("paragraph", {}).get("rich_text", [])
            elif block_type == "heading_1":
                rich_text = block.get("heading_1", {}).get("rich_text", [])
                prefix = "# "
            elif block_type == "heading_2":
                rich_text = block.get("heading_2", {}).get("rich_text", [])
                prefix = "## "
            elif block_type == "heading_3":
                rich_text = block.get("heading_3", {}).get("rich_text", [])
                prefix = "### "
            elif block_type == "bulleted_list_item":
                rich_text = block.get("bulleted_list_item", {}).get("rich_text", [])
                prefix = "- "
            else:
                continue

            if rich_text:
                text_content = "".join(
                    rt.get("text", {}).get("content", "") for rt in rich_text
                )
                if block_type == "paragraph":
                    markdown_lines.append(text_content)
                else:
                    markdown_lines.append(f"{prefix}{text_content}")

        return "\n".join(markdown_lines)

    def handle_webhook_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle a Notion webhook event and fetch the associated page details.

        Args:
            event_data: The webhook event data received from Notion

        Returns:
            Dict containing the page details and content
        """
        if not event_data:
            print("No event data provided")
            return {}

        # Extract relevant information from the event
        event_type = event_data.get("type")
        entity = event_data.get("entity", {})
        entity_id = entity.get("id")
        entity_type = entity.get("type")

        if not entity_id:
            print("No entity ID in webhook event")
            return {}

        if entity_type != "page":
            print(f"Entity type is not a page: {entity_type}")
            return {}

        try:
            # Get the page details
            page_details = self.get_page(entity_id)
        except Exception as e:
            print(f"Error getting page details: {e}")
            page_details = None

        try:
            # Get the page content
            page_content = self.get_page_content(entity_id)
        except Exception as e:
            print(f"Error getting page content: {e}")
            page_content = None

        # Convert content to markdown for easier reading
        markdown_content = None
        if page_content:
            try:
                markdown_content = self.notion_blocks_to_markdown(page_content)
            except Exception as e:
                print(f"Error converting content to markdown: {e}")

        # Prepare the response
        response = {
            "event_type": event_type,
            "page_id": entity_id,
        }

        if page_details:
            response["page_details"] = page_details
        if page_content:
            response["page_content"] = page_content
        if markdown_content:
            response["markdown_content"] = markdown_content

        return response

    def print_page_details(self, page_details: Dict[str, Any]) -> None:
        """
        Print the details of a Notion page in a readable format.

        Args:
            page_details: The page details from get_page()
        """
        if not page_details:
            print("No page details available")
            return

        print("\n=== Page Details ===")

        # Print basic page information
        print(f"Page ID: {page_details.get('id', 'N/A')}")
        print(f"Created Time: {page_details.get('created_time', 'N/A')}")
        print(f"Last Edited Time: {page_details.get('last_edited_time', 'N/A')}")

        # Print properties
        print("\nProperties:")
        properties = page_details.get("properties", {})
        if not properties:
            print("  No properties found")
            return

        for prop_name, prop_value in properties.items():
            if not prop_value:
                continue

            print(f"\n{prop_name}:")
            # Handle different property types
            prop_type = prop_value.get("type")
            if not prop_type:
                print("  Unknown property type")
                continue

            if prop_type == "title":
                title_content = [
                    t.get("text", {}).get("content", "")
                    for t in prop_value.get("title", [])
                ]
                print(f"  Title: {''.join(title_content) or 'N/A'}")
            elif prop_type == "rich_text":
                text_content = [
                    t.get("text", {}).get("content", "")
                    for t in prop_value.get("rich_text", [])
                ]
                print(f"  Text: {''.join(text_content) or 'N/A'}")
            elif prop_type == "select":
                select_object = prop_value.get("select")
                if select_object:
                    print(f"  Select: {select_object.get('name', 'N/A')}")
                else:
                    print(f"  Select: N/A (not set)")
            elif prop_type == "multi_select":
                options = [
                    opt.get("name", "") for opt in prop_value.get("multi_select", [])
                ]
                print(f"  Multi-select: {', '.join(options) or 'N/A'}")
            elif prop_type == "date":
                date_data = prop_value.get("date", {})
                print(
                    f"  Date: {date_data.get('start', 'N/A')} to {date_data.get('end', 'N/A')}"
                )
            elif prop_type == "number":
                print(f"  Number: {prop_value.get('number', 'N/A')}")
            elif prop_type == "checkbox":
                print(f"  Checkbox: {prop_value.get('checkbox', False)}")
            elif prop_type == "url":
                print(f"  URL: {prop_value.get('url', 'N/A')}")
            elif prop_type == "email":
                print(f"  Email: {prop_value.get('email', 'N/A')}")
            elif prop_type == "phone_number":
                print(f"  Phone: {prop_value.get('phone_number', 'N/A')}")
            else:
                print(f"  Type: {prop_type}")
                print(f"  Value: {json.dumps(prop_value, indent=2)}")

    def print_page_content(self, content: List[Dict[str, Any]]) -> None:
        """
        Print the content of a Notion page in a readable format.

        Args:
            content: The page content from get_page_content()
        """
        print("\n=== Page Content ===")
        markdown = self.notion_blocks_to_markdown(content)
        print(markdown)

    def get_page_status(
        self, page_id: str, status_property_name: str = "Joko Bot - Status"
    ) -> Optional[str]:
        """
        Get the current status from a select property on a Notion page.

        Args:
            page_id: The ID of the Notion page.
            status_property_name: The name of the select property holding the status.

        Returns:
            The name of the selected status option, or None if not found/set.
        """
        try:
            page_details = self.get_page(page_id)
            properties = page_details.get("properties", {})
            status_property = properties.get(status_property_name)

            if status_property and status_property.get("type") == "select":
                select_object = status_property.get("select")
                if select_object:
                    return select_object.get("name")
            return None
        except Exception as e:
            print(f"Error getting page status for {page_id}: {e}")
            return None

    def update_page_status(
        self,
        page_id: str,
        new_status: str,
        status_property_name: str = "Joko Bot - Status",
    ) -> Dict[str, Any]:
        """
        Update a select property on a Notion page (e.g., a status).

        Args:
            page_id: The ID of the Notion page.
            new_status: The name of the select option to set as the new status.
            status_property_name: The name of the select property to update.

        Returns:
            Dict containing the updated page data.
        """
        properties_payload = {status_property_name: {"select": {"name": new_status}}}
        return self.update_page_properties(page_id, properties_payload)

    def append_code_block_to_page(
        self, page_id: str, code_content: str, language: str = "json"
    ) -> Dict[str, Any]:
        """
        Append a code block to a Notion page.

        Args:
            page_id: The ID of the Notion page (can also be a block_id if appending to a block).
            code_content: The string content for the code block.
            language: The language for syntax highlighting in the code block.

        Returns:
            Dict containing the API response.
        """
        code_block = {
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [{"type": "text", "text": {"content": code_content}}],
                "language": language,
            },
        }
        return self.append_block_children(block_id=page_id, children=[code_block])
