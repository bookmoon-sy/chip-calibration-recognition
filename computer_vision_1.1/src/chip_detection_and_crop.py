# -*- coding: utf-8 -*-
import os
import glob
import cv2
import numpy as np

def load_images_from_folder(folder,
                            exts=('.png', '.jpg', '.jpeg', '.bmp', '.tif')):
    """
    从指定文件夹中读取所有图片，返回一个列表：
    [
        {
            'path': 图片完整路径,
            'name': 文件名,
            'img' : OpenCV 读入的图像 (numpy 数组)
        },
        ...
    ]
    """
    image_list = []

    for ext in exts:
        pattern = os.path.join(folder, f'*{ext}')
        for path in sorted(glob.glob(pattern)):
            img = cv2.imread(path)
            if img is None:
                print(f'[WARN] 读取失败，跳过: {path}')
                continue

            info = {
                'path': path,
                'name': os.path.basename(path),
                'img': img
            }
            image_list.append(info)

    print(f'[INFO] 共读取到 {len(image_list)} 张图片。')
    return image_list

def preprocess_board_image_simple(bgr_img,
                                  debug_show=False,
                                  window_name_prefix=''):
    """
    简单预处理：
    1. 高斯模糊
    2. 灰度化
    3. 二值化（默认阈值 120，反色让芯片=白）
    """

    # ================== 可调参数区 ==================
    BLUR_KSIZE = 9
    USE_OTSU = False
    TH_VAL = 120
    TH_TYPE = cv2.THRESH_BINARY_INV
    # =================================================

    if BLUR_KSIZE and BLUR_KSIZE > 1:
        k = BLUR_KSIZE if BLUR_KSIZE % 2 == 1 else BLUR_KSIZE + 1
        blur_bgr = cv2.GaussianBlur(bgr_img, (k, k), 0)
    else:
        blur_bgr = bgr_img

    gray = cv2.cvtColor(blur_bgr, cv2.COLOR_BGR2GRAY)

    if USE_OTSU:
        _, binary = cv2.threshold(gray, 0, 255, TH_TYPE + cv2.THRESH_OTSU)
    else:
        _, binary = cv2.threshold(gray, TH_VAL, 255, TH_TYPE)

    if debug_show:
        win_prefix = (window_name_prefix + '_') if window_name_prefix else ''
        # cv2.imshow(win_prefix + 'gray', gray)
        # cv2.imshow(win_prefix + 'binary', binary)

    return binary

def close_chip_mask(binary_img):
    """
    把芯片区域“焊”成实心块：闭运算连通缺口，开运算去掉零碎。
    """
    if len(binary_img.shape) == 3:
        mask = cv2.cvtColor(binary_img, cv2.COLOR_BGR2GRAY)
    else:
        mask = binary_img.copy()

    _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)

    h, w = mask.shape[:2]
    close_size = max(5, int(min(h, w) * 0.015))
    close_size = close_size if close_size % 2 == 1 else close_size + 1
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT,
                                             (close_size, close_size))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel,
                              iterations=2)

    open_size = max(3, int(close_size * 0.8))
    open_size = open_size if open_size % 2 == 1 else open_size + 1
    open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT,
                                            (open_size, open_size))
    clean_mask = cv2.morphologyEx(closed, cv2.MORPH_OPEN, open_kernel,
                                  iterations=1)
    return clean_mask

