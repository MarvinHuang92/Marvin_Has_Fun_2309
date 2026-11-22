# -*- coding: utf-8 -*-
"""把用户的需求 docx 全文导出来看。"""
import sys

from docx import Document

path = r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\dev_req\优化建议_20261122\人工对局可优化方向_20261122.docx"
doc = Document(path)

for i, p in enumerate(doc.paragraphs):
    t = p.text.strip()
    if not t:
        continue
    print("[%03d][%s] %s" % (i, p.style.name, t))

for ti, table in enumerate(doc.tables):
    print("\n=== 表格 %d ===" % ti)
    for row in table.rows:
        print(" | ".join(c.text.strip() for c in row.cells))
