# AI Global Trends

独立的 AI 出海商业热文网站 MVP。它复用 Next.js、React、Tailwind 和 lucide 的工程栈，但不接入主项目 `frontend` 的路由、状态或样式。

## Local Run

```powershell
cd D:\AI应用\langchain-agent\apps\ai-global-trends
npm install
npm run dev
```

Preview: `http://127.0.0.1:3100`

这个端口只属于该独立商业站点，不占用主 agent 项目的 `3000/8003` 固定节点。

## Data Contract

- `GET /api/trends?industry=ecommerce` returns normalized trend items and `dateRecords`.
- `dateRecords` is derived from item `publishedAt` in `Asia/Shanghai` time and is the MVP contract for daily archives.
- The MVP includes a public Hacker News connector plus seed signals for stable offline rendering.
- Set `DISABLE_LIVE_FETCH=1` to force seed-only mode.
- Later connectors should map external data into `TrendItem` instead of changing the UI contract.
- When Supabase is added, persist `publishedAt`, `capturedAt`, `recordDate`, `source`, `dedupeHash`, and `heatScore` so daily records are queryable historically instead of only derived from the current response.

## Payment Contract

The subscribe button posts to `POST /api/checkout`.

Fast MVP path:

```env
STRIPE_PAYMENT_LINK_URL=https://buy.stripe.com/...
```

Full Stripe Checkout path:

```env
STRIPE_SECRET_KEY=sk_live_...
STRIPE_MONTHLY_PRICE_ID=price_...
NEXT_PUBLIC_SITE_URL=https://your-domain.com
```

The current UI is production-shaped but intentionally fails closed when payment secrets are absent.
