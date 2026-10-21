# -*- coding: utf-8 -*-
"""为 23 个镜头生成「画面内部运动」设计表 shots/motion.json。

为什么需要这张表：参考片的运动量大头来自**主体局部形变**（衣袂、雾、水、能量），
而静帧 + 相机推移的局部运动几乎为 0 —— 这是"PPT 感"的量化根因。
本表把每个镜头的关键元素拆成若干"运动层"：
    band  : 只让这一横向条带动（y0..y1, x0..x1 归一化）
    drift : 该层的整体漂移速度 (px/s)，方向即运动方向
    amp   : 有机形变的幅度（噪声驱动的布料/雾/火焰呼吸感）
    speed : 噪声流动速度
再加上：
    parallax : 远/中/近三层不同跟随倍率 → 世界有纵深
    shutter  : 子帧数，动作镜取 3~4 → 真实的快门运动模糊
"""
import json

def W(y0, y1, amp, drift=(0, 0), speed=1.0, scale=1.0, x0=0.0, x1=1.0,
      feather=0.18, rate=0.9, phase=0.0):
    return dict(kind="band", y0=y0, y1=y1, x0=x0, x1=x1, amp=amp, drift=list(drift),
                speed=speed, scale=scale, feather=feather, rate=rate, phase=phase)

# 三层视差：天空/远景跟随弱，地面/近景跟随强
PARA_DEEP = [[0.00, 0.42, 0.55], [0.42, 0.78, 1.00], [0.78, 1.00, 1.45]]
PARA_NEAR = [[0.00, 0.34, 0.60], [0.34, 0.72, 1.05], [0.72, 1.00, 1.60]]

