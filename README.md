# 短剧 / 短视频下载工具合集

一组面向**短剧与短视频**场景的下载、提取与后处理工具，覆盖 TikTok、YouTube、微信视频号、DramaShorts、ShortMax 等平台。
每个子目录都是一个可独立运行的项目，彼此无强依赖。

> **免责声明**
> 本仓库所有工具仅供**个人学习、技术研究与已获授权内容的本地备份**使用。
> 请遵守目标平台的服务条款及你所在地区的法律法规，**不得用于批量抓取、二次分发、破解付费墙或任何商业用途**。
> 各平台内容多受版权保护，下载前请确认你拥有相应权利。使用本仓库造成的任何后果由使用者自行承担。

---

## 子项目一览

| 目录 | 说明 | 技术栈 |
| --- | --- | --- |
| `tiktok-drama-extractor` | TikTok 短剧视频提取。浏览器书签脚本抓取页面数据，配合本地 Node 服务与 yt-dlp 完成下载 | JavaScript / Node.js |
| `youtube-downloader` | YouTube 视频下载 Web 界面。支持 Cookie 导入、下载队列、实时进度推送 | Python / Flask / yt-dlp |
| `wechat-channels-downloader` | 微信视频号下载。本地代理抓包 + 网页控制台获取直链（内含第三方项目 `wx_channels_download`） | Go / JavaScript |
| `shortmax-downloader-android` | ShortMax 短剧批量下载 Android 客户端。WebView 登录、剧集解析、队列下载、下载记录持久化 | Kotlin / Jetpack Compose / Room |
| `dramashorts-downloader` | DramaShorts 剧集下载器，带 Web 操作界面 | Python / Flask |
| `dramashorts-downloader-alt` | DramaShorts 下载器的另一版实现（功能相近，实现不同，原样保留） | Python / Flask |
| `fsk-zaizaimao` | 仔仔猫：多平台短剧下载工具，流程为「认证 → 解析播放凭证 → 下载 HLS → 合并 MP4」 | Python |
| `zaizaicat` | 仔仔猫 ZaizaiCat：短剧批量下载 + 元数据提取 + 音量后处理的一站式中台 | Python / FastAPI |

---

## 通用前置依赖

- **Python 3.10+** —— Python 系项目
- **Node.js 18+** —— Node 系项目
- **FFmpeg / ffprobe** —— 音视频合并与转码
- **yt-dlp** —— 部分项目依赖（请自行安装最新版）

## 快速开始

进入对应子目录，按其自带说明操作：

```bash
cd <子项目目录>
# 多数项目提供 start.bat / 一键运行.bat，可直接双击运行
# 或参考该目录下的 README / 使用说明 / requirements.txt
```

## 关于登录态

各平台下载通常需要**你自己的登录 Cookie**。本仓库**不包含任何 Cookie、令牌、账号或数据库文件**，
请通过各项目提供的界面或配置文件自行导入。切勿将个人 Cookie 提交到公开仓库。

## 关于第三方代码

`wechat-channels-downloader/wx_channels_download` 为第三方开源项目
[wx_channels_download](https://github.com/ltaoo/wx_channels_download)（作者 **ltaoo**，MIT License + Commons Clause）。
此处保留其原始 `LICENSE`、文档与署名，仅作学习参考，版权归原作者所有。

---

## 说明

本仓库为**脱敏发布版**：已剔除全部下载产物（视频/音频）、虚拟环境、构建产物、
可执行二进制、数据库、日志、Cookie 文件与个人本机路径。
