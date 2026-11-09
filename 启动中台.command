#!/bin/bash
cd "$(dirname "$0")"
backend/.venv/bin/python scripts/local.py start
read -r -p '按回车关闭本窗口，服务会继续运行。' _
