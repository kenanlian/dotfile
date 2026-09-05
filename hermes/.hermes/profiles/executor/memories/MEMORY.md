Feishu 群 "MISC" 的机器人 open_id 按应用隔离（feishu.py 多 profile 版实测）：默认 profile 视角华生=ou_4c5fa38a012bf260485ed24c499482dd；executor profile（即小龙自己）视角华生=ou_e4e81f9f3ce308da4b0464b596ed3048，柯楠=ou_19234927e3331a9e1433c9a81dbf7aa1。发消息工具：python3 ~/.hermes/scripts/feishu.py send --profile executor --chat MISC --at 华生 --text "..."；在 executor 会话内可省 --profile。open_id 别写死，用 contacts --scan 按自己 profile 挖。艾特用户本人（Kenan）用 ou_c59ade9dbeda75801a274082a98b3209（executor 视角）。注意：API 消息发件人身份永远是 App 本身，@ 只是提及不改发件人。
§
feishu.py 局限（executor 实测）：send 的 payload 不含 thread_id，回复进话题需根消息 om_ id（omt_ 传 reply API 会报 invalid id）；找根消息需 im:message.group_msg 权限（当前 app 无）。兜底：send 到群 oc_ id（话题群内落为新话题，@ 仍生效），或依赖会话自身回复进 thread。
§
项目开发监控/验收职责已于 2026-09-01 移交回华生（任务专属 script-gated Cron 架构）。小龙不再接收 Relay 监控交接单、不部署 watchdog/digest cron、不做行为验收；仅在华生或柯楠明确单独委派时参与具体任务。
