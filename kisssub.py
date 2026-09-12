# -*- coding: utf-8 -*-
"""
kisssub.org(爱恋动漫)免登录 BT 链接获取工具

用法:
  python kisssub.py <关键词>              搜索并列出结果(含 BT 直链 / 磁力)
  python kisssub.py <关键词> -p 2        搜索第 2 页
  python kisssub.py --latest             首页最新种子
  python kisssub.py <关键词> -d 1 3      下载第 1、3 条的 .torrent 文件
  python kisssub.py <关键词> -d all      下载本页全部 .torrent
  python kisssub.py <关键词> -m          只输出磁力链接(每行一条,方便管道)
  python kisssub.py <关键词> -u          只输出 BT 直链(每行一条)

无需账号登录;无需 pip 依赖(Python 3.8+ 标准库)。
"""
import argparse
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = "https://www.kisssub.org/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
COOKIE = "visitor_test=human"          # 过站点访客验证,无需账号
TRACKER = "http://open.acgtracker.com:1096/announce"
DOWN = "http://v2.uploadbt.com/?r=down&hash="


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Cookie": COOKIE,
        "Referer": BASE,
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def strip_tags(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def parse_rows(html):
    """解析列表页每行: 日期 / 分类 / 标题+hash / 大小 / UP主"""
    rows = re.findall(r'<tr class="alt[12]">(.*?)</tr>', html, re.S)
    results = []
    for row in rows:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(tds) < 5:
            continue
        date, cat, title_html, size, uploader = tds[0], tds[1], tds[2], tds[3], tds[4]
        m = re.search(r'href="show-([0-9a-f]{40})\.html"', title_html)
        if not m:
            continue
        results.append({
            "date": strip_tags(date),
            "category": strip_tags(cat),
            "title": strip_tags(title_html),
            "hash": m.group(1),
            "size": strip_tags(size),
            "uploader": strip_tags(uploader),
        })
    return results


def search(keyword, page=1):
    url = BASE + "search.php?keyword=" + urllib.parse.quote(keyword) + f"&page={page}"
    return parse_rows(fetch(url))


def latest():
    return parse_rows(fetch(BASE))


def bt_url(h):
    return DOWN + h


def magnet(h, title=None):
    m = f"magnet:?xt=urn:btih:{h}&tr={urllib.parse.quote(TRACKER, safe='')}"
    if title:
        m += "&dn=" + urllib.parse.quote(title)
    return m


def download_torrents(items, idx_list, outdir):
    os.makedirs(outdir, exist_ok=True)
    for i in idx_list:
        item = items[i - 1]
        url = bt_url(item["hash"])
        data = fetch(url, timeout=60).encode("utf-8", "ignore")
        if not data.startswith(b"d"):
            print(f"[失败] #{i} {item['title'][:50]} (返回内容不是种子文件)")
            continue
        safe = re.sub(r'[\\/:*?"<>|]+', "_", item["title"])[:80]
        path = os.path.join(outdir, f"{safe}.torrent")
        with open(path, "wb") as f:
            f.write(data)
        print(f"[已下载] #{i} -> {path} ({len(data)} 字节)")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="kisssub.org 免登录 BT 链接工具")
    ap.add_argument("keyword", nargs="*", help="搜索关键词")
    ap.add_argument("--latest", action="store_true", help="浏览首页最新种子")
    ap.add_argument("-p", "--page", type=int, default=1, help="页码(默认1)")
    ap.add_argument("-n", "--num", type=int, default=20, help="显示条数(默认20)")
    ap.add_argument("-d", "--download", nargs="+", metavar="N",
                    help="下载指定序号的 .torrent,all=全部")
    ap.add_argument("--out", default="torrents", help="下载目录(默认 ./torrents)")
    ap.add_argument("-m", "--magnet-only", action="store_true", help="只输出磁力链接")
    ap.add_argument("-u", "--url-only", action="store_true", help="只输出BT直链")
    args = ap.parse_args()

    keyword = " ".join(args.keyword).strip()
    if not keyword and not args.latest:
        ap.error("请提供搜索关键词,或使用 --latest")

    items = latest() if args.latest else search(keyword, args.page)
    if not items:
        print("没有搜索到结果(站点结构可能变化,或网络被拦截)")
        return

    if args.magnet_only:
        for it in items:
            print(magnet(it["hash"]))
        return
    if args.url_only:
        for it in items:
            print(bt_url(it["hash"]))
        return

    show = items[: args.num]
    w = max(len(str(len(show))), 2)
    for i, it in enumerate(show, 1):
        print(f"#{i:>{w}} [{it['date']}] [{it['category']}] {it['size']:>9}  {it['title']}")
        print(f"{' ' * (w + 2)}BT直链: {bt_url(it['hash'])}")
        print(f"{' ' * (w + 2)}磁  力: {magnet(it['hash'])}")
        print(f"{' ' * (w + 2)}详情页: {BASE}show-{it['hash']}.html  (UP: {it['uploader']})")
    if len(items) > len(show):
        print(f"... 共 {len(items)} 条,更多请加 -p 2 翻页")

    if args.download:
        if args.download == ["all"]:
            idx = list(range(1, len(show) + 1))
        else:
            idx = []
            for x in args.download:
                if not x.isdigit() or not (1 <= int(x) <= len(show)):
                    print(f"[跳过] 无效序号: {x}")
                    continue
                idx.append(int(x))
        download_torrents(show, idx, args.out)


if __name__ == "__main__":
    main()
