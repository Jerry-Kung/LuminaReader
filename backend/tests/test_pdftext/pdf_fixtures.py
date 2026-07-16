"""手工构造的最小文本型 PDF fixture（pypdf 可解析、可提取文本）。"""

from __future__ import annotations


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_text_pdf(page_texts: list[str]) -> bytes:
    """生成 len(page_texts) 页的简单 PDF；空字符串页 = 无文本页（模拟扫描页）。"""
    n = len(page_texts)
    objs: list[str] = []
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs.append("<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, text in enumerate(page_texts):
        content = (
            f"BT /F1 12 Tf 72 720 Td ({_escape(text)}) Tj ET" if text else ""
        )
        objs.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {5 + 2 * i} 0 R >>"
        )
        objs.append(
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0] * (len(objs) + 1)
    for idx, body in enumerate(objs, start=1):
        offsets[idx] = len(out)
        out += f"{idx} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for idx in range(1, len(objs) + 1):
        out += f"{offsets[idx]:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode("latin-1")
    return bytes(out)
