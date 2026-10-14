"""开发自检: 界面运行期错误 + 菜单切换动画是否真的在跑。

用法::

    python tools/smoke.py            # 检查运行期错误
    python tools/smoke.py --anim     # 额外检查页面切换动画(对比切换中/切换后的画面)

退出码 0 表示通过。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def main() -> int:
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    want_anim = "--anim" in sys.argv

    from PySide6.QtCore import QEventLoop, QTimer, qInstallMessageHandler

    messages = []
    qInstallMessageHandler(lambda mode, ctx, msg: messages.append(msg))

    from pclpy.app import LauncherApp

    launcher = LauncherApp([])
    print("QML 加载:", launcher.ok)
    if not launcher.ok:
        for err in messages:
            print("  ", err)
        return 1

    window = launcher.window
    window.setPosition(-4000, -4000)
    window.show()

    def pump(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    pump(1500)

    ok = True
    bad = [m for m in messages if "TypeError" in m or "ReferenceError" in m
           or "is not defined" in m or "Unable to assign" in m or "SyntaxError" in m]
    # 退出阶段才会出现的拆解噪音在此阶段不应出现
    print("运行期 QML 错误:", len(bad))
    for m in bad[:10]:
        print("   ", m)
    ok = ok and not bad

    if want_anim:
        frames = []
        for delay in (90, 900):
            window.setPage(0)
            pump(500)
            window.openVersionSelect()
            pump(delay)
            img = window.grabWindow()
            path = os.path.join(ROOT, "shots", "_anim_%d.png" % delay)
            img.save(path, "PNG")
            frames.append(img)
            window.popPage()
            pump(400)

        mid, settled = frames
        diff = 0
        w = min(mid.width(), settled.width())
        h = min(mid.height(), settled.height())
        for y in range(0, h, 7):
            for x in range(0, w, 7):
                a = mid.pixelColor(x, y)
                b = settled.pixelColor(x, y)
                if abs(a.red() - b.red()) + abs(a.green() - b.green()) \
                        + abs(a.blue() - b.blue()) > 24:
                    diff += 1
        print("切换中/切换后的画面差异采样点:", diff)
        animated = diff > 20
        print("菜单切换动画:", "在跑" if animated else "没有动画(画面一致)")
        ok = ok and animated
        for name in ("_anim_90.png", "_anim_900.png"):
            try:
                os.remove(os.path.join(ROOT, "shots", name))
            except OSError:
                pass

    window.close()
    pump(200)
    print("SMOKE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
