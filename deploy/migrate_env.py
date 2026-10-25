"""서버 안에서만 실행: 옛 봇 .env 의 BOT_TOKEN·Claude 키를 마롱이 .env 로 옮긴다. 값은 화면에 출력하지 않는다.
사용(노트북): bash deploy/ovh.sh migrate-env
     (서버에서 직접: sudo python3 - /opt/marong/.env /opt/kakao-bot/.env < deploy/migrate_env.py)
마롱이 .env 에 이미 값이 있는 항목은 건드리지 않는다. 옛 봇 .env 는 읽기만 한다."""
import os
import re
import sys
import tempfile

KEYS = ("BOT_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_BACKUP")
LINE = re.compile(r"\s*([A-Z_][A-Z0-9_]*)\s*=(.*)$")


def read(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def values(lines: list[str]) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in map(LINE.match, lines) if m}


def main(dst: str, src: str) -> None:
    old, lines = values(read(src)), read(dst)
    cur = values(lines)
    move = {k for k in KEYS if not cur.get(k) and old.get(k)}
    out, done = [], set()
    for line in lines:
        m = LINE.match(line)
        if m and m.group(1) in move:
            out.append(f"{m.group(1)}={old[m.group(1)]}")
            done.add(m.group(1))
        else:
            out.append(line)
    out += [f"{k}={old[k]}" for k in KEYS if k in move and k not in done]
    st = os.stat(dst)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dst), prefix=".env.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.chown(tmp, st.st_uid, st.st_gid)
    os.chmod(tmp, 0o600)
    os.replace(tmp, dst)
    for k in KEYS:
        state = "옮김" if k in move else "이미 있음(그대로 둠)" if cur.get(k) else "옛 봇에도 없음"
        print(f"{k}: {state}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
