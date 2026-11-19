"""SQL predicates for the unified app's owned writing rooms (SPEC-375)."""


def writing_room(alias):
    return (f"{alias}.owner_friend_id IS NOT NULL AND "
            f"({alias}.room_key LIKE 'app:%%' OR {alias}.room_key LIKE 'discord-dm:%%')")


def writing_room_key(friend_id):
    return f"""(SELECT r.room_key FROM marong.rooms r
                WHERE r.owner_friend_id={friend_id} AND {writing_room('r')}
                ORDER BY (r.room_key LIKE 'discord-dm:%%') DESC,r.first_seen,r.room_key LIMIT 1)"""


def writing_user_key(friend_id):
    return f"""COALESCE((SELECT user_key FROM marong.people WHERE friend_id={friend_id}
                        AND user_key LIKE 'discord-user:%%' ORDER BY user_key LIMIT 1), 'app-user:' || {friend_id})"""
