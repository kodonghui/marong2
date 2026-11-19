"""SQL predicates for the unified app's owned writing rooms (SPEC-375)."""


def writing_room(alias):
    return (f"{alias}.owner_friend_id IS NOT NULL AND "
            f"({alias}.room_key LIKE 'app:%%' OR {alias}.room_key LIKE 'discord-dm:%%')")
