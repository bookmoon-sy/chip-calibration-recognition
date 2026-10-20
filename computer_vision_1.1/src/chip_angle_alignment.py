# -*- coding: utf-8 -*-
"""
用已有的裁剪芯片图（output_crops）做：
1) 自动估计芯片角度并摆正
2) 记录角度
3) 可选 OCR 文字识别（需要安装 pytesseract）
4) 可视化并保存摆正后的结果
"""
import os
import glob
import cv2
import numpy as np


def load_images_from_folder(folder, exts=('.png', '.jpg', '.jpeg', '.bmp', '.tif')):
    imgs = []
    for ext in exts:
        for path in sorted(glob.glob(os.path.join(folder, f'*{ext}'))):
            img = cv2.imread(path)
            if img is None:
                print(f'[WARN] 读取失败，跳过: {path}')
                continue
            imgs.append({'path': path, 'name': os.path.basename(path), 'img': img})
    print(f'[INFO] 共读取到 {len(imgs)} 张图片')
    return imgs

def detect_pins_only(binary_img, bgr_img=None, debug=False):
    """
    按“排针检测”逻辑找细长针脚。
    binary_img: 背景白，针脚/芯片黑
    """
    MORPH_OPEN_KSIZE = (3, 3)
    MORPH_OPEN_ITERS = 1
    MIN_AREA = 150
    MAX_AREA = 495
    MIN_ROT_ASPECT = 2.2
    MAX_ROT_ASPECT = 25.0
    MIN_SHORT_SIDE = 2.0
    MAX_SHORT_SIDE = 25.0
    MIN_LONG_SIDE = 6.0
    MAX_LONG_SIDE = 120.0

    inv = 255 - binary_img
    proc = inv
    if MORPH_OPEN_KSIZE is not None and MORPH_OPEN_ITERS > 0:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, MORPH_OPEN_KSIZE)
        proc = cv2.morphologyEx(proc, cv2.MORPH_OPEN, k, iterations=MORPH_OPEN_ITERS)

    contours, _ = cv2.findContours(proc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    pin_rects = []
    pin_boxes = []
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
        box = cv2.boxPoints(rect).astype(np.int32)
        x, y, w, h = cv2.boundingRect(c)
        pin_rects.append((x, y, w, h))
        pin_boxes.append(box)

    if debug and bgr_img is not None:
        vis = bgr_img.copy()
        for box in pin_boxes:
            cv2.polylines(vis, [box], True, (0, 255, 0), 2)
        cv2.imshow('pins', vis)
    return pin_rects, pin_boxes

def compute_rect_from_pin_boxes(pin_boxes,
                                shrink_long=0.05,
                                shrink_short=0.25):
    """
    根据所有排针的旋转框点集，计算整体 minAreaRect，并按比例向内收缩，
    确保红框内接于绿色排针区域。
    - shrink_long  : 长边收缩比例（调大→长边更短）
    - shrink_short : 短边收缩比例（调大→短边更短）
    """
    if not pin_boxes:
        return None, None, None
    pts = np.vstack(pin_boxes).astype(np.float32)
    rect = cv2.minAreaRect(pts)
    (cx, cy), (rw, rh), angle = rect
    if rw < rh:
        angle += 90.0
        rw, rh = rh, rw
    angle = ((angle + 90) % 180) - 90
    long_factor = max(0.5, 1.0 - shrink_long)
    short_factor = max(0.2, 1.0 - shrink_short)
    rw_new = rw * long_factor
    rh_new = rh * short_factor
    rect = ((cx, cy), (rw_new, rh_new), angle)
    return rect, angle, (rw_new, rh_new)

def compute_chip_bbox_from_pins(pin_rects, img_shape,
                                x_keep=(5, 95),
                                pad_ratio=0.08):
    """根据两排针脚快速推断芯片框。"""
    H, W = img_shape[:2]
    if len(pin_rects) < 2:
        return None
    centers = np.array([(x + w/2.0, y + h/2.0) for (x, y, w, h) in pin_rects],
                       dtype=np.float32)
    ys = centers[:, 1].reshape(-1, 1)
    _, labels, _ = cv2.kmeans(ys, 2, None,
                              (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.1),
                              10, cv2.KMEANS_PP_CENTERS)
    labels = labels.flatten()
    groups = [np.where(labels == i)[0] for i in range(2)]
    groups = [g for g in groups if len(g) > 0]
    if len(groups) < 2:
        return None
    groups = sorted(groups, key=lambda idxs: np.median(centers[idxs, 1]))
    top_idxs, bottom_idxs = groups[0], groups[1]

    def xr_span(idxs):
        xs_min = np.array([pin_rects[i][0] for i in idxs], dtype=np.float32)
        xs_max = np.array([pin_rects[i][0] + pin_rects[i][2] for i in idxs], dtype=np.float32)
        return np.percentile(xs_min, x_keep[0]), np.percentile(xs_max, x_keep[1])

    x1_top, x2_top = xr_span(top_idxs)
    x1_bot, x2_bot = xr_span(bottom_idxs)
    x1 = max(x1_top, x1_bot)
    x2 = min(x2_top, x2_bot)
    if x2 <= x1:
        x1 = min(x1_top, x1_bot)
        x2 = max(x2_top, x2_bot)

    y_top = max(pin_rects[i][1] + pin_rects[i][3] for i in top_idxs)
    y_bot = min(pin_rects[i][1] for i in bottom_idxs)

    pad_x = (x2 - x1) * pad_ratio
    pad_y = (y_bot - y_top) * pad_ratio

    bx1 = max(0, int(x1 - pad_x))
    bx2 = min(W - 1, int(x2 + pad_x))
    by1 = max(0, int(y_top - pad_y))
    by2 = min(H - 1, int(y_bot + pad_y))
    if bx2 <= bx1 or by2 <= by1:
        return None
    return (bx1, by1, bx2 - bx1, by2 - by1)

def estimate_chip_angle(bgr_img, target_size=None, shrink_long=0.05, shrink_short=0.25):
    """
    在裁剪后的芯片图上估计旋转角度：
    - OTSU + 反色得到芯片白、背景黑
    - 若有排针，则按排针框限定 ROI
    - 找最大轮廓的 minAreaRect 角度
    返回角度（顺时针）和二值 mask
    """
    gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, binary_inv = cv2.threshold(blur, 0, 255,
                                  cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    pin_rects, pin_boxes = detect_pins_only(binary_inv, bgr_img=None, debug=False)
    roi_box = compute_chip_bbox_from_pins(pin_rects, bgr_img.shape) if pin_rects else None
    rect_pins, angle_pins, size_pins = compute_rect_from_pin_boxes(pin_boxes, shrink_long, shrink_short) if pin_boxes else (None, None, None)

    mask = binary_inv
    if roi_box is not None:
        x, y, w, h = map(int, roi_box)
        x1 = max(0, x); y1 = max(0, y)
        x2 = min(mask.shape[1], x + w); y2 = min(mask.shape[0], y + h)
        mask_roi = np.zeros_like(mask)
        mask_roi[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
        mask = mask_roi

    h, w = mask.shape
    k = max(3, int(min(h, w) * 0.02))
    k = k if k % 2 == 1 else k + 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)),
                            iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rect_mask = None
    angle_mask = None
    if contours:
        cmax = max(contours, key=cv2.contourArea)
        rect = cv2.minAreaRect(cmax)
        (cx, cy), (rw, rh), angle = rect
        if rw < rh:
            angle += 90.0
        angle = ((angle + 90) % 180) - 90
        rect_mask = rect
        angle_mask = angle

    # 优先使用排针角度，其次 mask
    rect_use = None
    angle_use = 0.0
    if rect_pins is not None:
        rect_use = rect_pins
        angle_use = angle_pins
    elif rect_mask is not None:
        rect_use = rect_mask
        angle_use = angle_mask if angle_mask is not None else 0.0

    # 如指定 target_size，则强制使用同一尺寸（保持长边对应 angle）
    if rect_use is not None and target_size is not None:
        (cx, cy), (rw, rh), ang = rect_use
        t_long, t_short = target_size
        if rw < rh:
            # 角度的长边在高度方向
            rect_use = ((cx, cy), (t_short, t_long), ang)
        else:
            rect_use = ((cx, cy), (t_long, t_short), ang)

    # 确保长边为水平（w>=h），必要时交换并调整角度
    if rect_use is not None:
        (cx, cy), (rw, rh), ang = rect_use
        if rw < rh:
            rw, rh = rh, rw
            ang += 90.0
        # 归一化角度到 (-90, 90]，保持旋转信息用于裁剪
        ang = ((ang + 90) % 180) - 90
        rect_use = ((cx, cy), (rw, rh), ang)
        angle_use = ang

    return angle_use, mask, rect_use, pin_boxes, size_pins

def rotate_image_keep_bounds(img, cw_angle_deg):
    """
    顺时针旋转 cw_angle_deg，自动扩展画布，返回旋转图和仿射矩阵。
    """
    if abs(cw_angle_deg) < 1e-6:
        h, w = img.shape[:2]
        M = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
        return img.copy(), M
    h, w = img.shape[:2]
    center = (w / 2.0, h / 2.0)
    ccw = -cw_angle_deg  # OpenCV 正角逆时针
    M = cv2.getRotationMatrix2D(center, ccw, 1.0)
    cos = abs(M[0, 0]); sin = abs(M[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    M[0, 2] += (new_w / 2) - center[0]
    M[1, 2] += (new_h / 2) - center[1]
    border = (255, 255, 255) if len(img.shape) == 3 else 255
    rotated = cv2.warpAffine(img, M, (new_w, new_h),
                             flags=cv2.INTER_LINEAR,
                             borderValue=border)
    return rotated, M

def order_points(pts):
    """将4点按 tl, tr, br, bl 排序。"""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def crop_rect_to_canvas(img, rect):
    """
    将旋转矩形 rect（cx,cy,w,h,angle）裁成水平小图，放在白底画布上返回。
    """
    box = cv2.boxPoints(rect).astype(np.float32)
    box = order_points(box)
    (tl, tr, br, bl) = box
    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxW = int(max(widthA, widthB))
    maxH = int(max(heightA, heightB))
    dst = np.array([
        [0, 0],
        [maxW - 1, 0],
        [maxW - 1, maxH - 1],
        [0, maxH - 1]
    ], dtype="float32")
    M = cv2.getPerspectiveTransform(box, dst)
    warped = cv2.warpPerspective(img, M, (maxW, maxH),
                                 flags=cv2.INTER_LINEAR,
                                 borderValue=(255, 255, 255))
    return warped

def crop_after_rotation(img, rect, angle_cw):
    """
    按 rect 的角度先旋转回正，再裁剪矩形区域，返回裁剪图。
    """
    rotated, M = rotate_image_keep_bounds(img, -angle_cw)  # 逆转回正
    box = cv2.boxPoints(rect).astype(np.float32)
    # 应用同样的仿射矩阵到矩形四点
    ones = np.ones((box.shape[0], 1), dtype=np.float32)
    pts_h = np.hstack([box, ones])
    box_rot = (M @ pts_h.T).T
    box_rot = order_points(box_rot)
    x_min, y_min = np.min(box_rot, axis=0).astype(int)
    x_max, y_max = np.max(box_rot, axis=0).astype(int)
    x_min = max(0, x_min); y_min = max(0, y_min)
    x_max = min(rotated.shape[1], x_max); y_max = min(rotated.shape[0], y_max)
    crop = rotated[y_min:y_max, x_min:x_max]
    return crop


def main():
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    crop_dir = os.path.normpath(os.path.join(cur_dir, '..', 'output_crops'))
    out_dir = os.path.normpath(os.path.join(cur_dir, '..', 'output_rotated'))
    crop_save_dir = os.path.normpath(os.path.join(cur_dir, '..', 'output_chip_canvas'))
    aligned_dir = os.path.normpath(os.path.join(cur_dir, '..', 'output_chip_aligned'))
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(crop_save_dir, exist_ok=True)
    os.makedirs(aligned_dir, exist_ok=True)
    angle_log = os.path.join(out_dir, 'rotation_angles.txt')
    angle_list_path = os.path.join(out_dir, 'angle_list.txt')
    print('[INFO] 读取裁剪图：', crop_dir)
    print('[INFO] 摆正输出：', out_dir)
    print('[INFO] 红框裁剪输出：', crop_save_dir)
    print('[INFO] 摆正裁剪输出：', aligned_dir)

    # === 你可以调整的参数 ===
    SHRINK_LONG = 0.0    # 长边收缩比例（调大→长边更短）
    SHRINK_SHORT = 0.45   # 短边收缩比例（调大→短边更短）
    USE_UNIFIED_SIZE = True  # True: 所有红框使用首张图尺寸；False: 每张自适应
    # =======================

    # 清空角度日志
    open(angle_log, 'w', encoding='utf-8').close()
    open(angle_list_path, 'w', encoding='utf-8').close()

    dataset = load_images_from_folder(crop_dir)
    if not dataset:
        print('[ERROR] output_crops 为空')
        return

    target_size = None
    angle_list = []

    for idx, item in enumerate(dataset):
        img = item['img']
        name = item['name']
        print(f'\n[INFO] 处理第 {idx+1}/{len(dataset)} 张：{name}')

        angle, mask, rect, pin_boxes, size_pins = estimate_chip_angle(
            img,
            target_size=target_size if USE_UNIFIED_SIZE else None,
            shrink_long=SHRINK_LONG,
            shrink_short=SHRINK_SHORT
        )
        if USE_UNIFIED_SIZE and target_size is None and size_pins is not None:
            # 首张图确定统一尺寸
            target_size = size_pins

        print(f'[INFO] 顺时针旋转角度: {angle:.2f} 度')
        angle_list.append(angle)

        # 可视化：原图 + mask + 摆正裁剪
        img_vis = img.copy()
        if pin_boxes:
            for pb in pin_boxes:
                cv2.polylines(img_vis, [pb], True, (0, 255, 0), 1)
        if rect is not None:
            box = cv2.boxPoints(rect)
            box = np.intp(box)
            cv2.polylines(img_vis, [box], True, (0, 0, 255), 2)
            # 按角度回正并裁剪
            aligned_crop = crop_after_rotation(img, rect, angle)
            aligned_path = os.path.join(aligned_dir, f'{os.path.splitext(name)[0]}_aligned.png')
            cv2.imwrite(aligned_path, aligned_crop)
        target_h = 360
        def resize_keep_h(im):
            h, w = im.shape[:2]
            scale = target_h / float(h)
            return cv2.resize(im, (int(w * scale), target_h))
        show = resize_keep_h(img_vis)
        cv2.imshow('chip_align (orig with pins/chip)', show)

        # 叠加角度到原图并保存
        vis_save = img_vis.copy()
        cv2.putText(vis_save, f'angle: {angle:.2f}', (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)

        save_path = os.path.join(out_dir, f'{os.path.splitext(name)[0]}_annotated.png')
        cv2.imwrite(save_path, vis_save)
        if rect is not None:
            cropped = crop_rect_to_canvas(img, rect)
            crop_path = os.path.join(crop_save_dir, f'{os.path.splitext(name)[0]}_crop.png')
            cv2.imwrite(crop_path, cropped)
        with open(angle_log, 'a', encoding='utf-8') as f:
            f.write(f'{name}\t{angle:.2f}\n')

        key = cv2.waitKey(0) & 0xFF
        if key in (27, ord('q'), ord('Q')):
            print('[INFO] 用户中断，提前结束。')
            break

    cv2.destroyAllWindows()
    # 保存角度列表
    with open(angle_list_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(f'{a:.2f}' for a in angle_list))


if __name__ == '__main__':
    main()
