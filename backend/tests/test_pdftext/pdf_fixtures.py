"""手工构造的最小文本型 PDF fixture（pypdf 可解析、可提取文本）。"""

from __future__ import annotations

# 内容流字面量里若直接出现会被解释为语法字符，跳过不分配给任何字符
_RESERVED_BYTE_CODES = {0x00, 0x28, 0x29, 0x5C}  # NUL, '(', ')', '\\'


def _build_tounicode_cmap(codes: dict[str, int]) -> bytes:
    """构造最小 /ToUnicode CMap：把内容流里的自定义单字节占位码映射回真实字符。

    简单字体（非内嵌 CID 字体）的 /Encoding /Differences 里 uniXXXX 命名 pypdf 并不解析
    （其 `_parse_encoding` 只查 Adobe Glyph List 固定表），但 /ToUnicode CMap 的 bfchar
    条目会被显式解析（`_parse_to_unicode`），因此走 ToUnicode 路径而非 Differences 才能让
    pypdf 正确提取任意 Unicode 文本（含中文）。
    """
    bfchar_lines = "\n".join(f"<{code:02X}> <{ord(ch):04X}>" for ch, code in codes.items())
    cmap = (
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\nbegincmap\n"
        "1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
        f"{max(len(codes), 1)} beginbfchar\n{bfchar_lines}\nendbfchar\n"
        "endcmap\nend\nend"
    )
    return cmap.encode("ascii")


def make_text_pdf(page_texts: list[str]) -> bytes:
    """生成 len(page_texts) 页的简单 PDF；空字符串页 = 无文本页（模拟扫描页）。

    页面文本支持任意 Unicode（含中文）：每个出现的字符分配一个 1 字节占位码
    （内容流字面量落在 latin-1 范围内，构造过程零转义），再用 /ToUnicode CMap
    把占位码映射回真实字符，供 pypdf 的文本提取按 CMap 还原。
    """
    n = len(page_texts)
    chars = sorted(set("".join(page_texts)))
    codes: dict[str, int] = {}
    code = 1
    for ch in chars:
        while code in _RESERVED_BYTE_CODES or code > 255:
            code += 1
        codes[ch] = code
        code += 1
    tounicode_cmap = _build_tounicode_cmap(codes)

    # 对象编号：1=Catalog 2=Pages 3=Font，随后每页 (Page, Contents) 各占一号，末尾是 ToUnicode 流
    tounicode_obj_num = 3 + 2 * n + 1

    objs: list[str | tuple[int, bytes]] = []
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs.append("<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>")
    objs.append(
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        f"/ToUnicode {tounicode_obj_num} 0 R >>"
    )
    for i, text in enumerate(page_texts):
        content = bytes(codes[ch] for ch in text) if text else b""
        objs.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {5 + 2 * i} 0 R >>"
        )
        objs.append((len(content), content))

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0] * (tounicode_obj_num + 1)
    for idx, body in enumerate(objs, start=1):
        offsets[idx] = len(out)
        if isinstance(body, tuple):
            length, content = body
            stream = b"BT /F1 12 Tf 72 720 Td (" + content + b") Tj ET" if content else b""
            out += f"{idx} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
            out += stream
            out += b"\nendstream\nendobj\n"
        else:
            out += f"{idx} 0 obj\n{body}\nendobj\n".encode("latin-1")
    offsets[tounicode_obj_num] = len(out)
    out += f"{tounicode_obj_num} 0 obj\n<< /Length {len(tounicode_cmap)} >>\nstream\n".encode(
        "latin-1"
    )
    out += tounicode_cmap
    out += b"\nendstream\nendobj\n"

    xref_pos = len(out)
    out += f"xref\n0 {tounicode_obj_num + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for idx in range(1, tounicode_obj_num + 1):
        out += f"{offsets[idx]:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {tounicode_obj_num + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode("latin-1")
    return bytes(out)


def make_outline_pdf(
    page_texts: list[str],
    outline: list[tuple[str, int, list[tuple[str, int]]]],
) -> bytes:
    """在 make_text_pdf 基础上用 pypdf 写入内置 outline（支持两级）。

    outline: [(title, page_1based, [(child_title, child_page_1based), ...]), ...]
    """
    import io

    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(make_text_pdf(page_texts)))
    writer = pypdf.PdfWriter()
    writer.append(reader)
    for title, page, children in outline:
        parent = writer.add_outline_item(title, page - 1)
        for child_title, child_page in children:
            writer.add_outline_item(child_title, child_page - 1, parent=parent)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