def detect_pins_only(binary_img):
    """
    只检测排针（细长亮针脚），返回排针的外接矩形列表。
    binary_img: 预处理后的二值图，背景白255，排针/芯片暗色为0
    """
    MORPH_OPEN_KSIZE = (3, 3)
    MORPH_OPEN_ITERS = 1

    MIN_AREA = 150
    MAX_AREA = 500
    MIN_ROT_ASPECT = 2.0
    MAX_ROT_ASPECT = 20.0
    MIN_SHORT_SIDE = 2.0
    MAX_SHORT_SIDE = 20.0
    MIN_LONG_SIDE = 6.0
    MAX_LONG_SIDE = 120.0

    inv = 255 - binary_img
    proc = inv
    if MORPH_OPEN_KSIZE is not None and MORPH_OPEN_ITERS > 0:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, MORPH_OPEN_KSIZE)
        proc = cv2.morphologyEx(proc, cv2.MORPH_OPEN, k,
                                iterations=MORPH_OPEN_ITERS)

    contours, _ = cv2.findContours(proc, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

    pin_rects = []

    for c in contours:
        area = cv2.contourArea(c)
        if area < MIN_AREA or area > MAX_AREA:
            continue

        rect = cv2.minAreaRect(c)
        (_, _), (rw, rh), angle = rect
        if rw <= 1e-6 or rh <= 1e-6:
            continue

        long_side = max(rw, rh)
        short_side = min(rw, rh)
        rot_aspect = long_side / (short_side + 1e-6)

        if rot_aspect < MIN_ROT_ASPECT or rot_aspect > MAX_ROT_ASPECT:
            continue

        if short_side < MIN_SHORT_SIDE or short_side > MAX_SHORT_SIDE:
            continue
        if long_side < MIN_LONG_SIDE or long_side > MAX_LONG_SIDE:
            continue

        x, y, w, h = cv2.boundingRect(c)

        pin_rects.append((x, y, w, h))

    return pin_rects

def compute_chip_core_from_pins(pin_rects, img_shape,
                                x_keep=(5, 95),
                                y_pad_ratio=0.1,
                                x_pad_ratio=0.05):
    """
    基于排针几何位置直接推断芯片主体矩形：
    - 按 y 聚成上下两排
    - 取每排 x 的分位区间并求交集，得到芯片左右范围
    - 上下范围取两排的 min/max 并适当 padding
    """
    H, W = img_shape[:2]
    if len(pin_rects) < 4:
        return None

    centers = np.array([(x + w / 2.0, y + h / 2.0)
                        for (x, y, w, h) in pin_rects],
                       dtype=np.float32)
    ys = centers[:, 1].reshape(-1, 1)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.1)
    _, labels, _ = cv2.kmeans(ys, 2, None, criteria, 10, cv2.KMEANS_PP_CENTERS)
    labels = labels.flatten()

    groups = []
    for g in range(2):
        idxs = np.where(labels == g)[0]
        if len(idxs) == 0:
            continue
        groups.append(idxs)
    if len(groups) < 2:
        return None

    # 选 y 中位小的一组为上排
    groups = sorted(groups, key=lambda idxs: np.median(centers[idxs, 1]))
    top_idxs, bottom_idxs = groups[0], groups[1]

    def xr_span(idxs):
        xs_min = np.array([pin_rects[i][0] for i in idxs], dtype=np.float32)
        xs_max = np.array([pin_rects[i][0] + pin_rects[i][2] for i in idxs],
                          dtype=np.float32)
        p1 = np.percentile(xs_min, x_keep[0])
        p2 = np.percentile(xs_max, x_keep[1])
        return p1, p2

    x1_top, x2_top = xr_span(top_idxs)
    x1_bot, x2_bot = xr_span(bottom_idxs)

    x1 = max(x1_top, x1_bot)
    x2 = min(x2_top, x2_bot)
    if x2 <= x1:
        x1 = min(x1_top, x1_bot)
        x2 = max(x2_top, x2_bot)

    y_top = max(pin_rects[i][1] + pin_rects[i][3] for i in top_idxs)
    y_bot = min(pin_rects[i][1] for i in bottom_idxs)

    pad_x = (x2 - x1) * x_pad_ratio
    pad_y = (y_bot - y_top) * y_pad_ratio

    bx1 = max(0, int(x1 - pad_x))
    bx2 = min(W - 1, int(x2 + pad_x))
    by1 = max(0, int(y_top - pad_y))
    by2 = min(H - 1, int(y_bot + pad_y))

    if bx2 <= bx1 or by2 <= by1:
        return None
    return (bx1, by1, bx2 - bx1, by2 - by1)

