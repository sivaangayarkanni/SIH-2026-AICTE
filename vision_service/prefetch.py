"""Download model weights at build time (facebook/dinov2-small, PekingU/rtdetr_r18vd, kornia DISK/LightGlue)."""
import models as M
for n in ("dino", "detr", "lg"):
    M._load(n)
    print("cached", n)
