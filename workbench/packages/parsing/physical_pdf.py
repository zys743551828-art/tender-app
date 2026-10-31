"""Shared conservative PDFium lane. It never declares complete visual coverage."""

from contextlib import closing

import pypdfium2 as pdfium

from packages.domain.runtime import DomainError, sha
from packages.parsing.pdfium_guard import LOCK

PARSER_DIGEST = sha(
    {"parser": "pypdfium2", "version": "5.14.0", "purpose": "physical_page_text_only"}
)
CONFIG_DIGEST = sha({"bbox": None, "ocr": False, "tables": False, "visual": False})


def extract(data, *, max_pages=1000):
    pages = []
    with LOCK:
        try:
            with closing(pdfium.PdfDocument(data)) as pdf:
                if len(pdf) > max_pages:
                    raise DomainError("PDF_PAGE_LIMIT", "PDF 页数超过本轮解析上限", 413)
                if len(pdf) < 1:
                    raise DomainError("PDF_PARSE_FAILED", "PDF 不含可读取的物理页", 422)
                for index in range(len(pdf)):
                    with closing(pdf[index]) as page:
                        width, height = page.get_size()
                        with closing(page.get_textpage()) as textpage:
                            text = textpage.get_text_bounded()
                        gaps = ["OCR_NOT_CONFIGURED"] if len(text.strip()) < 20 else []
                        pages.append(
                            {
                                "physical_page": index + 1,
                                "width": width,
                                "height": height,
                                "rotation": page.get_rotation(),
                                "text": text,
                                "quality": "partial",
                                "gaps": gaps,
                            }
                        )
        except DomainError:
            raise
        except Exception as error:
            raise DomainError("PDF_PARSE_FAILED", "原件无法读取，未发布解析结果", 422) from error
    return {
        "pages": pages,
        "coverage": "partial",
        "gaps": ["TEXT_ONLY_TABLES_VISUAL_AND_LAYOUT_UNVERIFIED"],
        "parser_digest": PARSER_DIGEST,
        "config_digest": CONFIG_DIGEST,
    }