MOTION = {
 1:  dict(shutter=2, parallax=PARA_NEAR, warps=[           # 赤足入水：水波扩散 + 绿雾上升
        W(0.55, 1.00, 7.0, (5, 2), 1.5, 1.2),
        W(0.00, 0.60, 9.0, (-4, -20), 1.2, 0.9)]),
 2:  dict(shutter=3, parallax=PARA_NEAR, warps=[           # 箓雾爬腿、裙裾化焰
        W(0.40, 1.00, 12.0, (-6, -26), 1.4, 1.0),
        W(0.00, 0.45, 10.0, (7, -14), 1.1, 0.8)]),
 3:  dict(shutter=2, parallax=PARA_DEEP, warps=[           # 伞旋 + 金铃垂晃
        W(0.00, 0.34, 14.0, (10, -3), 1.6, 1.3),
        W(0.30, 0.72, 6.0, (-9, -5), 1.0, 0.9),
        W(0.70, 1.00, 5.0, (7, -9), 0.9, 0.7)]),
 4:  dict(shutter=3, parallax=PARA_DEEP, warps=[           # 俯拍伞面旋转（旋涡）
        W(0.00, 0.55, 20.0, (26, -8), 2.0, 1.6),
        W(0.45, 1.00, 9.0, (-16, 6), 1.4, 1.1)]),
 5:  dict(shutter=2, parallax=PARA_DEEP, warps=[           # 乌云自内发光、云海横移
        W(0.00, 0.55, 11.0, (22, -4), 1.3, 1.2),
        W(0.50, 1.00, 6.0, (10, 2), 1.0, 0.8)]),
 6:  dict(shutter=1, parallax=PARA_NEAR, warps=[           # 伞檐压脸：发丝与雨帘微动
        W(0.00, 0.55, 6.0, (5, -6), 1.1, 0.9),
        W(0.50, 1.00, 4.0, (-3, -4), 0.8, 0.7)]),
 7:  dict(shutter=1, parallax=PARA_NEAR, warps=[           # 竖瞳收缩：瞳孔区轻微呼吸 + 倒影流动
        W(0.18, 0.78, 8.0, (2, 0), 1.8, 1.5, 0.28, 0.72, 0.22),
        W(0.00, 0.30, 5.0, (9, -6), 1.0, 0.8)]),
 8:  dict(shutter=3, parallax=PARA_NEAR, warps=[           # 踏水入场：衣袂后拖、水花
        W(0.30, 0.95, 12.0, (-30, -6), 1.5, 1.0),
        W(0.62, 1.00, 9.0, (14, -8), 1.8, 1.2)]),
 9:  dict(shutter=2, parallax=PARA_DEEP, warps=[           # 对峙：雨幕中线流动、袍角轻颤
        W(0.00, 1.00, 5.0, (0, 9), 1.4, 1.4, 0.0, 1.0, 0.30),
        W(0.35, 0.90, 7.0, (3, -7), 0.8, 0.9)]),
10:  dict(shutter=4, parallax=PARA_NEAR, warps=[           # 直线冲刺：整体前推 + 水被劈开
        W(0.18, 0.98, 18.0, (-44, -10), 2.0, 1.3),
        W(0.55, 1.00, 14.0, (24, -14), 2.2, 1.4)]),
11:  dict(shutter=3, parallax=PARA_NEAR, warps=[           # 剑伞相撞：火花外扩 + 铜沿燃烧
        W(0.22, 0.80, 16.0, (-12, -16), 2.4, 1.5),
        W(0.55, 1.00, 10.0, (18, -10), 1.6, 1.1)]),
12:  dict(shutter=2, parallax=PARA_DEEP, warps=[           # 罗盘成盾：伞骨外张
        W(0.10, 0.78, 12.0, (14, -2), 1.2, 1.2),
        W(0.60, 1.00, 6.0, (6, -6), 0.9, 0.8)]),
13:  dict(shutter=4, parallax=PARA_NEAR, warps=[           # 金色光刃横扫
        W(0.15, 0.92, 22.0, (-56, -6), 2.6, 1.6),
        W(0.45, 1.00, 12.0, (-24, -16), 1.8, 1.1)]),
14:  dict(shutter=2, parallax=PARA_NEAR, warps=[           # 绿光沿血管蔓延（脉动）
        W(0.28, 0.85, 10.0, (2, -6), 2.2, 1.4, 0.30, 0.70, 0.16),
        W(0.00, 0.32, 6.0, (6, -8), 1.0, 0.8)]),
15:  dict(shutter=3, parallax=PARA_NEAR, warps=[           # 跃起穿过石柱：衣袂铺满
        W(0.10, 0.95, 20.0, (8, -34), 1.9, 1.3),
        W(0.55, 1.00, 11.0, (-10, 18), 1.5, 1.0)]),
16:  dict(shutter=3, parallax=PARA_NEAR, warps=[           # 冰晶阵爆发
        W(0.00, 0.70, 20.0, (10, -30), 2.4, 1.6),
        W(0.50, 1.00, 15.0, (-14, 12), 2.0, 1.3)]),
17:  dict(shutter=4, parallax=PARA_NEAR, warps=[           # 正面对撞：碎冰悬空环绕
        W(0.10, 0.90, 24.0, (-20, -18), 2.8, 1.7),
        W(0.45, 1.00, 16.0, (26, -12), 2.4, 1.4)]),
18:  dict(shutter=2, parallax=PARA_DEEP, warps=[           # 白闪余波：尘与烬上浮
        W(0.00, 0.65, 13.0, (4, -22), 1.9, 1.3),
        W(0.55, 1.00, 8.0, (-5, 10), 1.2, 0.9)]),
19:  dict(shutter=2, parallax=PARA_DEEP, warps=[           # 裂缝 → 巨手探出
        W(0.05, 0.75, 15.0, (3, -26), 2.1, 1.5),
        W(0.60, 1.00, 9.0, (-7, 9), 1.3, 1.0)]),
20:  dict(shutter=2, parallax=PARA_DEEP, warps=[           # 魔神浮现，云涌
        W(0.00, 0.62, 14.0, (16, -14), 1.7, 1.4),
        W(0.55, 1.00, 7.0, (-8, 8), 1.1, 0.9)]),
21:  dict(shutter=3, parallax=PARA_NEAR, warps=[           # 巨手砸下撑地，石阵崩裂
        W(0.00, 0.60, 18.0, (6, 26), 2.3, 1.6),
        W(0.45, 1.00, 16.0, (-10, 20), 2.6, 1.5)]),
22:  dict(shutter=1, parallax=PARA_NEAR, warps=[           # 金色竖瞳睁开
        W(0.20, 0.80, 9.0, (2, 0), 1.6, 1.5, 0.30, 0.70, 0.20),
        W(0.00, 0.26, 6.0, (8, -6), 1.0, 0.8)]),
23:  dict(shutter=1, parallax=[], warps=[                 # 标题金环缓旋
        W(0.10, 0.90, 6.0, (4, 0), 0.8, 1.0, 0.0, 1.0, 0.35)]),
}

if __name__ == "__main__":
    out = {str(k): v for k, v in MOTION.items()}
    with open("shots/motion.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote shots/motion.json  %d shots  warps=%d" %
          (len(out), sum(len(v["warps"]) for v in out.values())))
