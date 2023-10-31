import frappe
from frappe import _
from chat.utils import get_full_name
import ast
from typing import List, Dict
from taskerpage_core.taskerpage_core.api.util import get_possible_transitions


def get_user_avatar(user):
    try:
        customer_profile_doc = frappe.get_last_doc(
            "Customer Profile", filters={"user": user})
        if customer_profile_doc and customer_profile_doc.get("avatar"):
            return customer_profile_doc.avatar, customer_profile_doc.name
        else:
            return None, None
    except:
        return None, None


@frappe.whitelist()
def get(email: str, task: str = None) -> List[Dict]:
    """Get all the rooms for a user

    Args:
        email (str): Email of user requests all rooms

    """
    room_doctype = frappe.qb.DocType('Chat Room')

    all_rooms = (
        frappe.qb.from_(room_doctype)
        .select('name', 'modified', 'last_message', 'is_read', 'room_name', 'members', 'type', 'customer_task', 'chat_bot', 'workflow_state')
        .where((room_doctype.type.like('Guest') | room_doctype.members.like(f'%{email}%')))

    ).run(as_dict=True)

    user_rooms = []

    for room in all_rooms:
        if room['type'] == 'Direct':
            members = room['members'].split(', ')
            room['room_name'] = get_full_name(
                members[0]) if email == members[1] else get_full_name(members[1])
            room['opposite_person_email'] = members[0] if members[1] == email else members[1]
            if get_user_avatar(room['opposite_person_email']):
                room['opposite_person_avatar'], room['opposite_person_customer_profile'] = get_user_avatar(
                    room['opposite_person_email'])
        if room['type'] == 'Group':
            members = room['members'].split(',')
            if len(members) == 2:
                room['room_name'] = get_full_name(
                    members[0]) if email == members[1] else get_full_name(members[1])
                room['opposite_person_email'] = members[0] if members[1] == email else members[1]
                if get_user_avatar(room['opposite_person_email']):
                    room['opposite_person_avatar'], room['opposite_person_customer_profile'] = get_user_avatar(
                        room['opposite_person_email'])
        if room['type'] == 'Guest':
            users = frappe.get_cached_doc("Chat Room", room['name']).users
            if not users:
                users = frappe.get_cached_doc('Chat Settings').chat_operators
            if email not in [u.user for u in users]:
                continue
        if (task != "null" and task != "0") and str(room['customer_task']) != task:
            continue
        room['is_read'] = 1 if room['is_read'] and email in room['is_read'] else 0
        room['room'] = room['name']
        transitions = get_possible_transitions(
            room.workflow_state, "Chat Room")
        room["possible_transitions"] = transitions
        user_rooms.append(room)

    user_rooms.sort(key=lambda room: comparator(room))
    return user_rooms


@frappe.whitelist()
def get_room_by_name(room_name: str, email: str = None) -> Dict:
    """Get room details by room_name.

    Args:
        room_name (str): The unique name of the room to retrieve details for.
        email (str, optional): Email of the user. Used for some checks.

    Returns:
        dict: Details of the specified room.
    """

    try:
        room = frappe.get_doc("Chat Room", room_name).as_dict()

        if room['type'] == 'Direct':
            members = room['members'].split(', ')
            room['room_name'] = get_full_name(
                members[0]) if email == members[1] else get_full_name(members[1])
            room['opposite_person_email'] = members[0] if members[1] == email else members[1]
            if get_user_avatar(room['opposite_person_email']):
                room['opposite_person_avatar'], room['opposite_person_customer_profile'] = get_user_avatar(
                    room['opposite_person_email'])

        if room['type'] == 'Group':
            members = room['members'].split(',')
            if len(members) == 2:
                room['room_name'] = get_full_name(
                    members[0]) if email == members[1] else get_full_name(members[1])
                room['opposite_person_email'] = members[0] if members[1] == email else members[1]
                if get_user_avatar(room['opposite_person_email']):
                    room['opposite_person_avatar'], room['opposite_person_customer_profile'] = get_user_avatar(
                        room['opposite_person_email'])

        if room['type'] == 'Guest' and email:
            users = [user.user for user in room['users']]
            if not users:
                chat_settings = frappe.get_doc("Chat Settings")
                users = [user.user for user in chat_settings.chat_operators]
            if email not in users:
                return {"error": "Unauthorized access"}

        room['is_read'] = 1 if room['is_read'] and email in room['is_read'] else 0
        room['room'] = room['room_name']
        transitions = get_possible_transitions(
            room.workflow_state, "Chat Room")
        room["possible_transitions"] = transitions
        return room

    except frappe.DoesNotExistError:
        return {"error": f"No room found with the name {room_name}"}
    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def create_private(room_name, users, type, task=None, chat_bot=None):
    """Create a new private room

    Args:
        room_name (str): Room name
        users (str): List of users in room
    """
    users = ast.literal_eval(users)
    users.append(frappe.session.user)
    members = ", ".join(users)

    if type == "Direct":
        room_doctype = frappe.qb.DocType("Chat Room")
        direct_room_exists = (
            frappe.qb.from_(room_doctype)
            .select("name")
            .where(room_doctype.type == "Direct")
            .where(room_doctype.members.like(f"%{users[0]}%"))
            .where(room_doctype.members.like(f"%{users[1]}%"))
        ).run(as_dict=True)
        if direct_room_exists:
            frappe.throw(title="Error", msg=_("Direct Room already exists!"))

    room_doc = get_private_room_doc(
        room_name, members, type, task, chat_bot).insert(ignore_permissions=True)

    profile = {
        "room_name": room_name,
        "last_date": room_doc.modified,
        "room": room_doc.name,
        "is_read": 0,
        "room_type": type,
        "members": members,
    }

    if type == "Direct":
        profile["member_names"] = [
            {"name": get_full_name(u), "email": u} for u in users
        ]

    for user in users:
        frappe.publish_realtime(
            event="private_room_creation", message=profile, user=user, after_commit=True
        )

    frappe.response["message"] = profile


def get_private_room_doc(room_name, members, type, task=None, chat_bot=None):
    return frappe.get_doc({
        'doctype': 'Chat Room',
        'room_name': room_name,
        'members': members,
        'type': type,
        'customer_task': task,
        'chat_bot': chat_bot
    })


def comparator(key):
    return (
        key.is_read,
        reversor(key.modified)
    )


class reversor:
    def __init__(self, obj):
        self.obj = obj

    def __eq__(self, other):
        return other.obj == self.obj

    def __gt__(self, other):
        return other.obj > self.obj
