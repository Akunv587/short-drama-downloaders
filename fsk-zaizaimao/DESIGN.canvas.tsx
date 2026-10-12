import {
  Stack,
  Row,
  Grid,
  Card,
  CardHeader,
  CardBody,
  Table,
  Text,
  H1,
  H2,
  Pill,
  Progress,
  Callout,
  Code,
} from "qoder/canvas";

// ── 数据定义 ──────────────────────────────────────────

const platformData = [
  {
    name: "DramaShorts",
    url: "dramashorts.io",
    format: "HLS (Mux)",
    auth: "免费可用",
    status: "完成" as const,
    accent: "#4ade80",
  },
  {
    name: "ShortMax",
    url: "shorttv.live",
    format: "HLS (Akamai)",
    auth: "需代理 / 免费",
    status: "完成" as const,
    accent: "#4ade80",
  },
  {
    name: "TikTok",
    url: "tiktok.com",
    format: "独立视频",
    auth: "Cookie + 代理",
    status: "基础可用" as const,
    accent: "#fbbf24",
  },
];

const phaseData = [
  { phase: "Phase 0", label: "项目初始化", pct: 100, tone: "success" as const },
  { phase: "Phase 1", label: "DramaShorts 攻克", pct: 100, tone: "success" as const },
  { phase: "Phase 2", label: "ShortMax 攻克", pct: 100, tone: "success" as const },
  { phase: "Phase 3", label: "Web UI + 打磨", pct: 85, tone: "info" as const },
  { phase: "Phase 4", label: "VIP 内容支持", pct: 0, tone: "neutral" as const },
];

const riskData = [
  { risk: "Cloudflare 拦截", prob: "中", impact: "高", plan: "curl_cffi / Playwright" },
  { risk: "Firebase Token 过期", prob: "高", impact: "中", plan: "自动刷新机制" },
  { risk: "Mux 签名 URL 时效", prob: "高", impact: "中", plan: "下载前重取 token" },
  { risk: "API 格式变更", prob: "低", impact: "中", plan: "模块化隔离" },
  { risk: "平台逆向失效", prob: "中", impact: "高", plan: "监控 + 定期 CI 检测" },
];

const flowSteps = [
  { num: "1", label: "URL 解析", desc: "提取平台 + ID" },
  { num: "2", label: "认证/登录", desc: "token/cookie" },
  { num: "3", label: "获取剧集", desc: "元信息 + 列表" },
  { num: "4", label: "获取播放凭证", desc: "m3u8 地址" },
  { num: "5", label: "下载 .ts 分片", desc: "并发下载" },
  { num: "6", label: "合并为 MP4", desc: "ffmpeg concat" },
];

const directoryTree = [
  { path: "zaizaimao/", desc: "项目根" },
  { path: "  core/", desc: "核心基础设施", sub: "client.py · auth.py · hls.py · merger.py" },
  { path: "  platforms/", desc: "平台适配层", sub: "base.py · dramashorts.py · shortmax.py" },
  { path: "  models/", desc: "数据模型", sub: "episode.py · config.py" },
  { path: "  cli/", desc: "CLI 入口", sub: "main.py (Typer + Rich)" },
  { path: "  webui/", desc: "Web 界面", sub: "app.py (NiceGUI)" },
  { path: "  utils/", desc: "工具函数", sub: "url.py · retry.py · logger.py" },
  { path: "config/", desc: "配置文件", sub: "default.yaml" },
  { path: "tests/", desc: "测试", sub: "test_*.py" },
];

// ── 样式 ──────────────────────────────────────────────

const accentGreen = "#4ade80";
const accentBlue = "#60a5fa";
const accentAmber = "#fbbf24";
const accentPurple = "#a78bfa";

// ── 架构层盒子组件 ────────────────────────────────────

