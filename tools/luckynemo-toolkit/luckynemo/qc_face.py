"""人脸相似度初筛（InsightFace/ArcFace）。

定位：自动初筛，不替代人工品控。低于阈值的图打回重抽，
通过的图仍需人工过 checklist（见 checklists/photo_qc.md）。

依赖说明：insightface / numpy 为可选依赖（requirements.txt 中注释掉了）。
未安装时所有函数优雅降级——打印提示并返回"已跳过"，绝不抛错阻断管线。
阈值 0.4-0.6 是工程经验区间，必须用自有样本校准后再用于生产。
"""

from __future__ import annotations

from pathlib import Path

#: 相似度阈值（经验区间 0.4-0.6，需用自有样本校准）
DEFAULT_THRESHOLD = 0.5


def _import_deps():
    """尝试导入可选依赖；失败返回 None 并打印一次性提示。"""
    try:
        import numpy as np  # noqa: F401
        from insightface.app import FaceAnalysis
    except ImportError:
        print(
            "[qc_face] 未安装 insightface/numpy，跳过人脸相似度初筛。"
            "（可选依赖：pip install insightface numpy）"
        )
        return None
    return FaceAnalysis


class FaceScreener:
    """ArcFace 1:1 人脸比对器。"""

    def __init__(self) -> None:
        face_analysis_cls = _import_deps()
        self._app = None
        if face_analysis_cls is not None:
            app = face_analysis_cls(name="buffalo_l")
            app.prepare(ctx_id=-1)  # -1 = 纯 CPU，工作室无 GPU 运维
            self._app = app

    @property
    def available(self) -> bool:
        """依赖是否可用。"""
        return self._app is not None

    def _embedding(self, image_path: str | Path):
        """取图中最大人脸的 embedding；检测不到人脸返回 None。"""
        import cv2  # insightface 的传递依赖，随其一起安装

        img = cv2.imread(str(image_path))
        if img is None:
            print(f"[qc_face] 读图失败：{image_path}")
            return None
        faces = self._app.get(img)
        if not faces:
            print(f"[qc_face] 未检测到人脸：{image_path}")
            return None
        # 取最大人脸（面积最大），避免背景路人干扰
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        return face.normed_embedding

    def similarity(self, img_a: str | Path, img_b: str | Path) -> float | None:
        """两张图最大人脸的余弦相似度；任一张检测不到人脸返回 None。"""
        if not self.available:
            return None
        import numpy as np

        emb_a = self._embedding(img_a)
        emb_b = self._embedding(img_b)
        if emb_a is None or emb_b is None:
            return None
        return float(np.dot(emb_a, emb_b))

    def screen(
        self,
        references: list[str | Path],
        generated: list[str | Path],
        *,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> dict:
        """批量初筛：每张生成图与全部参考图取最高相似度，低于阈值列入打回。

        依赖不可用时返回 ``{"skipped": True}``，不阻断管线。
        """
        if not self.available:
            return {"skipped": True, "reason": "insightface/numpy 未安装"}
        report = {"skipped": False, "threshold": threshold, "passed": [], "rejected": []}
        for gen in generated:
            scores = [s for s in (self.similarity(gen, ref) for ref in references) if s is not None]
            best = max(scores) if scores else None
            item = {"file": str(gen), "best_similarity": best}
            if best is not None and best >= threshold:
                report["passed"].append(item)
            else:
                report["rejected"].append(item)
        return report
