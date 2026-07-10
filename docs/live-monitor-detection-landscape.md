# 直播监控项目的「开播检测」实现对比（参考调研）

> 目的：调研仓库外同类直播监控/录制项目**如何检测主播开播**（不含录屏本身），
> 与本仓库 `racheko-lab/blive-monitor` 的现有方案做对照，提炼可借鉴的检测思路。
> 生成时间：2026-07-10。调研对象：`nfe-w/aio-dynamic-push`（纯推送）、`ihmily/DouyinLiveRecorder`（录制）、`LyzenX/DouyinLiveRecorder`（录制）。

---

## 0. 结论速览

| 项目 | 定位 | B站检测 | 抖音检测 | 小红书检测 | 与本站关系 |
|------|------|--------|---------|-----------|-----------|
| `nfe-w/aio-dynamic-push` | 多平台动态/开播**推送**（无录屏） | ✅ 官方 API | ✅ `webcast/room/web/enter` | ⚠️ 仅动态，**开播❌** | 最像，可参考其 API 走向 |
| `ihmily/DouyinLiveRecorder` | 多平台**录制**（开播即录） | ✅ API | ✅ API+`ab_sign` 签名 | ⚠️ 网页解析+短链重抓 | 检测思路可借鉴 |
| `LyzenX/DouyinLiveRecorder` | 抖音/多平台录制 | ✅ | ✅ | — | 无需 cookie、轻量 |
| **本仓库** | 多平台**直播/新作推送** | ✅ 官方 API | ✅ 服务端 HTML 多策略 | ✅ 无头 Chromium 渲染直播间 | 小红书开播检测补了行业空白 |

> 共同范式（所有项目一致）：**定时轮询房间 → 调接口/解析页面拿 live_status → 状态变化才触发后续动作（推送或 ffmpeg 录制）**。ffmpeg 只负责录，不参与"是否开播"的判断。

---

## 1. `nfe-w/aio-dynamic-push`（最像本仓库，纯推送不打屏）

仓库：<https://github.com/nfe-w/aio-dynamic-push>
结构：`query_task/query_*.py` 每个平台一个文件，统一抽象 `QueryTask`，配置 `enable_living_check` / `enable_dynamic_check` 分别开关注播与动态。

### 1.1 B站（开播✅ + 动态✅）
- 开播接口：**POST** `https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids`，body `{"uids": [int,...]}`，批量按 UID 查。
- 判断：`live_status == 1` 为开播；房间号 `room_id` 从返回里取。
- 状态机：`living_status_dict[uid]` 记录上次状态，**仅当从非 1 变为 1 时推送**，下播（变 0）不推送。
- 动态接口（另一套）：`https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid={uid}`，需 `buvid3` cookie，码 `-352` 表示 cookie 失效要重取。

> 对比本仓库：`check_status.py` 用的是 `getRoomBaseInfo`（也是官方批量 API），思路一致；本项目只做直播不做动态，所以没引入 buvid3 那套。

### 1.2 抖音（开播✅ + 动态✅）
- 开播接口：**GET** `https://live.douyin.com/webcast/room/web/enter/?aid=6383&web_rid={user_account}&...`
- 关键前置：`ttwid`（字节设备标识）。先 POST `https://ttwid.bytedance.com/ttwid/union/register/` 拿 `ttwid` 写进 cookie，否则返回空。返回 `room_status == 0` 视为开播（抖音状态码与本站 `check_status.py` 的 `DOUYIN_STATUS_LIVE=2` 恰好相反——它们用 0 表开播，本站用 2，纯约定差异）。
- 动态接口：`http://www.iesdouyin.com/web/api/v2/aweme/post?sec_uid={sec_uid}&_signature={签名}`，签名来自外部 `signature_server_url` 签名服务（`_signature` 参数）。

> 对比本仓库：本仓库抖音走**服务端 HTML 多策略兜底**（`RENDER_DATA` / `share_meta` / 文本关键词），不依赖 `ttwid` + `webcast/room/web/enter` 结构化接口。前者更稳（结构化 JSON），后者在无登录态下易触发风控 → 这正是本仓库 `check_new_posts.py` 里"抖音作品接口被风控"难题的来由。可考虑借鉴 `webcast/room/web/enter` 这条更轻的直播状态接口。**但注意：抖音接口风控频繁变，本项目 2026-02 还在 commit「移除多余 a_bogus 参数」适配，维护成本高。**

