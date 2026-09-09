#!/usr/bin/env bash
# ==============================================================================
# myccusage 一键安装与环境配置脚本
# 支持 macOS & Linux
# ==============================================================================

set -e

# 终端彩色输出
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}${BLUE}==============================================================================${NC}"
echo -e "${BOLD}${BLUE}  🚀 正在配置 myccusage (多 Agent 会话用量与 DeepSeek-V4 等效计费工具)${NC}"
echo -e "${BOLD}${BLUE}==============================================================================${NC}"

# 1. 检查 Python 3
echo -e "\n${BLUE}[1/4] 检查 Python 环境...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ 错误: 未检测到 Python 3，请先安装 Python 3.8+ 后重试。${NC}"
    exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "${GREEN}✓ 检测到 Python 版本: ${PY_VER}${NC}"

# 2. 检查底层 ccusage CLI 依赖
echo -e "\n${BLUE}[2/4] 检查底层 ccusage CLI 依赖...${NC}"
if command -v ccusage &> /dev/null; then
    CC_VER=$(ccusage --version 2>/dev/null || echo "已安装")
    echo -e "${GREEN}✓ 检测到底层 ccusage: ${CC_VER}${NC}"
else
    echo -e "${YELLOW}⚠️  提示: 未检测到全局 ccusage 命令。${NC}"
    echo -e "   myccusage 依赖底层 ccusage 工具获取各 Agent 的 Token 切片。"
    if command -v npm &> /dev/null; then
        read -p "   是否现在通过 npm 自动安装 ccusage? [Y/n] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
            echo -e "   正在运行: npm install -g ccusage ..."
            npm install -g ccusage
            echo -e "${GREEN}✓ ccusage 安装成功！${NC}"
        else
            echo -e "${YELLOW}   请稍后手动运行: npm install -g ccusage (或 bun add -g ccusage)${NC}"
        fi
    else
        echo -e "${YELLOW}   未检测到 npm，请稍后手动安装: npm install -g ccusage (或 bun add -g ccusage)${NC}"
    fi
fi

# 3. 安装/链接 myccusage 命令
echo -e "\n${BLUE}[3/4] 注册全局 CLI 命令...${NC}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "${REPO_DIR}/myccusage.py"

# 优先尝试 pip 可编辑安装（最符合 Python 包标准）
INSTALLED_VIA_PIP=false
if command -v pip3 &> /dev/null; then
    echo -e "   正在通过 pip 安装 entry points 与模块..."
    if pip3 install -e "${REPO_DIR}" --quiet 2>/dev/null || pip3 install --user -e "${REPO_DIR}" --quiet 2>/dev/null; then
        INSTALLED_VIA_PIP=true
        echo -e "${GREEN}✓ pip 本地包模式配置成功${NC}"
    fi
fi

# 同时在 ~/.local/bin 建立安全软链接（保证双重冗余）
TARGET_BIN="${HOME}/.local/bin"
mkdir -p "${TARGET_BIN}"

ln -sf "${REPO_DIR}/myccusage.py" "${TARGET_BIN}/myccusage"
ln -sf "${REPO_DIR}/myccusage.py" "${TARGET_BIN}/ccusage-sessions"
echo -e "${GREEN}✓ 已在 ${TARGET_BIN} 建立软链接 (myccusage, ccusage-sessions)${NC}"

# 检查 PATH 环境变量
if [[ ":$PATH:" != *":${TARGET_BIN}:"* ]]; then
    echo -e "\n${YELLOW}⚠️  注意: ${TARGET_BIN} 似乎不在当前的 PATH 环境变量中。${NC}"
    echo -e "   建议将以下内容加入到您的 Shell 配置文件 (~/.zshrc 或 ~/.bashrc) 中:"
    echo -e "${BOLD}   export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
fi

# 4. 验证安装结果
echo -e "\n${BLUE}[4/4] 验证安装与测试运行...${NC}"
if "${TARGET_BIN}/myccusage" --help &> /dev/null; then
    echo -e "${GREEN}✓ 命令验证成功！${NC}"
else
    echo -e "${YELLOW}✓ 基础文件已就绪${NC}"
fi

echo -e "\n${BOLD}${GREEN}==============================================================================${NC}"
echo -e "${BOLD}${GREEN}  🎉 安装与配置已完成！您现在可以在终端随时使用:${NC}"
echo -e "  - ${BOLD}myccusage --agy${NC}       # 查看 Antigravity 每日会话用量账本"
echo -e "  - ${BOLD}myccusage --claude${NC}    # 查看 Claude Code 每日账本"
echo -e "  - ${BOLD}myccusage --web${NC}       # 启动高颜值本地 Web 仪表盘"
echo -e "${BOLD}${GREEN}==============================================================================${NC}\n"
