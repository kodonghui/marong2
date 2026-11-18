"""Grant published free defaults once when a member signs up or signs in (SPEC-346)."""


async def sync_defaults(conn, member_id):
    await conn.execute(
        """INSERT INTO pet.inventory(member_id,item_id,source)
        SELECT %s,id,'free_default' FROM pet.items WHERE is_default
        ON CONFLICT (member_id,item_id) WHERE withdrawn_at IS NULL DO NOTHING""", (member_id,),
    )
    await conn.execute("UPDATE pet.members SET defaults_synced_at=now() WHERE id=%s", (member_id,))
