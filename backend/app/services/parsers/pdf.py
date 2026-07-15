import os
# pyrefly: ignore [missing-import]
from pypdf import PdfReader
from app.services.parsers.base import BaseParser, ParsingResult, DocumentParsingError

class PDFParser(BaseParser):
    def parse(self, file_path: str) -> ParsingResult:
        if not os.path.exists(file_path):
            raise DocumentParsingError("File not found")
            
        if os.path.getsize(file_path) == 0:
            raise DocumentParsingError("Empty document")
            
        try:
            reader = PdfReader(file_path)
            page_count = len(reader.pages)
            
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception as e:
                    raise DocumentParsingError("PDF is encrypted and cannot be parsed", str(e))
                    
            text_parts = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
                    
            text = "\n".join(text_parts)
        except Exception as e:
            raise DocumentParsingError("Corrupted PDF: Failed to read page structure", str(e))
            
        if not text.strip():
            raise DocumentParsingError("Empty document")
            
        return ParsingResult(text=text, page_count=page_count, char_count=len(text))
