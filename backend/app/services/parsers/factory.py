import os
from app.services.parsers.base import BaseParser, DocumentParsingError
from app.services.parsers.pdf import PDFParser
from app.services.parsers.docx import DOCXParser
from app.services.parsers.txt import TXTParser
from app.services.parsers.markdown import MarkdownParser

class ParserFactory:
    @staticmethod
    def get_parser(file_path: str) -> BaseParser:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            return PDFParser()
        elif ext == ".docx":
            return DOCXParser()
        elif ext in (".txt", ".text"):
            return TXTParser()
        elif ext in (".md", ".markdown"):
            return MarkdownParser()
        else:
            raise DocumentParsingError(f"Unsupported file format: {ext}")
