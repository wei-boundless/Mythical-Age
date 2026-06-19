import { NextResponse } from "next/server";
import Stripe from "stripe";

type CheckoutBody = {
  email?: string;
  industry?: string;
  keyword?: string;
};

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as CheckoutBody;
  const keyword = normalizeField(body.keyword, 80);
  const industry = normalizeField(body.industry, 32) || "all";
  const email = normalizeField(body.email, 120);

  if (keyword.length < 2) {
    return NextResponse.json({ error: "请输入需要追踪的行业关键词。" }, { status: 400 });
  }

  const origin = request.headers.get("origin") || process.env.NEXT_PUBLIC_SITE_URL || "http://127.0.0.1:3100";
  const paymentLink = process.env.STRIPE_PAYMENT_LINK_URL;

  if (paymentLink) {
    return NextResponse.json({
      checkoutUrl: appendPaymentLinkParams(paymentLink, {
        client_reference_id: `${industry}:${keyword}`,
        prefilled_email: email
      }),
      mode: "payment_link"
    });
  }

  const secretKey = process.env.STRIPE_SECRET_KEY;
  const priceId = process.env.STRIPE_MONTHLY_PRICE_ID;

  if (!secretKey || !priceId) {
    return NextResponse.json(
      {
        error: "Stripe 付款通道尚未配置。请设置 STRIPE_PAYMENT_LINK_URL，或设置 STRIPE_SECRET_KEY 与 STRIPE_MONTHLY_PRICE_ID。"
      },
      { status: 503 }
    );
  }

  const stripe = new Stripe(secretKey);
  const session = await stripe.checkout.sessions.create({
    mode: "subscription",
    line_items: [
      {
        price: priceId,
        quantity: 1
      }
    ],
    success_url: `${origin}/?checkout=success`,
    cancel_url: `${origin}/?checkout=cancelled`,
    allow_promotion_codes: true,
    customer_email: email || undefined,
    metadata: {
      industry,
      keyword
    },
    subscription_data: {
      metadata: {
        industry,
        keyword
      }
    }
  });

  if (!session.url) {
    return NextResponse.json({ error: "Stripe 未返回 Checkout URL。" }, { status: 502 });
  }

  return NextResponse.json({
    checkoutUrl: session.url,
    mode: "checkout_session"
  });
}

function normalizeField(value: unknown, maxLength: number): string {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, maxLength);
}

function appendPaymentLinkParams(url: string, params: Record<string, string>) {
  try {
    const parsed = new URL(url);
    for (const [key, value] of Object.entries(params)) {
      if (value) parsed.searchParams.set(key, value);
    }
    return parsed.toString();
  } catch {
    return url;
  }
}
