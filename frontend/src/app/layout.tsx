import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { Providers } from '@/lib/providers';
import { TopNav } from '@/components/layout/top-nav';
import { TickerStrip } from '@/components/layout/ticker-strip';
import { APP_DISPLAY_NAME } from '@/lib/app-brand';

const inter = Inter({
  variable: '--font-inter',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: APP_DISPLAY_NAME,
  description: `${APP_DISPLAY_NAME} trading dashboard`,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const runtimeWsBase = (
    process.env.PUBLIC_WS_URL ??
    process.env.NEXT_PUBLIC_WS_URL ??
    ''
  ).trim();

  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} bg-slate-950 text-slate-100 antialiased`}
        data-ws-base={runtimeWsBase}
      >
        <Providers>
          {/* Top navigation bar (h-11 = 44px) */}
          <TopNav />
          {/* Mini watchlist ticker strip (h-7 = 28px, positioned at top-11) */}
          <TickerStrip />
          {/* Main content: offset by nav (44px) + ticker (28px) = 72px */}
          <main className="mt-[72px] min-h-[calc(100vh-72px)] p-4">
            <div className="animate-fade-in">
              {children}
            </div>
          </main>
        </Providers>
      </body>
    </html>
  );
}
