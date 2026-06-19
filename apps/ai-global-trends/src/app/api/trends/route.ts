import { NextResponse } from "next/server";

import { getTrendSnapshot, parseIndustryKey } from "@/lib/trends";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(request: Request) {
  const url = new URL(request.url);
  const industry = parseIndustryKey(url.searchParams.get("industry"));
  const snapshot = await getTrendSnapshot(industry);

  return NextResponse.json(snapshot, {
    headers: {
      "cache-control": "public, s-maxage=300, stale-while-revalidate=900"
    }
  });
}
