# Feishu open_id is scoped per app — observed case

In the "MISC" group, the bot 华生 self-reported open_id
`ou_4c5fa38a012bf260485ed24c499482dd`, while mention metadata delivered with
its message showed `ou_e4e81f9f3ce308da4b0464b596ed3048` for the same name.
Both are valid — they are the same bot seen from two different Feishu apps.

Verified empirically: `feishu.py send --chat MISC --at 华生` using the
contacts-file ID (`ou_4c5fa...`) was accepted by the API and echoed back in
`mentions` — twice, two distinct message_ids.

## Rules of thumb

1. When @-mentioning someone from OUR app, always use the ID in
   `feishu_contacts.json` (or freshly mined via `contacts --scan`) — those are
   resolved in our app's ID space.
2. An ID embedded in an incoming message's mention metadata describes the
   sender in the RECEIVER app's ID space; it is not interchangeable with ours.
3. If a remote bot tells you its open_id so you can @ it, that ID only works if
   the bot computed it for your app; otherwise fall back to local contact scan.
