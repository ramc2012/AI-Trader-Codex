import { redirect } from 'next/navigation';

export default function MarketRedirectPage() {
  redirect('/analytics?tab=charts');
}
