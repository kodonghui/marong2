"""Accepted friends and the shareable context between them."""

ACCEPTED_CIRCLE = """
    SELECT f.id,f.name,true AS unified,true AS told,CASE WHEN fs.close THEN '가까운 사이' ELSE '아는 사이' END AS label,
           NULL AS teller,fs.close,false AS same_group,
           CASE WHEN f.share THEN s.content END AS shared,
           CASE WHEN f.share AND fs.close THEN s.close_content END AS shared_close
    FROM marong.friendships fs JOIN marong.friends f
      ON f.id=CASE WHEN fs.friend_a=%(friend)s THEN fs.friend_b ELSE fs.friend_a END
    LEFT JOIN LATERAL (
        SELECT x.content,x.close_content FROM marong.shared_notes x WHERE x.friend_id=f.id ORDER BY x.id DESC LIMIT 1
    ) s ON f.share
    WHERE %(friend)s IN (fs.friend_a,fs.friend_b) AND fs.state='accepted'
    ORDER BY fs.close DESC,coalesce(fs.responded_at,fs.created_at),f.id
    LIMIT %(limit)s
"""