function ArchLayer({
  label,
  color,
  height = 52,
  children,
}: {
  label: string;
  color: string;
  height?: number;
  children?: React.ReactNode;
}) {
  return (
    <div
      style={{
        border: `1.5px solid ${color}`,
        borderRadius: 8,
        padding: "10px 16px",
        minHeight: height,
        display: "flex",
        alignItems: "center",
        gap: 10,
        background: `${color}18`,
      }}
    >
      <Text weight="semibold" size="small" style={{ color }}>
        {label}
      </Text>
      {children}
    </div>
  );
}

function FlowStep({
  num,
  label,
  desc,
  active,
}: {
  num: string;
  label: string;
  desc: string;
  active?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 4,
        flex: 1,
      }}
    >
      <div
        style={{
          width: 40,
          height: 40,
          borderRadius: 20,
          background: active ? accentGreen : "#f4f4f5",
          border: active ? `2px solid ${accentGreen}` : "2px solid #d4d4d8",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: active ? "#ffffff" : "#71717a",
          fontWeight: 700,
          fontSize: 15,
        }}
      >
        {num}
      </div>
      <Text weight="semibold" size="small" style={{ color: "#1a1a2e" }}>
        {label}
      </Text>
      <Text size="small" tone="tertiary">
        {desc}
      </Text>
    </div>
  );
}

// ── 主画布 ────────────────────────────────────────────

