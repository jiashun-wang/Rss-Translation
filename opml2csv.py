
"""
将 OPML 文件(订阅列表)转换为 CSV 文件，方便人工维护。

用法:
    python opml2csv.py 你的文件.opml  输出.csv

默认输出文件名: 输入文件名 + .csv
"""

import csv
import sys
import xml.etree.ElementTree as ET

def opml_to_csv(opml_path, csv_path):
    # 解析 OPML (XML)
    tree = ET.parse(opml_path)
    root = tree.getroot()

    # OPML 结构通常是 body > outline (可能多层嵌套，代表文件夹/分类)
    rows = []
    
    def walk(outlines, category=""):
        for outline in outlines:
            # 每个 outline 可能是一个"标题/文件夹"或一个"订阅源"
            text = outline.get("text", "").strip()
            title = outline.get("title", "")
            xml_url = outline.get("xmlUrl", "")   # 真正需要的 RSS/Atom 订阅地址
            html_url = outline.get("htmlUrl", "") # 网站主页
            type_ = outline.get("type", "")

            children = list(outline)
            if children:
                # 有子节点 -> 这是一个分类/文件夹
                walk(children, text if not category else f"{category} > {text}")
            else:
                # 叶子节点 -> 一个具体的订阅源
                rows.append({
                    "分类": category,
                    "标题": title or text,
                    "RSS/Atom 订阅地址": xml_url,
                    "网站主页": html_url,
                    "类型": type_,
                    "状态": "",          # 留空，人工维护
                    "备注": "",          # 留空，人工维护
                })
    
    body = root.find("body")
    if body is not None:
        walk(list(body))

    # 写入 CSV
    fieldnames = ["分类", "标题", "RSS/Atom 订阅地址", "网站主页", "类型", "状态", "备注"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"完成! 共转换 {len(rows)} 条订阅，已保存到: {csv_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python opml2csv.py <输入.opml> [输出.csv]")
        sys.exit(1)
    opml_file = sys.argv[1]
    csv_file = sys.argv[2] if len(sys.argv) > 2 else opml_file.rsplit(".", 1)[0] + ".csv"
    opml_to_csv(opml_file, csv_file)