# output_rotated

- 来源：`src/chip_angle_alignment.py`，输入 `output_crops/`。
- 内容：
  - `rotation_angles.txt`：每张图的旋转角度日志（顺时针，检测阶段得到）。
  - `angle_list.txt`：批量角度列表。
  - `*_crop_annotated.png`：裁剪图叠加角度与标注框的可视化。
- 用途：为 OCR 阶段提供原始角度，并供人工核对角度估计效果。