export default function DesignCanvas() {
  return (
    <main
      style={{
        background: "#fafafa",
        color: "#1a1a2e",
        minHeight: "100vh",
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
      }}
    >
      <style>{`
        .ds-page { max-width: 1120px; margin: 0 auto; padding: 0 24px 80px; }
        .ds-hero { padding: 64px 0 48px; }
        .ds-section { border-top: 1px solid #e5e5e5; padding: 40px 0; }
        .ds-kicker {
          font-size: 11px; font-weight: 600; letter-spacing: 0.9px;
          text-transform: uppercase; color: #9ca3af; margin-bottom: 8px;
        }
        .ds-arch-row {
          display: flex; align-items: center; gap: 0;
        }
        .ds-arrow-down {
          display: flex; justify-content: center; padding: 4px 0;
          color: #9ca3af; font-size: 18px;
        }
        .ds-sub-box {
          border: 1px solid #d4d4d8; border-radius: 6px;
          padding: 6px 12px; background: #f4f4f5;
          font-size: 13px; color: #52525b;
        }
        .ds-flow-row {
          display: flex; align-items: flex-start; gap: 0;
          padding: 16px 0;
        }
        .ds-flow-arrow {
          display: flex; align-items: center; color: #9ca3af;
          font-size: 20px; padding: 0 4px; margin-top: 8px;
        }
        .ds-tree-line {
          font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', monospace;
          font-size: 13px; line-height: 1.8; color: #52525b;
        }
        .ds-tree-path { color: #18181b; font-weight: 600; }
        .ds-tree-sub { color: #9ca3af; }
      `}</style>

      <div className="ds-page">
        {/* ── Hero ── */}
        <section className="ds-hero">
          <Stack gap={18}>
            <Row gap={10} align="center">
              <Text size="small" tone="tertiary" style={{ letterSpacing: "0.5px" }}>
                多平台短剧下载工具
              </Text>
              <Pill tone="success" size="sm">
                v1.0
              </Pill>
            </Row>
            <H1 style={{ color: "#18181b", fontSize: 36, fontWeight: 700 }}>
              仔仔猫 · Zaizaimao
            </H1>
            <Text tone="secondary" style={{ maxWidth: 680, lineHeight: 1.7 }}>
              输入短剧 URL → 自动完成认证、解析播放凭证、下载 HLS 流、合并
              MP4。支持 DramaShorts 和 ShortMax 两大平台，提供 CLI 命令行与
              NiceGUI Web 界面两种操作方式。
            </Text>
            <Row gap={10}>
              <Pill tone="success">DramaShorts</Pill>
              <Pill tone="success">ShortMax</Pill>
              <Pill tone="info">TikTok</Pill>
            </Row>
          </Stack>
        </section>

        {/* ── 01 整体架构 ── */}
        <section className="ds-section">
          <Stack gap={20}>
            <div>
              <Text className="ds-kicker">01 — 整体架构</Text>
              <H2>分层可插拔架构</H2>
            </div>

            {/* 顶层: CLI / Web UI */}
            <ArchLayer label="CLI / Web UI 入口层" color={accentBlue} height={48}>
              <Row gap={12}>
                <span className="ds-sub-box">CLI (Typer + Rich)</span>
                <span className="ds-sub-box">Web UI (NiceGUI)</span>
              </Row>
            </ArchLayer>

            <div className="ds-arrow-down">▼</div>

            {/* 调度层 */}
            <ArchLayer label="DownloadManager 调度层" color={accentPurple} height={48}>
              <span className="ds-sub-box">调度 · 队列 · 进度上报 · 错误恢复</span>
            </ArchLayer>

            <div className="ds-arrow-down">▼</div>

            {/* 平台适配层: 三个平台 */}
            <div style={{ display: "flex", gap: 10 }}>
              <div style={{ flex: 1 }}>
                <ArchLayer label="DramaShorts" color={accentGreen} height={64}>
                  <Stack gap={2}>
                    <Text size="small" tone="tertiary">
                      免费下载 · coverUrl hash → m3u8
                    </Text>
                  </Stack>
                </ArchLayer>
              </div>
              <div style={{ flex: 1 }}>
                <ArchLayer label="ShortMax" color={accentGreen} height={64}>
                  <Stack gap={2}>
                    <Text size="small" tone="tertiary">
                      免费下载 · NuxtDataResolver → m3u8
                    </Text>
                  </Stack>
                </ArchLayer>
              </div>
              <div style={{ flex: 1 }}>
                <ArchLayer label="TikTok" color={accentAmber} height={64}>
                  <Stack gap={2}>
                    <Text size="small" tone="tertiary">
                      yt-dlp 子进程 · Cookie
                    </Text>
                  </Stack>
                </ArchLayer>
              </div>
            </div>

            <div className="ds-arrow-down">▼</div>

            {/* 抽象基类 */}
            <ArchLayer label="PlatformAdapter 抽象基类" color={accentBlue} height={48}>
              <span className="ds-sub-box">
                parse_url · get_episode_list · get_playback · login
              </span>
            </ArchLayer>

            <div className="ds-arrow-down">▼</div>

            {/* 底层基础设施 */}
            <div style={{ display: "flex", gap: 10 }}>
              <div style={{ flex: 1 }}>
                <ArchLayer label="Auth Layer" color="#f87171" height={56}>
                  <Text size="small" tone="tertiary">
                    Firebase / OAuth
                  </Text>
                </ArchLayer>
              </div>
              <div style={{ flex: 1 }}>
                <ArchLayer label="HLS Engine" color="#fbbf24" height={56}>
                  <Text size="small" tone="tertiary">
                    m3u8 解析 + ffmpeg
                  </Text>
                </ArchLayer>
              </div>
              <div style={{ flex: 1 }}>
                <ArchLayer label="HTTP Client" color="#60a5fa" height={56}>
                  <Text size="small" tone="tertiary">
                    httpx + 反检测 + 代理
                  </Text>
                </ArchLayer>
              </div>
            </div>
          </Stack>
        </section>

        {/* ── 02 数据流 ── */}
        <section className="ds-section">
          <Stack gap={20}>
            <div>
              <Text className="ds-kicker">02 — 数据流</Text>
              <H2>从 URL 到 MP4</H2>
            </div>

            <Card>
              <CardBody>
                <div className="ds-flow-row">
                  {flowSteps.map((step, i) => (
                    <>
                      <FlowStep
                        key={step.num}
                        num={step.num}
                        label={step.label}
                        desc={step.desc}
                        active={true}
                      />
                      {i < flowSteps.length - 1 && (
                        <div className="ds-flow-arrow">→</div>
                      )}
                    </>
                  ))}
                </div>
              </CardBody>
            </Card>

            <Callout tone="info" title="技术要点">
              <Stack gap={6}>
                <Text size="small">
                  ① URL 解析自动识别平台；② 免费内容无需登录；③ NuxtDataResolver
                  递归解析 NUXT_DATA 索引引用；④ 多分辨率自动优选 1080p &gt;
                  720p &gt; 480p；⑤ aiohttp + Semaphore 控制并发下载；⑥ ffmpeg
                  concat 协议合并（-c copy，无重编码）
                </Text>
              </Stack>
            </Callout>
          </Stack>
        </section>

        {/* ── 03 平台支持状态 ── */}
        <section className="ds-section">
          <Stack gap={20}>
            <div>
              <Text className="ds-kicker">03 — 平台支持状态</Text>
              <H2>当前覆盖</H2>
            </div>

            <Table
              columns={[
                { key: "name", title: "平台", role: "label", width: "140px" },
                { key: "url", title: "网址", role: "description", width: "160px" },
                { key: "format", title: "视频格式", role: "description", width: "140px" },
                { key: "auth", title: "认证要求", role: "description", width: "160px" },
                {
                  key: "status",
                  title: "状态",
                  role: "label",
                  width: "120px",
                  render: (row: (typeof platformData)[number]) => (
                    <Pill
                      tone={row.status === "完成" ? "success" : "warning"}
                      size="sm"
                    >
                      {row.status}
                    </Pill>
                  ),
                },
              ]}
              rows={platformData}
              rowKey="name"
            />

            <Row gap={12}>
              <Card>
                <CardHeader title="DramaShorts 技术栈" />
                <CardBody>
                  <Stack gap={8}>
                    <Row gap={8}>
                      <Pill tone="info" size="sm">Next.js SSR</Pill>
                      <Pill tone="info" size="sm">Mux Player</Pill>
                    </Row>
                    <Row gap={8}>
                      <Pill tone="neutral" size="sm">Firebase Auth</Pill>
                      <Pill tone="neutral" size="sm">Cloudflare CDN</Pill>
                    </Row>
                    <Text size="small" tone="tertiary">
                      免费内容: coverUrl hash → m3u8 构造，无需登录
                    </Text>
                  </Stack>
                </CardBody>
              </Card>

              <Card>
                <CardHeader title="ShortMax 技术栈" />
                <CardBody>
                  <Stack gap={8}>
                    <Row gap={8}>
                      <Pill tone="info" size="sm">Nuxt SSR</Pill>
                      <Pill tone="info" size="sm">xgplayer</Pill>
                    </Row>
                    <Row gap={8}>
                      <Pill tone="neutral" size="sm">Akamai CDN</Pill>
                      <Pill tone="warning" size="sm">需代理</Pill>
                    </Row>
                    <Text size="small" tone="tertiary">
                      免费内容: NuxtDataResolver → m3u8 URL 提取 (HTTP/1.1)
                    </Text>
                  </Stack>
                </CardBody>
              </Card>
            </Row>
          </Stack>
        </section>

        {/* ── 04 目录结构 ── */}
        <section className="ds-section">
          <Stack gap={20}>
            <div>
              <Text className="ds-kicker">04 — 目录结构</Text>
              <H2>项目组织</H2>
            </div>

            <Card>
              <CardBody>
                <div className="ds-tree-line">
                  {directoryTree.map((item) => (
                    <div key={item.path}>
                      <span className="ds-tree-path">{item.path}</span>
                      <span style={{ color: "#1a1a2e" }}>{item.desc}</span>
                      {"  "}
                      {item.sub && (
                        <span className="ds-tree-sub">{item.sub}</span>
                      )}
                    </div>
                  ))}
                </div>
              </CardBody>
            </Card>
          </Stack>
        </section>

        {/* ── 05 开发路线图 ── */}
        <section className="ds-section">
          <Stack gap={20}>
            <div>
              <Text className="ds-kicker">05 — 开发路线图</Text>
              <H2>Phase 进度</H2>
            </div>

            <Stack gap={10}>
              {phaseData.map((p) => (
                <Row key={p.phase} gap={16} align="center">
                  <Text
                    weight="semibold"
                    size="small"
                    style={{ width: 80, color: "#71717a" }}
                  >
                    {p.phase}
                  </Text>
                  <Text
                    weight="semibold"
                    size="small"
                    style={{ width: 150, color: "#1a1a2e" }}
                  >
                    {p.label}
                  </Text>
                  <div style={{ flex: 1 }}>
                    <Progress
                      value={p.pct}
                      max={100}
                      tone={p.tone}
                      height={10}
                      showLabel={false}
                    />
                  </div>
                  <Text
                    size="small"
                    weight="semibold"
                    style={{ width: 45, textAlign: "right", color: "#71717a" }}
                  >
                    {p.pct}%
                  </Text>
                  <Pill
                    tone={p.pct === 100 ? "success" : p.pct > 0 ? "info" : "neutral"}
                    size="sm"
                  >
                    {p.pct === 100 ? "完成" : p.pct > 0 ? "进行中" : "待定"}
                  </Pill>
                </Row>
              ))}
            </Stack>

            <Callout tone="info" title="Phase 3 待完成项">
              <Text size="small">
                Token 持久化（VIP 功能需要）
              </Text>
            </Callout>
          </Stack>
        </section>

        {/* ── 06 技术风险 ── */}
        <section className="ds-section">
          <Stack gap={20}>
            <div>
              <Text className="ds-kicker">06 — 技术风险</Text>
              <H2>风险矩阵</H2>
            </div>

            <Table
              columns={[
                { key: "risk", title: "风险项", role: "label", width: "200px" },
                {
                  key: "prob",
                  title: "概率",
                  role: "label",
                  width: "80px",
                  render: (row: (typeof riskData)[number]) => (
                    <Pill
                      tone={row.prob === "高" ? "danger" : row.prob === "中" ? "warning" : "info"}
                      size="sm"
                    >
                      {row.prob}
                    </Pill>
                  ),
                },
                {
                  key: "impact",
                  title: "影响",
                  role: "label",
                  width: "80px",
                  render: (row: (typeof riskData)[number]) => (
                    <Pill
                      tone={row.impact === "高" ? "danger" : row.impact === "中" ? "warning" : "info"}
                      size="sm"
                    >
                      {row.impact}
                    </Pill>
                  ),
                },
                { key: "plan", title: "对策", role: "description" },
              ]}
              rows={riskData}
              rowKey="risk"
            />
          </Stack>
        </section>

        {/* ── 07 核心依赖 ── */}
        <section className="ds-section">
          <Stack gap={20}>
            <div>
              <Text className="ds-kicker">07 — 核心依赖</Text>
              <H2>技术栈</H2>
            </div>

            <Grid columns={3} gap={10}>
              {[
                { pkg: "httpx", ver: ">=0.27", desc: "HTTP/2 客户端" },
                { pkg: "m3u8", ver: ">=5.0", desc: "HLS 清单解析" },
                { pkg: "aiohttp", ver: ">=3.9", desc: "异步 .ts 分片下载" },
                { pkg: "nicegui", ver: ">=3.0", desc: "Web UI 框架" },
                { pkg: "rich", ver: ">=13.7", desc: "终端美化输出" },
                { pkg: "typer", ver: ">=0.12", desc: "CLI 框架" },
                { pkg: "ffmpeg", ver: ">=5.0", desc: "HLS 合并转码 (系统)" },
                { pkg: "pydantic", ver: ">=2.7", desc: "数据模型校验" },
                { pkg: "h2", ver: ">=4.0", desc: "HTTP/2 协议支持" },
              ].map((dep) => (
                <Card key={dep.pkg} size="sm">
                  <CardBody>
                    <Stack gap={2}>
                      <Text weight="semibold" size="small">
                        {dep.pkg}
                      </Text>
                      <Code>{dep.ver}</Code>
                      <Text size="small" tone="tertiary">
                        {dep.desc}
                      </Text>
                    </Stack>
                  </CardBody>
                </Card>
              ))}
            </Grid>
          </Stack>
        </section>
      </div>
    </main>
  );
}
