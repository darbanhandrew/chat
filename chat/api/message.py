import frappe
from frappe import _
from chat.utils import update_room, is_user_allowed_in_room, raise_not_authorized_error
from taskerpage_core.taskerpage_core.api.util import get_possible_transitions


@frappe.whitelist(allow_guest=True)
def send(content: str, user: str, room: str, email: str, chat_bot: str = None, action_type: str = None, action_required: int = 0,
         reference_doctype: str = None, reference_docname: str = None
         ):
    """Send the message via socketio

    Args:
        content (str): Message to be sent.
        user (str): Sender's name.
        room (str): Room's name.
        email (str): Sender's email.
    """
    if not is_user_allowed_in_room(room, email, user):
        raise_not_authorized_error()

    new_message = frappe.get_doc(
        {
            "doctype": "Chat Message",
            "content": content,
            "sender": user,
            "room": room,
            "sender_email": email,
            "chat_bot": chat_bot,
            "action_type": action_type,
            "action_required": action_required,
            "reference_doctype": reference_doctype,
            "reference_docname": reference_docname
        }
    ).insert(ignore_permissions=True)

    update_room(room=room, last_message=content)

    result = {
        "content": content,
        "user": user,
        "creation": new_message.creation,
        "room": room,
        "sender_email": email,
    }
    typing_data = {
        "room": room,
        "user": user,
        "is_typing": "false",
        "is_guest": "true" if user == "Guest" else "false",
    }
    typing_event = f"{room}:typing"

    for chat_user in frappe.get_cached_doc("Chat Room", room).get_members():
        frappe.publish_realtime(
            event=typing_event, user=chat_user, message=typing_data)
        frappe.publish_realtime(
            event=room, message=result, user=chat_user, after_commit=True
        )
        frappe.publish_realtime(
            event="latest_chat_updates",
            message=result,
            user=chat_user,
            after_commit=True,
        )


@frappe.whitelist(allow_guest=True)
def get_all(room: str, email: str, order_by: str = None, start: int = 0, page_length: int = 10):
    """Get all the messages of a particular room

    Args:
        room (str): Room's name.

    """
    if not is_user_allowed_in_room(room, email):
        raise_not_authorized_error()

    if order_by is None:
        order = "creation asc"
    else:
        order = order_by

    messages = frappe.get_all(
        "Chat Message",
        filters={
            "room": room,
        },
        fields=["name", "content", "sender", "creation", "sender_email",
                "content_type", "refrence_doctype", "refrence_doc", "workflow_state"],
        order_by=order,
        start=start,
        page_length=page_length
    )

    # For each chat message, get its possible transitions and attach to the message
    previous_date = None
    for index, message in enumerate(messages):
        current_date = message['creation'].date()
        if order_by == "creation desc":
            # If in descending order and there's a previous date that's different,
            # add the header to the current message
            if previous_date and previous_date != current_date:
                message['header'] = {
                    'type': 'day_change',
                    'date': previous_date.strftime('%Y-%m-%d')
                }
        else:
            # In ascending order, add the header to the next message
            if previous_date and previous_date != current_date:
                # Add to the next message if there's a next one
                if index + 1 < len(messages):
                    messages[index + 1]['header'] = {
                        'type': 'day_change',
                        'value': current_date.strftime('%Y-%m-%d')
                    }
                # Else, append a message for the day change
                else:
                    day_change_msg = {
                        'header': {
                            'type': 'day_change',
                            'date': current_date.strftime('%Y-%m-%d')
                        }
                    }
                    messages.append(day_change_msg)
        transitions = get_possible_transitions(
            message.workflow_state, "Chat Message")
        message["possible_transitions"] = transitions
        previous_date = current_date
    return messages


@frappe.whitelist()
def mark_as_read(room: str):
    """Mark the message as read

    Args:
        room (str): Room's name.
    """
    frappe.enqueue(
        "chat.utils.update_room", room=room, is_read=1, update_modified=False
    )


@frappe.whitelist(allow_guest=True)
def set_typing(room: str, user: str, is_typing: bool, is_guest: bool):
    """Set the typing text accordingly

    Args:
        room (str): Room's name.
        user (str): Sender who is typing.
        is_typing (bool): Whether user is typing.
        is_guest (bool): Whether user is guest or not.
    """
    result = {"room": room, "user": user,
              "is_typing": is_typing, "is_guest": is_guest}
    event = f"{room}:typing"

    for chat_user in frappe.get_cached_doc("Chat Room", room).get_members():
        frappe.publish_realtime(event=event, user=chat_user, message=result)
