import os
import re
import time
import logging
from typing import Tuple
from app.services.parsers.base import ParsingResult, DocumentParsingError
from app.services.parsers.factory import ParserFactory

logger = logging.getLogger("app.services.parser_service")

def normalize_text(text: str) -> str:
    if not text:
        return ""
        
    # 1. Remove invalid control characters (except tab \x09, newline \x0a, carriage return \x0d)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    
    # 2. Replace multiple consecutive spaces with a single space (excluding newlines)
    text = re.sub(r'[^\S\r\n]+', ' ', text)
    
    # 3. Limit consecutive blank lines to a maximum of two newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Strip leading/trailing whitespace on each line
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    
    # After stripping, re-clean blank lines sequence
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def detect_language_and_confidence(text: str) -> Tuple[str, float]:
    if not text:
        return "English", 1.0
        
    # Remove whitespace, digits, punctuation, and underscores to analyze pure letters
    letters = re.sub(r'[\s\d\W_]', '', text)
    if not letters:
        return "English", 1.0
        
    # Count Arabic characters in block \u0600-\u06FF
    arabic_chars = len(re.findall(r'[\u0600-\u06FF]', letters))
    # Count Latin/English characters
    english_chars = len(re.findall(r'[a-zA-Z]', letters))
    
    total = arabic_chars + english_chars
    if total == 0:
        return "English", 1.0
        
    arabic_ratio = arabic_chars / total
    english_ratio = english_chars / total
    
    if arabic_ratio > 0.8:
        return "Arabic", float(round(arabic_ratio, 4))
    elif english_ratio > 0.8:
        return "English", float(round(english_ratio, 4))
    else:
        # Mixed confidence represents how close they are to 50-50 (skew is low)
        confidence = 1.0 - abs(arabic_ratio - english_ratio)
        return "Mixed", float(round(confidence, 4))

class ParserService:
    def parse_document(self, file_path: str) -> ParsingResult:
        parser = ParserFactory.get_parser(file_path)
        return parser.parse(file_path)
