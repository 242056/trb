import io
import zipfile

from PIL import Image

from explainlaw.extraction.tiff_zip import tiff_zip_to_pdf


def _zip_with_pages(n: int = 2) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(n):
            img = Image.new("RGB", (800, 1000), color=(240, 240, 240))
            img_buf = io.BytesIO()
            img.save(img_buf, format="TIFF")
            zf.writestr(f"page_{i+1:03d}.tif", img_buf.getvalue())
    return buf.getvalue()


def test_tiff_zip_to_pdf_builds_pdf():
    pdf = tiff_zip_to_pdf(_zip_with_pages(2))
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 500


def test_tiff_zip_empty_raises():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "no images")
    try:
        tiff_zip_to_pdf(buf.getvalue())
        assert False, "expected ValueError"
    except ValueError:
        pass
