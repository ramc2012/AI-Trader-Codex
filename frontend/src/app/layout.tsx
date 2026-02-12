import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { Providers } from '@/lib/providers';
import { Sidebar } from '@/components/layout/sidebar';
import { Header } from '@/components/layout/header';

const inter = Inter({
  variable: '--font-inter',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'Nifty AI Trader',
  description: 'AI-driven automated Nifty options trading dashboard',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} bg-slate-950 text-slate-100 antialiased`}>
        <Providers>
          <Sidebar />
          <Header />
          <main className="ml-60 mt-16 min-h-[calc(100vh-4rem)] p-6">
            <div className="animate-fade-in">
              {children}
            </div>
          </main>
        </Providers>
      </body>
    </html>
  );
}
