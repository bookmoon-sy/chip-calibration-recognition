# -*- coding: utf-8 -*-
"""汇总 output_submit 结果，生成命中率/角度表与可视化。"""

import os

TOKENS = ["SANYO", "LC3664NML-10", "JAPAN", "2CB3"]


def load_ocr_results(path):
    """读取 ocr_results.txt，返回 {name: text}。"""
    results = {}
    if not os.path.isfile(path):
        print(f"[WARN] 未找到 OCR 结果文件: {path}")
        return results
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                name = parts[0]
                text = parts[1]
                results[name] = text
    return results


def load_angles_rotation(path):
    """读取 output_rotated/rotation_angles.txt，返回列表 [(name, angle)]。"""
    rows = []
    if not os.path.isfile(path):
        print(f"[WARN] 未找到角度文件: {path}")
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                rows.append((parts[0], float(parts[1])))
    return rows


def load_angles_with_orientation(path):
    """读取 output_submit/angles_with_orientation.txt，解析 base/add/final。"""
    rows = []
    if not os.path.isfile(path):
        print(f"[WARN] 未找到角度文件: {path}")
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 3:
                continue
            name = parts[0]
            vals = {}
            for p in parts[1:]:
                if ":" in p:
                    k, v = p.split(":", 1)
                    vals[k] = v
            rows.append(
                (
                    name,
                    vals.get("base", "NA"),
                    vals.get("add", "NA"),
                    vals.get("final", "NA"),
                )
            )
    return rows


def evaluate_tokens(text):
    """返回每个 token 是否命中及总体准确率。"""
    up = text.upper()
    hits = [1 if tok in up else 0 for tok in TOKENS]
    acc = sum(hits) / len(TOKENS) if TOKENS else 0.0
    return hits, acc


def make_plots(per_rows, angle_final_rows, out_dir):
    try:
        import matplotlib.pyplot as plt
    except Exception:
        print("[WARN] matplotlib 未安装或导入失败，跳过可视化。")
        return

    # 设置中文字体与负号显示
    try:
        plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS"]
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass

    if per_rows:
        token_rates = []
        for i, tok in enumerate(TOKENS):
            hits = sum(row["hits"][i] for row in per_rows)
            token_rates.append(hits / len(per_rows))
        plt.figure(figsize=(6, 4))
        plt.bar(TOKENS, token_rates, color="#4C72B0")
        plt.ylim(0, 1)
        plt.ylabel("命中率")
        plt.title("关键词命中率")
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, "token_accuracy_bar.png"))
        plt.close()

        names = [row["name"] for row in per_rows]
        accs = [row["acc"] for row in per_rows]
        plt.figure(figsize=(8, max(4, len(names) * 0.25)))
        plt.barh(names, accs, color="#55A868")
        plt.xlim(0, 1)
        plt.xlabel("总体命中率")
        plt.title("逐图命中率")
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, "per_image_accuracy.png"))
        plt.close()

    final_angles = []
    for _, _, _, final in angle_final_rows:
        if final not in ("NA", "", None):
            try:
                final_angles.append(float(final))
            except ValueError:
                pass
    if final_angles:
        plt.figure(figsize=(6, 4))
        plt.hist(final_angles, bins=12, color="#C44E52", edgecolor="white")
        plt.xlabel("最终角度 (deg)")
        plt.ylabel("数量")
        plt.title("角度分布")
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, "angle_hist.png"))
        plt.close()

    base_angles, final_angles_scatter = [], []
    for _, base, _, final in angle_final_rows:
        if base not in ("NA", "", None) and final not in ("NA", "", None):
            try:
                base_angles.append(float(base))
                final_angles_scatter.append(float(final))
            except ValueError:
                pass
    if base_angles:
        plt.figure(figsize=(5, 5))
        plt.scatter(base_angles, final_angles_scatter, alpha=0.7, color="#8172B2")
        plt.xlabel("原始角度 (deg)")
        plt.ylabel("最终角度 (deg)")
        plt.title("原始 vs 最终角度")
        plt.axline((0, 0), slope=1, color="gray", linestyle="--", linewidth=1)
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, "angle_base_vs_final.png"))
        plt.close()


def main():
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.normpath(os.path.join(cur_dir, ".."))
    submit_dir = os.path.join(base_dir, "output_submit")
    out_dir = os.path.join(base_dir, "output_submit_report")

    ocr_path = os.path.join(submit_dir, "ocr_results.txt")
    angle_src = os.path.join(base_dir, "output_rotated", "rotation_angles.txt")
    angle_final = os.path.join(submit_dir, "angles_with_orientation.txt")

    os.makedirs(out_dir, exist_ok=True)

    results = load_ocr_results(ocr_path)
    angle_rot_rows = load_angles_rotation(angle_src)
    angle_final_rows = load_angles_with_orientation(angle_final)

    acc_path = os.path.join(out_dir, "token_accuracy.tsv")
    summary_path = os.path.join(out_dir, "accuracy_summary.txt")
    angle_rot_out = os.path.join(out_dir, "angles_original.tsv")
    angle_final_out = os.path.join(out_dir, "angles_final.tsv")

    per_rows = []
    with open(acc_path, "w", encoding="utf-8") as f:
        header = ["name", "text"] + [f"hit_{t}" for t in TOKENS] + ["hit_count", "accuracy"]
        f.write("\t".join(header) + "\n")
        for name, text in sorted(results.items()):
            hits, acc = evaluate_tokens(text)
            row = {"name": name, "text": text, "hits": hits, "acc": acc}
            per_rows.append(row)
            data = [name, text] + [str(h) for h in hits] + [str(sum(hits)), f"{acc:.2f}"]
            f.write("\t".join(data) + "\n")

    overall = sum(r["acc"] for r in per_rows) / len(per_rows) if per_rows else 0.0
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"images\t{len(per_rows)}\n")
        f.write(f"overall_accuracy\t{overall:.2f}\n")

    with open(angle_rot_out, "w", encoding="utf-8") as f:
        f.write("name\tangle_deg\n")
        for name, ang in angle_rot_rows:
            f.write(f"{name}\t{ang:.2f}\n")

    with open(angle_final_out, "w", encoding="utf-8") as f:
        f.write("name\tangle_base\tangle_add\tangle_final\n")
        for name, base, add, final in angle_final_rows:
            f.write(f"{name}\t{base}\t{add}\t{final}\n")

    make_plots(per_rows, angle_final_rows, out_dir)

    print("[INFO] 完成汇总，输出目录:", out_dir)


if __name__ == "__main__":
    main()
