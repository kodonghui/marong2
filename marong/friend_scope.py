"""Accepted friends and the shareable context between them."""

RELATIONSHIP = "CASE WHEN fs.close THEN '가까운 사이' ELSE '아는 사이' END AS label"


def accepted_circle(note_filter="", *, names_only=False):
    columns = f"f.name,{RELATIONSHIP}" if names_only else f"""
           f.id,f.name,true AS unified,true AS told,{RELATIONSHIP},
           NULL AS teller,fs.close,false AS same_group,
           CASE WHEN f.share THEN s.content END AS shared,
           CASE WHEN f.share AND fs.close THEN s.close_content END AS shared_close
    """
    notes = "" if names_only else f"""
    LEFT JOIN LATERAL (
        SELECT x.content,x.close_content FROM marong.shared_notes x WHERE x.friend_id=f.id {note_filter} ORDER BY x.id DESC LIMIT 1
    ) s ON f.share
    """
    return f"""
    SELECT {columns}
    FROM marong.friendships fs JOIN marong.friends f
      ON f.id=CASE WHEN fs.friend_a=%(friend)s THEN fs.friend_b ELSE fs.friend_a END
    {notes}
    WHERE %(friend)s IN (fs.friend_a,fs.friend_b) AND fs.state='accepted'
    ORDER BY fs.close DESC,coalesce(fs.responded_at,fs.created_at),f.id
    LIMIT %(limit)s
"""
