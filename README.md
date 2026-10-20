# 芯片检测、角度校正与文字识别

本仓库整理了基于传统图像处理的 PCB 芯片定位、裁剪、角度校正和丝印文字识别课程项目，以及相关课程资料和汇报文件。

## 项目流程

代码项目位于 [`computer_vision_1.1/`](computer_vision_1.1/)，以 PCB 原始图像为输入，依次执行芯片检测与裁剪、角度估计与摆正、OCR 方向判断与识别，并生成结果统计和可视化文件。算法主要使用 OpenCV 图像处理方法及芯片排针等几何特征，不依赖训练好的深度学习模型。

详细算法说明和目录结构见[项目 README](computer_vision_1.1/README.md)。

## 环境与依赖

- Python 3.8 或更高版本
- `opencv-python`、`numpy`、`matplotlib`、`pytesseract`
- Tesseract OCR 引擎（需单独安装）

仓库中的较大 PPT 和 PDF 文件使用 Git LFS 保存。克隆仓库前请安装 Git LFS，并运行 git lfs install，以获取这些文件的完整内容。

在项目目录中安装 Python 依赖：

```powershell
cd computer_vision_1.1
python -m pip install opencv-python numpy matplotlib pytesseract
```

OCR 脚本当前将 Tesseract 可执行文件配置为 Windows 默认安装路径 `C:\Program Files\Tesseract-OCR\tesseract.exe`。若实际安装路径不同，请在运行 OCR 前调整 `src/chip_text_ocr_2.py` 中的 `pytesseract.pytesseract.tesseract_cmd`。

## 运行步骤

在 `computer_vision_1.1/` 目录中依次执行：

```powershell
python src/chip_detection_and_crop.py
python src/chip_angle_alignment.py
python src/chip_text_ocr_2.py
python src/report_submit_results.py
```

输入图像存放在 `computer_vision_1.1/3board/`。各阶段结果分别保存在 `output_crops/`、`output_rotated/`、`output_chip_aligned/`、`output_submit/` 和 `output_submit_report/` 等目录中。仓库保留了当前样例图像和已有处理结果，重新运行脚本会更新相应输出。

## 仓库目录

```text
芯片校正识别/
├── computer_vision_1.1/   # 芯片识别代码、样例图像、处理结果和项目说明
├── PPT/                   # 项目汇报与流程图材料
├── 机器视觉PPT/           # 机器视觉课程课件及配图
├── 学习资料/              # 根目录整理的讲义、笔记和打印资料
├── README.md
└── .gitignore
```

`computer_vision_1.1/` 下各脚本的输入输出、处理步骤和结果目录说明以其项目 README 为准。

