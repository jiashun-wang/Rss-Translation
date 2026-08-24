# -*- coding: utf-8 -*-
import configparser
import datetime
import hashlib
import os
import time
from urllib import parse
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from jinja2 import Template
from mtranslate import translate

# =========================================================
# 全局统计（运行结束时汇总输出）
# =========================================================
stats = {
    "new_total": 0,       # 本次检测到有更新（md5 变化 / 首次无 md5）的条数
    "new_ok": 0,          # 上述"需要更新"中成功生成/更新的条数
    "new_fail": 0,        # 上述"需要更新"中失败的条数
    "exist_updated": 0,   # 已存在 RSS、本次成功更新的条数
    "exist_latest": 0,    # 已存在 RSS、内容已经是最新的条数
    "exist_fail": 0,      # 已存在 RSS、处理失败的条数
}

old_opml_entries = []   # (标题, 原始 url)
new_opml_entries = []   # (标题, 新 rss 路径)


def get_md5_value(src):
    if isinstance(src, bytes):
        src = src.decode("utf-8", errors="ignore")
    _m = hashlib.sha256()
    _m.update(src.encode(encoding="utf-8"))
    return _m.hexdigest()


def getTime(e):
    try:
        struct_time = e.published_parsed
    except AttributeError:
        struct_time = time.localtime()
    if struct_time is None:
        struct_time = time.localtime()
    return datetime.datetime(*struct_time[:6])


class BingTran:
    def __init__(self, url, source="auto", target="zh-CN"):
        self.url = url
        self.service = source
        self.target = target
        self.d = feedparser.parse(url)

    def tr(self, content):
        return translate(content, to_language=self.target, from_language=self.service)

    def get_newcontent(self, max_item=10):
        item_set = set()
        item_list = []
        entries = getattr(self.d, "entries", None) or []
        for entry in entries:
            try:
                title = self.tr(entry.title)
            except Exception:
                title = ""
            parsed_link = urlparse(entry.link)
            if not all([parsed_link.scheme, parsed_link.netloc]):
                continue
            link = entry.link
            description = ""
            try:
                description = self.tr(entry.summary)
            except Exception:
                try:
                    description = self.tr(entry.content[0].value)
                except Exception:
                    description = ""
            guid = link
            pubDate = getTime(entry)
            one = {
                "title": title,
                "link": link,
                "description": description,
                "guid": guid,
                "pubDate": pubDate,
            }
            if guid not in item_set:
                item_set.add(guid)
                item_list.append(one)
            if len(item_list) >= max_item:
                break
        sorted_list = sorted(item_list, key=lambda x: x["pubDate"], reverse=True)
        feed = self.d.feed
        try:
            rss_description = feed.subtitle
        except AttributeError:
            rss_description = ""
        newfeed = {
            "title": getattr(feed, "title", ""),
            "link": getattr(feed, "link", ""),
            "description": rss_description,
            "lastBuildDate": getTime(feed),
            "items": sorted_list,
        }
        return newfeed


def update_readme(links):
    if os.path.isfile("README.md"):
        with open("README.md", "r", encoding="UTF-8") as f:
            list1 = f.readlines()
    else:
        list1 = []
    head = list1[:20]
    tail = head + links
    with open("README.md", "w+", encoding="UTF-8") as f:
        f.writelines(tail)


def write_opml():
    """生成 rss-old.opml（原始订阅源）和 rss-new.opml（新翻译源）到根目录。"""

    def xml_escape(s):
        return (str(s)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))

    def build(entries, title):
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<opml version="1.0">',
            "  <head>",
            "    <title>%s</title>" % xml_escape(title),
            "    <dateCreated>%s</dateCreated>"
            % datetime.datetime.now().strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "  </head>",
            "  <body>",
        ]
        for text, xml_url in entries:
            lines.append(
                '    <outline text="%s" type="rss" xmlUrl="%s"/>'
                % (xml_escape(text), xml_escape(xml_url))
            )
        lines.append("  </body>")
        lines.append("</opml>")
        return "\n".join(lines) + "\n"

    with open("rss-old.opml", "w", encoding="utf-8") as f:
        f.write(build(old_opml_entries, "原始 RSS 订阅源"))
    with open("rss-new.opml", "w", encoding="utf-8") as f:
        f.write(build(new_opml_entries, "翻译后 RSS 订阅源"))


def get_cfg(sec, name):
    return config.get(sec, name).strip('"')


