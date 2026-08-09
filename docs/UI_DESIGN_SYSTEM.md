# UI Design System

视觉基准：用户提供的 **CNKH Hardware POS V5.0 UI Concept**。

## Tokens

| Role | Value |
| --- | --- |
| Sidebar | `#071B36` → `#0B2A53` |
| Primary | `#1769E0` |
| Success | `#16A34A` |
| Warning | `#F59E0B` |
| Danger | `#E5484D` |
| Canvas | `#F3F6FA` |
| Card | `#FFFFFF` |
| Main text | `#10213A` |
| Muted text | `#68768A` |
| Border | `#DCE3EC` |

Cards 使用 12px 圆角、轻边框和克制阴影。按钮高度至少 40px；POS 主要结账按钮至少 92px。所有主要操作都必须可见可点，不绑定 POS 自定义快捷键。

## Scaling

- Qt High-DPI 自动缩放，不使用固定窗口像素假设。
- Layout 设置 minimum size、stretch 和 scroll area；100%/125%/150% 均不得遮挡底部操作。
- 表格与列表默认接受 wheel event；不覆盖标准复制粘贴或 Alt+Tab。

## Staff POS interaction

搜索框是唯一搜索输入。实时结果最多 3 条，精确 barcode 唯一命中可加入购物车。鼠标可以完成选择、数量、折扣、挂单、恢复、清空、结账与重印。

