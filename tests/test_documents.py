"""Tests for the document generation module."""

from __future__ import annotations

from pathlib import Path

import pytest

from koda2.modules.documents.service import DocumentService


class TestDocumentService:
    """Tests for document generation."""

    @pytest.fixture
    def doc_service(self, tmp_path: Path) -> DocumentService:
        """Create a DocumentService with a temp template directory."""
        return DocumentService(template_dir=str(tmp_path / "templates"))

    def test_generate_docx(self, doc_service: DocumentService, tmp_path: Path) -> None:
        """DOCX generation creates a valid file."""
        output = str(tmp_path / "test.docx")
        content = [
            {"type": "heading", "data": "Chapter 1", "level": 1},
            {"type": "paragraph", "data": "This is a test paragraph."},
            {"type": "table", "data": [["Name", "Age"], ["Alice", "30"], ["Bob", "25"]]},
        ]
        result = doc_service.generate_docx("Test Document", content, output)
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0

    def test_generate_xlsx(self, doc_service: DocumentService, tmp_path: Path) -> None:
        """XLSX generation creates a valid file."""
        output = str(tmp_path / "test.xlsx")
        sheets = {
            "Sheet1": [["Name", "Score"], ["Alice", 95], ["Bob", 87]],
            "Sheet2": [["Item", "Price"], ["Widget", 9.99]],
        }
        result = doc_service.generate_xlsx("Test Workbook", sheets, output)
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0

    def test_generate_pdf(self, doc_service: DocumentService, tmp_path: Path) -> None:
        """PDF generation creates a valid file."""
        output = str(tmp_path / "test.pdf")
        content = [
            {"type": "heading", "data": "Section 1", "level": 1},
            {"type": "paragraph", "data": "PDF content here."},
            {"type": "table", "data": [["Col A", "Col B"], ["1", "2"]]},
        ]
        result = doc_service.generate_pdf("Test PDF", content, output)
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0

    def test_render_string_template(self, doc_service: DocumentService) -> None:
        """Jinja2 string template rendering works."""
        result = doc_service.render_string_template(
            "Hello {{ name }}, you have {{ count }} items.",
            {"name": "Ronald", "count": 5},
        )
        assert result == "Hello Ronald, you have 5 items."

    def test_scaffold_python_project(self, doc_service: DocumentService, tmp_path: Path) -> None:
        """Python project scaffolding creates expected files."""
        result = doc_service.scaffold_project(
            "myproject", "python", str(tmp_path),
        )
        base = Path(result)
        assert base.exists()
        assert (base / "pyproject.toml").exists()
        assert (base / "myproject" / "__init__.py").exists()
        assert (base / "myproject" / "main.py").exists()
        assert (base / "tests" / "test_main.py").exists()
        assert (base / "README.md").exists()

    def test_scaffold_fastapi_project(self, doc_service: DocumentService, tmp_path: Path) -> None:
        """FastAPI project scaffolding creates expected files."""
        result = doc_service.scaffold_project(
            "myapi", "fastapi", str(tmp_path),
        )
        base = Path(result)
        assert (base / "app" / "main.py").exists()
        assert (base / "Dockerfile").exists()

    def test_generate_docx_creates_parent_dirs(self, doc_service: DocumentService, tmp_path: Path) -> None:
        """Document generation creates parent directories if missing."""
        output = str(tmp_path / "deep" / "nested" / "test.docx")
        result = doc_service.generate_docx("Test", [], output)
        assert Path(result).exists()
