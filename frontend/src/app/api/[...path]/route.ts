import { NextRequest } from "next/server";

const FIXED_BACKEND_BASE = "http://127.0.0.1:8003";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxyRequest(request, context.params.path ?? []);
}

export async function POST(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxyRequest(request, context.params.path ?? []);
}

export async function PUT(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxyRequest(request, context.params.path ?? []);
}

export async function PATCH(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxyRequest(request, context.params.path ?? []);
}

export async function DELETE(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxyRequest(request, context.params.path ?? []);
}

export async function HEAD(request: NextRequest, context: { params: { path?: string[] } }) {
  return proxyRequest(request, context.params.path ?? []);
}

async function proxyRequest(request: NextRequest, path: string[]) {
  const targetUrl = new URL(`/api/${path.map(encodeURIComponent).join("/")}`, backendBase());
  targetUrl.search = request.nextUrl.search;
  const init: RequestInit = {
    method: request.method,
    headers: proxyRequestHeaders(request.headers),
    cache: "no-store",
    redirect: "manual",
  };
  if (!["GET", "HEAD"].includes(request.method.toUpperCase())) {
    init.body = await request.arrayBuffer();
  }
  const response = await fetch(targetUrl, init);
  const headers = proxyResponseHeaders(response.headers);
  const body = headers.get("content-type")?.includes("text/event-stream")
    ? response.body
    : await response.arrayBuffer();
  return new Response(body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function backendBase() {
  return (process.env.API_PROXY_TARGET || process.env.NEXT_PUBLIC_API_BASE || FIXED_BACKEND_BASE)
    .trim()
    .replace(/\/$/, "")
    .replace(/\/api$/, "");
}

function proxyRequestHeaders(headers: Headers) {
  const result = new Headers(headers);
  result.delete("host");
  result.delete("connection");
  result.delete("content-length");
  result.delete("accept-encoding");
  return result;
}

function proxyResponseHeaders(headers: Headers) {
  const result = new Headers(headers);
  result.delete("content-encoding");
  result.delete("content-length");
  result.delete("transfer-encoding");
  result.delete("connection");
  if (result.get("content-type")?.includes("text/event-stream")) {
    result.set("cache-control", "no-cache, no-transform");
    result.set("x-accel-buffering", "no");
  }
  return result;
}
