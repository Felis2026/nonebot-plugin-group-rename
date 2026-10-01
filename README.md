<div align="center">

  <img src="assets/group-rename-cover.jpg" width="180" alt="改群名插件头图">

  <h1>🏷️ 改群名 · Group Rename</h1>

  <p><strong>面向 PJSK、BanG Dream! 等使用五位房间号的固车、冲榜群的 NoneBot 插件</strong></p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.10%2B-blue" alt="Python >= 3.10">
    <img src="https://img.shields.io/badge/NoneBot-2.4.4%2B-black" alt="NoneBot >= 2.4.4">
    <img src="https://img.shields.io/badge/Adapter-OneBot%20V11-orange" alt="OneBot V11">
    <img src="https://img.shields.io/badge/Version-0.1.0-ff69b4" alt="Version 0.1.0">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License"></a>
  </p>

  <p>
    <a href="#-适用范围">适用范围</a> ·
    <a href="#-主要功能">主要功能</a> ·
    <a href="#-快速开始">快速开始</a> ·
    <a href="#️-指令与效果">指令与效果</a> ·
    <a href="#️-配置">配置</a>
  </p>
</div>

> 本项目参考了 [luban652 的 AstrBot 群名前缀插件](https://github.com/luban652/astrbot_plugin_group_prefix_manager)的功能需求

## 🎯 适用范围

适合 **PJSK**、**BanG Dream!** 等使用**五位数字房间号**的固车、冲榜群。
群管理员开启后，在群内发送房间号，Bot 会移除群名中的旧号码，并把新号码放在群名开头；
发送 `清空` 可移除号码。插件依据群消息中的数字工作，不区分具体游戏。

## ✨ 主要功能

| 功能 | 行为 |
| --- | --- |
| 车牌改名 | 群内发送独立的连续五位数字（车牌），将其放在群名开头 |
| 清空车牌 | 发送 `清空`，移除群名中的连续五位及以上数字 |
| 按群开关 | 默认关闭，由**群管理员及以上**在目标群内开启或关闭 |
| 混合消息 | 数字或“清空”可与 @、图片、回复同条发送；数字不能被非文本消息段隔开 |
| 防止覆盖 | 同一群的改名串行处理，并有默认 1 秒操作冷却 |

---

## 🚀 快速开始

环境要求：

- Python `>= 3.10`
- NoneBot `>= 2.4.4`
- OneBot V11 适配器
- 机器人账号具备修改目标群名称的权限

将仓库放到 Bot 设备上，在该 Bot 的 Python 环境中运行：

```bash
pip install -e /path/to/nonebot-plugin-group-rename
```

上架 NoneBot 商店后，可在 Bot 项目中使用 NB-CLI 安装：

```bash
nb plugin install nonebot-plugin-group-rename
```


如果手动管理插件加载，请在 NoneBot 初始化后加载：

```python
nonebot.load_plugin("nonebot_plugin_group_rename")
```

确认 Bot 已加载 OneBot V11 适配器，并在 `COMMAND_START` 中包含 `/`。随后由群管理员、群主或 SUPERUSER 在目标群发送 `/group_rename on` 或 `/改群名 on`。首次安装时所有群均关闭。

---

## ⌨️ 指令与效果

### 群开关

| 指令 | 权限 | 作用 |
| --- | --- | --- |
| `/group_rename on` 或 `/改群名 on` | 群管理员、群主或 SUPERUSER | 开启当前群 |
| `/group_rename off` 或 `/改群名 off` | 群管理员、群主或 SUPERUSER | 关闭当前群 |
| `/group_rename status` 或 `/改群名 status` | 群管理员、群主或 SUPERUSER | 查看当前群状态 |
| `12345` | 默认群成员；开启管理员限制后仅上述管理员 | 将 `12345` 设置为群名车牌 |
| `清空` | 默认群成员；开启管理员限制后仅上述管理员 | 从群名移除旧车牌 |

SUPERUSER 权限依据 NoneBot 的 `SUPERUSERS` 配置判定，支持纯 ID 和 `onebot:ID` 两种写法；群开关命令仍只在群内生效。

### 改名前后举例

| 原群名 | 群消息 | 修改后 | 原因 |
| --- | --- | --- | --- |
| `冲榜群` | `12345` | `12345 冲榜群` | 新增车牌 |
| `12345 冲榜群` | `67890` | `67890 冲榜群` | 替换旧车牌 |
| `1234567冲榜群` | `67890` | `67890 冲榜群` | 连续五位及以上数字整体移除 |
| `12345 冲榜群` | `清空` | `冲榜群` | 清除车牌 |
| `12345` | `67890` | `67890` | 原群名只剩车牌时仅替换 |
| `12345` | `清空` | `12345` | 清空会得到空群名，因此保留原名并提示先手动设置群名 |

发送 `@某人 12345`、`[回复]12345` 或 `12345[图片]` 仍可触发。`12[图片]345`、`123456`、`文字 12345` 和同一条消息里的两段非空文本不会触发。被 `group_rename_ignore_patterns` 忽略的数字也不会触发。


---

## ⚙️ 配置

不写配置文件即可使用默认参数，群开关仍默认关闭。
配置文件由 `nonebot-plugin-localstore` 管理。

| JSON 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `group_rename_max_length` | `30` | 目标群名的最长字符数，最小为 `5` |
| `group_rename_enable_notify` | `true` | 冷却、读取或修改群名失败、仅剩车牌无法清空时发送提示 |
| `group_rename_admin_only` | `false` | 开启后仅允许群管理员、群主或 SUPERUSER 通过车牌消息触发改名 |
| `group_rename_ignore_patterns` | `[]` | 忽略的五位数字，使用 JSON 数组 |
| `group_rename_cooldown_seconds` | `1` | 每群改名尝试的冷却秒数 |

例如，在 `config.json` 中只填写需要覆盖的参数：

```json
{
  "group_rename_admin_only": true,
  "group_rename_ignore_patterns": ["12345", "99999"]
}
```

群开关状态另存在 `nonebot-plugin-localstore` 管理的数据目录下的 `groups.json`，不与参数配置混用；换设备时复制该状态文件，或在目标群重新执行 `/group_rename on`。

---

## 📋 版本记录

### 未发布

- SUPERUSER 权限兼容纯 ID 和 `onebot:ID`，群开关和管理员模式使用同一套官方权限判定。
- 测试使用无服务器驱动，增加 CI 与发布前测试门禁，构建依赖下限修正为 setuptools 77。

### 0.1.0

- 支持 OneBot V11 群内发送连续五位数字更新群名，发送“清空”移除旧号码；@、图片和回复可与号码同条发送。
- 群开关默认关闭，由群管理员及以上在目标群管理；开关状态单独保存。
- 同群改名串行处理，默认冷却 1 秒；号码与原群名之间保留空格，清空后群名为空时保留原名。
- 使用独立 JSON 文件配置插件参数。

本项目代码采用 [MIT License](LICENSE)。
