from typing import Optional

class DocumentParsingError(Exception):
    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message)
        self.detail = detail

class ParsingResult:
    def __init__(self, text: str, page_count: Optional[int] = None, char_count: int = 0):
        self.text = text
        self.page_count = page_count
        self.char_count = char_count

class BaseParser:
    def parse(self, file_path: str) -> ParsingResult:
        raise NotImplementedError("Subclasses must implement parse()")