### 1.3 小红书（动态✅ / 开播❌ —— 明确不支持）
- `query_xhs.py` **只有 `query_dynamic`，`query()` 里没有直播分支**（README 表格也标开播❌）。
- 动态检测：GET `https://www.xiaohongshu.com/user/profile/{profile_id}`，带可选 cookie，从 `<script>window.__INITIAL_STATE__=` 取出，替换 `undefined→null` 后 `json.loads`，读 `user.notes[0]` 判断最新笔记。
- 它同样面对 SSR 空模板问题：靠 `window.__INITIAL_STATE__`（动态笔记能拿到，直播状态拿不到）。**直播开播是它的盲区**。

> 这就是本仓库小红书「无头 Chromium 渲染直播间 + `xgplayer-is-live`」方案补的空白（见 `docs/blive-monitor-context.md` §3）。

---

## 2. `ihmily/DouyinLiveRecorder`（录制类，先看检测再录）

仓库：<https://github.com/ihmily/DouyinLiveRecorder>
- 循环值守：`main.py` 定时遍历 `URL_config.ini` 里的直播间地址 → 请求拿状态 → 开播则取流地址交给 ffmpeg。
- 建议"循环时间设长一点，避免请求频繁被封 IP"——与本站 CI 每 5 分钟一轮的思路同源。
- 抖音：`spider.py` 请求接口 + `ab_sign.py` 生成签名 token（`a_bogus` 类），有「修复抖音风控」等大量适配 commit。
- 小红书：支持**作者主页地址**录制，但「每次开播都要重新获取一次链接」（直播链接不固定），靠短链 `xhslink.com` 解析 + 网页/接口提取。
- 结论：它的检测本质也是**轮询 + 接口/页面解析**，ffmpeg 只在确认开播后上场——和本仓库"检测到就推送"在技术链上只差最后一步。

> 对录屏类项目，检测精度要求更低（反正要录，错过几分钟无所谓）；对**纯推送**的本仓库，误报/漏报直接影响体验，所以本仓库额外做了去重账本（notify_dedup）防闪烁重复推送，这是录制类不需要的复杂度。

---

## 3. `LyzenX/DouyinLiveRecorder`（轻量录制）

仓库：<https://github.com/LyzenX/DouyinLiveRecorder>
- 卖点：**无需 cookie、不用 selenium、开箱即用**，GUI/命令行，支持弹幕。
- 检测同样基于轮询直播间地址拿状态，确认开播后 ffmpeg 录制。
- 印证一条路线：**抖音纯靠直播间 URL + 接口即可检测，不一定要 cookie；但要稳定拿流/绕过风控，cookie/sign 几乎必加**（录制类宁可偶尔失败也不上重依赖）。

---

## 4. 各平台检测路线归纳（可借鉴点）

| 平台 | 主流检测路线 | 关键信号 | 坑 |
|------|-------------|---------|----|
| **B站** | 官方批量 API（`get_status_info_by_uids` / `getRoomBaseInfo`） | `live_status==1`（或本仓库映射表） | 几乎无坑，最稳；动态需 buvid3 |
| **抖音** | ① 直播间 `/webcast/room/web/enter?web_rid=` + `ttwid`（结构化）；② 直播间 HTML `RENDER_DATA` 兜底 | `room_status`（0/2 因项目而异） | 风控频繁、需 ttwid/a_bogus 签名；无登录态下作品接口基本废 |
| **小红书** | ① 动态：`__INITIAL_STATE__`（能拿到）；② **开播：无头浏览器渲染直播间 + 播放器 class** | `xgplayer-is-live` / `xhsplayer-skin-live` | SSR 空模板，签名 API 不回写 script，纯 HTTP 拿不到开播态；数据中心 IP 触发风控页 |
| **斗鱼/虎牙** | 各自房间状态 API | 房间 `status` 字段 | 不同域名、接口各异，需逐平台适配 |

---

## 5. 对本仓库的启示（可选行动，未执行）

1. **抖音直播检测可升级为双保险**：现有 `RENDER_DATA` 多策略兜底之外，可并行试 `live.douyin.com/webcast/room/web/enter/?web_rid=` + `ttwid`，拿到结构化 `room_status` 更稳（参考 aio-dynamic-push）。代价：要维护 ttwid 获取与签名适配。
2. **B站**：当前方案已与业界一致，无需改。
3. **小红书开播**：本仓库已是最优解（无头 Chromium 渲染），业界纯推送项目都避开这块；保持现状即可。
4. **轮询节奏**：录制类靠"长间隔 + 宁漏勿错"，本仓库纯推送靠"短间隔 + 去重账本防抖"，路线不同但都正确。

> 所有参考项目均为"检测即触发后续动作（推送/录制）"的轮询模型，与本仓库架构同源。**本仓库的独特价值正是小红书开播检测**——aio-dynamic-push 这类最像的项目都明确标 ❌。