def get_cfg_opt(sec, name):
    """读取可选字段；缺失或为空都返回空字符串，不抛错。"""
    try:
        val = config.get(sec, name)
    except (configparser.NoOptionError, configparser.NoSectionError):
        return ""
    val = val.strip('"').strip()
    return val if val else ""


def set_cfg(sec, name, value):
    config.set(sec, name, '"%s"' % value)


def get_cfg_tra(sec, config):
    cc = config.get(sec, "action").strip('"')
    target = ""
    source = ""
    if cc == "auto":
        source = "auto"
        target = "zh-CN"
    else:
        source, target = cc.split("->")
    return source, target


def tran(sec, max_item):
    # 读取配置；name/url 缺失则直接失败（标记为存在失败，因为未知新旧）
    try:
        xml_file = os.path.join(BASE, f'{get_cfg(sec, "name")}.xml')
        url = get_cfg(sec, "url")
    except Exception as e:
        print("Config error for %s: %s" % (sec, str(e)))
        stats["exist_fail"] += 1
        return

    # md5 可能为空/缺失 -> 视为新增
    old_md5 = get_cfg_opt(sec, "md5")

    try:
        source, target = get_cfg_tra(sec, config)
    except Exception as e:
        print("Action config error for %s: %s" % (sec, str(e)))
        stats["exist_fail"] += 1
        return

    global links, old_opml_entries, new_opml_entries
    old_opml_entries.append((sec, url))
    new_opml_entries.append((sec, parse.quote(xml_file)))
    links += [
        " - [%s](%s) | [源: %s](%s)\n"
        % (get_cfg(sec, "name"), parse.quote(xml_file), sec, url)
    ]

    # 判断 RSS 是否有更新
    try:
        r = requests.get(url, timeout=30)
        new_md5 = get_md5_value(r.text)
    except Exception as e:
        print("Fetch error for %s: %s" % (sec, str(e)))
        # 是否"已有"取决于文件是否存在
        if os.path.isfile(xml_file):
            stats["exist_fail"] += 1
        else:
            stats["new_fail"] += 1
            stats["new_total"] += 1  # 首次尝试（即使没抓到也算一次新增尝试）
        return

    file_exists = os.path.isfile(xml_file)

    # 判断新旧：
    #  - old_md5 为空（首次） => 一定是新增
    #  - old_md5 == new_md5 且文件已存在 => 已经是最新
    #  - 否则 => 有更新
    is_new = (old_md5 == "") or (old_md5 != new_md5 and not file_exists)

    if old_md5 == new_md5:
        # md5 未变
        if file_exists:
            print("No update needed for %s" % sec)
            stats["exist_latest"] += 1
            return
        # md5 未变但文件不存在 => 仍需生成，按新增处理
        is_new = True

    if is_new:
        stats["new_total"] += 1
        if not file_exists:
            # 真正意义的新增
            pass
        else:
            # 老文件已存在且 md5 变了 => 视为更新，但计入已有更新
            stats["exist_updated"] += 1

    print("Updating %s..." % sec)
    set_cfg(sec, "md5", new_md5)

    # 生成新内容
    try:
        feed = BingTran(url, source=source, target=target).get_newcontent(
            max_item=max_item
        )
    except Exception as e:
        print("Parse/translate error for %s: %s" % (sec, str(e)))
        if file_exists:
            stats["exist_fail"] += 1
        else:
            stats["new_fail"] += 1
        return

    rss_items = []
    for item in feed.get("items", []):
        title = item.get("title", "")
        link = item.get("link", "")
        description = item.get("description", "")
        guid = item.get("guid", "")
        pubDate = item.get("pubDate")
        try:
            soup = BeautifulSoup(description, "html.parser")
            description = soup.get_text()
        except Exception:
            description = str(description)
        description = (
            description.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )
        link = link.replace("&", "&amp;")
        guid = guid.replace("&", "&amp;")
        if not isinstance(pubDate, datetime.datetime):
            pubDate = datetime.datetime.now()
        rss_items.append(
            dict(
                title=title,
                link=link,
                description=description,
                guid=guid,
                pubDate=pubDate,
            )
        )

    rss_title = feed.get("title", "")
    rss_link = feed.get("link", "")
    rss_description = feed.get("description", "")
    rss_last_build_date = feed["lastBuildDate"].strftime("%a, %d %b %Y %H:%M:%S GMT")

    template = Template(
        """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{{ rss_title }}</title>
    <link>{{ rss_link }}</link>
    <description>{{ rss_description }}</description>
    <lastBuildDate>{{ rss_last_build_date }}</lastBuildDate>
    {% for item in rss_items -%}
    <item>
      <title>{{ item.title }}</title>
      <link>{{ item.link }}</link>
      <description><![CDATA[{{ item.description }}]]></description>
      <guid>{{ item.guid }}</guid>
      <pubDate>{{ item.pubDate.strftime('%a, %d %b %Y %H:%M:%S GMT') }}</pubDate>
    </item>
    {% endfor -%}
  </channel>
</rss>"""
    )

    rss = template.render(
        rss_title=rss_title,
        rss_link=rss_link,
        rss_description=rss_description,
        rss_last_build_date=rss_last_build_date,
        rss_items=rss_items,
    )

    try:
        os.makedirs(BASE, exist_ok=True)
    except Exception as e:
        print("Failed to create dir %s: %s" % (BASE, str(e)))
        if file_exists:
            stats["exist_fail"] += 1
        else:
            stats["new_fail"] += 1
        return

    if os.path.isfile(xml_file):
        try:
            with open(xml_file, "r", encoding="utf-8") as f:
                old_rss = f.read()
            if rss == old_rss:
                print("No change in RSS content for %s" % sec)
                stats["exist_latest"] += 1
                return
            else:
                os.remove(xml_file)
        except Exception as e:
            print("Delete error for %s: %s" % (sec, str(e)))
            if file_exists:
                stats["exist_fail"] += 1
            else:
                stats["new_fail"] += 1
            return

    try:
        with open(xml_file, "w", encoding="utf-8") as f:
            f.write(rss)
    except Exception as e:
        print("Write error for %s: %s" % (sec, str(e)))
        if file_exists:
            stats["exist_fail"] += 1
        else:
            stats["new_fail"] += 1
        return

    # 写入成功
    if file_exists:
        stats["exist_updated"] += 1
    else:
        stats["new_ok"] += 1

    set_cfg(sec, "md5", new_md5)