def infer_chip_bbox_from_pins(pin_rects, img_shape, expand_x=0.05, expand_y=0.08):
    """
    根据两排针脚推断芯片框：
    - y 方向聚成两组
    - 去掉左右离群点
    - 用上下两组的极值 + padding 得到芯片框
    """
    H, W = img_shape[:2]
    if len(pin_rects) < 2:
        return None

    centers_all = np.array([(x + w / 2.0, y + h / 2.0)
                            for (x, y, w, h) in pin_rects],
                           dtype=np.float32)

    # 过滤掉离图像边缘太近的点，避免误检
    margin_x = W * 0.1
    margin_y = H * 0.1
    valid_idx = [
        i for i, (cx, cy) in enumerate(centers_all)
        if (margin_x < cx < W - margin_x) and (margin_y < cy < H - margin_y)
    ]

    if len(valid_idx) >= 4:
        centers = centers_all[valid_idx]
        rects_use = [pin_rects[i] for i in valid_idx]
    else:
        centers = centers_all
        rects_use = pin_rects

    ys = centers[:, 1].reshape(-1, 1)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.1)
    _, labels, _ = cv2.kmeans(ys, 2, None, criteria, 10, cv2.KMEANS_PP_CENTERS)
    labels = labels.flatten()

    group_bounds = []
    for g in range(2):
        idxs = np.where(labels == g)[0]
        if len(idxs) == 0:
            continue

        xs = centers[idxs, 0]
        p10, p90 = np.percentile(xs, [10, 90])

        keep_x = []
        for idx in idxs:
            cx = centers[idx, 0]
            if cx < p10 or cx > p90:
                continue
            keep_x.append(idx)

        if not keep_x:
            continue

        xs_keep, ys_keep, xe_keep, ye_keep = [], [], [], []
        for idx in keep_x:
            x, y, w, h = rects_use[idx]
            xs_keep.append(x)
            ys_keep.append(y)
            xe_keep.append(x + w)
            ye_keep.append(y + h)

        group_bounds.append((min(xs_keep), min(ys_keep),
                             max(xe_keep), max(ye_keep)))

    if len(group_bounds) < 2:
        # 兜底：用所有针脚的分位数做框
        xs = centers[:, 0]
        ys_all = centers[:, 1]
        x1, x2 = np.percentile(xs, [5, 95])
        y1, y2 = np.percentile(ys_all, [5, 95])
        pad_x = (x2 - x1) * expand_x
        pad_y = (y2 - y1) * expand_y
        bx1 = max(0, x1 - pad_x)
        bx2 = min(W - 1, x2 + pad_x)
        by1 = max(0, y1 - pad_y)
        by2 = min(H - 1, y2 + pad_y)
        if bx2 > bx1 and by2 > by1:
            return (bx1, by1, bx2 - bx1, by2 - by1)
        return None

    group_bounds = sorted(group_bounds, key=lambda g: (g[1] + g[3]) / 2.0)
    top, bottom = group_bounds[0], group_bounds[1]

    x1 = min(top[0], bottom[0])
    x2 = max(top[2], bottom[2])
    y1 = top[1]
    y2 = bottom[3]

    pad_x = min(int((x2 - x1) * expand_x), int(W * 0.1))
    row_gap = max(1, y2 - y1)
    pad_y = min(int(row_gap * expand_y), int(H * 0.1))

    bx1 = max(0, x1 - pad_x)
    by1 = max(0, y1 - pad_y)
    bx2 = min(W - 1, x2 + pad_x)
    by2 = min(H - 1, y2 + pad_y)

    # 限制最终框不要超过整图的一定比例，避免误框整块 PCB
    max_w = W * 0.45
    max_h = H * 0.45
    bw = bx2 - bx1
    bh = by2 - by1
    cx = (bx1 + bx2) / 2.0
    cy = (by1 + by2) / 2.0
    if bw > max_w:
        half = max_w / 2.0
        bx1 = max(0, int(cx - half))
        bx2 = min(W - 1, int(cx + half))
    if bh > max_h:
        half = max_h / 2.0
        by1 = max(0, int(cy - half))
        by2 = min(H - 1, int(cy + half))

    return (bx1, by1, bx2 - bx1, by2 - by1)

