"""Tests for the OCR fallback path. Mocks pdf2image / pytesseract so CI doesn't need
the real binaries."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _bootstrap_wiki(tmp_path: Path, lang: str = "en") -> Path:
    """Copy lang templates into a fresh wiki dir."""
    from importlib.resources import files

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    template_dir = files("scinotes.templates") / lang
    for entry in template_dir.iterdir():
        if entry.name.endswith(".md"):
            (wiki / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
    return wiki


@pytest.fixture
def server(monkeypatch, tmp_path):
    wiki = _bootstrap_wiki(tmp_path, "en")
    monkeypatch.setenv("WIKI_PATH", str(wiki))
    monkeypatch.setenv("BOT_LANG", "en")
    monkeypatch.setenv("SCINOTES_JOURNAL_PATH", str(wiki / ".wiki_journal.jsonl"))
    for k in list(sys.modules):
        if k.startswith("scinotes.server"):
            del sys.modules[k]
    from scinotes import server as srv  # type: ignore

    return srv


def _make_blank_pdf(path: Path) -> None:
    """Write a 1-page PDF whose page has no extractable text (image-only-ish)."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)


def test_ocr_not_available_returns_friendly_hint(server, tmp_path, monkeypatch):
    """If neither pdf2image nor pytesseract is importable, OCR raises OCRNotAvailable
    and read_local_pdf surfaces the install hint to the user."""
    pdf = tmp_path / "scan.pdf"
    _make_blank_pdf(pdf)

    # Force ImportError when these modules are imported by the helper
    monkeypatch.setitem(sys.modules, "pdf2image", None)
    monkeypatch.setitem(sys.modules, "pytesseract", None)

    out = server.read_local_pdf(str(pdf))
    assert "OCR" in out
    assert "scinotes[ocr]" in out  # actionable install hint
    assert "tesseract" in out.lower()


def test_ocr_auto_fallback_when_pypdf_empty(server, tmp_path, monkeypatch):
    """When pypdf yields no text and OCR pipeline succeeds, read_local_pdf returns
    OCR text with a clear note."""
    pdf = tmp_path / "scan.pdf"
    _make_blank_pdf(pdf)

    # Stub pdf2image: returns one fake "image"
    fake_pdf2image = types.ModuleType("pdf2image")
    fake_image = MagicMock(name="PIL.Image")
    fake_pdf2image.convert_from_path = MagicMock(return_value=[fake_image])
    monkeypatch.setitem(sys.modules, "pdf2image", fake_pdf2image)

    # Stub pytesseract
    fake_pytesseract = types.ModuleType("pytesseract")
    fake_pytesseract.image_to_string = MagicMock(return_value="OCR-EXTRACTED-TEXT")

    class _TNF(Exception):
        pass

    class _TE(Exception):
        pass

    fake_pytesseract.TesseractNotFoundError = _TNF
    fake_pytesseract.TesseractError = _TE
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    out = server.read_local_pdf(str(pdf))
    assert "OCR-EXTRACTED-TEXT" in out
    assert "via OCR fallback" in out


def test_explicit_read_pdf_ocr(server, tmp_path, monkeypatch):
    """The explicit read_pdf_ocr tool returns OCR text directly without trying pypdf
    first, and threads the lang argument through."""
    pdf = tmp_path / "scan.pdf"
    _make_blank_pdf(pdf)

    fake_pdf2image = types.ModuleType("pdf2image")
    fake_image = MagicMock()
    fake_pdf2image.convert_from_path = MagicMock(return_value=[fake_image, fake_image])
    monkeypatch.setitem(sys.modules, "pdf2image", fake_pdf2image)

    fake_pytesseract = types.ModuleType("pytesseract")
    captured_lang: list[str] = []

    def _img_to_string(img, lang="eng"):
        captured_lang.append(lang)
        return f"page text in {lang}"

    fake_pytesseract.image_to_string = _img_to_string

    class _TNF(Exception):
        pass

    class _TE(Exception):
        pass

    fake_pytesseract.TesseractNotFoundError = _TNF
    fake_pytesseract.TesseractError = _TE
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    out = server.read_pdf_ocr(str(pdf), lang="chi_sim+eng")
    assert "page text in chi_sim+eng" in out
    assert captured_lang == ["chi_sim+eng", "chi_sim+eng"]  # one call per page


def test_pypdf_text_returned_when_present(server, tmp_path, monkeypatch):
    """If pypdf already gets adequate text, OCR is NOT invoked even if installed."""
    # Use a real born-digital PDF: pypdf supports adding text via PageObject
    # but it's complex; simpler approach is to mock pypdf to return enough text.
    pdf = tmp_path / "real.pdf"
    _make_blank_pdf(pdf)  # actual file existence still required by Path check

    # Patch pypdf so it returns substantial text
    fake_pypdf = types.ModuleType("pypdf")
    fake_page = MagicMock()
    fake_page.extract_text = MagicMock(
        return_value="lorem ipsum dolor sit amet. " * 20  # ~530 chars
    )
    fake_reader = MagicMock()
    fake_reader.pages = [fake_page]
    fake_pypdf.PdfReader = MagicMock(return_value=fake_reader)
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)

    # If OCR were called, this would fail because we're not stubbing pdf2image.
    # So if read_local_pdf works without OCR, it confirms pypdf text was sufficient.
    out = server.read_local_pdf(str(pdf))
    assert "lorem ipsum" in out
    assert "OCR" not in out