def main():
    global config, BASE, links, stats, old_opml_entries, new_opml_entries
    # 关键修复：禁用插值，避免 URL 中的 % 报错
    config = configparser.ConfigParser(interpolation=None)
    config.read("test.ini", encoding="utf-8")

    BASE = get_cfg("cfg", "base")
    try:
        os.makedirs(BASE, exist_ok=True)
    except Exception:
        pass

    links = []
    old_opml_entries = []
    new_opml_entries = []
    stats = {
        "new_total": 0,
        "new_ok": 0,
        "new_fail": 0,
        "exist_updated": 0,
        "exist_latest": 0,
        "exist_fail": 0,
    }

    secs = config.sections()
    for x in secs[1:]:
        try:
            max_item = int(get_cfg(x, "max"))
        except Exception as e:
            print("Bad max for %s: %s" % (x, str(e)))
            stats["exist_fail"] += 1
            continue
        try:
            tran(x, max_item)
        except Exception as e:
            print("Unhandled error for %s: %s" % (x, str(e)))
            stats["exist_fail"] += 1
            continue

    try:
        with open("test.ini", "w", encoding="utf-8") as configfile:
            config.write(configfile)
    except Exception as e:
        print("Failed to save config: %s" % str(e))

    # 顶部区块（前20行）之后：先加二级标题，再并列所有订阅源 + OPML 链接
    opml_links = [
        "## 订阅源列表\n",
        "",
        "- 原始 RSS：[rss-old.opml](rss-old.opml)\n",
        "- 翻译后 RSS：[rss-new.opml](rss-new.opml)\n",
    ]
    final_links = opml_links + links
    update_readme(final_links)
    write_opml()

    # ======= 运行结束统计汇总 =======
    print("\n" + "=" * 52)
    print("运行结束统计汇总")
    print("=" * 52)
    print(f"本次检测到有更新（需要处理）的总条数:      {stats['new_total']}")
    print(f"   - 其中成功的条数:                       {stats['new_ok']}")
    print(f"   - 其中失败的条数:                       {stats['new_fail']}")
    print("-" * 52)
    print(f"已存在 RSS 中，本次成功更新的条数:         {stats['exist_updated']}")
    print(f"已存在 RSS 中，已经是最新的条数:           {stats['exist_latest']}")
    print(f"已存在 RSS 中，处理失败的条数:             {stats['exist_fail']}")
    print("=" * 52)


if __name__ == "__main__":
    main()