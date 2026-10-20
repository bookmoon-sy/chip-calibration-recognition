# output_submit_report

- 来源：`src/report_submit_results.py`，汇总 `output_submit/` 的 OCR 与角度结果。
- 内容：
  - `token_accuracy.tsv`：每张图的文本、各关键词命中标记、命中数、总体命中率。
  - `accuracy_summary.txt`：总体样本数与平均命中率。
  - `angles_original.tsv`：`output_rotated/rotation_angles.txt` 导出的原始角度。
  - `angles_final.tsv`：`output_submit/angles_with_orientation.txt` 导出的最终角度（含 180° 叠加）。
  - `*.png`（如有）：命中率柱状图、逐图命中率条形图、角度直方图、原始 vs 最终角度散点图。
- 用途：提交/汇报时的结果汇总，不被其他代码继续读取。
