# -*- coding: utf-8 -*-
"""对摆正且裁剪好的芯片图做 OCR，输入 output_chip_aligned，输出到 output_submit。"""

import os
import glob
import cv2
import numpy as np
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# --- 读取图片 ---
def load_images_from_folder(folder,
                            exts=('.png', '.jpg', '.jpeg', '.bmp', '.tif')):
    images = []
    for ext in exts:
        for path in sorted(glob.glob(os.path.join(folder, f'*{ext}'))):
            img = cv2.imread(path)
            if img is None:
                print(f'[WARN] 读取失败: {path}')
                continue
            images.append({
                'path': path,
                'name': os.path.basename(path),
                'img': img
            })
    print(f'[INFO] 共读取到 {len(images)} 张图片')
    return images


# --- 芯片文字预处理 ---
def preprocess_for_chip_ocr(bgr):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # 放大，避免字符过小
    gray = cv2.resize(
        gray, None,
        fx=2.0, fy=2.0,
        interpolation=cv2.INTER_CUBIC
    )

    # 轻度去噪
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    # 对比度增强（温和的 CLAHE）
    clahe = cv2.createCLAHE(
        clipLimit=3.0,
        tileGridSize=(8, 8)
    )
    gray = clahe.apply(gray)

    # OTSU 二值化
    _, bin_img = cv2.threshold(
        gray, 0, 255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    return bin_img



# --- OCR 识别 ---
def ocr_once(bin_img):
    config = (
        "--oem 3 "
        "--psm 6 "
        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
    )
    text = pytesseract.image_to_string(
        bin_img,
        lang="eng",
        config=config
    )
    return text.strip()

def decide_text_orientation(bin_img, debug=False):
    """
    判断文字方向
    返回:
        0   -> 正常方向
        180 -> 需要旋转 180°
    """

    text_0 = ocr_once(bin_img)

    bin_180 = cv2.rotate(bin_img, cv2.ROTATE_180)
    text_180 = ocr_once(bin_180)

    def score(text):
        if not text:
            return 0
        s = 0
        s += len(text)                          # 总长度
        s += sum(c.isalpha() for c in text) * 2 # 字母权重更高
        s += sum(c.isdigit() for c in text)
        if "SANYO" in text:
            s += 10
        if "JAPAN" in text:
            s += 5
        if "-" in text:
            s += 2
        return s

    score_0 = score(text_0)
    score_180 = score(text_180)

    if debug:
        print('[DEBUG] OCR 正向:', repr(text_0), 'score=', score_0)
        print('[DEBUG] OCR 180°:', repr(text_180), 'score=', score_180)

    return 0 if score_0 >= score_180 else 180


def get_base_angle(name_base, angle_map):
    candidates = [
        name_base,
        name_base.replace('_aligned', ''),
        name_base + '.png',
        name_base.replace('_aligned', '') + '.png'
    ]
    for k in candidates:
        if k in angle_map:
            return angle_map[k]
    return None


# --- 主函数 ---
def main():
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.normpath(os.path.join(cur_dir, '..'))
    img_folder = os.path.join(base_dir, 'output_chip_aligned')
    out_dir = os.path.join(base_dir, 'output_submit')
    prep_dir = os.path.join(out_dir, 'preprocess')
    vis_dir = os.path.join(out_dir, 'vis')
    result_path = os.path.join(out_dir, 'ocr_results.txt')
    angle_out_path = os.path.join(out_dir, 'angles_with_orientation.txt')
    angles_src = os.path.join(base_dir, 'output_rotated', 'rotation_angles.txt')

    os.makedirs(prep_dir, exist_ok=True)
    os.makedirs(vis_dir, exist_ok=True)
    open(result_path, 'w', encoding='utf-8').close()
    open(angle_out_path, 'w', encoding='utf-8').close()

    print('[INFO] OCR 输入文件夹:', img_folder)
    print('[INFO] 结果输出文件夹:', out_dir)

    angle_map = {}
    if os.path.isfile(angles_src):
        with open(angles_src, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    fname = parts[0]
                    ang = float(parts[1])
                    angle_map[fname] = ang
                    angle_map[os.path.splitext(fname)[0]] = ang

    dataset = load_images_from_folder(img_folder)
    if not dataset:
        print('[ERROR] 没有读取到任何芯片图像')
        return

    for idx, item in enumerate(dataset):
        img = item['img']
        name = item['name']

        print(f'\n[INFO] OCR 第 {idx+1}/{len(dataset)} 张：{name}')

        # 预处理
        ocr_bin = preprocess_for_chip_ocr(img)

        # 判断方向
        orientation = decide_text_orientation(ocr_bin, debug=True)

        if orientation == 180:
            print('[INFO] 判定为倒置文字，旋转 180°')
            img_final = cv2.rotate(img, cv2.ROTATE_180)
            ocr_bin = cv2.rotate(ocr_bin, cv2.ROTATE_180)
        else:
            print('[INFO] 判定为正常方向')
            img_final = img

        # 最终 OCR
        final_text = pytesseract.image_to_string(
            ocr_bin,
            lang='eng',
            config='--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.'
        )

        lines = [l.strip() for l in final_text.splitlines() if len(l.strip()) >= 3]
        print('[INFO] 识别结果:', lines)

        # 角度累加（如有 180° 翻转则叠加）
        base_angle = get_base_angle(os.path.splitext(name)[0], angle_map)
        add_angle = 180.0 if orientation == 180 else 0.0
        final_angle = base_angle + add_angle if base_angle is not None else None
        base_angle_str = f'{base_angle:.2f}' if base_angle is not None else 'NA'
        add_angle_str = f'{add_angle:.1f}'
        final_angle_str = f'{final_angle:.2f}' if final_angle is not None else 'NA'

        # 保存预处理与可视化
        base, _ = os.path.splitext(name)
        cv2.imwrite(os.path.join(prep_dir, f'{base}_prep.png'), ocr_bin)

        vis = img_final.copy()
        text_show = lines[0] if lines else ''
        if text_show:
            cv2.putText(vis, text_show, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 255, 0), 2, cv2.LINE_AA)
        if final_angle_str != 'NA':
            cv2.putText(vis, f'angle:{final_angle_str}', (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2, cv2.LINE_AA)
        cv2.imwrite(os.path.join(vis_dir, f'{base}_vis.png'), vis)

        with open(result_path, 'a', encoding='utf-8') as f:
            f.write(f'{name}\t{" | ".join(lines)}\tfinal_angle:{final_angle_str}\n')
        with open(angle_out_path, 'a', encoding='utf-8') as f:
            f.write(f'{name}\tbase:{base_angle_str}\tadd:{add_angle_str}\tfinal:{final_angle_str}\n')

        # 可视化
        cv2.imshow('chip (final orientation)', img_final)
        cv2.imshow('ocr_input (final)', ocr_bin)

        key = cv2.waitKey(0) & 0xFF
        if key in (27, ord('q'), ord('Q')):
            break

    cv2.destroyAllWindows()




if __name__ == '__main__':
    main()