def find_chip_by_contours(binary_img, bgr_img, debug=False):
    """
    先用排针推断芯片框；失败再在闭合 mask 上按面积+长宽比兜底找轮廓。
    binary_img : 二值图（芯片=255，背景=0）
    bgr_img    : 原图，用于获取尺寸
    """
    MIN_AREA = 2000
    MAX_AREA = 150000
    MIN_ASPECT = 1.6
    MAX_ASPECT = 3.5
    USE_RECTANGULARITY = False
    MIN_RECTANGULARITY = 0.75

    if len(binary_img.shape) == 3:
        bin_img = cv2.cvtColor(binary_img, cv2.COLOR_BGR2GRAY)
    else:
        bin_img = binary_img.copy()
    _, bin_img = cv2.threshold(bin_img, 127, 255, cv2.THRESH_BINARY)

    mask = close_chip_mask(bin_img)
    img_area = mask.shape[0] * mask.shape[1]
    MIN_AREA_PIX = max(MIN_AREA, img_area * 0.01)
    MAX_AREA_PIX = min(MAX_AREA, img_area * 0.5)

    chip_boxes = []
    chip_polys = []
    pin_rects = []

    # 排针检测
    pin_rects = detect_pins_only(binary_img)
    pin_bbox = infer_chip_bbox_from_pins(pin_rects, bgr_img.shape)

    # 基于排针框裁剪 mask，再在 ROI 内找最大符合条件的轮廓
    roi_box = pin_bbox
    if roi_box is None:
        roi_box = compute_chip_core_from_pins(pin_rects, bgr_img.shape)

    best_det = None
    if roi_box is not None:
        rx, ry, rw, rh = map(int, roi_box)
        pad_r = 0.08
        px = int(rw * pad_r)
        py = int(rh * pad_r)
        rx1 = max(0, rx - px)
        ry1 = max(0, ry - py)
        rx2 = min(mask.shape[1], rx + rw + px)
        ry2 = min(mask.shape[0], ry + rh + py)
        mask_roi = mask[ry1:ry2, rx1:rx2]
        roi_area = max(1, (rx2 - rx1) * (ry2 - ry1))

        conts, _ = cv2.findContours(mask_roi, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
        for c in conts:
            area = cv2.contourArea(c)
            if area < roi_area * 0.05 or area > roi_area * 1.05:
                continue
            rect = cv2.minAreaRect(c)
            rwc, rhc = rect[1]
            if rwc == 0 or rhc == 0:
                continue
            aspect = max(rwc, rhc) / float(min(rwc, rhc))
            if aspect < 1.0 or aspect > MAX_ASPECT:
                continue

            x, y, w, h = cv2.boundingRect(c)
            box = cv2.boxPoints(rect)
            box = np.intp(box)
            box[:, 0] += rx1
            box[:, 1] += ry1
            x += rx1
            y += ry1
            c_full = c.copy()
            c_full[:, :, 0] += rx1
            c_full[:, :, 1] += ry1
            det = {
                'bbox': (x, y, w, h),
                'box': box,
                'area': area
            }
            if best_det is None or area > best_det['area']:
                best_det = det

    if best_det:
        x, y, w, h = best_det['bbox']
        chip_boxes.append((x, y, w, h))
        chip_polys.append(best_det['box'])

    # 兜底：全局轮廓
    if not chip_boxes:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        detections = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < MIN_AREA_PIX or area > img_area * 0.5:
                continue

            rect = cv2.minAreaRect(c)
            rwc, rhc = rect[1]
            if rwc == 0 or rhc == 0:
                continue

            aspect = max(rwc, rhc) / float(min(rwc, rhc))
            if aspect < MIN_ASPECT or aspect > MAX_ASPECT:
                continue

            x, y, w, h = cv2.boundingRect(c)
            box = cv2.boxPoints(rect)
            box = np.intp(box)

            detections.append({
                'bbox': (x, y, w, h),
                'area': area,
                'box': box
            })

        detections.sort(key=lambda d: d['area'], reverse=True)
        if detections:
            det = detections[0]
            x, y, w, h = det['bbox']
            chip_boxes.append((x, y, w, h))
            chip_polys.append(det['box'])

    return {
        'chip_boxes': chip_boxes,
        'mask': mask,
        'polys': chip_polys,
        'pin_rects': pin_rects
    }

def save_cropped_box(img, box, name, out_dir):
    """
    将检测到的芯片外接矩形直接裁剪并保存，便于目视确认。
    """
    os.makedirs(out_dir, exist_ok=True)
    x, y, w, h = map(int, box)
    x = max(0, x); y = max(0, y)
    x2 = min(img.shape[1], x + w)
    y2 = min(img.shape[0], y + h)
    crop = img[y:y2, x:x2]
    base, ext = os.path.splitext(name)
    save_path = os.path.join(out_dir, f"{base}_crop{ext}")
    cv2.imwrite(save_path, crop)

def main():
    """
    主流程：
    1. 读取 3board 文件夹下的所有图片
    2. 阈值 + 形态学预处理
    3. 利用排针推断芯片框（失败则兜底轮廓）
    """
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    img_folder = os.path.normpath(os.path.join(cur_dir, '..', '3board'))
    crop_dir = os.path.normpath(os.path.join(cur_dir, '..', 'output_crops'))
    proc_dir = os.path.normpath(os.path.join(cur_dir, '..', 'output_chip_preprocess'))
    vis_dir = os.path.normpath(os.path.join(cur_dir, '..', 'output_chip_vis'))
    pin_log_path = os.path.join(vis_dir, 'pin_rects.txt')
    print('[INFO] 图片文件夹：', img_folder)
    print('[INFO] 裁剪结果输出：', crop_dir)
    print('[INFO] 预处理结果输出：', proc_dir)
    print('[INFO] 可视化输出：', vis_dir)

    dataset = load_images_from_folder(img_folder)
    if not dataset:
        print('[ERROR] 没有读到任何图片')
        return

    os.makedirs(proc_dir, exist_ok=True)
    os.makedirs(vis_dir, exist_ok=True)
    open(pin_log_path, 'w', encoding='utf-8').close()

    for idx, item in enumerate(dataset):
        img = item['img']
        name = item['name']
        base, ext = os.path.splitext(name)
        print(f'\n[INFO] 处理第 {idx+1}/{len(dataset)} 张：{name}')

        binary = preprocess_board_image_simple(img)
        cv2.imwrite(os.path.join(proc_dir, f'{base}_binary.png'), binary)

        chip_info = find_chip_by_contours(binary, img, debug=False)
        chip_boxes = chip_info['chip_boxes']
        mask = chip_info['mask']
        polys = chip_info['polys']
        pins = chip_info['pin_rects']
        cv2.imwrite(os.path.join(proc_dir, f'{base}_mask.png'), mask)

        annotated = img.copy()
        if len(chip_boxes) == 0:
            print('[WARN] 未找到满足条件的芯片轮廓')
        else:
            main_box = chip_boxes[0]
            print(f"[INFO] 芯片框: {tuple(int(v) for v in main_box)}")
            save_cropped_box(img, main_box, name, crop_dir)
        for i, box in enumerate(chip_boxes):
            x, y, w, h = map(int, box)
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)
            if i < len(polys):
                cv2.polylines(annotated, [polys[i]], True, (0, 200, 255), 2)
        # 叠加排针框
        for pr in pins:
            px, py, pw, ph = map(int, pr)
            cv2.rectangle(annotated, (px, py), (px + pw, py + ph), (255, 0, 255), 1)
        # 记录排针坐标
        with open(pin_log_path, 'a', encoding='utf-8') as f:
            f.write(f'{name}\tcount:{len(pins)}\t' +
                    ';'.join(f'({int(px)},{int(py)},{int(pw)},{int(ph)})' for px, py, pw, ph in pins) +
                    '\n')
        cv2.imwrite(os.path.join(vis_dir, f'{base}_annotated{ext}'), annotated)

if __name__ == '__main__':
    main()
