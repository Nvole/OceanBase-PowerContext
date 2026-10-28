"""Deterministic stand-in for the 池神 LLM node.

The Dify workflow writes the echo letter with a real model. The eval box, unit
tests and local play scripts have no bound model, so this module produces the
exact same output schema deterministically: the same wish and the same hits
always produce the same reply. The tests compare the DSL code node against
this reference.
"""
import re

ECHO_NAME = "池神"

_GIFTS = [
    "一枚只会报晴天的怀表",
    "一只能装下整个傍晚的玻璃瓶",
    "一张永远停在周五的日历",
    "一把会自己收起来的雨伞",
    "一颗泡进水里会讲故事的水果糖",
    "一对只在深夜营业的拖鞋",
    "一根能量出梦想长度的皮尺",
    "一本写满别人愿望的空白本子",
    "一只替你打哈欠的绒毛猫",
    "一盏照到哪里哪里就慢五分钟的灯",
    "半张没写完的请假条",
    "一瓶闻起来像暑假第一天的风",
]

_CITATIONS = [
    "池面泛起一圈旧涟漪：{player} 当年在这里许过「{wish}」，回声至今还没散。",
    "本神翻了翻旧账，{player} 曾把「{wish}」投进池子，如今正好游到你脚边。",
    "有一枚旧硬币自己浮了上来——{player} 说过「{wish}」，看来你们的愿望是邻居。",
]


def fnv1a(text):
    value = 2166136261
    for byte in text.encode("utf-8"):
        value ^= byte
        value = (value * 16777619) & 0xFFFFFFFF
    return value


def coin_id_for(player, wish):
    return f"{fnv1a(f'{player}|{wish}'):08x}"


def grant_for(wish):
    return 1 + (fnv1a(f"grant|{wish}") % 99)


def absurdity_for(wish, hits):
    return 1 + ((fnv1a(f"absurdity|{wish}") + len(hits) * 7) % 99)


def gift_for(wish):
    return _GIFTS[fnv1a(f"gift|{wish}") % len(_GIFTS)]


def _wish_of(hit):
    metadata = hit.get("metadata") or {}
    wish = metadata.get("wish")
    if wish:
        return str(wish)
    document = hit.get("document") or ""
    match = re.search(r"【愿望】([^\n]+)", document)
    return match.group(1).strip() if match else document.strip()


def _player_of(hit):
    metadata = hit.get("metadata") or {}
    player = metadata.get("player")
    if player:
        return str(player)
    document = hit.get("document") or ""
    match = re.search(r"【许愿人】([^\n]+)", document)
    return match.group(1).strip() if match else "某位旧许愿人"


def echo_letter(player, wish, hits):
    """Same wish + same hits always produce the same letter."""
    coin = coin_id_for(player, wish)
    cited_ids = [str(hit.get("id") or "") for hit in hits[:2] if hit.get("id")]
    citations = []
    for index, hit in enumerate(hits[:2]):
        what = _wish_of(hit)
        if not what:
            continue
        citations.append(_CITATIONS[index % len(_CITATIONS)].format(
            player=_player_of(hit), wish=what))
    if not citations:
        citations = ["池面出奇地平静，还没有旧愿望浮上来。你是第一个把今天投进池子的人。"]
    grant = grant_for(wish)
    absurdity = absurdity_for(wish, hits)
    gift = gift_for(wish)
    ending = "" if re.search(r"[。！？!?…~]$", wish) else "。"
    lines = [
        "池神把硬币在手心捂热，才慢悠悠地回信：",
        "",
        f"「{player}，池子已经听见了。你说：{wish}{ending}",
    ]
    lines.extend(citations)
    lines.append(f"本神掐指一算：应验概率 {grant}%，离谱指数 {absurdity}/99。")
    lines.append(f"作为回礼，送你一件不存在的赠品：{gift}。")
    lines.append(f"记住这枚许愿币：W-{coin}。等回声浮起来，会有人替你说完下半句。」")
    echo = "\n".join(lines)
    return {
        "player": player,
        "wish": wish,
        "echo": echo,
        "grant": grant,
        "absurdity": absurdity,
        "gift": gift,
        "cited_ids": cited_ids,
        "coin_id": coin,
    }


def god_payload(player, wish, hits):
    """JSON-serialisable payload in the same shape the DSL LLM node outputs."""
    letter = echo_letter(player, wish, hits)
    return {key: letter[key] for key in ("echo", "grant", "absurdity", "gift", "cited_ids", "coin_id")}