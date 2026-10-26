"""Rule-based debate host. Same input always gets the same rebuttal."""

OPPOSITE = {"正方": "反方", "反方": "正方"}
PIVOTS = (
    ("猫", "猫如果交税，税务局得先学会听懂呼噜，否则征到的只是毛。"),
    ("税", "税单一出，连路过的影子都会要求退税。"),
    ("冰箱", "冰箱投出的票一定是冷藏票，热食提案永远过不了。"),
    ("周一", "取消周一之后，周二会连夜改名，麻烦只是换了工牌。"),
    ("梦想", "梦想按斤卖会缺斤短两，因为灵感在秤上会蒸发。"),
    ("汤", "免费热汤一开放，全城的勺子都会来开会。"),
    ("雨", "雨没有编制，热汤却要进预算，财政局会先感冒。"),
    ("投票", "投票权一发放，弃权的人会比菜叶子还多。"),
)
HOST_NAME = "主持人杠精"
_FNV_OFFSET = 2166136261
_FNV_PRIME = 16777619


def round_id_for(player, motion, argument):
    value = _FNV_OFFSET
    for byte in f"{player}|{motion}|{argument}".encode("utf-8"):
        value ^= byte
        value = (value * _FNV_PRIME) & 0xFFFFFFFF
    return f"{value:08x}"


def host_reply(player, motion, side, argument, hits):
    host_side = OPPOSITE.get(side, "反方")
    cited_id = ""
    cite = "档案库这会儿没有更早的同题发言，本席只能现场抬杠。"
    if hits:
        top = hits[0] or {}
        cited_id = str(top.get("id") or "")
        who = (top.get("metadata") or {}).get("player") or "某位旧辩手"
        snippet = str(top.get("document") or "").replace("\n", " ")
        if len(snippet) > 42:
            snippet = snippet[:42] + "…"
        cite = f"我翻到旧档案 {cited_id}：{who}说过「{snippet}」。"
    pivot = "你的论证把音量当成了证据，音量越大，漏洞越亮。"
    blob = f"{motion}{argument}"
    for key, line in PIVOTS:
        if key in blob:
            pivot = line
            break
    bangs = argument.count("！") + argument.count("!")
    score = 35 + (len(argument) % 40) + min(bangs, 4) * 6 + (8 if cited_id else 0)
    score = max(1, min(score, 99))
    rebuttal = (
        f"{HOST_NAME}站{host_side}。{player}，你以{side}主张「{motion}」。"
        f"{cite}{pivot}"
        f"所以本席不接受「{argument}」作为定论。"
        f"离谱指数 {score}/99。下一句请给一个反例，不许只加感叹号。"
    )
    return {
        "rebuttal": rebuttal,
        "score": score,
        "cited_id": cited_id,
        "host_side": host_side,
        "round_id": round_id_for(player, motion, argument),
        "host": HOST_NAME,
    }