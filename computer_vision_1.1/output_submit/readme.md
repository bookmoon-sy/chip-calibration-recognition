# output_submit

- 来源：`src/chip_text_ocr_2.py`（提交版 OCR），输入 `output_chip_aligned/`。
- 内容：
  - `ocr_results.txt`：每张图的 OCR 文本及最终角度。
  - `angles_with_orientation.txt`：原始角度（来自 `output_rotated/rotation_angles.txt`）+ 0/180° 判定后的最终角度。
  - `preprocess/`：`*_prep.png`，方向校正后的预处理二值图。
  - `vis/`：`*_vis.png`，原图叠加首行 OCR 文本与最终角度。
- 用途：提交用的汇总输出，不再被后续脚本读取（汇总报告另见 `output_submit_report/`）。
