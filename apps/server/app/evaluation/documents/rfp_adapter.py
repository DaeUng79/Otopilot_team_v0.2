"""Read fixed document snapshots directly, without a second document web server."""
import json
import re
from pathlib import Path
from urllib.parse import quote

from .envelope import ApiError, not_found, upstream_unavailable
from app.documents.rfp_toc import load_toc
from .settings import API_PREFIX


class DocumentReader:
    def __init__(self, conn, project_id, document_id, parse_revision, *, title, label):
        self.conn, self.project_id = conn, project_id
        self.document_id, self.parse_revision = document_id, parse_revision
        self.title, self.label = title, label

    def _document(self):
        row = self.conn.execute(
            "SELECT d.document_id, d.filename, d.source_sha256, s.revision "
            "FROM documents d JOIN parse_snapshots s ON s.document_id=d.document_id "
            "WHERE d.document_id=? AND s.revision=?", (self.document_id, self.parse_revision)).fetchone()
        if row is None:
            raise not_found("평가에 연결된 문서 버전이 없습니다. 담당자가 문서 연결을 확인해야 합니다.")
        return row

    def overview(self):
        doc = self._document()
        pages = self.conn.execute(
            "SELECT physical_page_number AS n, page_number AS label FROM pages "
            "WHERE document_id=? AND revision=? ORDER BY physical_page_number",
            (self.document_id, self.parse_revision)).fetchall()
        toc = []
        # Derive navigation only from actual headings with physical page references.
        for row in self.conn.execute(
            "SELECT text, physical_page_numbers_json FROM blocks WHERE document_id=? AND revision=? "
            "AND type='paragraph' AND parent_block_id IS NULL ORDER BY order_index",
            (self.document_id, self.parse_revision)):
            text = (row['text'] or '').strip()
            numbers = json.loads(row['physical_page_numbers_json'])
            if numbers and len(text) <= 80 and re.match(r'^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]+|\d+|[가-힣])\s*[.．]\s+\S', text):
                toc.append({'t': text, 'lv': 1, 'page': numbers[0], 'seen': True, 'printed': None})
        has_source = self.conn.execute("SELECT 1 FROM source_files WHERE sha256=?", (doc['source_sha256'],)).fetchone() is not None
        return {'project': {'id': self.project_id}, 'document': {
            'id': self.document_id, 'parse_revision': self.parse_revision, 'filename': doc['filename'],
            'title': self.title, 'page_count': len(pages), 'has_source': has_source,
            'source_version': doc['source_sha256']}, 'pages': [dict(p) for p in pages], 'toc': toc}

    def page(self, number):
        self._document()
        page = self.conn.execute(
            "SELECT page_number FROM pages WHERE document_id=? AND revision=? AND physical_page_number=?",
            (self.document_id, self.parse_revision, number)).fetchone()
        if page is None:
            raise not_found("없는 쪽입니다.")
        blocks = []
        for row in self.conn.execute(
            "SELECT * FROM blocks WHERE document_id=? AND revision=? AND parent_block_id IS NULL "
            "AND parent_cell_id IS NULL AND json_extract(physical_page_numbers_json, '$[0]')=? ORDER BY order_index",
            (self.document_id, self.parse_revision, number)):
            span = json.loads(row['physical_page_numbers_json'])
            item = {'id': row['block_id'], 'type': row['type'], 'continues': len(span) > 1}
            if row['type'] == 'paragraph':
                if not (row['text'] or '').strip():
                    continue
                item['text'] = row['text']
            elif row['type'] == 'table':
                grouped = {}
                for cell in self.conn.execute(
                    "SELECT * FROM table_cells WHERE document_id=? AND revision=? AND block_id=? ORDER BY row_index,col_index",
                    (self.document_id, self.parse_revision, row['block_id'])):
                    grouped.setdefault(cell['row_index'], []).append({'text': cell['text'], 'rs': cell['row_span'], 'cs': cell['col_span']})
                item['rows'] = list(grouped.values())
            elif row['type'] == 'image':
                asset = (json.loads(row['block_json']).get('image') or {}).get('asset_id')
                if not asset:
                    continue
                sha = self.conn.execute(
                    "SELECT sha256 FROM snapshot_assets WHERE document_id=? AND revision=? AND asset_id=?",
                    (self.document_id, self.parse_revision, asset)).fetchone()
                if sha is None:
                    continue
                item['src'] = f"{API_PREFIX}/projects/{quote(self.project_id, safe='')}/documents/assets/{sha[0]}"
            else:
                continue
            blocks.append(item)
        return {'n': number, 'label': page['page_number'], 'blocks': blocks}

    def source(self):
        doc = self._document()
        row = self.conn.execute("SELECT filename,data FROM source_files WHERE sha256=?", (doc['source_sha256'],)).fetchone()
        if row is None:
            raise not_found("원본 파일이 없습니다.")
        return row['filename'], bytes(row['data'])

    def asset(self, sha256):
        self._document()
        row = self.conn.execute(
            "SELECT a.data,s.metadata_json FROM snapshot_assets s JOIN assets a ON a.sha256=s.sha256 "
            "WHERE s.document_id=? AND s.revision=? AND s.sha256=?",
            (self.document_id, self.parse_revision, sha256)).fetchone()
        if row is None:
            raise not_found("이 문서의 그림이 아닙니다.")
        data = bytes(row['data'])
        # Do not serve active HTML/SVG supplied by an uploaded document.
        mime = ('image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else
                'image/jpeg' if data.startswith(b'\xff\xd8\xff') else
                'image/gif' if data.startswith((b'GIF87a', b'GIF89a')) else
                'image/webp' if data[:4] == b'RIFF' and data[8:12] == b'WEBP' else None)
        if not mime:
            raise not_found("지원하지 않는 그림 형식입니다.")
        return data, mime


    def page_svg(self, number: int) -> bytes:
        doc = self._document()
        if self.conn.execute("SELECT 1 FROM pages WHERE document_id = ? AND revision = ? AND physical_page_number = ?",
                             (self.document_id, self.parse_revision, number)).fetchone() is None:
            raise not_found("없는 쪽이에요.")
        source = self.conn.execute("SELECT data FROM source_files WHERE sha256 = ?", (doc["source_sha256"],)).fetchone()
        if source is None:
            raise not_found("원본 파일을 찾을 수 없어요.")
        suffix = Path(doc["filename"]).suffix.lower()
        if suffix not in {".hwpx", ".hwp"}:
            raise ApiError("VALIDATION_FAILED", "이 형식은 원본 쪽 렌더링을 지원하지 않아요.", 422)
        try:
            from pyhwpxlib.rhwp_bridge import RhwpEngine  # type: ignore
        except ImportError as exc:
            raise upstream_unavailable("원본 쪽 SVG 렌더러를 사용할 수 없어요.") from exc
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ev04_render_") as directory:
            path = Path(directory) / ("source" + suffix)
            path.write_bytes(bytes(source["data"]))
            renderer = RhwpEngine().load(str(path))
            try:
                if number > renderer.page_count:
                    raise ApiError("VALIDATION_FAILED", "파싱된 쪽번호와 원본 쪽 수가 달라요.", 422)
                svg = renderer.render_page_svg(number - 1)
            finally:
                renderer.close()
        return svg.encode("utf-8")

    def page_png(self, number: int) -> bytes:
        """Render one PDF source page for the shared document reader."""
        doc = self._document()
        if Path(doc["filename"]).suffix.lower() != ".pdf":
            raise ApiError("VALIDATION_FAILED", "PDF 문서가 아니에요.", 422)
        if self.conn.execute("SELECT 1 FROM pages WHERE document_id=? AND revision=? AND physical_page_number=?",
                             (self.document_id, self.parse_revision, number)).fetchone() is None:
            raise not_found("없는 쪽이에요.")
        source = self.conn.execute("SELECT data FROM source_files WHERE sha256=?",
                                   (doc["source_sha256"],)).fetchone()
        if source is None:
            raise not_found("원본 파일을 찾을 수 없어요.")
        try:
            import pymupdf
        except ImportError as exc:
            raise upstream_unavailable("PDF 쪽 렌더러를 사용할 수 없어요.") from exc
        with pymupdf.open(stream=bytes(source["data"]), filetype="pdf") as pdf:
            if number > len(pdf):
                raise ApiError("VALIDATION_FAILED", "파싱된 쪽번호와 원본 쪽 수가 달라요.", 422)
            page = pdf.load_page(number - 1)
            scale = min(2.0, 2000 / max(page.rect.width, page.rect.height))
            return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")


class RfpReader(DocumentReader):
    def __init__(self, conn, project_id, binding):
        if not binding:
            raise not_found("평가 사업에 연결된 제안요청서가 없습니다.")
        super().__init__(conn, project_id, binding['document_id'], binding['parse_revision'],
                         title='제안요청서', label='제안요청서')

    def overview(self):
        data = super().overview()
        data['toc'] = load_toc(self.conn, self.document_id,
                               self.parse_revision, data['pages'])
        return data
