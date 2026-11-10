"""Генератор нативных .docx документов на стандартной библиотеке Python (без сторонних pip-пакетов).
Формирует полноценный валидный OpenXML Word (.docx) архив.
"""
import io
import html
import zipfile
from pathlib import Path
from typing import List, Tuple

CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>
"""

RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

DOCUMENT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
"""

STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>
        <w:sz w:val="22"/>
        <w:szCs w:val="22"/>
        <w:lang w:val="ru-RU"/>
      </w:rPr>
    </w:rPrDefault>
  </w:docDefaults>
</w:styles>
"""

class DocxBuilder:
    def __init__(self, title: str):
        self.title = title
        self.paragraphs = []

    def add_title(self, text: str):
        self.paragraphs.append(f"""
        <w:p>
          <w:pPr>
            <w:pStyle w:val="Title"/>
            <w:jc w:val="center"/>
            <w:spacing w:before="240" w:after="240"/>
          </w:pPr>
          <w:r>
            <w:rPr>
              <w:b/>
              <w:color w:val="003366"/>
              <w:sz w:val="36"/>
              <w:szCs w:val="36"/>
            </w:rPr>
            <w:t>{html.escape(text)}</w:t>
          </w:r>
        </w:p>
        """)

    def add_heading_1(self, text: str):
        self.paragraphs.append(f"""
        <w:p>
          <w:pPr>
            <w:spacing w:before="360" w:after="120"/>
          </w:pPr>
          <w:r>
            <w:rPr>
              <w:b/>
              <w:color w:val="003366"/>
              <w:sz w:val="28"/>
              <w:szCs w:val="28"/>
            </w:rPr>
            <w:t>{html.escape(text)}</w:t>
          </w:r>
        </w:p>
        """)

    def add_heading_2(self, text: str):
        self.paragraphs.append(f"""
        <w:p>
          <w:pPr>
            <w:spacing w:before="240" w:after="80"/>
          </w:pPr>
          <w:r>
            <w:rPr>
              <w:b/>
              <w:color w:val="006699"/>
              <w:sz w:val="24"/>
              <w:szCs w:val="24"/>
            </w:rPr>
            <w:t>{html.escape(text)}</w:t>
          </w:r>
        </w:p>
        """)

    def add_paragraph(self, text: str, bold: bool = False, italic: bool = False, color: str = None):
        rpr = []
        if bold:
            rpr.append("<w:b/>")
        if italic:
            rpr.append("<w:i/>")
        if color:
            rpr.append(f'<w:color w:val="{color}"/>')
        rpr_str = "".join(rpr)

        self.paragraphs.append(f"""
        <w:p>
          <w:pPr>
            <w:spacing w:after="120" w:line="276" w:lineRule="auto"/>
          </w:pPr>
          <w:r>
            <w:rPr>{rpr_str}</w:rPr>
            <w:t xml:space="preserve">{html.escape(text)}</w:t>
          </w:r>
        </w:p>
        """)

    def add_bullet(self, text: str, bold_prefix: str = ""):
        runs = []
        if bold_prefix:
            runs.append(f"<w:r><w:rPr><w:b/></w:rPr><w:t xml:space=\"preserve\">{html.escape(bold_prefix)} </w:t></w:r>")
        runs.append(f"<w:r><w:t xml:space=\"preserve\">{html.escape(text)}</w:t></w:r>")
        runs_str = "".join(runs)

        self.paragraphs.append(f"""
        <w:p>
          <w:pPr>
            <w:ind w:left="360" w:hanging="240"/>
            <w:spacing w:after="80"/>
          </w:pPr>
          <w:r><w:t xml:space="preserve">• </w:t></w:r>
          {runs_str}
        </w:p>
        """)

    def add_table(self, headers: List[str], rows: List[List[str]]):
        tbl_xml = ['<w:tbl>',
                   '<w:tblPr>',
                   '  <w:tblW w:w="0" w:type="auto"/>',
                   '  <w:tblBorders>',
                   '    <w:top w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
                   '    <w:bottom w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
                   '    <w:insideH w:val="single" w:sz="4" w:space="0" w:color="E0E0E0"/>',
                   '    <w:insideV w:val="none"/>',
                   '  </w:tblBorders>',
                   '</w:tblPr>']
        
        # Header Row
        tbl_xml.append('<w:tr><w:trPr><w:tblHeader/></w:trPr>')
        for h in headers:
            tbl_xml.append(f"""
            <w:tc>
              <w:tcPr>
                <w:shd w:val="clear" w:color="auto" w:fill="003366"/>
                <w:tcMar><w:top w:w="120"/><w:bottom w:w="120"/><w:left w:w="140"/><w:right w:w="140"/></w:tcMar>
              </w:tcPr>
              <w:p><w:r><w:rPr><w:b/><w:color w:val="FFFFFF"/></w:rPr><w:t>{html.escape(h)}</w:t></w:r></w:p>
            </w:tc>
            """)
        tbl_xml.append('</w:tr>')

        # Data Rows
        for r_idx, row in enumerate(rows):
            fill = "F9F9F9" if r_idx % 2 == 1 else "FFFFFF"
            tbl_xml.append('<w:tr>')
            for cell in row:
                tbl_xml.append(f"""
                <w:tc>
                  <w:tcPr>
                    <w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>
                    <w:tcMar><w:top w:w="100"/><w:bottom w:w="100"/><w:left w:w="140"/><w:right w:w="140"/></w:tcMar>
                  </w:tcPr>
                  <w:p><w:r><w:t>{html.escape(str(cell))}</w:t></w:r></w:p>
                </w:tc>
                """)
            tbl_xml.append('</w:tr>')

        tbl_xml.append('</w:tbl>')
        tbl_xml.append('<w:p><w:pPr><w:spacing w:after="180"/></w:pPr></w:p>')
        self.paragraphs.append("".join(tbl_xml))

    def save(self, filepath: Path):
        doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {"".join(self.paragraphs)}
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""
        with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
            z.writestr("_rels/.rels", RELS_XML)
            z.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS_XML)
            z.writestr("word/document.xml", doc_xml)
            z.writestr("word/styles.xml", STYLES_XML)
