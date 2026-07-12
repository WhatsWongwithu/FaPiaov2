"""
本地发票识别引擎
- PDF电子发票：直接提取嵌入文字（100%准确）
- 图片发票：使用RapidOCR识别
数据完全本地处理，无需联网
"""

import os
import threading
import fitz  # PyMuPDF
import numpy as np
from rapidocr_onnxruntime import RapidOCR


class OCREngine:
    """发票识别引擎"""

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    @property
    def engine(self):
        if self._engine is None:
            self._engine = RapidOCR()
        return self._engine

    def _extract_pdf_text(self, pdf_path):
        """
        直接从PDF提取文字+坐标（电子发票100%准确）
        坐标缩放以匹配OCR的坐标范围（200DPI）
        返回: [(text, center_x, center_y), ...]
        """
        SCALE = 200 / 72  # PDF点坐标 → 200DPI像素坐标
        doc = fitz.open(pdf_path)
        results = []

        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if not text:
                            continue
                        bbox = span["bbox"]  # (x0, y0, x1, y1)
                        cx = (bbox[0] + bbox[2]) / 2 * SCALE
                        cy = (bbox[1] + bbox[3]) / 2 * SCALE
                        results.append((text, cx, cy))

        doc.close()
        return results

    def _ocr_image(self, image_path):
        """用RapidOCR识别图片（自适应放大提高小字识别率）"""
        import cv2

        img = cv2.imread(image_path)
        if img is not None:
            h, w = img.shape[:2]
            if w < 4000:
                img = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            with self._lock:
                result, _ = self.engine(img)
        else:
            with self._lock:
                result, _ = self.engine(image_path)

        if not result:
            return []

        all_results = []
        for line in result:
            box, text, _ = line
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            cx = sum(xs) / 4
            cy = sum(ys) / 4
            all_results.append((text, cx, cy))
        return all_results

    def _pdf_to_images(self, pdf_path):
        """将PDF每页转为图片（用于扫描版PDF的OCR回退）"""
        doc = fitz.open(pdf_path)
        images = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_array = np.frombuffer(pix.samples, dtype=np.uint8)
            img_array = img_array.reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                img_array = img_array[:, :, :3]
            images.append(img_array)
        doc.close()
        return images

    def recognize(self, file_path):
        """
        识别文件，返回带坐标的文字列表
        - PDF：优先直接提取文字；若文字太少则回退到OCR
        - 图片：使用OCR

        返回: [(text, center_x, center_y), ...]
        """
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".pdf":
            # 优先直接提取PDF嵌入文字
            text_results = self._extract_pdf_text(file_path)
            if len(text_results) >= 10:
                # 文字足够多，是电子发票PDF
                return text_results
            # 文字太少，可能是扫描版PDF，回退到OCR
            images = self._pdf_to_images(file_path)
            all_results = []
            for img in images:
                with self._lock:
                    result, _ = self.engine(img)
                if result:
                    for line in result:
                        box, text, _ = line
                        xs = [p[0] for p in box]
                        ys = [p[1] for p in box]
                        cx = sum(xs) / 4
                        cy = sum(ys) / 4
                        all_results.append((text, cx, cy))
            return all_results
        else:
            return self._ocr_image(file_path)
