# -*- coding: utf-8 -*-
"""动漫云端追更·每日任务(MoviePilot 订阅驱动)

每天凌晨运行:
  1. 读取 MoviePilot「我的订阅」(include/exclude 作为资源过滤条件)
  2. 经 MP 索引器搜索各站点资源, 优先简体字幕版本(简繁内封 > 简体内嵌 > 其他)
  3. 新集提交 115 离线下载(目标 /影视库/动画/2026-10月新番)
  4. 下载完成的集数重命名成 Emby 标准结构:
     /影视库/动画/2026-10月新番/<作品>/Season N/<作品> - S<NN>E<NN>.<ext>
  5. 触发 LitePan STRM 事件(需在 LitePan 后台配置 anime_ready/hermes 规则)并刷新 Emby

用法: python mp_daily.py [--dry-run] [--backfill <tmdbid>]
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

DEPLOY = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, r"C:/Users/屑穹/.zcode/skills/anime-cloud-pipeline/scripts")
from pipeline.real_adapters import read_secret_file  # noqa: E402

CONFIG = os.path.join(DEPLOY, "config.json")
STATE = os.path.join(DEPLOY, "mp_state.json")
SECRETS = os.path.join(DEPLOY, "secrets")
DONE_STAGES = ("renamed", "downloaded")


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def mp(method, path, body=None):
    token = read_secret_file(os.path.join(SECRETS, "mp_token.dpapi"))
    req = urllib.request.Request(
        f"http://192.168.1.49:3000{path}", data=json.dumps(body).encode() if body else None,
        method=method, headers={"Content-Type": "application/json", "X-API-KEY": token})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def mcp(name, args):
    token = read_secret_file(os.path.join(SECRETS, "mp_token.dpapi"))
    body = json.dumps({"tool_name": name, "arguments": args}).encode()
    req = urllib.request.Request("http://192.168.1.49:3000/api/v1/mcp/tools/call",
                                 data=body, method="POST",
                                 headers={"X-API-KEY": token,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.load(r)
    try:
        return json.loads(d.get("result") or "{}")
    except Exception:
        return {}


_client = None


def p115():
    global _client
    if _client is None:
        from p115client import P115Client
        _client = P115Client(read_secret_file(os.path.join(SECRETS, "p115_cookie.dpapi")))
    return _client


def ls(pid):
    r = p115().fs_files(int(pid))
    data = r.get("data") if isinstance(r, dict) else None
    return [it for it in (data if isinstance(data, list) else []) if isinstance(it, dict)]


def find_child(pid, name):
    for d in ls(pid):
        if d.get("n") == name:
            return d
    return None


def mkdir_chain(pid, *names):
    cur = int(pid)
    for n in names:
        child = find_child(cur, n)
        if not child:
            p115().fs_mkdir(n, pid=cur)
            for _ in range(6):
                time.sleep(1)
                child = find_child(cur, n)
                if child:
                    break
        cur = int(child["cid"])
    return cur


# ---------------- 匹配与排序 ----------------
def simplified_rank(title: str) -> int:
    """简繁内封 0 < 简体 1 < 其他 9"""
    for kw, rank in (("简繁", 0), ("简体", 1), ("简日", 1), ("chs&cht", 0), ("简", 1)):
        if kw.lower() in title.lower():
            return rank
    return 9


def parse_ep(season_episode: str):
    m = re.search(r"S(\d+)\s*E(\d+)", season_episode or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


# ---------------- 主流程 ----------------
def run(cfg, dry=False, only_tmdb=None):
    state = load_json(STATE, {"items": {}, "baselines": {}, "dir_ids": {}})
    p115_cfg = cfg.get("p115") or {}
    root_cid = int(p115_cfg["target_directory_id"])
    backfill_tmdb = {int(x) for x in (cfg.get("mp_daily", {}).get("backfill_tmdb") or [])}
    if only_tmdb:
        backfill_tmdb.add(int(only_tmdb))

    subs = mp("GET", "/api/v1/subscribe/")
    summary = []
    for sub in subs if isinstance(subs, list) else []:
        tmdb = sub.get("tmdbid")
        if not tmdb:
            continue
        tmdb = int(tmdb)
        work = sub.get("name") or f"tmdb{tmdb}"
        include = (sub.get("include") or "").strip()
        exclude = [k for k in re.split(r"[,\s]+", (sub.get("exclude") or "")) if k]
        is_backfill = tmdb in backfill_tmdb

        # 1) 经 MP 索引器搜索
        res = mcp("search_torrents", {"tmdb_id": tmdb, "media_type": "tv"})
        if not res.get("total_count"):
            summary.append(f"[{work}] 搜索无结果")
            continue
        candidates = []
        page = 1
        while page <= 3:
            r2 = mcp("get_search_results", {"page": page, "limit": 50})
            for row in (r2.get("results") or []):
                ti, mi = row.get("torrent_info") or {}, row.get("meta_info") or {}
                title = ti.get("title") or ""
                m = re.search(r"show-([0-9a-fA-F]{40})\.html", ti.get("page_url") or "")
                if not m:
                    continue  # 仅支持可解析 infohash 的来源(爱恋动漫)
                season, episode = parse_ep(mi.get("season_episode"))
                if episode is None:
                    continue
                if include and include not in title:
                    continue
                if any(k in title for k in exclude):
                    continue
                candidates.append({
                    "title": title, "infohash": m.group(1).lower(),
                    "season": season or 1, "episode": episode,
                    "rank": simplified_rank(title), "size": ti.get("size") or ""})
            if page >= (r2.get("total_pages") or 1):
                break
            page += 1
        if not candidates:
            summary.append(f"[{work}] 无可提交候选(需爱恋动漫来源)")
            continue

        # 2) 基线/追更/补集
        base_key = str(tmdb)
        max_ep = max(c["episode"] for c in candidates)
        if not is_backfill and base_key not in state["baselines"]:
            state["baselines"][base_key] = max_ep
            summary.append(f"[{work}] 首轮基线 S1E{max_ep}:历史集不下载,只追新集")
        baseline = state["baselines"].get(base_key)

        by_ep = {}
        for c in candidates:
            if baseline is not None and c["episode"] <= baseline and not is_backfill:
                continue
            by_ep.setdefault(c["episode"], []).append(c)
        done_eps = {v["episode"] for k, v in state["items"].items()
                    if v.get("tmdb") == tmdb and v.get("stage") in DONE_STAGES}
        todo = []
        for ep in sorted(by_ep):
            if ep in done_eps:
                continue
            it_state = state["items"].get(f"{tmdb}:{ep}")
            if it_state and it_state.get("stage") in ("submitted",):
                continue  # 已在 115 下载中
            todo.append(sorted(by_ep[ep], key=lambda c: c["rank"])[0])
        summary.append(f"[{work}] 待提交 {len(todo)} 集: E{[t['episode'] for t in todo]}")

        # 3) 提交 115 离线
        for c in todo:
            if dry:
                summary.append(f"  [dry] E{c['episode']} {c['title'][:46]} ({c['size']})")
                continue
            r = p115().clouddownload_task_add_bt(
                {"info_hash": c["infohash"], "wp_path_id": root_cid})
            ok = (r.get("state") is True) or (r.get("errno") == 0)
            state["items"][f"{tmdb}:{c['episode']}"] = {
                "tmdb": tmdb, "work": work, "season": c["season"],
                "episode": c["episode"], "infohash": c["infohash"],
                "stage": "submitted" if ok else "failed", "title": c["title"]}
            summary.append(f"  [{'已提交' if ok else '提交失败'}] E{c['episode']} "
                           f"{c['title'][:46]}")

    # 4) 完成下载的集数 → 重命名成 Emby 结构
    advance_renames(cfg, state, summary)
    save_json(STATE, state)
    return summary


def advance_renames(cfg, state, summary):
    changed = False
    p115_cfg = cfg.get("p115") or {}
    root_cid = int(p115_cfg["target_directory_id"])
    # 用已验证的适配器:任务表把"下载文件夹"关联到 info_hash
    from pipeline.real_adapters import P115CloudAdapter
    adapter = P115CloudAdapter(os.path.join(SECRETS, "p115_cookie.dpapi"), root_cid)
    files = adapter.list_files(root_cid)
    by_ih = {}
    for f in files:
        if f.get("infohash"):
            by_ih.setdefault(f["infohash"], []).append(f)
    for key, it in list(state["items"].items()):
        if it.get("stage") != "submitted":
            continue
        mine = by_ih.get(it["infohash"]) or []
        if not mine:
            continue  # 仍在下载
        target_file = mine[0]
        folder_name = target_file["name"].split("/")[0] if "/" in target_file["name"] else None
        # 重命名+移动到 Emby 结构
        season = it.get("season") or 1
        episode = it.get("episode")
        ext = os.path.splitext(target_file.get("name") or ".mkv")[1]
        season_dir = mkdir_chain(root_cid, it["work"], f"Season {season}")
        new_name = f"{it['work']} - S{season:02d}E{episode:02d}{ext}"
        p115().fs_move(int(target_file["file_id"]), pid=season_dir)
        p115().fs_rename((int(target_file["file_id"]), new_name))
        if folder_name:
            folder = find_child(root_cid, folder_name)
            if folder:
                try:
                    p115().fs_delete(int(folder["cid"]))
                except Exception:
                    pass
        it["stage"] = "renamed"
        it["renamed_path"] = (f"{p115_cfg.get('target_path', '').strip('/')}"
                              f"/{it['work']}/Season {season}/{new_name}")
        changed = True
        summary.append(f"  [已重命名] {it['work']} S{season:02d}E{episode:02d} -> {new_name}")

    if changed:
        try:
            st = litepan_event(cfg)
            summary.append(f"  [LitePan 事件] HTTP {st}(规则需在 LitePan 后台配置)")
        except Exception as e:
            summary.append(f"  [LitePan 事件失败] {type(e).__name__}")
        try:
            emby_refresh(cfg)
            summary.append("  [Emby] 媒体库刷新已触发")
        except Exception as e:
            summary.append(f"  [Emby 刷新失败] {type(e).__name__}")
    return changed


def litepan_event(cfg):
    lite = cfg.get("litepan") or {}
    key = read_secret_file(lite["api_key_file"]) if lite.get("api_key_file") else ""
    body = json.dumps({"event": lite.get("automation_event", "anime_ready"),
                       "source": lite.get("automation_source", "hermes"),
                       "message": "anime renamed"}).encode()
    req = urllib.request.Request(
        (lite.get("base_url") or "").rstrip("/") + "/api/open/automation/events",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def emby_refresh(cfg):
    emby = cfg.get("emby") or {}
    key = read_secret_file(emby["api_key_file"])
    lib = emby.get("library_id")
    req = urllib.request.Request(
        f"{emby['base_url'].rstrip('/')}/emby/Items/{lib}/Refresh?"
        + urllib.parse.urlencode({"Recursive": "true", "api_key": key}), method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backfill", type=int, default=None, help="指定 tmdbid 强制补集")
    args = ap.parse_args()
    cfg = load_json(CONFIG, {})
    lines = run(cfg, dry=args.dry_run, only_tmdb=args.backfill)
    print("\n".join(lines) if lines else "(无变化)")


if __name__ == "__main__":
    main()
