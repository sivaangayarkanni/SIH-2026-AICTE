# SealCheck detector evaluation — SYNTHETIC DATA ONLY

> **These numbers come from procedurally generated images and PDFs (`ml/eval/scenes.py`, `ml/eval/synth_eval.py`).
> They are not real-world accuracy.** No labelled set of real AICTE submissions was available, so nothing here was
> trained or fine-tuned on real data. RT-DETR (object detection) is COCO-pretrained and was **not** evaluated on lab equipment.

Re-run: `.venv/bin/python ml/eval/synth_eval.py` (about 14 min on CPU). Raw output: `results/synthetic_eval.json`.
Split: even-indexed scenes/documents calibrate, odd-indexed ones are held out. A threshold set is chosen only if calibration precision is at least 0.97.

## Lab-photo reuse (280 pairs from 40 scenes: 2 reuse, 1 mirrored reuse, 1 sibling room, 3 unrelated per scene)

| Detector | Thresholds | Held-out precision | Held-out recall | Held-out F1 |
|---|---|---|---|---|
| Classic pHash + ORB (previous) | pHash ≤ 8, or ORB ≥ 40 inliers when pHash ≤ 22 | 0.857 | 0.400 | 0.545 |
| **Classic pHash + ORB (calibrated, now the default)** | pHash ≤ 2, or ORB ≥ 15 inliers | **1.000** | **0.667** | **0.800** |
| DINOv2 + LightGlue (previous) | cosine ≥ 0.90 and ≥ 100 inliers | 0.875 | 0.233 | 0.368 |
| **DINOv2 + LightGlue (calibrated, now the default)** | cosine ≥ 0.70 and ≥ 150 inliers | **0.977** | **0.700** | **0.816** |

By pair type (held out, calibrated): crop/scale/rotate/recompress reuse is found every time by both detectors. **Mirrored reuse is mostly missed**
(classic 0/20, models 2/20), and that accounts for all of the missed recall. Sibling rooms (same layout, different lab) and unrelated rooms
were not flagged by the classic detector. The models detector had one false positive.
Thresholds are environment-overridable: `PHOTO_PHASH_DUP`, `PHOTO_ORB_INLIERS`, `PHOTO_ORB_GATE_PHASH`, `VISION_DUP_COSINE`, `VISION_DUP_INLIERS`.

## PDF forensics (240 documents, 8 kinds × 30)

| Kind | Rule fired | Result |
|---|---|---|
| clean signed / clean unsigned | none | correct (no false alarm) |
| hidden white text, tiny 1 pt black text | F-HID-01 | all detected |
| white-box overlay over text, near-white (#FAFAFA) overlay | F-OVL-01 | all detected |
| edited after signing | F-DSC-02 | all detected |
| **decorative white box that covers nothing** | F-OVL-01 | **false positive every time** (15/15 held out) |

Held-out precision is 0.833 and recall is 1.000. The overlay rule cannot yet tell a harmless white rectangle from one that hides text.
Because SealCheck routes these cases to an officer for **manual review** instead of auto-rejecting, the cost is extra review, not wrong decisions. Fixing it needs a check that text underneath is actually occluded.

## What would make this real
A few hundred real, consented and labelled submissions (lab photos with known reuse; genuine versus edited certificates). Run the same script on them and recalibrate. Only after that can any accuracy claim be made.
