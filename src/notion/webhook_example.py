"""
Example of handling a Notion webhook event.
"""

from client import NotionClient


def main():
    # Example webhook event data
    webhook_event = {
        "id": "4754b16a-24a0-4329-9a2a-99b823bddaad",
        "timestamp": "2025-05-18T11:13:21.319Z",
        "workspace_id": "6ba2db14-f6ed-4875-8ecb-82fd19857b42",
        "workspace_name": "Arthur",
        "subscription_id": "1f7d872b-594c-81a8-912c-0099de694b07",
        "integration_id": "1f7d872b-594c-807f-b7a0-0037870c4a35",
        "authors": [{"id": "a35af545-1a6b-40a8-988f-253cee23dc24", "type": "person"}],
        "attempt_number": 4,
        "entity": {"id": "1f768be4-9d86-80b2-ae87-d173cab50126", "type": "page"},
        "type": "page.created",
        "data": {
            "parent": {"id": "1f768be4-9d86-8083-b495-feb715f7e480", "type": "database"}
        },
    }

    # Initialize the client
    client = NotionClient()

    try:
        # Handle the webhook event
        response = client.handle_webhook_event(webhook_event)

        # Print the page details
        client.print_page_details(response["page_details"])

        # Print the page content
        client.print_page_content(response["page_content"])

    except Exception as e:
        print(f"Error handling webhook event: {e}")


if __name__ == "__main__":
    main()
