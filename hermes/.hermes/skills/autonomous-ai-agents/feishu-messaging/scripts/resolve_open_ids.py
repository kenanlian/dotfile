#!/usr/bin/env python3
"""Resolve Feishu group members' open_ids by scanning message history.

Works without im:chat.members:read — only needs the message-history scope the
Hermes bot app already has. Run with the Hermes venv python:

  ~/.hermes/hermes-agent/venv/bin/python resolve_open_ids.py <chat_id> [--thread omt_xxx]

Prints each human sender's open_id with message count and recent previews,
so a person can be identified by name or message content. System template
events and bot (app) senders are excluded.
"""
import argparse
import os
import sys


def load_creds():
    creds = {}
    env_path = os.path.expanduser("~/.hermes/.env")
    for line in open(env_path):
        if line.startswith("FEISHU_APP_ID="):
            creds["app_id"] = line.strip().split("=", 1)[1]
        elif line.startswith("FEISHU_APP_SECRET="):
            creds["app_secret"] = line.strip().split("=", 1)[1]
    if len(creds) != 2:
        sys.exit("FEISHU_APP_ID/FEISHU_APP_SECRET not found in ~/.hermes/.env")
    return creds["app_id"], creds["app_secret"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chat_id", help="oc_xxx chat id")
    ap.add_argument("--thread", default=None, help="omt_xxx thread id (scan only this topic)")
    ap.add_argument("--pages", type=int, default=5)
    args = ap.parse_args()

    import lark_oapi as lark
    import lark_oapi.api.im.v1 as imv1

    app_id, app_secret = load_creds()
    client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

    if args.thread:
        container_type, container_id = "thread", args.thread
    else:
        container_type, container_id = "chat", args.chat_id

    users = {}
    token = None
    for _ in range(args.pages):
        b = (
            imv1.ListMessageRequest.builder()
            .container_id_type(container_type)
            .container_id(container_id)
            .page_size(50)
        )
        if token:
            b = b.page_token(token)
        resp = client.im.v1.message.list(b.build())
        if not resp.success():
            sys.exit(f"message.list failed: [{resp.code}] {resp.msg}")
        for item in resp.data.items or []:
            s = item.sender
            body = item.body.content if item.body and item.body.content else ""
            if not s or not s.id or s.id_type != "open_id":
                continue  # skip bots and system template events (empty sender)
            if '"template"' in body[:30]:
                continue
            users.setdefault(s.id, []).append(body[:70].replace("\n", " "))
        if not resp.data.has_more or not resp.data.page_token:
            break
        token = resp.data.page_token

    if not users:
        print("No human messages found in scope.")
        return
    for uid, msgs in users.items():
        print(f"USER {uid} ({len(msgs)} msgs)")
        for m in msgs[-3:]:
            print(f"    {m}")


if __name__ == "__main__":
    main()
