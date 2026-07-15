import os
from app.services.parsers.base import BaseParser, ParsingResult, DocumentParsingError

class TXTParser(BaseParser):
    def parse(self, file_path: str) -> ParsingResult:
        if not os.path.exists(file_path):
            raise DocumentParsingError("File not found")
            
        if os.path.getsize(file_path) == 0:
            raise DocumentParsingError("Empty document")
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError as e:
            raise DocumentParsingError("Unsupported encoding: File is not valid UTF-8", str(e))
        except Exception as e:
            raise DocumentParsingError(f"Error reading TXT file: {str(e)}")
            
        if not text.strip():
            raise DocumentParsingError("Empty document")
            
        return ParsingResult(text=text, page_count=None, char_count=len(text))
