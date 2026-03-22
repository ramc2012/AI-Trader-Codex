import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function GET() {
  const wsBase = (
    process.env.PUBLIC_WS_URL ??
    process.env.NEXT_PUBLIC_WS_URL ??
    ''
  ).trim();

  return NextResponse.json(
    { wsBase },
    {
      headers: {
        'Cache-Control': 'no-store, no-cache, must-revalidate',
      },
    }
  );
}
