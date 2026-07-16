"""V1.2.2 第 2 层：启发式章节识别（置信门槛"宁缺毋滥"）。"""

from lumina.toc.heuristic import recognize_from_pages


def _pages_for(titles_at: dict[int, str], total: int = 40) -> list[tuple[int, str]]:
    """构造 total 页文本：指定页首行为章节标题，其余为正文。"""
    pages = []
    for p in range(1, total + 1):
        title = titles_at.get(p)
        body = f"ordinary body text of page {p} " * 5
        pages.append((p, f"{title}\n{body}" if title else body))
    return pages


def test_numbered_chinese_chapters_recognized():
    pages = _pages_for({1: "第一章 引言", 9: "第二章 方法", 20: "第三章 结论"})
    items = recognize_from_pages(pages)
    assert [(i.title, i.page, i.depth) for i in items] == [
        ("第一章 引言", 1, 0), ("第二章 方法", 9, 0), ("第三章 结论", 20, 0),
    ]


def test_english_chapters_and_numbered_sections():
    pages = _pages_for({
        1: "Chapter 1 Introduction", 5: "1.1 Background",
        12: "Chapter 2 Methods", 25: "Chapter 3 Results",
    })
    items = recognize_from_pages(pages)
    tops = [i for i in items if i.depth == 0]
    subs = [i for i in items if i.depth == 1]
    assert [t.page for t in tops] == [1, 12, 25]
    assert [(s.title, s.page) for s in subs] == [("1.1 Background", 5)]


def test_too_few_chapters_fails_gate():
    pages = _pages_for({1: "第一章 引言", 20: "第二章 结论"})
    assert recognize_from_pages(pages) == []


def test_non_increasing_pages_fails_gate():
    # 同页出现两个顶层章节起点 → 非严格递增 → 整体不落库
    pages = _pages_for({1: "第一章 引言", 9: "第二章 方法"})
    pages[8] = (9, "第二章 方法\n第三章 结论\nbody")
    assert recognize_from_pages(pages) == []


def test_toc_listing_page_is_excluded():
    # 目录页本身罗列全部章节标题（单页 ≥4 个顶层命中）应被剔除，不影响正文识别
    toc_page = "目录\n第一章 引言\n第二章 方法\n第三章 结论\n第四章 展望"
    pages = _pages_for({3: "第一章 引言", 12: "第二章 方法", 22: "第三章 结论", 33: "第四章 展望"})
    pages[1] = (2, toc_page)
    items = recognize_from_pages(pages)
    assert [i.page for i in items if i.depth == 0] == [3, 12, 22, 33]


def test_duplicate_titles_fail_gate():
    pages = _pages_for({1: "第一章 复读", 9: "第一章 复读", 20: "第一章 复读", 30: "第一章 复读"})
    # 页码递增但标题大面积重复 → 门槛失败
    assert recognize_from_pages(pages) == []


def test_empty_or_scanned_pages_return_empty():
    assert recognize_from_pages([]) == []
    assert recognize_from_pages([(1, ""), (2, "")]) == []
