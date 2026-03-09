import { NextRequest, NextResponse } from 'next/server';

// Dynamic API proxy to backend
// This catches all /api/* requests and forwards them to the backend
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path);
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  return proxyRequest(request, path);
}

async function proxyRequest(request: NextRequest, path: string[]) {
  const apiHost = process.env.API_HOST || 'localhost';
  // Add back 'v1' since the route is at /api/v1/[...path]
  const backendUrl = `http://${apiHost}:8000/api/v1/${path.join('/')}`;

  // Copy search params
  const url = new URL(backendUrl);
  request.nextUrl.searchParams.forEach((value, key) => {
    url.searchParams.append(key, value);
  });

  console.log(`[API Proxy] ${request.method} ${request.url} -> ${url.toString()}`);

  // Read body once so it can be retried (ReadableStream can only be consumed once)
  let bodyBuffer: ArrayBuffer | null = null;
  if (request.body && request.method !== 'GET' && request.method !== 'HEAD') {
    bodyBuffer = await request.arrayBuffer();
  }

  const MAX_RETRIES = 2;
  let lastError: unknown;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      // Forward the request to backend
      const headers = new Headers(request.headers);
      headers.delete('host'); // Remove host header to avoid conflicts
      // Disable keep-alive to prevent stale connection reuse issues
      headers.set('connection', 'close');

      const response = await fetch(url.toString(), {
        method: request.method,
        headers,
        body: bodyBuffer,
        // @ts-ignore - duplex is needed for streaming but not in types yet
        duplex: 'half',
      });

      // Copy response headers
      const responseHeaders = new Headers(response.headers);

      // Get response body
      const data = await response.text();

      return new NextResponse(data, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    } catch (error) {
      lastError = error;
      const isSocketError =
        error instanceof TypeError &&
        (error.message.includes('fetch failed') || error.message.includes('socket'));
      if (isSocketError && attempt < MAX_RETRIES) {
        console.warn(`[API Proxy] Retrying (attempt ${attempt + 1}) after socket error:`, error);
        await new Promise((r) => setTimeout(r, 200 * (attempt + 1)));
        continue;
      }
      break;
    }
  }

  console.error(`[API Proxy] Error:`, lastError);
  return NextResponse.json(
    { error: 'Failed to proxy request to backend' },
    { status: 500 }
  );
}
