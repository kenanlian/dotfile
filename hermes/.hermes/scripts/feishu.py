#!/usr/bin/env python3
"""feishu.py — 飞书快捷发消息 / @ 人小工具（Hermes 用）。

用法:
  feishu.py send --chat MISC [--at 小龙 ...] --text "你好"
      --chat  接受群名（模糊匹配 channel_directory.json）、oc_ 开头的 chat_id、
              或 "群名/话题" 的 thread_id（omt_ 开头）
      --at    联系人名（查 feishu_contacts.json）或 ou_ 开头的 open_id，可多次
  feishu.py contacts            列出已知联系人
  feishu.py contacts --scan     从 Hermes 会话库自动挖掘 @ 记录，补充联系人

Profile 支持（多机器人共机时，发送身份跟着 profile 走）：
  自动：若设置了 $HERMES_HOME（Hermes profile 会话内天然携带），用它作为根目录。
  手动：--profile <name> 显式指定 ~/.hermes/profiles/<name>，优先级最高。

凭证取自 <根目录>/.env 的 FEISHU_APP_ID / FEISHU_APP_SECRET；
联系人库与会话库也从同一根目录读取。
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request

DEFAULT_HERMES = os.path.expanduser("~/.hermes")
API = "https://open.feishu.cn/open-apis"


def load_env(hermes):
    env = {}
    path = os.path.join(hermes, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def call(url, payload=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"http_error": e.code}


def get_token(hermes):
    env = load_env(hermes)
    r = call(f"{API}/auth/v3/tenant_access_token/internal",
             {"app_id": env["FEISHU_APP_ID"], "app_secret": env["FEISHU_APP_SECRET"]})
    if "tenant_access_token" not in r:
        sys.exit(f"取 token 失败: {json.dumps(r, ensure_ascii=False)[:300]}")
    return r["tenant_access_token"], env["FEISHU_APP_ID"]


def resolve_root(profile):
    if profile:
        root = os.path.join(DEFAULT_HERMES, "profiles", profile)
    elif os.environ.get("HERMES_HOME"):
        root = os.environ["HERMES_HOME"]
    else:
        root = DEFAULT_HERMES
    if not os.path.isdir(root):
        sys.exit(f"profile 目录不存在: {root}")
    return root


def contacts_path(hermes):
    return os.path.join(hermes, "scripts", "feishu_contacts.json")


def load_contacts(hermes):
    p = contacts_path(hermes)
    if os.path.exists(p):
        return json.load(open(p))
    return {}


def save_contacts(hermes, c):
    p = contacts_path(hermes)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(c, open(p, "w"), ensure_ascii=False, indent=1)


def resolve_chat(key, hermes):
    """群名/id -> (chat_id, thread_id)"""
    path = os.path.join(hermes, "channel_directory.json")
    if not os.path.exists(path):
        sys.exit("找不到 channel_directory.json")
    entries = json.load(open(path))["platforms"].get("feishu", [])
    # 精确 id
    if key.startswith("oc_"):
        for e in entries:
            if e["id"] == key or e["id"].split(":")[0] == key:
                return e["id"].split(":")[0], e.get("thread_id")
    if key.startswith("omt_") or key.startswith("om_"):
        for e in entries:
            if e.get("thread_id") == key:
                return e["id"].split(":")[0], e.get("thread_id")
    # 名字模糊匹配（优先短名）
    cands = [e for e in entries if key in (e.get("name") or "")]
    if not cands:
        sys.exit(f"找不到会话: {key}\n已知: " + ", ".join(e.get("name") or e["id"] for e in entries))
    e = min(cands, key=lambda x: len(x.get("name") or ""))
    return e["id"].split(":")[0], e.get("thread_id")


def resolve_at(name, hermes):
    if name.startswith("ou_"):
        return name, name
    c = load_contacts(hermes)
    if name not in c:
        sys.exit(f"未知联系人: {name}（先跑 feishu.py contacts --scan，或直接传 ou_ ID）已知: {json.dumps(c, ensure_ascii=False)}")
    return name, c[name]


def cmd_send(args):
    hermes = resolve_root(args.profile)
    chat_id, thread_id = resolve_chat(args.chat, hermes)
    at_tags, names = [], []
    for n in args.at or []:
        disp, ou = resolve_at(n, hermes)
        at_tags.append(f'<at user_id="{ou}"></at>')
        names.append(disp)
    text = " ".join(at_tags) + (" " if at_tags else "") + args.text
    token, app_id = get_token(hermes)
    payload = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    r = call(f"{API}/im/v1/messages?receive_id_type=chat_id", payload, token=token)
    if r.get("code") != 0:
        sys.exit(f"发送失败: {json.dumps(r, ensure_ascii=False)[:400]}")
    d = r["data"]
    print(f"send: 0 message_id={d.get('message_id')} chat={d.get('chat_id')}")
    print(f"identity: {app_id}  thread: {thread_id or '-'}  at: {names or '-'}")
    print(f"mentions: {[m['id'] for m in (d.get('mentions') or [])]}")


def cmd_contacts(args):
    hermes = resolve_root(args.profile)
    contacts = load_contacts(hermes)
    if args.scan:
        db = os.path.join(hermes, "state.db")
        if not os.path.exists(db):
            sys.exit("找不到 state.db")
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        pat = re.compile(r"\[Mentioned:\s*(.+?)\s*\(open_id=(ou_[0-9a-f]+)\)\]")
        seen = {}
        for (content,) in con.execute(
            "SELECT content FROM messages WHERE content LIKE '%[Mentioned:%' AND content LIKE '%open_id=ou_%'"
        ):
            for name, ou in pat.findall(content):
                seen.setdefault(name, set()).add(ou)
        added = []
        for name, ous in seen.items():
            if name not in contacts and len(ous) == 1:
                contacts[name] = next(iter(ous))
                added.append(name)
        # 注意：open_id 按应用隔离，不同 profile 看到同一人的 ou_ 不同，
        # 因此不写死任何默认联系人，全部以各 profile 自己的 scan 结果为准。
        save_contacts(hermes, contacts)
        print(f"scan 新增 {len(added)} 人: {added}")
    print(json.dumps(contacts, ensure_ascii=False, indent=1))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("send")
    ps.add_argument("--chat", required=True)
    ps.add_argument("--at", action="append")
    ps.add_argument("--text", required=True)
    ps.add_argument("--profile")
    ps.set_defaults(fn=cmd_send)
    pc = sub.add_parser("contacts")
    pc.add_argument("--scan", action="store_true")
    pc.add_argument("--profile")
    pc.set_defaults(fn=cmd_contacts)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
