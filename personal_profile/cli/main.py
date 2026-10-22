"""CLI 入口：python -m personal_profile <command>（或 python personal_profile/cli/main.py）。

用法示例：
  python -m personal_profile add-person --name 张三
  python -m personal_profile tree --person p_zhangsan --pretty
"""

from __future__ import annotations

import json
import os
import sys

# 使 `python personal_profile/cli/main.py` 直接可运行（无需安装为包）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from personal_profile.cli.commands import build_parser, render_text  # noqa: E402
from personal_profile.core.logutil import get_logger  # noqa: E402
from personal_profile.core.store import Archive, ArchiveError  # noqa: E402

log = get_logger("cli", console=False)  # 命令留痕：logs/cli.log（只落文件，不混入命令输出）


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # Windows 下保证中文输出正常
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    log.info("CMD %s", " ".join(argv if argv is not None else sys.argv[1:]))
    try:
        archive = Archive(args.data).load()
        payload = args.func(archive, args)
    except ArchiveError as e:
        log.warning("CMD 失败(ArchiveError): %s", e)
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    except Exception as e:  # noqa: BLE001 未预期异常也以 JSON 反馈，便于 AI 解析
        log.exception("CMD 未捕获异常")
        print(json.dumps({"error": f"internal: {type(e).__name__}: {e}"}, ensure_ascii=False))
        return 2
    if args.pretty:
        print(render_text(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
